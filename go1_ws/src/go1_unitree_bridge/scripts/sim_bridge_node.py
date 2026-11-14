#!/usr/bin/env python3
"""Мост Gazebo -> LowState; в lowcmd_enabled дополнительно LowCmd -> момент приводов.

В Highlevel /cmd_vel и /body_pose подаются непосредственно в CHAMP, без дополнительных мостов команд.
Данные: /joint_states, /imu/data -> /lowstate.
Gazebo публикует бинарные контакты, но не измеренную силу: foot_force в LowState = 0.
"""
import sys

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Imu, JointState
from std_msgs.msg import Bool, Float64MultiArray
from unitree_go.msg import LowCmd, LowState

from go1_unitree_bridge import core


class Go1UnitreeBridge(Node):
    def __init__(self):
        super().__init__('go1_unitree_bridge')
        self.declare_parameter('lowcmd_enabled', True)
        self.declare_parameter('state_rate', 500.0)          # Гц, частота публикации LowState (по времени симуляции)
        self.declare_parameter('cmd_timeout', 0.5)           # с без LowCmd -> действие timeout_action
        self.declare_parameter('timeout_action', 'hold')     # hold - держать позу на момент потери команд, damp - демпфировать
        self.declare_parameter('hold_kp', 40.0)
        self.declare_parameter('hold_kd', 2.0)
        self.declare_parameter('damping', 2.0)               # Н*м*с/рад в режиме damp и при mode != 0x0A
        self.declare_parameter('forward_topic', '/joint_group_effort_forward_controller/commands')
        # мягкий старт (только lowcmd): плавный подъём в позу стоя, LowCmd игнорируется до сообщения «ГОТОВ К ДВИЖЕНИЮ»
        self.declare_parameter('soft_start', True)
        self.declare_parameter('rise_time', 2.5)             # с
        self.declare_parameter('ramp_tol', 0.25)             # рад: допуск позы стоя при kp = hold_kp (под весом корпуса ошибка ~0.1)
        self.declare_parameter('max_tilt', 0.35)             # рад: при большем наклоне собака «не стоит»
        self.declare_parameter('ready_topic', '/go1_ready')

        self.state_period = 1.0 / float(self.get_parameter('state_rate').value)
        self.cmd_timeout = float(self.get_parameter('cmd_timeout').value)
        self.hold_kp = float(self.get_parameter('hold_kp').value)
        self.hold_kd = float(self.get_parameter('hold_kd').value)
        self.damping = float(self.get_parameter('damping').value)
        self.lowcmd_enabled = bool(self.get_parameter('lowcmd_enabled').value)
        self.timeout_action = str(self.get_parameter('timeout_action').value)

        self.rs = core.RobotState()
        self.idx = None                    # joint_states name -> индекс в порядке Unitree
        self.cmd = None                    # последний LowCmd (словарь массивов)
        self.cmd_time = None               # время приёма (сим.)
        self.hold_q = core.STAND_Q.copy()
        self.prev_dq = None
        self.prev_t = None
        self.next_state_t = 0.0
        self.last_tau = np.zeros(12)
        self.warned_timeout = False
        self.soft_start = bool(self.get_parameter('soft_start').value) and self.lowcmd_enabled
        self.ramp = core.StandRamp(self.get_parameter('rise_time').value, tol=self.get_parameter('ramp_tol').value)
        self.max_tilt = float(self.get_parameter('max_tilt').value)
        self.ready = not self.soft_start
        self.t_rise = None
        self.last_warn = {}

        qos_fast = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        qos_stream = QoSProfile(depth=20, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.create_subscription(JointState, 'joint_states', self._on_joint_states, qos_stream)
        self.create_subscription(Imu, 'imu/data', self._on_imu, 10)
        self.create_subscription(LowCmd, 'lowcmd', self._on_lowcmd, qos_stream)

        self.low_pub = self.create_publisher(LowState, 'lowstate', 10)
        self.tau_pub = self.create_publisher(Float64MultiArray, self.get_parameter('forward_topic').value, 1)
        self.ready_pub = None
        if self.soft_start:   # в режиме trajectory /go1_ready публикует soft_stand_gate
            self.ready_pub = self.create_publisher(
                Bool, self.get_parameter('ready_topic').value,
                QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL))
            self.ready_pub.publish(Bool(data=False))

        self.get_logger().info(
            f'Unitree-мост готов. lowcmd_enabled={self.lowcmd_enabled}; до первого LowCmd робот держит позу стоя '
            f'(kp={self.hold_kp}, kd={self.hold_kd}). Команды: /lowcmd (только при lowcmd_enabled); состояние: /lowstate')
        if self.soft_start:
            self.get_logger().info(
                f'Мягкий старт: плавный подъём {self.ramp.duration:.1f} с; /lowcmd игнорируется до сообщения '
                '«ГОТОВ К ДВИЖЕНИЮ» (топик /go1_ready)')

    # ----------------------------------------------------------------- вход от Gazebo
    def _now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def _on_imu(self, m: Imu):
        o, w, a = m.orientation, m.angular_velocity, m.linear_acceleration
        self.rs.quat = (o.w, o.x, o.y, o.z)
        self.rs.gyro = (w.x, w.y, w.z)
        self.rs.accel = (a.x, a.y, a.z)

    # ----------------------------------------------------------------- команды
    def _on_lowcmd(self, m: LowCmd):
        if not self.lowcmd_enabled:
            return
        if not self.ready:
            if self._throttle('lowcmd', 2.0):
                self.get_logger().warn('LowCmd проигнорирован: собака ещё встаёт (ждите «ГОТОВ К ДВИЖЕНИЮ» или /go1_ready)')
            return
        self.cmd = core.read_low_cmd(m)
        self.cmd_time = self._now()
        self.warned_timeout = False

    def _throttle(self, key, period):
        t = self._now()
        if t - self.last_warn.get(key, -1e9) >= period:
            self.last_warn[key] = t
            return True
        return False

    # ----------------------------------------------------------------- главный такт
    def _on_joint_states(self, m: JointState):
        if self.idx is None:
            try:
                names = list(m.name)
                self.idx = [names.index(n) for n in core.JOINT_NAMES]
            except ValueError:
                return
        if len(m.position) < len(m.name) or len(m.velocity) < len(m.name):
            return
        pos = np.array(m.position)[self.idx]
        vel = np.array(m.velocity)[self.idx]
        t = m.header.stamp.sec + m.header.stamp.nanosec * 1e-9
        if t == 0.0:
            t = self._now()

        # ddq конечной разностью с фильтром
        if self.prev_dq is not None and self.prev_t is not None and t > self.prev_t:
            raw = (vel - self.prev_dq) / (t - self.prev_t)
            self.rs.ddq = 0.9 * self.rs.ddq + 0.1 * raw
        self.prev_dq, self.prev_t = vel.copy(), t

        tau, servo = self._compute_torque(pos, vel)
        msg = Float64MultiArray()
        msg.data = [float(v) for v in tau]
        self.tau_pub.publish(msg)

        self.rs.q, self.rs.dq, self.rs.tau_est, self.rs.servo = pos, vel, tau, servo
        self.rs.tick_ms = int(t * 1000.0)

        # допуск в четверть периода: штампы приходят с шагом 1 мс, и строгое `t >= t0 + 2 мс`
        # из-за округления float через раз пропускает кадр (получалось ~400 Гц вместо 500)
        if t >= self.next_state_t - 0.25 * self.state_period:
            if t - self.next_state_t > 5 * self.state_period:
                self.next_state_t = t           # после паузы/перезапуска симуляции не догоняем
            self.next_state_t += self.state_period
            low = LowState()
            core.fill_low_state(low, self.rs)
            self.low_pub.publish(low)
    def _rise_torque(self, q, dq):
        """Плавный подъём в позу стоя по законам мотора Unitree с hold-коэффициентами; после него открывает LowCmd."""
        t = self._now()
        if self.ramp.state == 'idle':
            self.ramp.start(t, q, core.STAND_Q)
            self.t_rise = t
            self.get_logger().info(
                f'Подъём начат: макс. отклонение ног от позы стоя {float(np.max(np.abs(core.STAND_Q - q))):.2f} рад')
        state = self.ramp.update(t, q, dq)
        z = np.zeros(12)
        kp, kd = np.full(12, self.hold_kp), np.full(12, self.hold_kd)
        tau = core.motor_torque(np.full(12, core.MODE_SERVO), self.ramp.target(t), self.ramp.target_velocity(t), z, kp, kd, q, dq)
        if state == 'ready':
            tilt = self._tilt()
            if tilt > self.max_tilt:
                if self._throttle('failed', 5.0):
                    self.get_logger().error(
                        f'Собака не стоит (наклон {tilt:.2f} рад > {self.max_tilt:.2f}); LowCmd заблокирован. '
                        'Перезапустите симуляцию')
            else:
                self.ready = True
                self.hold_q = q.copy()
                if self.ramp.inexact:
                    self.get_logger().warn(f'Поза стоя достигнута неточно (макс. ошибка {self.ramp.max_err:.2f} рад), управление всё же разрешено')
                self.get_logger().info(
                    f'ГОТОВ К ДВИЖЕНИЮ: собака стоит (подъём {t - self.t_rise:.1f} с, макс. ошибка суставов '
                    f'{self.ramp.max_err:.3f} рад). Управление разрешено: /lowcmd')
                if self.ready_pub is not None:
                    self.ready_pub.publish(Bool(data=True))
        return tau, np.ones(12, dtype=bool)

    def _tilt(self):
        roll, pitch, _ = core.quat_to_rpy(*self.rs.quat)
        return max(abs(roll), abs(pitch))

    def _compute_torque(self, q, dq):
        z = np.zeros(12)
        if not self.ready:
            return self._rise_torque(q, dq)
        now = self._now()
        have_cmd = self.cmd is not None and self.cmd_time is not None
        fresh = have_cmd and (now - self.cmd_time) <= self.cmd_timeout

        if fresh:
            self.hold_q = q.copy()   # на случай потери связи держим последнюю позу
            c = self.cmd
            tau = core.motor_torque(c['mode'], c['q'], c['dq'], c['tau'], c['kp'], c['kd'], q, dq, damping=self.damping)
            return tau, c['mode'] == core.MODE_SERVO

        if have_cmd and not self.warned_timeout:
            self.warned_timeout = True
            self.get_logger().warn(f'LowCmd не приходит более {self.cmd_timeout} с: {self.timeout_action}')
        target = core.STAND_Q if not have_cmd else self.hold_q
        if have_cmd and self.timeout_action == 'damp':
            tau = core.motor_torque(np.zeros(12, dtype=int), z, z, z, z, z, q, dq, damping=self.damping)
            return tau, np.zeros(12, dtype=bool)
        kp = np.full(12, self.hold_kp)
        kd = np.full(12, self.hold_kd)
        tau = core.motor_torque(np.full(12, core.MODE_SERVO), target, z, z, kp, kd, q, dq)
        return tau, np.ones(12, dtype=bool)


def main():
    rclpy.init(args=sys.argv)
    node = Go1UnitreeBridge()
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
