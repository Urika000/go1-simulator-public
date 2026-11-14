cmake_minimum_required(VERSION 3.8)
project(go1_unitree_bridge)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)

ament_python_install_package(${PROJECT_NAME})

install(PROGRAMS
  scripts/sim_bridge_node.py
  scripts/soft_stand_gate.py
  scripts/foot_force_node.py
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
