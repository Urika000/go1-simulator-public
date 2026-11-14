"""Go1 в MuJoCo (окно viewer + ROS 2 топики). Запускает узел go1_mujoco.py.

ros2 launch go1_simulation mujoco.launch.py                       # собака стоит на полу; управление /lowcmd
ros2 launch go1_simulation mujoco.launch.py box:=true             # лежит на подставке-параллелепипеде (ноги свисают)
ros2 launch go1_simulation mujoco.launch.py box:=true flip:=true  # на подставке, перевёрнутая на спину
ros2 launch go1_simulation mujoco.launch.py headless:=true        # без окна
ros2 launch go1_simulation mujoco.launch.py box:=true box_size:="0.3 0.15 0.4"   # длина ширина высота подставки, м

Обычно запускается через сценарий:  ros2 launch go1_simulation scenario.launch.py scenario:=lowlevel
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node


def _node(context):
    cfg = lambda n: LaunchConfiguration(n).perform(context)  # noqa: E731
    truthy = lambda n: cfg(n).lower() in ('true', '1')  # noqa: E731
    size = [float(v) for v in cfg('box_size').replace(',', ' ').split()]
    if len(size) != 3:
        raise RuntimeError(f"box_size: три числа 'длина ширина высота' (м), получено: {cfg('box_size')}")
    return [Node(
        package='go1_simulation', executable='go1_mujoco.py', name='go1_mujoco', output='screen',
        parameters=[{
            'model_dir': cfg('model_dir'),
            'box': truthy('box'),
            'flip': truthy('flip'),
            'box_size': size,
            'headless': truthy('headless'),
        }])]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('box', default_value='false', description='true - собака на подставке-параллелепипеде'),
        DeclareLaunchArgument('flip', default_value='false', description='true - на спине (имеет смысл с box:=true)'),
        DeclareLaunchArgument('box_size', default_value='0.24 0.12 0.30', description='Подставка: длина ширина высота, м'),
        DeclareLaunchArgument('headless', default_value='false', description='true - без окна MuJoCo viewer'),
        DeclareLaunchArgument('model_dir',
                              default_value=EnvironmentVariable('GO1_MUJOCO_MODEL_DIR', default_value='/opt/mujoco_menagerie/unitree_go1'),
                              description='Каталог unitree_go1 из mujoco_menagerie'),
        OpaqueFunction(function=_node),
    ])
