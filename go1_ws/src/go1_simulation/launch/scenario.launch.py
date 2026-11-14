"""Go1 Developer scenarios: lowlevel (MuJoCo), highlevel (Gazebo), course (Gazebo).

  scenario:=course width:=1.0|2.0  - sketch-based obstacle course with ArUco markers.
  scenario:=highlevel            - odometry validation room and CHAMP.
  scenario:=lowlevel             - MuJoCo LowCmd / LowState.

  ros2 launch go1_simulation scenario.launch.py scenario:=course width:=1.0 gui:=true
  ros2 launch go1_simulation scenario.launch.py scenario:=course width:=2.0 gui:=true

Nav2 is intentionally NOT started by scenario:=course. Ground truth remains a
validation topic without odom->robot TF.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare

SCENARIOS = ('lowlevel', 'highlevel', 'course')
COURSE_WIDTHS = {'1.0': 'course_w10', '2.0': 'course_w20'}

def _norm_width(text):
    try:
        key = f'{float(text):.1f}'
    except ValueError:
        key = text
    if key not in COURSE_WIDTHS:
        raise RuntimeError(f"width должен быть одним из {sorted(COURSE_WIDTHS)} (ширина прохода, м), получено: {text}")
    return key


def _setup(context):
    cfg = lambda n: LaunchConfiguration(n).perform(context)  # noqa: E731
    scenario = cfg('scenario')
    if scenario not in SCENARIOS:
        raise RuntimeError(f"scenario должен быть одним из {SCENARIOS}, получено: {scenario}")
    truthy = lambda n: cfg(n).lower() in ('true', '1')  # noqa: E731
    sim_share = FindPackageShare('go1_simulation')

    if scenario == 'lowlevel':
        # Lowlevel не может запускаться через Gazebo независимо от внешних аргументов.
        return [IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([sim_share, 'launch', 'mujoco.launch.py'])),
            launch_arguments={
                'box': 'true' if truthy('on_box') or truthy('box') else 'false',
                'flip': cfg('flip'),
                'headless': 'false' if truthy('gui') else 'true',
            }.items())]

    def auto(name, default_on):
        """'auto' -> значение по умолчанию сценария; иначе true/false как задано."""
        v = cfg(name).lower()
        return str(default_on).lower() if v == 'auto' else ('true' if v in ('true', '1') else 'false')

    # Лидар включён по умолчанию для Highlevel и Course.
    lidar = auto('lidar', True)
    cameras = auto('cameras', scenario != 'lowlevel')
    rgbd = auto('rgbd_camera', scenario != 'lowlevel')
    common = {'lockstep': cfg('lockstep'), 'gui': cfg('gui'), 'verbose': cfg('verbose'),
              'lidar': lidar, 'rgbd_camera': rgbd, 'unitree_cameras': cameras,
              'unitree_cam_width': cfg('cam_width'), 'unitree_cam_height': cfg('cam_height'), 'unitree_cam_rate': cfg('cam_rate'),
              'soft_start': cfg('soft_start'), 'rise_time': cfg('rise_time')}
    actions = []

    # высокий уровень: ходит champ
    args = dict(common, champ='true')
    launch_file = 'go1_simulation.launch.py'
    if scenario == 'course':
        width = f"{float(cfg('width')):.1f}"
        if width not in COURSE_WIDTHS:
            raise RuntimeError(f'course width must be 1.0 or 2.0, got {cfg("width")}')
        args['world'] = COURSE_WIDTHS[width]
        args.update(world_init_x=cfg('start_x'), world_init_y=cfg('start_y'), world_init_heading=cfg('start_yaw'))
    else:
        args['world'] = cfg('world')

    actions.append(IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution([sim_share, 'launch', launch_file])),
        launch_arguments=args.items()))

    if scenario == 'course' and truthy('auto_goal'):
        # Timer starts when the course launch brings up Gazebo, NOT when Nav2 becomes ready.
        # The sender then waits for a subscriber to avoid losing the one-shot goal.
        actions.append(TimerAction(period=15.0, actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(PathJoinSubstitution([sim_share, 'launch', 'goal_sender.launch.py'])),
                launch_arguments={'width': width}.items()),
        ]))

    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('scenario', default_value='course', description='lowlevel | highlevel | course'),
        DeclareLaunchArgument('gui', default_value='true', description='Окно Gazebo'),
        DeclareLaunchArgument('verbose', default_value='false'),
        DeclareLaunchArgument('lockstep', default_value=EnvironmentVariable('GO1_GAZEBO_LOCKSTEP', default_value='false'),
                              choices=['true', 'false'], description='Gazebo only: synchronize sensors with simulation time'),
        DeclareLaunchArgument('world', default_value='odom_validation',
                              description='Мир для highlevel (для course выбирается по width)'),
        DeclareLaunchArgument('box', default_value='false', description='lowlevel: синоним on_box'),
        DeclareLaunchArgument('on_box', default_value='false', description='lowlevel: собака на подставке (MuJoCo)'),
        DeclareLaunchArgument('flip', default_value='false', description='lowlevel + on_box: на спине (по умолчанию лапами вниз)'),
        DeclareLaunchArgument('width', default_value='1.0', description='course: 1.0 или 2.0 м'),
        DeclareLaunchArgument('auto_goal', default_value='true',
                              description='course: отправить /goal_pose спустя 15 секунд после запуска сцены'),
        DeclareLaunchArgument('start_x', default_value='0.0', description='course: x позиции спавна, м; по умолчанию старт (0,0)'),
        DeclareLaunchArgument('start_y', default_value='0.0'),
        DeclareLaunchArgument('start_yaw', default_value='0.0'),
        DeclareLaunchArgument('lidar', default_value='auto', description='auto (включён для Highlevel/Course) | true | false'),
        DeclareLaunchArgument('cameras', default_value='auto', description='4 камеры Unitree: auto (в lowlevel выкл.) | true | false'),
        DeclareLaunchArgument('rgbd_camera', default_value='auto', description='фронтальная RGB-D: auto (в lowlevel выкл.) | true | false'),
        DeclareLaunchArgument('cam_width', default_value='464', description='ширина кадра камер Unitree (у робота 928)'),
        DeclareLaunchArgument('cam_height', default_value='400', description='высота кадра (у робота 800)'),
        DeclareLaunchArgument('cam_rate', default_value='10', description='частота камер Unitree, Гц (у робота 16)'),
        DeclareLaunchArgument('soft_start', default_value='true',
                              description='плавный подъём в позу стоя; команды блокированы до сообщения «ГОТОВ К ДВИЖЕНИЮ» и топика /go1_ready'),
        DeclareLaunchArgument('rise_time', default_value='2.5', description='длительность подъёма, с'),
        OpaqueFunction(function=_setup),
    ])
