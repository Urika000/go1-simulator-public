#!/bin/bash
# Build only the ROS IMU plugin against the runtime's installed Gazebo/ROS ABI.
set -eo pipefail
src=${1:?source directory required}
source /opt/ros/humble/setup.bash
build_dir=$(mktemp -d)
trap 'rm -rf "$build_dir"' EXIT
cmake -S "$src" -B "$build_dir" -DCMAKE_BUILD_TYPE=Release
cmake --build "$build_dir" --target gazebo_ros_imu_sensor --parallel "${BUILD_JOBS:-2}"
install -m 755 "$build_dir/libgazebo_ros_imu_sensor.so" /opt/ros/humble/lib/libgazebo_ros_imu_sensor.so
ldd -r /opt/ros/humble/lib/libgazebo_ros_imu_sensor.so > "$build_dir/ldd.txt" 2>&1
cat "$build_dir/ldd.txt"
if grep -E 'not found|undefined symbol' "$build_dir/ldd.txt"; then exit 1; fi
mkdir -p /usr/local/share/go1-imu
sha256sum /opt/ros/humble/lib/libgazebo_ros_imu_sensor.so > /usr/local/share/go1-imu/plugin.sha256
dpkg-query -W gazebo libgazebo11 libgazebo-dev ros-humble-gazebo-plugins ros-humble-gazebo-ros > /usr/local/share/go1-imu/packages.txt
