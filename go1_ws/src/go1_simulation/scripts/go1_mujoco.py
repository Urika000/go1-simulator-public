#!/usr/bin/env python3
"""Go1 в MuJoCo + мост в ROS 2.

Модель - unitree_go1 из mujoco_menagerie (12 позиционных приводов). Окно MuJoCo viewer открывается само.

Lowlevel: управление 12 приводами исключительно через /lowcmd (unitree_go/LowCmd).
Моменты: tau = tau_ff + kp*(q_des-q) + kd*(dq_des-dq).
Публикация: /lowstate и отладочный /odom/ground_truth (без TF).
Другие режимы управления и JointTrajectory в MuJoCo не поддерживаются.
До первого LowCmd собака держит позу стоя (kp=hold_kp, kd=hold_kd), после cmd_timeout без LowCmd - позу на момент потери связи.

Параметры (ros2 run go1_simulation go1_mujoco.py --ros-args -p box:=true -p flip:=true):
  model_dir  каталог unitree_go1 (по умолчанию /opt/mujoco_menagerie/unitree_go1)
  box        true - поставить под корпус подставку-параллелепипед и положить на неё собаку
  flip       true - перевернуть собаку на спину (имеет смысл с box)
  box_size   [длина, ширина, высота] подставки, м
  headless   true - без окна (для проверок)
  rate       частота публикации топиков, Гц
"""
import os
import shutil
import sys
import tempfile
import time

import mujoco
import numpy as np
import rclpy
from nav_msgs.msg import Odometry
from rosgraph_msgs.msg import Clock
from rclpy.node import Node
from unitree_go.msg import LowCmd, LowState

from go1_unitree_bridge import core

TRUNK_HALF_HEIGHT = 0.058   # радиус цилиндров корпуса в go1.xml
GAP = 0.01

SCENE_BOX = """<mujoco model="go1 on box">
  <include file="scene.xml"/>
  <worldbody>
    <geom name="support_box" type="box" pos="0 0 {hz}" size="{hx} {hy} {hz}" friction="1.0" rgba="0.8 0.5 0.2 1"/>
  </worldbody>
</mujoco>
"""


class Go1MuJoCo(Node):
    def __init__(self):
        super().__init__('go1_mujoco')
        self.declare_parameter('model_dir', '/opt/mujoco_menagerie/unitree_go1')
        self.declare_parameter('box', False)
        self.declare_parameter('flip', False)
        self.declare_parameter('box_size', [0.24, 0.12, 0.30])
        self.declare_parameter('headless', False)
        self.declare_parameter('rate', 100.0)
        self.declare_parameter('state_rate', 500.0)
        self.declare_parameter('cmd_timeout', 0.5)
        self.declare_parameter('hold_kp', 40.0)
        self.declare_parameter('hold_kd', 2.0)
        self.declare_parameter('damping', 2.0)

        model_dir = self.get_parameter('model_dir').value
        box = self.get_parameter('box').value
        flip = self.get_parameter('flip').value
        size = [float(v) for v in self.get_parameter('box_size').value]
        self.headless = self.get_parameter('headless').value
        self.period = 1.0 / float(self.get_parameter('rate').value)

        if not os.path.isfile(os.path.join(model_dir, 'scene.xml')):
            raise RuntimeError(f'scene.xml не найден в {model_dir}')
        scene = os.path.join(model_dir, 'scene.xml')
        self._tmp = None
        if box:
            # include в MJCF и meshdir считаются от каталога файла, поэтому копируем модель во временный каталог
            self._tmp = tempfile.mkdtemp(prefix='go1_mujoco_')
            work = os.path.join(self._tmp, 'unitree_go1')
            shutil.copytree(model_dir, work)
            scene = os.path.join(work, 'scene_box.xml')
            with open(scene, 'w') as f:
                f.write(SCENE_BOX.format(hx=size[0] / 2, hy=size[1] / 2, hz=size[2] / 2))

        self.model = mujoco.MjModel.from_xml_path(scene)
        self.data = mujoco.MjData(self.model)

        key = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_KEY, 'home')
        if key >= 0:
            mujoco.mj_resetDataKeyframe(self.model, self.data, key)
        if box:
            self.data.qpos[2] = size[2] + TRUNK_HALF_HEIGHT + GAP
        if flip:
            self.data.qpos[3:7] = [0.0, 1.0, 0.0, 0.0]   # (w, x, y, z): поворот на 180° вокруг x
        mujoco.mj_forward(self.model, self.data)

        # приводы <-> суставы
        self.act_joint_names = []
        self.act_qadr = []
        self.act_dadr = []
        for a in range(self.model.nu):
            j = int(self.model.actuator_trnid[a, 0])
            self.act_joint_names.append(mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_JOINT, j))
            self.act_qadr.append(int(self.model.jnt_qposadr[j]))
            self.act_dadr.append(int(self.model.jnt_dofadr[j]))
        self.act_index = {n: i for i, n in enumerate(self.act_joint_names)}

        # ---- Unitree-интерфейс
        self.cmd_timeout = float(self.get_parameter('cmd_timeout').value)
        self.hold_kp = float(self.get_parameter('hold_kp').value)
        self.hold_kd = float(self.get_parameter('hold_kd').value)
        self.damping = float(self.get_parameter('damping').value)
        self.state_period = 1.0 / float(self.get_parameter('state_rate').value)
        try:
            self.u_qadr = [self.act_qadr[self.act_index[n]] for n in core.JOINT_NAMES]
            self.u_dadr = [self.act_dadr[self.act_index[n]] for n in core.JOINT_NAMES]
        except KeyError as e:
            raise RuntimeError(f'в модели нет сустава {e}; ожидаются имена вида FR_hip_joint')
        self.cmd = None
        self.cmd_time = None
        self.hold_q = core.STAND_Q.copy()
        self.last_tau = np.zeros(12)
        self.last_servo = np.zeros(12, dtype=bool)
        self.warned_timeout = False
        self.foot_geoms = self._find_foot_geoms()
        # Встроенные позиционные приводы отключены: моменты задаёт только LowCmd/безопасный hold.
        self.model.actuator_gainprm[:, 0] = 0.0
        self.model.actuator_biasprm[:, :] = 0.0
        self.data.ctrl[:] = 0.0
        self.hold_q = np.array([self.data.qpos[a] for a in self.u_qadr])
        self.clock_pub = self.create_publisher(Clock, '/clock', 10)
        self.low_pub = self.create_publisher(LowState, 'lowstate', 10)
        self.create_subscription(LowCmd, os.environ.get('GO1_ACTUATOR_COMMAND_TOPIC', 'lowcmd'), self._on_lowcmd, 1)

        self.odom_pub = self.create_publisher(Odometry, 'odom/ground_truth', 10)
        self.get_logger().info(
            f'MuJoCo Go1 готов: {self.model.nu} приводов, box={box}, flip={flip}, headless={self.headless}. '
            'Команды: /lowcmd; состояние: /lowstate')

    # ---------------------------------------------------------------- Unitree-интерфейс
    def _find_foot_geoms(self):
        """Геометрии голеней по ногам в порядке Unitree [FR, FL, RR, RL] (для foot_force)."""
        out = []
        for leg in core.LEG_ORDER:
            bid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, f'{leg}_calf')
            geoms = [g for g in range(self.model.ngeom) if self.model.geom_bodyid[g] == bid] if bid >= 0 else []
            if not geoms:
                self.get_logger().warn(f'нет геометрии голени {leg}_calf: foot_force для этой ноги будет 0')
            out.append(set(geoms))
        return out

    def _foot_forces(self):
        ff = [0, 0, 0, 0]
        f6 = np.zeros(6)
        for i in range(self.data.ncon):
            c = self.data.contact[i]
            for leg, geoms in enumerate(self.foot_geoms):
                for a, b in ((c.geom1, c.geom2), (c.geom2, c.geom1)):
                    # нога в контакте с телом мира (пол, подставка)
                    if a in geoms and self.model.geom_bodyid[b] == 0:
                        mujoco.mj_contactForce(self.model, self.data, i, f6)
                        ff[leg] += int(abs(f6[0]))
        return ff

    def _on_lowcmd(self, m: LowCmd):
        self.cmd = core.read_low_cmd(m)
        self.cmd_time = float(self.data.time)
        self.warned_timeout = False

    def _apply_lowcmd(self):
        """Один шаг закона управления моторами Unitree; вызывается перед каждым mj_step."""
        d = self.data
        q = np.array([d.qpos[a] for a in self.u_qadr])
        dq = np.array([d.qvel[a] for a in self.u_dadr])
        z = np.zeros(12)
        now = float(d.time)
        have = self.cmd is not None
        fresh = have and (now - self.cmd_time) <= self.cmd_timeout
        if fresh:
            c = self.cmd
            self.hold_q = q
            tau = core.motor_torque(c['mode'], c['q'], c['dq'], c['tau'], c['kp'], c['kd'], q, dq, damping=self.damping)
            servo = c['mode'] == core.MODE_SERVO
        else:
            if have and not self.warned_timeout:
                self.warned_timeout = True
                self.get_logger().warn(f'LowCmd не приходит более {self.cmd_timeout} с: держу позу')
            target = self.hold_q if have else core.STAND_Q
            tau = core.motor_torque(np.full(12, core.MODE_SERVO), target, z, z,
                                    np.full(12, self.hold_kp), np.full(12, self.hold_kd), q, dq)
            servo = np.ones(12, dtype=bool)
        d.qfrc_applied[:] = 0.0
        for k, a in enumerate(self.u_dadr):
            d.qfrc_applied[a] = tau[k]
        self.last_tau, self.last_servo = tau, servo

    def publish_unitree(self):
        d = self.data
        rs = core.RobotState()
        rs.q = np.array([d.qpos[a] for a in self.u_qadr])
        rs.dq = np.array([d.qvel[a] for a in self.u_dadr])
        rs.ddq = np.array([d.qacc[a] for a in self.u_dadr])
        rs.tau_est = self.last_tau.copy()
        rs.servo = self.last_servo.copy()
        w, x, y, z = (float(v) for v in d.qpos[3:7])
        rs.quat = (w, x, y, z)
        rs.gyro = tuple(float(v) for v in d.qvel[3:6])
        inv = np.zeros(4)
        mujoco.mju_negQuat(inv, d.qpos[3:7])
        a_body = np.zeros(3)
        mujoco.mju_rotVecQuat(a_body, np.array([d.qacc[0], d.qacc[1], d.qacc[2] + 9.81]), inv)
        rs.accel = tuple(float(v) for v in a_body)
        rs.foot_force = tuple(self._foot_forces())
        rs.tick_ms = int(d.time * 1000.0)
        low = LowState()
        core.fill_low_state(low, rs)
        self.low_pub.publish(low)
    # ---------------------------------------------------------------- публикация
    def publish(self):
        d = self.data
        clock = Clock()
        clock.clock.sec = int(d.time)
        clock.clock.nanosec = int((d.time-int(d.time))*1e9)
        self.clock_pub.publish(clock)
        now = clock.clock

        w, x, y, z = (float(v) for v in d.qpos[3:7])

        odom = Odometry()
        odom.header.stamp = now
        odom.header.frame_id = 'odom'
        odom.child_frame_id = 'trunk'
        odom.pose.pose.position.x, odom.pose.pose.position.y, odom.pose.pose.position.z = (float(v) for v in d.qpos[0:3])
        odom.pose.pose.orientation.w, odom.pose.pose.orientation.x = w, x
        odom.pose.pose.orientation.y, odom.pose.pose.orientation.z = y, z
        inv = np.zeros(4)
        mujoco.mju_negQuat(inv, d.qpos[3:7])
        v_local = np.zeros(3)
        mujoco.mju_rotVecQuat(v_local, d.qvel[0:3], inv)   # линейная скорость - в системе корпуса
        odom.twist.twist.linear.x, odom.twist.twist.linear.y, odom.twist.twist.linear.z = (float(v) for v in v_local)
        odom.twist.twist.angular.x, odom.twist.twist.angular.y, odom.twist.twist.angular.z = (float(v) for v in d.qvel[3:6])
        if self.odom_pub is not None:
            self.odom_pub.publish(odom)
    # ---------------------------------------------------------------- главный цикл
    def run(self):
        viewer = None
        if not self.headless:
            from mujoco import viewer as mujoco_viewer
            viewer = mujoco_viewer.launch_passive(self.model, self.data)
        wall0 = time.perf_counter()
        sim0 = float(self.data.time)
        next_pub = 0.0
        next_state = 0.0
        next_view = 0.0
        try:
            while rclpy.ok() and (viewer is None or viewer.is_running()):
                wall = time.perf_counter() - wall0
                steps = 0
                # физика в реальном времени; не больше 100 шагов за итерацию, чтобы не уходить в спираль
                while float(self.data.time) - sim0 < wall and steps < 100:
                    self._apply_lowcmd()
                    mujoco.mj_step(self.model, self.data)
                    steps += 1
                if steps == 100:
                    wall0 = time.perf_counter() - (float(self.data.time) - sim0)   # компьютер не успевает - замедляемся
                if wall >= next_pub:
                    self.publish()
                    next_pub = wall + self.period
                if wall >= next_state:
                    self.publish_unitree()
                    next_state = wall + self.state_period
                if viewer is not None and wall >= next_view:
                    viewer.sync()
                    next_view = wall + 1.0 / 60.0
                rclpy.spin_once(self, timeout_sec=0.0)
                time.sleep(0.0005)
        finally:
            if viewer is not None:
                viewer.close()
            if self._tmp:
                shutil.rmtree(self._tmp, ignore_errors=True)


def main():
    rclpy.init(args=sys.argv)
    node = Go1MuJoCo()
    try:
        node.run()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
