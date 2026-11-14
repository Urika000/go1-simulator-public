# syntax=docker/dockerfile:1
# Цифровой двойник Go1: ROS2 Humble + Gazebo Classic 11 + MuJoCo (amd64)
# registry.cookcloud.ru/unitree_go1_hackathon/extra-humble-amd64-digital-twin
#
# Строится на ros2-base-humble-amd64 (ROS2, CycloneDDS, терминал, пользователь ros, entrypoint с подгонкой
# UID/GID). Кэш: ./scripts/prepare-standalone-cache.sh; сборка: ./build_image.sh
ARG BASE_IMAGE=registry.cookcloud.ru/base_images/ros2-base-humble-amd64:v1.0.1
FROM --platform=linux/amd64 ${BASE_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive
ARG ROS_DISTRO=humble
ARG BUILD_JOBS=1
# пины внешних зависимостей (воспроизводимая сборка)
ARG CHAMP_REF=049b33ccaf77847bbea168cbb0a11c260ce119cd
ARG LIBCHAMP_REF=8c50f649b3fd28a123beaf6f9618ddfaa1589559
ARG MENAGERIE_REF=0059d4335f8156206f63a35662313385f7ad6d74
ARG GAZEBO_MODELS_REF=8163eb4b5e7e21985c6591d1c0bfb56468c0093f
# интерфейсы unitree_go (Go2) берём из официального репозитория (ветка master на момент пина, версия 0.3.0)
ARG UNITREE_ROS2_REF=668d1ec5a05d1c38d3306bdca7d59f2ba3581a88

USER root
SHELL ["/bin/bash", "-c"]

# Same apt transport preparation as Dockerfile.dependencies-base, inlined so
# the complete build depends directly on the approved CookCloud image only.
RUN test "$(id -u ros)" = 1000 && test "$(id -g ros)" = 1000 \
    && test -x /ros2_custom_entrypoint.sh \
    && sed -i -e 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' \
              -e 's|http://security.ubuntu.com|https://security.ubuntu.com|g' \
              /etc/apt/sources.list /etc/apt/sources.list.d/* \
    && printf 'Acquire::Retries "3";\nAcquire::http::Timeout "60";\nAcquire::https::Timeout "60";\n' > /etc/apt/apt.conf.d/80go1-downloads

# ---- 1. системные пакеты -------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-upgrade --no-install-recommends \
        git ca-certificates curl \
        python3-colcon-common-extensions python3-rosdep python3-pip \
        ros-${ROS_DISTRO}-gazebo-ros-pkgs \
        ros-${ROS_DISTRO}-gazebo-ros2-control \
        ros-${ROS_DISTRO}-ros2-control \
        ros-${ROS_DISTRO}-ros2-controllers \
        ros-${ROS_DISTRO}-effort-controllers \
        ros-${ROS_DISTRO}-rosidl-generator-dds-idl \
        ros-${ROS_DISTRO}-xacro \
        ros-${ROS_DISTRO}-robot-state-publisher \
        ros-${ROS_DISTRO}-image-transport-plugins \
        ros-${ROS_DISTRO}-tf2-ros ros-${ROS_DISTRO}-tf2-geometry-msgs \
        ros-${ROS_DISTRO}-urdf ros-${ROS_DISTRO}-message-filters \
        ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
        liburdfdom-tools \
        bash-completion python3-argcomplete python3-opencv python3-yaml python3-numpy python3-zipp \
        libglfw3 libegl1 libosmesa6 \
        xvfb libgl1-mesa-dri \
    && rm -rf /var/lib/apt/lists/*

# Stock go1-full debugging tools, with a guard against dependency upgrades.
COPY scripts/install-original-tools.sh /usr/local/src/go1/install-original-tools.sh
RUN bash /usr/local/src/go1/install-original-tools.sh

# Common ROS IMU correction; build against installed packages, never Gazebo core.
COPY vendor/gazebo_ros_imu /usr/local/src/go1/gazebo_ros_imu
COPY scripts/build-imu-plugin.sh /usr/local/src/go1/build-imu-plugin.sh
RUN bash /usr/local/src/go1/build-imu-plugin.sh /usr/local/src/go1/gazebo_ros_imu

# ---- 1c. ~/go1_ws: underlay с пересборкой пакетов лежит в домашней директории и принадлежит ros (UID подгоняется entrypoint-ом) ----
RUN mkdir -p /home/ros/go1_ws/src && chown -R ros:ros /home/ros/go1_ws
USER ros

# ---- 2. интерфейсы Unitree: ~/unitree_ros2 (https://github.com/unitreerobotics/unitree_ros2) ----
# Используем сообщения Go2 (пакет unitree_go): из репозитория берётся только cyclonedds_ws/src/unitree/unitree_go.
# Пакет подключается в рабочую область символической ссылкой, поэтому обычный `colcon build` в ~/go1_ws собирает и его.
WORKDIR /home/ros
COPY --chown=ros:ros .dependency-cache/sources/unitree_ros2/ /home/ros/unitree_ros2/
RUN cd unitree_ros2 && test "$(cat .go1-source-revision)" = "${UNITREE_ROS2_REF}" \
    && sha256sum --quiet -c .go1-source-files.sha256 \
    && test -f cyclonedds_ws/src/unitree/unitree_go/msg/LowCmd.msg \
    && ln -s /home/ros/unitree_ros2/cyclonedds_ws/src/unitree/unitree_go /home/ros/go1_ws/src/unitree_go

# ---- 2b. champ (контроллер походки, ветка ros2) --------------------------------------
WORKDIR /home/ros/go1_ws/src
COPY --chown=ros:ros .dependency-cache/sources/champ/ /home/ros/go1_ws/src/champ/
RUN cd champ && test "$(cat .go1-source-revision)" = "${CHAMP_REF}" \
    && test "$(cat .go1-libchamp-revision)" = "${LIBCHAMP_REF}" \
    && sha256sum --quiet -c .go1-source-files.sha256 \
    && touch champ_bringup/COLCON_IGNORE champ_config/COLCON_IGNORE \
             champ_navigation/COLCON_IGNORE champ_description/COLCON_IGNORE

# ---- 3. пакеты Go1 ---------------------------------------------------------------------
COPY --chown=ros:ros go1_ws/src/ /home/ros/go1_ws/src/

# ---- 4. сборка -------------------------------------------------------------------------
WORKDIR /home/ros/go1_ws
RUN source /opt/ros/${ROS_DISTRO}/setup.bash \
    && CMAKE_BUILD_PARALLEL_LEVEL=${BUILD_JOBS} MAKEFLAGS="-j${BUILD_JOBS}" \
       colcon build --parallel-workers ${BUILD_JOBS} \
        --cmake-args -DCMAKE_BUILD_TYPE=Release \
        --packages-up-to go1_simulation \
    && rm -rf build log

# ---- 4b. страховка: интерфейсы unitree_go собрались и импортируются (Go2-типы, которыми пользуются мост, MuJoCo и скрипты) ----
RUN source /opt/ros/${ROS_DISTRO}/setup.bash && source /home/ros/go1_ws/install/setup.bash \
    && python3 -c "from unitree_go.msg import LowCmd, LowState, MotorCmd, MotorState; assert len(LowCmd().motor_cmd) == 20"

# ---- 5. страховка: URDF должен собираться, проходить check_urdf и разбираться как YAML ----
# gazebo_ros2_control передаёт URDF как '--param robot_description:=<xml>', т.е. разбирает его как YAML:
# ": " или " #" в тексте (например, в XML-комментариях) ломают разбор -> плагин не стартует.
RUN source /opt/ros/${ROS_DISTRO}/setup.bash && source /home/ros/go1_ws/install/setup.bash \
    && for s in false true; do \
         xacro $(ros2 pkg prefix go1_description)/share/go1_description/urdf/go1.urdf.xacro sim:=${s} \
             ros_control_file:=/home/ros/go1_ws/install/go1_config/share/go1_config/config/ros_control/ros_control.yaml \
             > /tmp/go1_${s}.urdf \
         && check_urdf /tmp/go1_${s}.urdf >/dev/null \
         && python3 -c "import sys,yaml; assert isinstance(yaml.safe_load(open(sys.argv[1]).read()), str)" /tmp/go1_${s}.urdf \
         || exit 1; \
       done; rm -f /tmp/go1_*.urdf

# Gazebo ищет package://go1_description/meshes/... в GAZEBO_MODEL_PATH; gzserver/gzclient launch берут пути из package.xml
# (<gazebo_ros gazebo_model_path=.../>). Проверяем, что меши действительно находятся.
RUN source /opt/ros/${ROS_DISTRO}/setup.bash && source /home/ros/go1_ws/install/setup.bash \
    && python3 -c "import os,sys; sys.path.append('/opt/ros/humble/lib/gazebo_ros'); from gazebo_ros_paths import GazeboRosPaths as G; m=G.get_paths()[0].split(':'); assert any(os.path.isfile(p+'/go1_description/meshes/trunk.dae') for p in m), m"

# ---- 5b. проверка актуальных полос, материалов ArUco и карт --------------------------------
RUN source /opt/ros/${ROS_DISTRO}/setup.bash && source /home/ros/go1_ws/install/setup.bash \
    && python3 -c "import os,sys; sys.path.append('/opt/ros/humble/lib/gazebo_ros'); from gazebo_ros_paths import GazeboRosPaths as G; m=G.get_paths()[0].split(':'); assert any(os.path.isfile(p+'/go1_course_assets/materials/scripts/aruco.material') for p in m), m" \
    && for w in w10 w20; do \
         test -f /home/ros/go1_ws/install/go1_config/share/go1_config/maps/course_${w}.yaml \
         && test -f /home/ros/go1_ws/install/go1_config/share/go1_config/maps/course_${w}_markers.yaml \
         && test -f /home/ros/go1_ws/install/go1_simulation/share/go1_simulation/worlds/course_${w}.world || exit 1; \
       done \
    && python3 -c "import cv2; cv2.aruco; print('opencv', cv2.__version__)"

# ---- 5c. страховка: мягкий старт (ядро подъёма, узел-ворота и мост на заглушках rclpy), скрипты установлены, launch-файлы разбираются ----
RUN source /opt/ros/${ROS_DISTRO}/setup.bash && source /home/ros/go1_ws/install/setup.bash \
    && python3 /home/ros/go1_ws/src/go1_unitree_bridge/test/test_soft_stand.py \
    && python3 /home/ros/go1_ws/src/go1_simulation/test/test_stage51_launch_loading.py \
    && test -x /home/ros/go1_ws/install/go1_unitree_bridge/lib/go1_unitree_bridge/soft_stand_gate.py \
    && ros2 launch go1_simulation scenario.launch.py --show-args >/dev/null \
    && ros2 launch go1_simulation go1_simulation.launch.py --show-args >/dev/null \
    && ros2 launch go1_simulation mujoco.launch.py --show-args >/dev/null

# ---- 6. модели Gazebo (оффлайн, без обращения к database) ------------------------------
USER root
COPY .dependency-cache/sources/gazebo_models/ /opt/gazebo_models/
RUN cd /opt/gazebo_models && test "$(cat .go1-source-revision)" = "${GAZEBO_MODELS_REF}" \
    && sha256sum --quiet -c .go1-source-files.sha256

# ---- 6b. MuJoCo + модель Go1 из mujoco_menagerie (пин) --------------------------------
# numpy<2: пакеты ROS 2 Humble собраны под numpy 1.x
ENV PIP_BREAK_SYSTEM_PACKAGES=1 PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=3
COPY .dependency-cache/wheels/ /opt/go1_wheels/
COPY config/standalone-python.lock /opt/go1_wheels/requirements.lock
COPY .dependency-cache/sources/mujoco_menagerie/ /opt/mujoco_menagerie/
RUN pip3 install --no-index --find-links=/opt/go1_wheels --no-deps --require-hashes -r /opt/go1_wheels/requirements.lock \
    && cd /opt/mujoco_menagerie && test "$(cat .go1-source-revision)" = "${MENAGERIE_REF}" \
    && sha256sum --quiet -c .go1-source-files.sha256 \
    && python3 -c "import numpy; assert int(numpy.__version__.split('.')[0]) < 2; import mujoco; m = mujoco.MjModel.from_xml_path('/opt/mujoco_menagerie/unitree_go1/scene.xml'); assert m.nu == 12, m.nu"

# ---- 7. окружение ----------------------------------------------------------------------
COPY user_data/ros2_custom_config_setup/ /home/ros/ros2_custom_config_setup/
COPY scripts/go1_env.sh /etc/go1_sim_env.sh
COPY scripts/go1_entrypoint.sh /usr/local/bin/go1_entrypoint.sh
COPY scripts/go1-help /usr/local/bin/go1-help
RUN chmod +x /usr/local/bin/go1_entrypoint.sh /usr/local/bin/go1-help \
    && echo 'source /etc/go1_sim_env.sh' >> /etc/bash.bashrc

ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    CYCLONEDDS_URI=file:///home/ros/ros2_custom_config_setup/cyclonedds.xml \
    GAZEBO_MODEL_PATH=/opt/gazebo_models \
    GAZEBO_MODEL_DATABASE_URI="" \
    GO1_MUJOCO_MODEL_DIR=/opt/mujoco_menagerie/unitree_go1 \
    QT_X11_NO_MITSHM=1 \
    ROS_DISTRO=humble

# Без USER ros: go1_entrypoint.sh стартует от root, добавляет группы /dev/dri, затем entrypoint базового образа
# подгоняет UID/GID под хост и переходит на ros. ~/go1_ws и ~/unitree_ros2 читаются любым UID.
USER root
RUN chmod -R a+rX /home/ros/go1_ws /home/ros/unitree_ros2
COPY licenses/ /usr/local/share/go1-licenses/
WORKDIR /home/ros/go1_ws
ENTRYPOINT ["/usr/local/bin/go1_entrypoint.sh"]
CMD ["bash"]
