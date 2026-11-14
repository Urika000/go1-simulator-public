#!/usr/bin/env python3
"""Publish four actual Gazebo foot-contact vertical-force magnitudes (N).

Ordering: FL, FR, RL, RR. Each gazebo_ros_bumper sensor yields
Gazebo ContactsState with a wrench expressed in the world frame.
The absolute world-Z component of each contact wrench is summed per foot;
no arbitrary contact flags or fake force constants are involved.
No contact (or stale sensor data) produces zero.
"""
import math

import rclpy
from gazebo_msgs.msg import ContactsState
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import Float32MultiArray

LEG_ORDER = ('FL', 'FR', 'RL', 'RR')


def vertical_contact_force(states):
    """Magnitude of total Z contact reaction, summing distinct collisions."""
    total = 0.0
    for contact in states:
        z = float(contact.total_wrench.force.z)
        if math.isfinite(z):
            total += abs(z)
    return total


class FootForcePublisher(Node):
    def __init__(self):
        super().__init__('go1_foot_force')
        self.declare_parameter('publish_rate', 100.0)
        self.declare_parameter('timeout', 0.2)
        rate = float(self.get_parameter('publish_rate').value)
        if rate <= 0:
            raise ValueError('publish_rate must be positive')
        self.timeout = float(self.get_parameter('timeout').value)
        self.forces = {leg: 0.0 for leg in LEG_ORDER}
        self.updated_at = {leg: None for leg in LEG_ORDER}
        self.pub = self.create_publisher(Float32MultiArray, '/foot_force', 10)
        self.subs = []
        for leg in LEG_ORDER:
            self.subs.append(self.create_subscription(
                ContactsState, f'/go1_contacts/{leg}',
                lambda msg, current_leg=leg: self.on_contact(current_leg, msg),
                qos_profile_sensor_data))
        self.timer = self.create_timer(1.0 / rate, self.publish)
        self.get_logger().info('Publishing /foot_force [FL, FR, RL, RR] in newtons, Gazebo world Z')

    def on_contact(self, leg, msg):
        self.forces[leg] = vertical_contact_force(msg.states)
        self.updated_at[leg] = self.get_clock().now().nanoseconds * 1e-9

    def publish(self):
        now = self.get_clock().now().nanoseconds * 1e-9
        values = []
        for leg in LEG_ORDER:
            last = self.updated_at[leg]
            values.append(float(self.forces[leg]) if last is not None and 0 <= now-last <= self.timeout else 0.0)
        msg = Float32MultiArray()
        msg.data = values
        self.pub.publish(msg)


def main():
    rclpy.init()
    node = FootForcePublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
