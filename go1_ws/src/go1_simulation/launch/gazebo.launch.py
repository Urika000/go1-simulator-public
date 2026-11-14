"""Gazebo Classic + спавн Go1 + контроллеры ros2_control.

Сам по себе этот launch-файл не запускает champ и robot_state_publisher: топик /robot_description
берётся оттуда, поэтому обычно используют go1_simulation.launch.py, который запускает всё вместе.

ros2 launch go1_simulation gazebo.launch.py world:=playground gui:=false
"""
import os
import tempfile

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


_BOX_SDF = '''<?xml version="1.0"?>
<sdf version="1.6">
  <model name="support_box">
    <static>true</static>
    <link name="link">
      <collision name="collision">
        <geometry><box><size>{size}</size></box></geometry>
        <surface><friction><ode><mu>1.0</mu><mu2>1.0</mu2></ode></friction></surface>
      </collision>
      <visual name="visual">
        <geometry><box><size>{size}</size></box></geometry>
        <material><ambient>0.8 0.5 0.2 1</ambient><diffuse>0.8 0.5 0.2 1</diffuse></material>
      </visual>
    </link>
  </model>
</sdf>
'''


def _resolve_world(context):
    """world:=playground -> .../go1_simulation/worlds/playground.world; полный путь остаётся как есть."""
    world = LaunchConfiguration('world').perform(context)
    if os.sep not in world:
        name = world if world.endswith('.world') else world + '.world'
        world = os.path.join(get_package_share_directory('go1_simulation'), 'worlds', name)
    if not os.path.isfile(world):
        raise RuntimeError(f'Файл мира не найден: {world}')

    gazebo_ros = FindPackageShare('gazebo_ros')
    sim_share = FindPackageShare('go1_simulation')
    use_sim_time = LaunchConfiguration('use_sim_time')

    gzserver = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution([gazebo_ros, 'launch', 'gzserver.launch.py'])),
        launch_arguments={
            'world': world,
            'lockstep': LaunchConfiguration('lockstep'),
            'verbose': LaunchConfiguration('verbose'),
            'pause': LaunchConfiguration('paused'),
            'params_file': PathJoinSubstitution([sim_share, 'config', 'gazebo.yaml']),
        }.items(),
    )
    gzclient = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution([gazebo_ros, 'launch', 'gzclient.launch.py'])),
        launch_arguments={'verbose': LaunchConfiguration('verbose')}.items(),
        condition=IfCondition(LaunchConfiguration('gui')),
    )

    spawn_robot = Node(
        package='gazebo_ros',
        executable='spawn_entity.py',
        output='screen',
        arguments=[
            '-entity', LaunchConfiguration('robot_name'),
            '-topic', '/robot_description',
            '-x', LaunchConfiguration('world_init_x'),
            '-y', LaunchConfiguration('world_init_y'),
            '-z', LaunchConfiguration('world_init_z'),
            '-R', LaunchConfiguration('world_init_roll'), '-P', '0',
            '-Y', LaunchConfiguration('world_init_heading'),
        ],
    )

    # Опционально: неподвижная подставка (параллелепипед) под корпусом. Её спавним первой,
    # а робота - только после завершения спавна подставки, чтобы он не успел упасть на землю.
    actions = [gzserver, gzclient]
    if LaunchConfiguration('support_box').perform(context).lower() in ('true', '1'):
        size = LaunchConfiguration('box_size').perform(context).split()
        if len(size) != 3:
            raise RuntimeError("box_size должен быть строкой 'длина ширина высота', например '0.24 0.12 0.30'")
        sdf_path = os.path.join(tempfile.gettempdir(), 'go1_support_box.sdf')
        with open(sdf_path, 'w') as f:
            f.write(_BOX_SDF.format(size=' '.join(size)))
        spawn_box = Node(
            package='gazebo_ros', executable='spawn_entity.py', output='screen',
            arguments=['-entity', 'support_box', '-file', sdf_path,
                       '-x', LaunchConfiguration('world_init_x'), '-y', LaunchConfiguration('world_init_y'),
                       '-z', str(float(size[2]) / 2.0)],
        )
        actions += [spawn_box,
                    RegisterEventHandler(OnProcessExit(target_action=spawn_box, on_exit=[spawn_robot]))]
    else:
        actions.append(spawn_robot)

    # Спавнеры: плагин gazebo_ros2_control поднимает controller_manager при вставке модели, спавнер ждёт его
    # до --controller-manager-timeout секунд. use_sim_time спавнеру не задаём: пока /clock не пошёл,
    # таймауты на симулированном времени не тикают.
    # Gazebo используется исключительно для Highlevel: CHAMP посылает JointTrajectory.
    # LowCmd работает только в MuJoCo, поэтому альтернативный контроллер здесь не запускаем.
    common = ['--controller-manager', '/controller_manager', '--controller-manager-timeout', '120']
    controllers = [
        Node(package='controller_manager', executable='spawner', output='screen',
             arguments=['joint_states_controller', 'joint_group_effort_controller'] + common),
    ]

    # Контакты стоп с землёй: champ_gazebo подписывается на ~/physics/contacts Gazebo и публикует /foot_contacts
    contact_sensor = Node(
        package='champ_gazebo',
        executable='contact_sensor',
        output='screen',
        parameters=[
            {'use_sim_time': use_sim_time},
            PathJoinSubstitution([FindPackageShare('go1_config'), 'config', 'links', 'links.yaml']),
        ],
        condition=IfCondition(LaunchConfiguration('enable_contact_sensor')),
    )

    return actions + controllers + [contact_sensor]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('world', default_value='odom_validation',
                              description='Имя мира из go1_simulation/worlds (odom_validation, outdoor, playground, '
                                          'willow_garage) или полный путь к .world'),
        DeclareLaunchArgument('use_sim_time', default_value='true'),
        DeclareLaunchArgument('gui', default_value='true', description='Запустить gzclient (окно Gazebo)'),
        DeclareLaunchArgument('paused', default_value='false',
                              description='Не ставьте true: пока физика на паузе, ros2_control не включит контроллеры'),
        DeclareLaunchArgument('verbose', default_value='false'),
        DeclareLaunchArgument('lockstep', default_value=EnvironmentVariable('GO1_GAZEBO_LOCKSTEP', default_value='false'),
                              choices=['true', 'false'], description='Gazebo only: synchronize sensors with simulation time'),
        DeclareLaunchArgument('robot_name', default_value='go1', description='Имя модели в Gazebo'),
        DeclareLaunchArgument('world_init_x', default_value='0.0'),
        DeclareLaunchArgument('world_init_y', default_value='0.0'),
        DeclareLaunchArgument('world_init_z', default_value='0.33',
                              description='Высота корпуса при спавне (м); стоя корпус на ~0.30 м, поэтому падение всего ~3 см '
                                          '(с 0.5 м собака падала с нулевым моментом до включения контроллеров и могла перевернуться)'),
        DeclareLaunchArgument('world_init_heading', default_value='0.0'),
        DeclareLaunchArgument('world_init_roll', default_value='0.0', description='Крен при спавне, рад (3.14159 - на спину)'),
        DeclareLaunchArgument('support_box', default_value='false', description='Поставить подставку-параллелепипед под корпус'),
        DeclareLaunchArgument('box_size', default_value='0.24 0.12 0.30', description='Размеры подставки: длина(x) ширина(y) высота(z), м'),
        DeclareLaunchArgument('enable_contact_sensor', default_value='true'),
        OpaqueFunction(function=_resolve_world),
    ])
