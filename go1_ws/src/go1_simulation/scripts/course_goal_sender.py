#!/usr/bin/env python3
"""One-shot PoseStamped publisher. Wait for DDS subscription, then send once.

A /goal_pose subscriber is necessary for delivery, but does not prove Nav2 is
fully active or that a goal has been accepted; this is a developer convenience.
"""
import math
import time

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from rclpy.clock import Clock, ClockType
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy


class CourseGoalSender(Node):
    def __init__(self):
        super().__init__('course_goal_sender')
        self.declare_parameter('goal_x', 22.7)
        self.declare_parameter('goal_y', 0.0)
        self.declare_parameter('goal_yaw', 0.0)
        self.declare_parameter('wait_timeout', 0.0)
        # Volatile: compatible with the typical /goal_pose Nav2/RViz subscription.
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.VOLATILE)
        self.publisher = self.create_publisher(PoseStamped, '/goal_pose', qos)
        self.started = time.monotonic()
        self.sent = False
        self.timer = self.create_timer(0.2, self.tick, clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.get_logger().info('Ожидание подписчика /goal_pose и времени /clock...')

    def tick(self):
        if self.sent:
            return
        timeout = self.get_parameter('wait_timeout').value
        if timeout > 0 and time.monotonic() - self.started >= timeout:
            self.get_logger().error('Тайм-аут ожидания подписчика /goal_pose и /clock')
            self.sent = True
            self.timer.cancel()
            return
        if self.publisher.get_subscription_count() == 0:
            return
        # Avoid publishing a zero timestamp before simulation time is available.
        stamp = self.get_clock().now().to_msg()
        if stamp.sec == 0 and stamp.nanosec == 0:
            return
        x = float(self.get_parameter('goal_x').value)
        y = float(self.get_parameter('goal_y').value)
        yaw = float(self.get_parameter('goal_yaw').value)
        pose = PoseStamped()
        pose.header.frame_id = 'map'
        pose.header.stamp = stamp
        pose.pose.position.x = x
        pose.pose.position.y = y
        pose.pose.orientation.z = math.sin(yaw / 2)
        pose.pose.orientation.w = math.cos(yaw / 2)
        self.publisher.publish(pose)
        self.get_logger().info(f'Отправлена ОДНА цель /goal_pose: map x={x:.3f} y={y:.3f} yaw={yaw:.3f}')
        self.sent = True
        self.timer.cancel()


def main(args=None):
    rclpy.init(args=args)
    node = CourseGoalSender()
    try:
        while rclpy.ok() and not node.sent:
            rclpy.spin_once(node, timeout_sec=0.2)
        # Keep publisher alive briefly after publish for reliable DDS delivery.
        if node.sent:
            until = time.monotonic() + 1.0
            while rclpy.ok() and time.monotonic() < until:
                rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
