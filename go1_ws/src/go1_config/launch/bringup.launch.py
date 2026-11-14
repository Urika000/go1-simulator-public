"""Управление Go1: CHAMP (походка) и robot_state_publisher (кинематика).

Режимы:
  * без Gazebo: gazebo:=false
        champ сам публикует joint_states и контакты стоп по фазе шага;
  * с Gazebo: gazebo:=true use_sim_time:=true (обычно вызывается из go1_simulation/launch/go1_simulation.launch.py)
        joint_states даёт ros2_control, контакты - узел contact_sensor из champ_gazebo, ориентацию даёт IMU.

Управление: geometry_msgs/Twist в /cmd_vel, поза корпуса: geometry_msgs/Pose в /body_pose.

Отличия от ROS1-версии:
  * yocs_velocity_smoother не используется (нет в ROS2); champ читает /cmd_vel напрямую;
  * одометрия CHAMP и оба EKF не запускаются. Ground truth симулятора доступен только в
    /odom/ground_truth, без TF odom -> корпус. Кинематику публикует robot_state_publisher.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import EnvironmentVariable, Command, LaunchConfiguration, PathJoinSubstitution, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    config_share = FindPackageShare('go1_config')
    description_share = FindPackageShare('go1_description')

    joints_map = PathJoinSubstitution([config_share, 'config', 'joints', 'joints.yaml'])
    links_map = PathJoinSubstitution([config_share, 'config', 'links', 'links.yaml'])
    gait_config = PathJoinSubstitution([config_share, 'config', 'gait', 'gait.yaml'])
    default_ros_control = PathJoinSubstitution([config_share, 'config', 'ros_control', 'ros_control.yaml'])
    default_model = PathJoinSubstitution([description_share, 'urdf', 'go1.urdf.xacro'])

    use_sim_time = LaunchConfiguration('use_sim_time')
    gazebo = LaunchConfiguration('gazebo')
    champ_gate = LaunchConfiguration('champ_gate')

    def gated(name_gated, name_direct):
        """Имя топика: через ворота мягкого старта или прямое."""
        return PythonExpression(["'", name_gated, "' if '", champ_gate, "' == 'true' else '", name_direct, "'"])

    robot_description = ParameterValue(
        Command([
            'xacro ', LaunchConfiguration('description_path'),
            ' sim:=', gazebo,
            ' gazebo_gt_mode:=', EnvironmentVariable('GO1_GAZEBO_GT_MODE', default_value='public'),
            ' ros_control_file:=', LaunchConfiguration('ros_control_file'),
            ' lidar:=', LaunchConfiguration('lidar'),
            ' rgbd_camera:=', LaunchConfiguration('rgbd_camera'),
            ' unitree_cameras:=', LaunchConfiguration('unitree_cameras'),
            ' unitree_cam_width:=', LaunchConfiguration('unitree_cam_width'),
            ' unitree_cam_height:=', LaunchConfiguration('unitree_cam_height'),
            ' unitree_cam_rate:=', LaunchConfiguration('unitree_cam_rate'),
        ]),
        value_type=str,
    )

    declared_args = [
        DeclareLaunchArgument('use_sim_time', default_value='false',
                              description='Использовать часы Gazebo (/clock)'),
        DeclareLaunchArgument('gazebo', default_value='false',
                              description='true - работаем с Gazebo (ros2_control, IMU, contact_sensor)'),
        DeclareLaunchArgument('champ', default_value='true',
                              description='false - не запускать quadruped_controller_node (нет /cmd_vel и походки)'),
        DeclareLaunchArgument('description_path', default_value=default_model,
                              description='xacro-описание робота'),
        DeclareLaunchArgument('ros_control_file', default_value=default_ros_control,
                              description='yaml контроллеров ros2_control'),
        DeclareLaunchArgument('lidar', default_value='true', description='Виртуальный Hokuyo (/scan) включён по умолчанию'),
        DeclareLaunchArgument('rgbd_camera', default_value='true', description='Фронтальная RGB-D камера в голове (/camera/...)'),
        DeclareLaunchArgument('unitree_cameras', default_value='true',
                              description='Камеры Unitree: chin (голова, вниз), left, right, rearDown (корпус, вниз)'),
        DeclareLaunchArgument('unitree_cam_width', default_value='464', description='Ширина кадра камер Unitree (полный размер 928)'),
        DeclareLaunchArgument('unitree_cam_height', default_value='400', description='Высота кадра (полный размер 800)'),
        DeclareLaunchArgument('unitree_cam_rate', default_value='10', description='Частота камер Unitree, Гц (у робота 16)'),
        DeclareLaunchArgument('joint_controller_topic',
                              default_value='joint_group_effort_controller/joint_trajectory',
                              description='Топик, в который champ публикует JointTrajectory'),
        DeclareLaunchArgument('champ_gate', default_value='false',
                              description='true - champ работает через узел мягкого старта (soft_stand_gate): его траектории, '
                                          '/cmd_vel и /body_pose пропускаются только после подъёма (задаёт go1_simulation.launch.py)'),
        DeclareLaunchArgument('publish_joint_control', default_value='true'),
        DeclareLaunchArgument('publish_joint_states', default_value='true',
                              description='Только вне Gazebo: публиковать joint_states по командам champ'),
        DeclareLaunchArgument('publish_foot_contacts', default_value='true',
                              description='Только вне Gazebo: контакты стоп по фазе шага'),
    ]

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        output='screen',
        parameters=[{
            'robot_description': robot_description,
            'use_tf_static': False,
            'publish_frequency': 200.0,
            'ignore_timestamp': True,
            'use_sim_time': use_sim_time,
        }],
    )

    quadruped_controller = Node(
        package='champ_base',
        executable='quadruped_controller_node',
        output='screen',
        parameters=[
            {'use_sim_time': use_sim_time},
            {'gazebo': gazebo},
            {'publish_joint_states': LaunchConfiguration('publish_joint_states')},
            {'publish_joint_control': LaunchConfiguration('publish_joint_control')},
            {'publish_foot_contacts': LaunchConfiguration('publish_foot_contacts')},
            {'joint_controller_topic': gated('/champ/joint_trajectory', LaunchConfiguration('joint_controller_topic'))},
            {'urdf': robot_description},
            joints_map,
            links_map,
            gait_config,
        ],
        # champ слушает cmd_vel/smooth; сглаживателя нет, поэтому берём прямо /cmd_vel.
        # С воротами мягкого старта champ слушает /cmd_vel_gated и /body_pose_gated, а траектории отдаёт узлу ворот
        remappings=[('/cmd_vel/smooth', gated('/cmd_vel_gated', '/cmd_vel')),
                    ('/body_pose', gated('/body_pose_gated', '/body_pose'))],
        condition=IfCondition(LaunchConfiguration('champ')),
    )

    return LaunchDescription(declared_args + [
        robot_state_publisher,
        quadruped_controller,
    ])
