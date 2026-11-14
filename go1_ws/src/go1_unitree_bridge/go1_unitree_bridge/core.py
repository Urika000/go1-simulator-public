"""Общая логика Unitree-интерфейса Go1 (без зависимости от ROS: легко тестируется).

Порядок моторов как у Unitree:
    0..2  FR hip, thigh, calf     3..5  FL     6..8  RR     9..11  RL
В сообщениях unitree_go/LowCmd и LowState массивы motor_cmd / motor_state имеют 20 слотов, используются первые 12.
"""
import math
from dataclasses import dataclass, field

import numpy as np

LEG_ORDER = ['FR', 'FL', 'RR', 'RL']
JOINT_KINDS = ['hip', 'thigh', 'calf']
JOINT_NAMES = [f'{leg}_{kind}_joint' for leg in LEG_ORDER for kind in JOINT_KINDS]
N_MOTORS = 12
N_SLOTS = 20

# Признаки "параметр не используется" в Unitree SDK: PosStopF = 2.146e9 , VelStopF = 16000
POS_STOP_THRESHOLD = 1.0e8
VEL_STOP_THRESHOLD = 1.0e4

MODE_DAMPING = 0x00
MODE_SERVO = 0x0A

# Пределы моментов Go1 (hip, thigh 23.7 Н*м, calf 35.55 Н*м)
TORQUE_LIMIT = np.array([23.7, 23.7, 35.55] * 4)

# Поза стоя (как initial_value в ros2_control и стартовая поза в Gazebo)
STAND_Q = np.array([0.0, 0.8536, -1.7072] * 4)

# Геометрия (из go1_description/urdf/const.xacro)
LEG_OFFSET_X = 0.1881
LEG_OFFSET_Y = 0.04675
HIP_OFFSET = 0.08          # смещение thigh по y от оси hip
THIGH_LENGTH = 0.213
CALF_LENGTH = 0.213
# (front_hind, mirror) для ног в порядке Unitree: FR, FL, RR, RL
_LEG_SIGNS = [(+1, -1), (+1, +1), (-1, -1), (-1, +1)]


def motor_torque(mode, q_des, dq_des, tau_ff, kp, kd, q, dq, damping=1.0, limit=TORQUE_LIMIT):
    """Закон управления мотором Unitree: tau = tau_ff + kp*(q_des - q) + kd*(dq_des - dq).

    q_des >= PosStop  -> позиционная часть выключена; dq_des >= VelStop -> целевая скорость 0 (остаётся демпфирование kd).
    mode != 0x0A (servo) -> пассивное демпфирование -damping*dq. Результат ограничен пределами моментов.
    """
    mode = np.asarray(mode)
    q_des, dq_des, tau_ff = (np.asarray(v, dtype=float) for v in (q_des, dq_des, tau_ff))
    kp, kd, q, dq = (np.asarray(v, dtype=float) for v in (kp, kd, q, dq))
    pos_on = np.abs(q_des) < POS_STOP_THRESHOLD
    dq_target = np.where(np.abs(dq_des) < VEL_STOP_THRESHOLD, dq_des, 0.0)
    tau_servo = tau_ff + np.where(pos_on, kp * (q_des - q), 0.0) + kd * (dq_target - dq)
    tau = np.where(mode == MODE_SERVO, tau_servo, -damping * dq)
    return np.clip(tau, -limit, limit)


def smoothstep(u):
    """s(u) = 3u^2 - 2u^3 на [0, 1]: нулевая скорость в начале и в конце."""
    u = min(1.0, max(0.0, float(u)))
    return u * u * (3.0 - 2.0 * u)


def smoothstep_rate(u):
    """ds/du = 6u(1 - u)."""
    u = min(1.0, max(0.0, float(u)))
    return 6.0 * u * (1.0 - u)


class StandRamp:
    """Плавный подъём в позу стоя: q_des(t) = q0 + (q1 - q0) * s((t - t0) / T), s(u) = 3u^2 - 2u^3.

    Состояния: 'idle' -> 'ramp' (идёт подъём) -> 'settle' (цель достигнута, ждём, пока ноги успокоятся) -> 'ready'.
    Если за timeout_extra секунд после конца подъёма ноги так и не пришли в позу, состояние всё равно становится
    'ready', но флаг `inexact` остаётся True (и узел пишет предупреждение), чтобы управление не блокировалось навсегда.
    Время только по часам симуляции, ROS не нужен.
    """

    def __init__(self, duration=2.5, settle=0.5, tol=0.15, vel_tol=0.3, timeout_extra=4.0):
        self.duration, self.settle, self.tol = float(duration), float(settle), float(tol)
        self.vel_tol, self.timeout_extra = float(vel_tol), float(timeout_extra)
        self.state = 'idle'
        self.inexact = False
        self.max_err = 0.0
        self.t0 = 0.0
        self.q0 = None
        self.q1 = None
        self._ok_since = None

    def start(self, t, q0, q1):
        self.t0 = float(t)
        self.q0 = np.array(q0, dtype=float)
        self.q1 = np.array(q1, dtype=float)
        self.state = 'ramp'
        self.inexact = False
        self._ok_since = None

    def _u(self, t):
        return (t - self.t0) / self.duration

    def target(self, t):
        """Желаемые углы в момент t."""
        return self.q0 + (self.q1 - self.q0) * smoothstep(self._u(t))

    def target_velocity(self, t):
        """Желаемые скорости в момент t (рад/с)."""
        return (self.q1 - self.q0) * smoothstep_rate(self._u(t)) / self.duration

    def update(self, t, q, dq):
        """Продвигает состояние по измеренным q, dq; возвращает текущее состояние."""
        if self.state in ('idle', 'ready'):
            return self.state
        q, dq = np.asarray(q, dtype=float), np.asarray(dq, dtype=float)
        self.max_err = float(np.max(np.abs(q - self.q1)))
        elapsed = t - self.t0
        if elapsed < self.duration:
            return self.state
        self.state = 'settle'
        ok = self.max_err <= self.tol and float(np.max(np.abs(dq))) <= self.vel_tol
        if ok:
            if self._ok_since is None:
                self._ok_since = t
            if t - self._ok_since >= self.settle:
                self.state = 'ready'
        else:
            self._ok_since = None
            if elapsed >= self.duration + self.timeout_extra:
                self.state = 'ready'
                self.inexact = True
        return self.state


def foot_positions_body(q):
    """Положение стоп относительно центра корпуса (trunk), ноги в порядке Unitree. q: 12 углов -> массив (4, 3)."""
    q = np.asarray(q, dtype=float).reshape(4, 3)
    out = np.zeros((4, 3))
    for i, (fh, m) in enumerate(_LEG_SIGNS):
        q0, q1, q2 = q[i]
        x = -THIGH_LENGTH * math.sin(q1) - CALF_LENGTH * math.sin(q1 + q2)
        y = m * HIP_OFFSET
        z = -THIGH_LENGTH * math.cos(q1) - CALF_LENGTH * math.cos(q1 + q2)
        c, s = math.cos(q0), math.sin(q0)
        out[i] = [fh * LEG_OFFSET_X + x,
                  m * LEG_OFFSET_Y + c * y - s * z,
                  s * y + c * z]
    return out


def foot_speeds_body(q, dq, eps=1e-5):
    """Скорость стоп в системе корпуса (только за счёт движения суставов)."""
    q = np.asarray(q, dtype=float)
    dq = np.asarray(dq, dtype=float)
    return (foot_positions_body(q + eps * dq) - foot_positions_body(q)) / eps


def quat_to_rpy(w, x, y, z):
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    sinp = max(-1.0, min(1.0, 2 * (w * y - z * x)))
    pitch = math.asin(sinp)
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return roll, pitch, yaw


@dataclass
class RobotState:
    """Измеряемые данные для LowState. Единицы СИ, кватернион (w, x, y, z)."""
    q: np.ndarray = field(default_factory=lambda: STAND_Q.copy())
    dq: np.ndarray = field(default_factory=lambda: np.zeros(12))
    ddq: np.ndarray = field(default_factory=lambda: np.zeros(12))
    tau_est: np.ndarray = field(default_factory=lambda: np.zeros(12))
    servo: np.ndarray = field(default_factory=lambda: np.zeros(12, dtype=bool))
    quat: tuple = (1.0, 0.0, 0.0, 0.0)
    gyro: tuple = (0.0, 0.0, 0.0)
    accel: tuple = (0.0, 0.0, 0.0)
    foot_force: tuple = (0, 0, 0, 0)
    tick_ms: int = 0
    wireless_remote: bytes = bytes(40)


def _set_imu(imu, rs: RobotState):
    imu.quaternion = [float(v) for v in rs.quat]
    imu.gyroscope = [float(v) for v in rs.gyro]
    imu.accelerometer = [float(v) for v in rs.accel]
    imu.rpy = [float(v) for v in quat_to_rpy(*rs.quat)]
    imu.temperature = 0  # температура IMU не моделируется


def fill_low_state(msg, rs: RobotState):
    """Заполняет unitree_go/LowState (или объект с теми же полями)."""
    msg.head = [0xFE, 0xEF]
    msg.level_flag = 0xFF
    _set_imu(msg.imu_state, rs)
    for i in range(N_MOTORS):
        m = msg.motor_state[i]
        m.mode = MODE_SERVO if rs.servo[i] else MODE_DAMPING
        m.q = float(rs.q[i])
        m.dq = float(rs.dq[i])
        m.ddq = float(rs.ddq[i])
        m.tau_est = float(rs.tau_est[i])
        m.q_raw = 0.0  # отдельных сырых данных энкодеров нет
        m.dq_raw = 0.0
        m.ddq_raw = 0.0
        m.temperature = 0
        m.lost = 0
    # Аккумулятор и силовая электроника не моделируются.
    msg.bms_state.soc = 0
    msg.bms_state.current = 0
    msg.bms_state.cell_vol = [0] * len(msg.bms_state.cell_vol)
    msg.foot_force = [int(v) for v in rs.foot_force]  # MuJoCo: контактная реакция; Gazebo: неизвестно (0)
    msg.foot_force_est = [0] * len(msg.foot_force_est)  # отдельной оценки сил нет
    msg.tick = int(rs.tick_ms) & 0xFFFFFFFF
    msg.wireless_remote = list(rs.wireless_remote)
    msg.power_v = 0.0
    msg.power_a = 0.0
    msg.temperature_ntc1 = 0
    msg.temperature_ntc2 = 0
    return msg


def read_low_cmd(msg):
    """Из unitree_go/LowCmd -> словарь массивов длиной 12 (mode, q, dq, tau, kp, kd)."""
    cmds = msg.motor_cmd[:N_MOTORS]
    return {
        'mode': np.array([c.mode for c in cmds], dtype=int),
        'q': np.array([c.q for c in cmds], dtype=float),
        'dq': np.array([c.dq for c in cmds], dtype=float),
        'tau': np.array([c.tau for c in cmds], dtype=float),
        'kp': np.array([c.kp for c in cmds], dtype=float),
        'kd': np.array([c.kd for c in cmds], dtype=float),
    }


def foot_force_from_contacts(contacts, value=100):
    """Контакты champ [LF, RF, LH, RH] (bool) -> foot_force в порядке Unitree [FR, FL, RR, RL]."""
    lf, rf, lh, rh = (bool(c) for c in contacts)
    return (value if rf else 0, value if lf else 0, value if rh else 0, value if lh else 0)
