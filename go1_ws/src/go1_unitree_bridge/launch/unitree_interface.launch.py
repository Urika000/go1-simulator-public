"""Unitree Lowlevel-совместимый интерфейс: /lowcmd -> моменты, /lowstate.

ros2 launch go1_unitree_bridge unitree_interface.launch.py lowcmd_enabled:=true
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time')
    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='true'),
        DeclareLaunchArgument('lowcmd_enabled', default_value='true'),
        DeclareLaunchArgument('soft_start', default_value='true',
                              description='lowcmd: плавный подъём в позу стоя, /lowcmd игнорируется до «ГОТОВ К ДВИЖЕНИЮ»'),
        DeclareLaunchArgument('rise_time', default_value='2.5', description='Длительность подъёма, с'),
        Node(package='go1_unitree_bridge', executable='sim_bridge_node.py', name='go1_unitree_bridge',
             output='screen',
             parameters=[{'use_sim_time': use_sim_time, 'lowcmd_enabled': LaunchConfiguration('lowcmd_enabled'),
                          'soft_start': LaunchConfiguration('soft_start'),
                          'rise_time': ParameterValue(LaunchConfiguration('rise_time'), value_type=float)}]),
    ])
