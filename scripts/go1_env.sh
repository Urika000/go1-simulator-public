# Окружение Go1 simulation. Подключается из /etc/bash.bashrc и из go1_entrypoint.sh.
# Часть 1: окружение (экспортируемый флаг - entrypoint уже подключил его, повторно не нужно)
if [ -z "$GO1_ENV_LOADED" ]; then
  export GO1_ENV_LOADED=1
  source /opt/ros/humble/setup.bash
  [ -f /home/ros/go1_ws/install/setup.bash ] && source /home/ros/go1_ws/install/setup.bash
  [ -f /usr/share/gazebo/setup.sh ] && source /usr/share/gazebo/setup.sh
  # setup.sh gazebo перезаписывает GAZEBO_MODEL_PATH - добавляем наши модели.
  # /home/ros/go1_ws/install/go1_description/share нужен, чтобы Gazebo находил package://go1_description/meshes/...
  export GAZEBO_MODEL_PATH=/opt/gazebo_models:/home/ros/go1_ws/install/go1_description/share:/home/ros/go1_ws/install/go1_simulation/share/go1_simulation/models${GAZEBO_MODEL_PATH:+:$GAZEBO_MODEL_PATH}
  export GAZEBO_MODEL_DATABASE_URI=""
  export GAZEBO_PLUGIN_PATH=/home/ros/go1_ws/install/go1_simulation/lib${GAZEBO_PLUGIN_PATH:+:$GAZEBO_PLUGIN_PATH}
fi

# Часть 2: только для интерактивной оболочки (флаг НЕ экспортируется, чтобы работало и после entrypoint)
if [[ $- == *i* ]] && [ -z "$GO1_UI_DONE" ]; then
  GO1_UI_DONE=1
  # --- автодополнение: bash, colcon, ros2 (ros2 подключается через setup.bash + argcomplete)
  [ -f /usr/share/bash-completion/bash_completion ] && source /usr/share/bash-completion/bash_completion
  [ -f /usr/share/colcon_argcomplete/hook/colcon-argcomplete.bash ] && source /usr/share/colcon_argcomplete/hook/colcon-argcomplete.bash
  if command -v register-python-argcomplete3 >/dev/null 2>&1; then
    eval "$(register-python-argcomplete3 ros2 2>/dev/null)"
    eval "$(register-python-argcomplete3 colcon 2>/dev/null)"
  fi

fi
