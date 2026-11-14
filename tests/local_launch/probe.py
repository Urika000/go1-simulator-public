"""Run inside either existing container; no additional container or ROS daemon."""
import argparse
import json
import time
import rclpy
from rclpy.qos import qos_profile_sensor_data, QoSProfile, ReliabilityPolicy
from rosidl_runtime_py.utilities import get_message

p = argparse.ArgumentParser()
p.add_argument('--topics', nargs='+', required=True, help='topic=package/msg/Type')
p.add_argument('--publish', help='topic=package/msg/Type; default zero message')
p.add_argument('--seconds', type=float, default=20)
a = p.parse_args()
rclpy.init()
n = rclpy.create_node('local_launch_payload_probe')
counts = {}
subscriptions = []
for spec in a.topics:
    topic, typename = spec.split('=')
    counts[topic] = 0
    def receive(msg, topic=topic):
        counts[topic] += 1
    # Camera publishers offer RELIABLE; retain retransmission for large raw frames.
    qos = (QoSProfile(depth=5, reliability=ReliabilityPolicy.RELIABLE)
           if typename == 'sensor_msgs/msg/Image' else qos_profile_sensor_data)
    subscriptions.append(n.create_subscription(get_message(typename), topic, receive, qos))
if a.publish:
    topic, typename = a.publish.split('=')
    cls = get_message(typename)
    pub = n.create_publisher(cls, topic, 10)
    timer = n.create_timer(0.1, lambda: pub.publish(cls()))
end = time.monotonic() + a.seconds
while time.monotonic() < end:
    rclpy.spin_once(n, timeout_sec=0.1)
print(json.dumps(counts), flush=True)
n.destroy_node()
rclpy.shutdown()
raise SystemExit(0 if all(counts.values()) else 1)
