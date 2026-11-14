"""Interface example: receives sensors, publishes zero Twist for T4/T5.

No locomotion policy, odometry estimation, navigation or task solution.
"""
import sys
import rclpy
from rclpy.qos import qos_profile_sensor_data
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Imu
from unitree_go.msg import LowState

rclpy.init()
node = rclpy.create_node('participant_interface_example')
low = sys.argv[1] in ('T2', 'T3')
count = 0

def receive(msg):
    global count
    count += 1
    if count == 1:
        node.get_logger().info('Received sensor payload')

sub = node.create_subscription(LowState if low else Imu,
                               '/lowstate' if low else '/imu/data', receive,
                               qos_profile_sensor_data)
if not low:
    pub = node.create_publisher(Twist, '/cmd_vel', 10)
    timer = node.create_timer(0.1, lambda: pub.publish(Twist()))
try:
    rclpy.spin(node)
except KeyboardInterrupt:
    pass
finally:
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
