"""robot_state_publisher для Go1 (xacro -> robot_description).

ros2 launch go1_description description.launch.py sim:=false
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import Command, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    default_model = PathJoinSubstitution([FindPackageShare('go1_description'), 'urdf', 'go1.urdf.xacro'])

    description_path = LaunchConfiguration('description_path')
    use_sim_time = LaunchConfiguration('use_sim_time')
    robot_description = ParameterValue(
        Command([
            'xacro ', description_path,
            ' sim:=', LaunchConfiguration('sim'),
            ' ros_control_file:=', LaunchConfiguration('ros_control_file'),
            ' lidar:=', LaunchConfiguration('lidar'),
            ' rgbd_camera:=', LaunchConfiguration('rgbd_camera'),
            ' unitree_cameras:=', LaunchConfiguration('unitree_cameras'),
        ]),
        value_type=str,
    )

    return LaunchDescription([
        DeclareLaunchArgument('description_path', default_value=default_model),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('sim', default_value='false',
                              description='true: добавить ros2_control и плагины Gazebo'),
        DeclareLaunchArgument('ros_control_file', default_value='',
                              description='yaml контроллеров (нужен только при sim:=true)'),
        DeclareLaunchArgument('lidar', default_value='true'),
        DeclareLaunchArgument('rgbd_camera', default_value='true'),
        DeclareLaunchArgument('unitree_cameras', default_value='false'),
        Node(
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
        ),
    ])
