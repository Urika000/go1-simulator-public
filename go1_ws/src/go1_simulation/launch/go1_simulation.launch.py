"""Go1 в Gazebo целиком: Gazebo + модель + контроллеры + CHAMP (только походка).

ros2 launch go1_simulation go1_simulation.launch.py
ros2 launch go1_simulation go1_simulation.launch.py world:=playground
ros2 launch go1_simulation go1_simulation.launch.py gui:=false          # без окна Gazebo (headless)

Управление: топик /cmd_vel (geometry_msgs/Twist), например
ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.2}}"
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.substitutions import PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    passthrough = ['lockstep', 'world', 'gui', 'verbose', 'robot_name', 'world_init_x', 'world_init_y', 'world_init_z',
                   'world_init_heading', 'enable_contact_sensor', 'world_init_roll', 'support_box', 'box_size']

    # Ворота мягкого старта включаем только при работающем CHAMP.
    gate_on = PythonExpression(["'true' if ('", LaunchConfiguration('soft_start'), "' == 'true' and '",
                                LaunchConfiguration('champ'), "' == 'true') else 'false'"])
    soft_gate = Node(
        package='go1_unitree_bridge', executable='soft_stand_gate.py', name='soft_stand_gate', output='screen',
        parameters=[{'use_sim_time': True,
                     'rise_time': ParameterValue(LaunchConfiguration('rise_time'), value_type=float)}],
        condition=IfCondition(gate_on))

    bringup = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([FindPackageShare('go1_config'), 'launch', 'bringup.launch.py'])),
        launch_arguments={
            'use_sim_time': 'true',
            'gazebo': 'true',
            'publish_foot_contacts': 'false',   # контакты публикует contact_sensor
            'lidar': LaunchConfiguration('lidar'),
            'rgbd_camera': LaunchConfiguration('rgbd_camera'),
            'unitree_cameras': LaunchConfiguration('unitree_cameras'),
            'unitree_cam_width': LaunchConfiguration('unitree_cam_width'),
            'unitree_cam_height': LaunchConfiguration('unitree_cam_height'),
            'unitree_cam_rate': LaunchConfiguration('unitree_cam_rate'),
            'champ': LaunchConfiguration('champ'),
            'champ_gate': gate_on,
        }.items(),
    )

    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([FindPackageShare('go1_simulation'), 'launch', 'gazebo.launch.py'])),
        launch_arguments={k: LaunchConfiguration(k) for k in passthrough}.items(),
    )

    # Highlevel: only standard ROS telemetry. Contact forces are real Gazebo contact wrenches.
    foot_force = Node(
        package='go1_unitree_bridge', executable='foot_force_node.py',
        name='go1_foot_force', output='screen',
        parameters=[{'use_sim_time': True}],
    )

    return LaunchDescription([
        DeclareLaunchArgument('world', default_value='odom_validation'),
        DeclareLaunchArgument('gui', default_value='true'),
        DeclareLaunchArgument('verbose', default_value='false'),
        DeclareLaunchArgument('lockstep', default_value=EnvironmentVariable('GO1_GAZEBO_LOCKSTEP', default_value='false'),
                              choices=['true', 'false'], description='Gazebo only: synchronize sensors with simulation time'),
        DeclareLaunchArgument('robot_name', default_value='go1'),
        DeclareLaunchArgument('world_init_x', default_value='0.0'),
        DeclareLaunchArgument('world_init_y', default_value='0.0'),
        DeclareLaunchArgument('world_init_z', default_value='0.33'),
        DeclareLaunchArgument('world_init_heading', default_value='0.0'),
        DeclareLaunchArgument('enable_contact_sensor', default_value='true'),
        DeclareLaunchArgument('champ', default_value='true',
                              description='false - не запускать champ (нет ходьбы и подписки на /cmd_vel)'),
        DeclareLaunchArgument('world_init_roll', default_value='0.0'),
        DeclareLaunchArgument('support_box', default_value='false'),
        DeclareLaunchArgument('box_size', default_value='0.24 0.12 0.30'),
        DeclareLaunchArgument('lidar', default_value='true', description='Виртуальный Hokuyo (/scan); по умолчанию включён'),
        DeclareLaunchArgument('rgbd_camera', default_value='true',
                              description='Фронтальная RGB-D камера в голове (/camera/...)'),
        DeclareLaunchArgument('unitree_cameras', default_value='true',
                              description='Ещё 4 камеры Unitree (/camera_chin, /camera_left, /camera_right, /camera_rearDown); '
                                          'вместе с фронтальной - 5 камер Go1'),
        DeclareLaunchArgument('unitree_cam_width', default_value='464',
                              description='Ширина кадра камер Unitree; полный размер робота 928 (тяжело без GPU)'),
        DeclareLaunchArgument('unitree_cam_height', default_value='400', description='Высота кадра; полный размер 800'),
        DeclareLaunchArgument('unitree_cam_rate', default_value='10', description='Частота камер Unitree, Гц; у робота 16'),
        DeclareLaunchArgument('soft_start', default_value='true',
                              description='Плавный подъём в позу стоя; управление блокировано до сообщения «ГОТОВ К ДВИЖЕНИЮ» и /go1_ready'),
        DeclareLaunchArgument('rise_time', default_value='2.5', description='Длительность подъёма, с'),
        bringup,
        gazebo,
        foot_force,
        soft_gate,
    ])
