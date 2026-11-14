"""Send one course-specific navigation goal to /goal_pose in the map frame.

ros2 launch go1_simulation goal_sender.launch.py width:=1.0
ros2 launch go1_simulation goal_sender.launch.py width:=2.0
Optional: x:=22.7 y:=0.0 yaw:=0.0, wait_timeout:=0.0 (unlimited).
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

# Derived from tools/gen_course.py: finish (22.7, 0, 0), traversable
# final corridor x=[14.8-width/2, 23.8], y=[-width/2, width/2].
# Distinct target poses for the two variants, both inside the final corridor.
COURSE_GOALS = {
    '1.0': (22.7, 0.0, 0.0),
    '2.0': (22.7, 0.35, 0.0),
}


def _setup(context):
    get = lambda name: LaunchConfiguration(name).perform(context)
    try:
        width = f'{float(get("width")):.1f}'
    except ValueError as exc:
        raise RuntimeError('width должен быть 1.0 или 2.0') from exc
    if width not in COURSE_GOALS:
        raise RuntimeError(f'width должен быть 1.0 или 2.0, получено {get("width")}')
    defaults = COURSE_GOALS[width]
    xyz = [float(get(k)) if get(k).strip() else defaults[i]
           for i, k in enumerate(('x', 'y', 'yaw'))]
    timeout = float(get('wait_timeout'))
    if timeout < 0:
        raise RuntimeError('wait_timeout должен быть >= 0')
    return [Node(
        package='go1_simulation', executable='course_goal_sender.py',
        name='course_goal_sender', output='screen',
        parameters=[{'use_sim_time': True, 'goal_x': xyz[0],
                     'goal_y': xyz[1], 'goal_yaw': xyz[2],
                     'wait_timeout': timeout}],
    )]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('width', default_value='1.0', description='Ширина лабиринта: 1.0 или 2.0 м'),
        DeclareLaunchArgument('x', default_value='', description='Переопределить координату x (м)'),
        DeclareLaunchArgument('y', default_value='', description='Переопределить координату y (м)'),
        DeclareLaunchArgument('yaw', default_value='', description='Переопределить yaw (рад)'),
        DeclareLaunchArgument('wait_timeout', default_value='0.0',
                              description='Время ожидания подписчика /goal_pose, сек; 0 — неограниченно'),
        OpaqueFunction(function=_setup),
    ])
