"""Проверки мягкого старта без ROS: python3 test/test_soft_stand.py

1. ядро плавного подъёма core.StandRamp (формула, состояния, таймаут);
2. законы подъёма на упрощённой модели ноги: рывка моментов нет, поза достигается;
3. логика узла soft_stand_gate на заглушках rclpy: ворота закрыты до конца подъёма, после него открываются.
"""
import importlib.util
import os
import sys
import types

import numpy as np

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, '..'))
from go1_unitree_bridge import core  # noqa: E402


# ---------------------------------------------------------------------------------------------------- 1. ядро
def test_smoothstep():
    assert core.smoothstep(0.0) == 0.0 and core.smoothstep(1.0) == 1.0 and abs(core.smoothstep(0.5) - 0.5) < 1e-12
    assert core.smoothstep(-1) == 0.0 and core.smoothstep(2) == 1.0
    h = 1e-6
    for u in (0.1, 0.3, 0.7):   # ds/du совпадает с численной производной
        num = (core.smoothstep(u + h) - core.smoothstep(u - h)) / (2 * h)
        assert abs(num - core.smoothstep_rate(u)) < 1e-6
    assert core.smoothstep_rate(0.0) == 0.0 and core.smoothstep_rate(1.0) == 0.0
    print('smoothstep: ok')


def test_ramp_target():
    q0 = np.array([0.0, 1.2, -2.7] * 4)
    r = core.StandRamp(duration=2.0)
    r.start(10.0, q0, core.STAND_Q)
    assert np.allclose(r.target(10.0), q0)
    assert np.allclose(r.target(12.0), core.STAND_Q) and np.allclose(r.target(20.0), core.STAND_Q)
    assert np.allclose(r.target(11.0), (q0 + core.STAND_Q) / 2)            # середина: s(0.5) = 0.5
    assert np.allclose(r.target_velocity(10.0), 0.0) and np.allclose(r.target_velocity(12.0), 0.0)
    # скорость = производная цели
    h = 1e-5
    num = (r.target(11.3 + h) - r.target(11.3 - h)) / (2 * h)
    assert np.allclose(num, r.target_velocity(11.3), atol=1e-5)
    print('ramp target: ok')


def _follow(r, q, dq, t):
    """Нога идеально идёт за целью (проверка конечного автомата)."""
    return r.update(t, q, dq)


def test_ramp_states():
    q0 = np.array([0.0, 1.2, -2.7] * 4)
    r = core.StandRamp(duration=2.0, settle=0.5, tol=0.1, vel_tol=0.3, timeout_extra=3.0)
    assert r.update(0.0, q0, np.zeros(12)) == 'idle'
    r.start(0.0, q0, core.STAND_Q)
    assert r.update(1.0, q0, np.zeros(12)) == 'ramp'
    assert r.update(2.0, core.STAND_Q + 0.5, np.zeros(12)) == 'settle'       # далеко от позы: ждём
    assert r.update(2.1, core.STAND_Q, np.zeros(12)) == 'settle'             # пришла, но ещё не 0.5 с
    assert r.update(2.4, core.STAND_Q, np.zeros(12)) == 'settle'
    assert r.update(2.7, core.STAND_Q, np.zeros(12)) == 'ready' and not r.inexact
    # движущиеся ноги не считаются успокоившимися
    r.start(0.0, q0, core.STAND_Q)
    assert r.update(2.1, core.STAND_Q, np.full(12, 1.0)) == 'settle'
    assert r.update(3.0, core.STAND_Q, np.full(12, 1.0)) == 'settle'
    # таймаут: не блокируем навсегда, но помечаем неточность
    r.start(0.0, q0, core.STAND_Q)
    assert r.update(4.9, q0, np.zeros(12)) == 'settle'
    assert r.update(5.1, q0, np.zeros(12)) == 'ready' and r.inexact and r.max_err > 0.9
    print('ramp states: ok')


# ---------------------------------------------------------------------------------------------------- 2. модель ноги
def _simulate_leg(snap, T=2.5, kp=40.0, kd=2.0, inertia=0.05, dt=0.001, t_end=6.0):
    """12 независимых суставов, инерция I, постоянный момент тяжести (голень -5 Н*м, бедро 0); PD по закону Unitree.
    snap=True - как раньше: мгновенная цель = поза стоя; snap=False - плавный подъём."""
    q = np.array([0.0, 1.2, -2.7] * 4)
    dq = np.zeros(12)
    grav = np.array([0.0, 0.0, -5.0] * 4)
    r = core.StandRamp(duration=T, tol=0.25)
    r.start(0.0, q, core.STAND_Q)
    t, max_tau, ready_t = 0.0, 0.0, None
    prev_tau = None
    max_jump = 0.0
    while t < t_end:
        if snap:
            tgt, dtgt = core.STAND_Q, np.zeros(12)
        else:
            tgt, dtgt = r.target(t), r.target_velocity(t)
        tau = core.motor_torque(np.full(12, core.MODE_SERVO), tgt, dtgt, np.zeros(12),
                                np.full(12, kp), np.full(12, kd), q, dq)
        if prev_tau is not None:
            max_jump = max(max_jump, float(np.max(np.abs(tau - prev_tau))))
        prev_tau = tau
        max_tau = max(max_tau, float(np.max(np.abs(tau) / core.TORQUE_LIMIT)))
        ddq = (tau + grav) / inertia
        dq = dq + ddq * dt
        q = q + dq * dt
        t += dt
        if not snap and ready_t is None and r.update(t, q, dq) == 'ready':
            ready_t = t
    return q, max_tau, ready_t, max_jump


def test_leg_model():
    q_s, tau_s, _, _ = _simulate_leg(snap=True)
    q_r, tau_r, ready_t, jump_r = _simulate_leg(snap=False)
    # рывок: раньше момент упирался в предел сразу (ошибка 1 рад * kp), сейчас он нарастает плавно
    assert tau_s >= 0.99, tau_s
    assert tau_r < tau_s, (tau_r, tau_s)
    assert jump_r < 0.5, jump_r                 # Н*м за 1 мс
    # поза достигнута, подъём завершился за разумное время
    assert np.max(np.abs(q_r - core.STAND_Q)) < 0.25
    assert ready_t is not None and 2.5 <= ready_t <= 5.0, ready_t
    print(f'leg model: snap max tau {tau_s:.2f} of limit, ramp {tau_r:.2f}, ready at {ready_t:.2f} s: ok')


# ---------------------------------------------------------------------------------------------------- 3. узел-ворота
class _Msg:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _install_stubs():
    """Заглушки rclpy и сообщений ровно в объёме, который использует soft_stand_gate.py."""
    mods = {}

    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        mods[name] = m
        return m

    class Clock:
        def __init__(self, node):
            self.node = node

        def now(self):
            return _Msg(nanoseconds=int(self.node.t * 1e9))

    class Pub:
        def __init__(self):
            self.sent = []

        def publish(self, m):
            self.sent.append(m)

    class Logger:
        def __init__(self):
            self.lines = []

        def _w(self, lvl, m):
            self.lines.append((lvl, m))

        def info(self, m):
            self._w('info', m)

        def warn(self, m):
            self._w('warn', m)

        def error(self, m):
            self._w('error', m)

    class Client:
        def __init__(self):
            self.active = False
            self.ready = True

        def service_is_ready(self):
            return self.ready

        def call_async(self, req):
            fut = _Msg()
            fut.done = lambda: True
            ctrl = _Msg(name='joint_group_effort_controller', state='active' if self.active else 'inactive')
            fut.result = lambda: _Msg(controller=[ctrl])
            return fut

    class Node:
        def __init__(self, name):
            self.t = 0.0
            self.params = {}
            self.log = Logger()
            self.pubs = {}
            self.subs = {}
            self.timers = []
            self.client = Client()

        def declare_parameter(self, n, v):
            self.params[n] = v

        def get_parameter(self, n):
            return _Msg(value=self.params[n])

        def get_logger(self):
            return self.log

        def get_clock(self):
            return Clock(self)

        def create_publisher(self, typ, topic, qos):
            self.pubs[topic] = Pub()
            return self.pubs[topic]

        def create_subscription(self, typ, topic, cb, qos):
            self.subs[topic] = cb

        def create_timer(self, period, cb):
            self.timers.append(cb)

        def create_client(self, typ, name):
            return self.client

    class Duration:
        def __init__(self, seconds=0.0):
            self.s = seconds

        def to_msg(self):
            return self.s

    mod('rclpy', init=lambda *a, **k: None, spin=lambda *a, **k: None, ok=lambda: True, try_shutdown=lambda: None)
    mod('rclpy.node', Node=Node)
    mod('rclpy.duration', Duration=Duration)
    mod('rclpy.qos', QoSProfile=lambda **k: None,
        ReliabilityPolicy=_Msg(RELIABLE=1, BEST_EFFORT=2), DurabilityPolicy=_Msg(TRANSIENT_LOCAL=1))
    mod('controller_manager_msgs')
    mod('controller_manager_msgs.srv', ListControllers=_Msg(Request=lambda: None))
    mod('geometry_msgs')
    mod('geometry_msgs.msg', Pose=lambda: _Msg(), Twist=lambda: _Msg(linear=_Msg(x=0, y=0, z=0), angular=_Msg(x=0, y=0, z=0)))
    mod('nav_msgs')
    mod('nav_msgs.msg', Odometry=object)
    mod('sensor_msgs')
    mod('sensor_msgs.msg', JointState=object, Imu=object)
    mod('std_msgs')
    mod('std_msgs.msg', Bool=lambda data=False: _Msg(data=data), Float64MultiArray=lambda: _Msg(data=[]))
    mod('champ_msgs')
    mod('champ_msgs.msg', ContactsStamped=object)
    mod('unitree_go')
    mod('unitree_go.msg', LowCmd=object, LowState=object)
    mod('trajectory_msgs')
    mod('trajectory_msgs.msg', JointTrajectory=lambda: _Msg(joint_names=[], points=[]),
        JointTrajectoryPoint=lambda: _Msg(positions=[], velocities=[], time_from_start=None))
    saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)
    return saved


def _load_script(name):
    saved = _install_stubs()
    try:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, '..', 'scripts', name + '.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _load_gate():
    return _load_script('soft_stand_gate')


NAMES = [f'{leg}_{k}_joint' for leg in ('FL', 'FR', 'RL', 'RR') for k in ('hip', 'thigh', 'calf')]
STAND = np.array([0.0, 0.8536, -1.7072] * 4)
FOLDED = np.array([0.0, 1.2, -2.7] * 4)


def _raw_msg():
    return _Msg(joint_names=list(NAMES), points=[_Msg(positions=[float(v) for v in STAND])])


def _js_msg(q, dq=None):
    dq = np.zeros(12) if dq is None else dq
    return _Msg(name=list(NAMES), position=[float(v) for v in q], velocity=[float(v) for v in dq])


def _twist(x):
    return _Msg(linear=_Msg(x=x, y=0.0, z=0.0), angular=_Msg(x=0, y=0, z=0.0))


def _run(gate, node, g, q, seconds, active, dt=0.01, tau_follow=0.15):
    """Крутит узел по времени симуляции; ноги догоняют цель из последней опубликованной траектории (инерция первого порядка)."""
    node.client.active = active
    steps = int(seconds / dt)
    for _ in range(steps):
        node.t += dt
        node.subs['joint_states'](_js_msg(q))
        node.subs['/champ/joint_trajectory'](_raw_msg())
        out = node.pubs['/joint_group_effort_controller/joint_trajectory'].sent
        if out and g.phase != 'ready':
            q = q + (np.array(out[-1].points[0].positions) - q) * dt / tau_follow
        elif g.phase == 'ready':
            q = STAND.copy()
        for cb in node.timers:
            cb()
    return q


def test_gate_flow():
    gate = _load_gate()
    g = gate.SoftStandGate()     # наследует заглушечный Node
    node = g
    node.t = 100.0
    ready_pub = node.pubs['/go1_ready']
    assert ready_pub.sent[-1].data is False

    # до подъёма: движение игнорируется и предупреждает, ворота закрыты
    node.subs['/cmd_vel'](_twist(0.3))
    assert node.pubs['/cmd_vel_gated'].sent == []
    assert any(l == 'warn' and 'проигнорирована' in m for l, m in node.log.lines)
    node.subs['/champ/joint_trajectory'](_raw_msg())
    assert node.pubs['/joint_group_effort_controller/joint_trajectory'].sent == []

    # контроллер не активен: ждём (не раньше active_fallback)
    q = _run(gate, node, g, FOLDED.copy(), 3.0, active=False)
    assert g.phase == 'wait' and not node.pubs['/joint_group_effort_controller/joint_trajectory'].sent

    # контроллер активен: подъём -> ready
    q = _run(gate, node, g, q, 1.0, active=True)
    assert g.phase == 'rise', g.phase
    first = node.pubs['/joint_group_effort_controller/joint_trajectory'].sent[0]
    assert np.max(np.abs(np.array(first.points[0].positions) - FOLDED)) < 0.1     # старт из фактической позы, без рывка
    node.subs['/cmd_vel'](_twist(0.3))
    assert node.pubs['/cmd_vel_gated'].sent == []
    q = _run(gate, node, g, q, 4.0, active=True)
    assert g.phase == 'ready', (g.phase, node.log.lines[-3:])
    assert ready_pub.sent[-1].data is True
    assert any(l == 'info' and 'ГОТОВ К ДВИЖЕНИЮ' in m for l, m in node.log.lines)

    # после готовности: траектории champ, cmd_vel и body_pose проходят
    n_out = len(node.pubs['/joint_group_effort_controller/joint_trajectory'].sent)
    node.subs['/champ/joint_trajectory'](_raw_msg())
    assert len(node.pubs['/joint_group_effort_controller/joint_trajectory'].sent) == n_out + 1
    node.subs['/cmd_vel'](_twist(0.3))
    assert node.pubs['/cmd_vel_gated'].sent[-1].linear.x == 0.3
    node.subs['/body_pose'](_Msg(z=1))
    assert len(node.pubs['/body_pose_gated'].sent) == 1
    print('gate flow: ok')


def test_gate_fallback_and_tilt():
    gate = _load_gate()
    # сервис контроллеров недоступен: через active_fallback секунд подъём всё равно начинается (с предупреждением)
    g = gate.SoftStandGate()
    g.t = 50.0
    g.client.ready = False
    q = _run(gate, g, g, FOLDED.copy(), 9.0, active=False)
    assert g.phase in ('rise', 'ready'), g.phase
    assert any(l == 'warn' and 'не подтверждена' in m for l, m in g.log.lines)

    # собака наклонена: «готов» не объявляется, ворота закрыты, в логе ошибка
    g2 = gate.SoftStandGate()
    g2.t = 10.0
    g2.tilt = 2.0
    q = _run(gate, g2, g2, FOLDED.copy(), 8.0, active=True)
    assert g2.phase == 'failed', g2.phase
    assert g2.pubs['/go1_ready'].sent[-1].data is False
    g2.subs['/cmd_vel'](_twist(0.3))
    assert g2.pubs['/cmd_vel_gated'].sent == []
    print('gate fallback + tilt: ok')


def _lowcmd(q_des):
    cmds = [_Msg(mode=core.MODE_SERVO, q=float(q_des[i]), dq=0.0, tau=0.0, kp=40.0, kd=2.0) for i in range(12)]
    return _Msg(motor_cmd=cmds + [_Msg(mode=0, q=0.0, dq=0.0, tau=0.0, kp=0.0, kd=0.0)] * 8)


def test_bridge_soft_start():
    """Мост в режиме lowcmd: подъём из сложенной позы, /lowcmd игнорируется до «ГОТОВ К ДВИЖЕНИЮ», потом принимается."""
    bridge_mod = _load_script('sim_bridge_node')
    b = bridge_mod.Go1UnitreeBridge()
    b.next_state_t = 1e18                        # LowState в этом тесте не заполняем
    assert b.soft_start and not b.ready
    q, dq = np.array([0.0, 1.2, -2.7] * 4), np.zeros(12)
    grav = np.array([0.0, 0.0, -5.0] * 4)
    dt, inertia = 0.001, 0.05
    b.t = 200.0
    b._on_lowcmd(_lowcmd(core.STAND_Q))          # до подъёма
    assert b.cmd is None and any('LowCmd проигнорирован' in m for _, m in b.log.lines)
    max_tau = 0.0
    ready_at = None
    for i in range(int(6.0 / dt)):
        b.t += dt
        sec = int(b.t)
        js = _Msg(name=list(core.JOINT_NAMES), position=[float(v) for v in q], velocity=[float(v) for v in dq],
                  header=_Msg(stamp=_Msg(sec=sec, nanosec=int((b.t - sec) * 1e9))))
        b._on_joint_states(js)
        tau = np.array(b.pubs['/joint_group_effort_forward_controller/commands'].sent[-1].data)
        max_tau = max(max_tau, float(np.max(np.abs(tau) / core.TORQUE_LIMIT)))
        dq = dq + (tau + grav) / inertia * dt
        q = q + dq * dt
        if b.ready and ready_at is None:
            ready_at = b.t - 200.0
    assert b.ready and 2.5 <= ready_at <= 5.0, ready_at
    assert max_tau < 0.5, max_tau                # рывка до предела момента нет
    assert any('ГОТОВ К ДВИЖЕНИЮ' in m for _, m in b.log.lines)
    assert b.pubs['/go1_ready'].sent[-1].data is True
    b._on_lowcmd(_lowcmd(core.STAND_Q))          # после подъёма принимается
    assert b.cmd is not None
    print(f'bridge soft start: ready at {ready_at:.2f} s, max tau {max_tau:.2f} of limit: ok')


if __name__ == '__main__':
    test_smoothstep()
    test_ramp_target()
    test_ramp_states()
    test_leg_model()
    test_gate_flow()
    test_gate_fallback_and_tilt()
    test_bridge_soft_start()
    print('ALL OK')
