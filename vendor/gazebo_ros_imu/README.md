# ROS IMU measurement timestamp correction

Vendored source: ros-simulation/gazebo_ros_pkgs tag **3.9.0**, file
`gazebo_plugins/src/gazebo_ros_imu_sensor.cpp` (Apache-2.0, original copyright retained).
Upstream: https://github.com/ros-simulation/gazebo_ros_pkgs/blob/3.9.0/gazebo_plugins/src/gazebo_ros_imu_sensor.cpp

Reused from verified project experiment `230d0853d5dab7205eb98cdd6aa8fc4cbd8e4f2b`.
The only source change replaces `sensor_->LastUpdateTime()` with
`gazebo::msgs::Convert(sensor_->ImuMessage().stamp())`. The latter is the timestamp
of the completed native measurement, copied under the sensor mutex. It is not
callback arrival or wall time. Measurement getters, covariances, frame selection,
topic remapping and publisher QoS are unchanged.

Build with `bash scripts/build-imu-plugin.sh vendor/gazebo_ros_imu` as root inside
the Simulator build environment. No downloads or Gazebo core rebuild. It replaces
only `/opt/ros/humble/lib/libgazebo_ros_imu_sensor.so`; package metadata still names
the upstream package, so `/usr/local/share/go1-imu/plugin.sha256` records the override.
The Simulator Dockerfile uses this script.

Validated dependency family: Gazebo Classic 11.10.2, ROS Humble gazebo_plugins 3.9.0.
The build checks compatibility with the installed ABI; dependency upgrades
require another build and runtime check. This correction does not backport Gazebo
core scheduler changes or claim to fix timestamps of other sensor plugins.
