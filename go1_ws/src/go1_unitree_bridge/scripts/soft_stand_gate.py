#!/usr/bin/env python3
"""Мягкий старт Go1 в Gazebo: плавный подъём в позу стоя и «ворота» на управление.

Зачем. Пока ros2_control не включил контроллер, ноги модели обмякают и складываются. Когда контроллер включается,
champ тут же требует позу стоя, ПИД даёт предельный момент, и корпус подбрасывает; иногда он переворачивается на спину.

Что делает узел (режим control_mode:=trajectory, champ включён):
  1. champ публикует траектории не прямо в контроллер, а в /champ/joint_trajectory (ремап в bringup.launch.py),
     /cmd_vel и /body_pose для champ идут через узел (/cmd_vel_gated, /body_pose_gated);
  2. узел ждёт joint_states, траекторию champ (она задаёт позу стоя) и активный joint_group_effort_controller;
  3. плавно ведёт ноги из фактических углов в позу стоя: q_des(t) = q0 + (q1 - q0) s(t/T), s(u) = 3u^2 - 2u^3;
  4. когда ноги пришли в позу и собака не наклонена, открывает ворота: траектории champ, /cmd_vel и /body_pose
     пропускаются дальше, в лог идёт сообщение «ГОТОВ К ДВИЖЕНИЮ», топик /go1_ready (std_msgs/Bool, latched) = true.
До открытия ворот команды движения игнорируются (с предупреждением в логе).

Параметры: rise_time (2.5 с), settle (0.5 с), tol (0.15 рад), vel_tol (0.3 рад/с), max_tilt (0.35 рад),
controller (joint_group_effort_controller), active_fallback (8 с: сколько ждать подтверждения активности контроллера
по сервису, прежде чем начать подъём без него), horizon (0.03 с, как у champ: 1/60 с).
"""
import sys

import numpy as np
import rclpy
from controller_manager_msgs.srv import ListControllers
from geometry_msgs.msg import Pose, Twist
from sensor_msgs.msg import Imu
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

from go1_unitree_bridge import core


class SoftStandGate(Node):
    def __init__(self):
        super().__init__('soft_stand_gate')
        for name, default in (('rise_time', 2.5), ('settle', 0.5), ('tol', 0.15), ('vel_tol', 0.3),
                              ('max_tilt', 0.35), ('active_fallback', 8.0), ('horizon', 0.03),
                              ('controller', 'joint_group_effort_controller'),
                              ('controller_manager', '/controller_manager'),
                              ('raw_topic', '/champ/joint_trajectory'),
                              ('out_topic', '/joint_group_effort_controller/joint_trajectory'),
                              ('cmd_in', '/cmd_vel'), ('cmd_out', '/cmd_vel_gated'),
                              ('pose_in', '/body_pose'), ('pose_out', '/body_pose_gated'),
                              ('ready_topic', '/go1_ready')):
            self.declare_parameter(name, default)
        g = lambda n: self.get_parameter(n).value  # noqa: E731
        self.ramp = core.StandRamp(g('rise_time'), g('settle'), g('tol'), g('vel_tol'))
        self.max_tilt = float(g('max_tilt'))
        self.active_fallback = float(g('active_fallback'))
        self.horizon = float(g('horizon'))
        self.controller = str(g('controller'))

        self.phase = 'wait'             # wait -> rise -> ready | failed
        self.js = {}                    # имя сустава -> (положение, скорость)
        self.js_first = None            # когда пришёл первый joint_states
        self.raw = None                 # последняя траектория champ (JointTrajectory)
        self.ctrl_active = False
        self.pending = None
        self.next_poll = 0.0
        self.tilt = None
        self.names = None
        self.last_log = {}
        self.t_rise = None

        latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.ready_pub = self.create_publisher(Bool, g('ready_topic'), latched)
        self.out_pub = self.create_publisher(JointTrajectory, g('out_topic'), 10)
        self.cmd_pub = self.create_publisher(Twist, g('cmd_out'), 10)
        self.pose_pub = self.create_publisher(Pose, g('pose_out'), 10)
        self.cli = self.create_client(ListControllers, g('controller_manager') + '/list_controllers')

        self.create_subscription(JointState, 'joint_states', self._on_js, QoSProfile(depth=20, reliability=ReliabilityPolicy.BEST_EFFORT))
        self.create_subscription(JointTrajectory, g('raw_topic'), self._on_raw, 10)
        self.create_subscription(Twist, g('cmd_in'), self._on_cmd, 10)
        self.create_subscription(Pose, g('pose_in'), self._on_pose, 10)
        self.create_subscription(Imu, '/imu/data', self._on_imu,
                                 QoSProfile(depth=20, reliability=ReliabilityPolicy.BEST_EFFORT))
        self.create_timer(0.01, self._tick)

        self._publish_ready(False)
        self.get_logger().info(
            f'Мягкий старт: жду контроллеры, затем плавный подъём ({self.ramp.duration:.1f} с); '
            f'команды движения блокированы до сообщения «ГОТОВ К ДВИЖЕНИЮ» (топик {g("ready_topic")})')

    # ----------------------------------------------------------------- вспомогательное
    def _now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def _throttle(self, key, period):
        t = self._now()
        if t - self.last_log.get(key, -1e9) >= period:
            self.last_log[key] = t
            return True
        return False

    def _publish_ready(self, value):
        self.ready_pub.publish(Bool(data=bool(value)))

    # ----------------------------------------------------------------- входы
    def _on_js(self, m):
        if self.js_first is None and m.name:
            self.js_first = self._now()
        for i, n in enumerate(m.name):
            if i < len(m.position) and i < len(m.velocity):
                self.js[n] = (m.position[i], m.velocity[i])

    def _on_raw(self, m):
        if len(m.points) and len(m.joint_names) == len(m.points[0].positions):
            self.raw = m
        if self.phase == 'ready':
            self.out_pub.publish(m)

    def _on_cmd(self, m):
        if self.phase == 'ready':
            self.cmd_pub.publish(m)
        elif any(abs(v) > 1e-3 for v in (m.linear.x, m.linear.y, m.angular.z)) and self._throttle('cmd', 2.0):
            self.get_logger().warn('Команда /cmd_vel проигнорирована: собака ещё встаёт (ждите «ГОТОВ К ДВИЖЕНИЮ» или /go1_ready)')

    def _on_pose(self, m):
        if self.phase == 'ready':
            self.pose_pub.publish(m)

    def _on_imu(self, m):
        # IMU is normal public telemetry. The gate no longer needs privileged GT.
        q = m.orientation
        roll, pitch, _ = core.quat_to_rpy(q.w, q.x, q.y, q.z)
        self.tilt = max(abs(roll), abs(pitch))

    # ----------------------------------------------------------------- контроллер активен?
    def _poll_controller(self, t):
        if self.pending is not None:
            if self.pending.done():
                try:
                    res = self.pending.result()
                    self.ctrl_active = any(c.name == self.controller and c.state == 'active' for c in res.controller)
                except Exception:       # сервис пропал: пробуем снова
                    self.ctrl_active = False
                self.pending = None
            return
        if t >= self.next_poll and self.cli.service_is_ready():
            self.next_poll = t + 0.2
            self.pending = self.cli.call_async(ListControllers.Request())

    # ----------------------------------------------------------------- основной такт
    def _tick(self):
        t = self._now()
        if t <= 0.0:                        # /clock ещё не пошёл
            return
        if self.phase == 'wait':
            self._poll_controller(t)
            have = self.js_first is not None and self.raw is not None
            if not have:
                if self._throttle('wait', 5.0):
                    self.get_logger().info('Жду joint_states и позу стоя от champ (/champ/joint_trajectory)')
                return
            waited = t - self.js_first
            if self.ctrl_active or waited >= self.active_fallback:
                if not self.ctrl_active:
                    self.get_logger().warn(f'Активность {self.controller} не подтверждена за {waited:.0f} с, начинаю подъём всё равно')
                self._begin_rise(t)
        elif self.phase == 'rise':
            self._rise_step(t)
        elif self.phase == 'failed' and self._throttle('failed', 5.0):
            self.get_logger().error(
                f'Собака не стоит (наклон {self.tilt:.2f} рад > {self.max_tilt:.2f}); управление заблокировано. '
                'Перезапустите симуляцию, а при повторении пришлите график roll/pitch и q[0-11] с первых секунд')

    def _vectors(self):
        try:
            q = np.array([self.js[n][0] for n in self.names])
            dq = np.array([self.js[n][1] for n in self.names])
        except KeyError:
            return None, None
        return q, dq

    def _begin_rise(self, t):
        self.names = list(self.raw.joint_names)
        q0, _ = self._vectors()
        if q0 is None:
            if self._throttle('names', 5.0):
                self.get_logger().warn('В joint_states нет суставов из траектории champ; жду')
            return
        q1 = np.array(self.raw.points[0].positions, dtype=float)   # поза стоя, которую сейчас держит champ
        self.ramp.start(t, q0, q1)
        self.t_rise = t
        self.phase = 'rise'
        self.get_logger().info(
            f'Подъём начат: макс. отклонение ног от позы стоя {float(np.max(np.abs(q1 - q0))):.2f} рад, '
            f'длительность {self.ramp.duration:.1f} с')

    def _rise_step(self, t):
        q, dq = self._vectors()
        if q is None:
            return
        state = self.ramp.update(t, q, dq)
        ta = t + self.horizon
        msg = JointTrajectory()
        msg.joint_names = self.names
        pt = JointTrajectoryPoint()
        pt.positions = [float(v) for v in self.ramp.target(ta)]
        pt.velocities = [float(v) for v in self.ramp.target_velocity(ta)]
        pt.time_from_start = Duration(seconds=self.horizon).to_msg()
        msg.points = [pt]
        self.out_pub.publish(msg)
        if state == 'ready':
            self._finish(t)

    def _finish(self, t):
        if self.tilt is not None and self.tilt > self.max_tilt:
            self.phase = 'failed'
            self._publish_ready(False)
            return
        self.phase = 'ready'
        self._publish_ready(True)
        if self.ramp.inexact:
            self.get_logger().warn(f'Поза стоя достигнута неточно (макс. ошибка суставов {self.ramp.max_err:.2f} рад), управление всё же разрешено')
        self.get_logger().info(
            f'ГОТОВ К ДВИЖЕНИЮ: собака стоит (подъём {t - self.t_rise:.1f} с, макс. ошибка суставов '
            f'{self.ramp.max_err:.3f} рад). Управление разрешено: /cmd_vel, /body_pose')


def main():
    rclpy.init(args=sys.argv)
    node = SoftStandGate()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception:       # при остановке launch контекст становится недействительным посреди обратного вызова
        if rclpy.ok():
            raise
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
