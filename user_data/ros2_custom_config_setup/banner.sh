#!/usr/bin/env bash
# Русскоязычный приветственный экран интерактивного контейнера Unitree Go1.
# Вызывается из bashrc.sh. Настройки отображения не влияют на работу симуляции.

# Не показывать баннер в неинтерактивных сессиях.
[[ $- == *i* ]] || exit 0

# Сообщение от организаторов. Можно оставить пустым.
MESSAGE=""

if [[ -t 1 && "${TERM:-}" != "dumb" && -z "${NO_COLOR:-}" ]]; then
    C=$'\033[1;36m'  # бирюзовый
    P=$'\033[1;35m'  # фиолетовый
    G=$'\033[0;32m'  # зелёный
    Y=$'\033[0;33m'  # жёлтый
    R=$'\033[0;31m'  # красный
    B=$'\033[1m'     # жирный
    N=$'\033[0m'     # сброс
else
    C='' P='' G='' Y='' R='' B='' N=''
fi

ros_distro="${ROS_DISTRO:-не определён}"
rmw="${RMW_IMPLEMENTATION:-не задан}"
ros_domain="${ROS_DOMAIN_ID:-0}"
workspace="/home/ros/go1_ws"

if [[ -f "${workspace}/install/setup.bash" ]]; then
    workspace_status="${G}готов к работе${N}"
else
    workspace_status="${Y}не найден установленный workspace${N}"
fi

if [[ -n "${CYCLONEDDS_URI:-}" ]]; then
    dds_cfg="${CYCLONEDDS_URI#file://}"
    if [[ -f "$dds_cfg" ]]; then
        dds_status="${G}${dds_cfg}${N}"
    else
        dds_status="${R}не найден: ${dds_cfg}${N}"
    fi
else
    dds_status="${Y}настройки DDS по умолчанию${N}"
fi

if [[ -n "${DISPLAY:-}" ]]; then
    gui_status="${G}DISPLAY=${DISPLAY}${N} (доступность X11 не проверялась)"
else
    gui_status="${Y}DISPLAY не задан${N}"
fi

printf '\n'
printf '%b\n' "${C}╭──────────────────────────────────────────────────────────────╮${N}"
printf '%b\n' "${C}│${N}  ${P}${B}UNITREE GO1${N}  ${C}│${N}  ЦИФРОВОЙ ДВОЙНИК                         ${C}│${N}"
printf '%b\n' "${C}│${N}  ROS 2 · Gazebo · MuJoCo · CHAMP                            ${C}│${N}"
printf '%b\n' "${C}╰──────────────────────────────────────────────────────────────╯${N}"
printf '  %bДобро пожаловать в среду симуляции!%b\n\n' "$B" "$N"
printf '  %-17s %s\n' 'Пользователь:' "$(whoami)"
printf '  %-17s %s\n' 'Версия ROS 2:' "$ros_distro"
printf '  %-17s %s\n' 'ROS_DOMAIN_ID:' "$ros_domain"
printf '  %-17s %s\n' 'RMW:' "$rmw"
printf '  %-17s %b\n' 'CycloneDDS:' "$dds_status"
printf '  %-17s %b\n' 'Рабочая среда:' "$workspace_status"
printf '  %-17s %b\n' 'Графика:' "$gui_status"
printf '\n  %bРабочее пространство:%b %s\n' "$C" "$N" "$workspace"
printf '\n  %b%s%b\n' "$P$B" 'БЫСТРЫЙ ЗАПУСК СИМУЛЯЦИИ' "$N"
printf '  %b%s%b\n' "$G" 'Lowlevel · MuJoCo:' "$N"
printf '    %s\n' 'ros2 launch go1_simulation scenario.launch.py scenario:=lowlevel'
printf '  %b%s%b\n' "$G" 'Highlevel · Gazebo + CHAMP:' "$N"
printf '    %s\n' 'ros2 launch go1_simulation scenario.launch.py scenario:=highlevel'
printf '  %b%s%b\n' "$G" 'Полоса препятствий · Gazebo:' "$N"
printf '    %s\n' 'ros2 launch go1_simulation scenario.launch.py scenario:=course width:=1.0'
printf '\n  %b%s%b\n' "$C" 'Основные параметры: gui:=true|false · width:=1.0|2.0 (только course)' "$N"
printf '  %b%s%b\n' "$C" 'Все параметры: ros2 launch go1_simulation scenario.launch.py --show-args' "$N"
printf '  %b%s%b\n' "$C" 'Подробная справка: go1-help' "$N"
if [[ -n "$MESSAGE" ]]; then
    printf '\n  %b%s%b\n' "$Y" "$MESSAGE" "$N"
fi
printf '\n'
