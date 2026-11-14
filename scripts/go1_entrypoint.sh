#!/bin/bash
# !!!! DO NOT EDIT !!!!
# Entrypoint образа extra-humble-amd64-digital-twin. Работает поверх entrypoint базового образа
# (/ros2_custom_entrypoint.sh: подгонка UID/GID, переход на ros, setup.sh).
# Здесь от root добавляется то, что нужно только симуляции, затем управление передаётся базе.
set -e

if [ "$(id -u)" = "0" ] && [ "${HOST_UID:-}" != "0" ]; then
    # /dev/dri (рендеринг Gazebo): группе устройства даём доступ пользователю ros
    # (gosu сбрасывает группы из compose group_add, поэтому прописываем их в /etc/group)
    for dev in /dev/dri/*; do
        [ -e "$dev" ] || continue
        gid=$(stat -c %g "$dev")
        [ "$gid" != "0" ] || continue
        grp=$(getent group "$gid" | cut -d: -f1 || true)
        if [ -z "$grp" ]; then grp="hostgrp$gid"; groupadd -g "$gid" "$grp"; fi
        usermod -aG "$grp" ros
    done
    # ~/go1_ws (underlay с пересборкой пакетов) и ~/unitree_ros2 (интерфейсы) принадлежат ros: после смены UID перепривязываем
    new_uid=${HOST_UID:-$(id -u ros)}
    new_gid=${HOST_GID:-$(id -g ros)}
    for d in /home/ros/go1_ws /home/ros/unitree_ros2; do
        if [ -d "$d" ] && [ "$(stat -c %u "$d")" != "$new_uid" ]; then
            chown -R "$new_uid:$new_gid" "$d"
        fi
    done
fi

# Headless Gazebo cameras still need an X server for rendering. Keep the original
# ROS launch command and use the installed Xvfb only for explicit headless Gazebo.
if [[ "${1:-}" == ros2 && "${2:-}" == launch && "${3:-}" == go1_simulation ]]; then
    case " $* " in
        *" scenario:=lowlevel "*|*" mujoco.launch.py "*) ;;
        *" gui:=false "*)
            # Xvfb readiness signalling stalls when xvfb-run itself is PID 1.
            set -- bash -c 'xvfb-run -a "$@" & child=$!; trap "kill -TERM $child 2>/dev/null" TERM INT; wait "$child"' _ "$@"
            ;;
    esac
fi

# База сделает остальное и запустит команду от ros; перед ней подключается окружение симуляции
if [ ! -x /ros2_custom_entrypoint.sh ]; then
    source /etc/go1_sim_env.sh
    if [ "$(id -u)" = 0 ]; then
        exec runuser -u ros -- "$@"
    fi
    exec "$@"
fi
exec /ros2_custom_entrypoint.sh bash -c 'source /etc/go1_sim_env.sh; exec "$@"' _ "$@"
