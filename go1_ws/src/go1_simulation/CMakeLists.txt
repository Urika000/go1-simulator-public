cmake_minimum_required(VERSION 3.8)
project(go1_simulation)

find_package(ament_cmake REQUIRED)
install(DIRECTORY launch worlds models config
  DESTINATION share/${PROJECT_NAME}
)

install(PROGRAMS scripts/go1_mujoco.py scripts/course_goal_sender.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
