#!/bin/bash
# Run in the RageOS-derived download tool, before compiling any Go1 application.
set -euo pipefail
root=/dependency-cache
mkdir -p "$root/git" "$root/sources"
export GIT_CONFIG_COUNT=3 GIT_CONFIG_KEY_0=http.version GIT_CONFIG_VALUE_0=HTTP/1.1
export GIT_CONFIG_KEY_1=http.lowSpeedLimit GIT_CONFIG_VALUE_1=1000
export GIT_CONFIG_KEY_2=http.lowSpeedTime GIT_CONFIG_VALUE_2=120
pin() { sed -n "s/^ARG $1=//p" /Dockerfile; }
retry() {
  local attempt
  for attempt in 1 2; do
    if timeout 300 "$@"; then return 0; fi
    echo "Source fetch attempt $attempt failed: $*" >&2
  done
  return 1
}
prepare() {
  local name=$1 url=$2 ref=$3
  shift 3
  local repo="$root/git/$name" dest="$root/sources/$name"
  if [[ -f "$dest/.go1-source-revision" ]] && [[ "$(cat "$dest/.go1-source-revision")" == "$ref" ]] \
      && (cd "$dest" && sha256sum --quiet -c .go1-source-files.sha256); then
    echo "Verified cached source $name $ref"
    return
  fi
  if [[ ! -d "$repo/.git" ]]; then
    git init -q "$repo"
    git -C "$repo" remote add origin "$url"
  fi
  [[ "$(git -C "$repo" remote get-url origin)" == "$url" ]]
  if [[ $# -gt 0 ]]; then
    git -C "$repo" sparse-checkout init --cone
    git -C "$repo" sparse-checkout set "$@"
  fi
  retry git -C "$repo" fetch --depth 1 --filter=blob:none origin "$ref"
  retry git -C "$repo" checkout --detach "$ref"
  [[ "$(git -C "$repo" rev-parse HEAD)" == "$ref" ]]
  if [[ "$name" == champ ]]; then
    retry git -C "$repo" submodule update --init --recursive
    [[ "$(git -C "$repo/champ/include/champ" rev-parse HEAD)" == "$(pin LIBCHAMP_REF)" ]]
  fi
  if [[ -e "$dest" ]]; then mv "$dest" "$dest.previous-$(date +%s)"; fi
  mkdir -p "$dest"
  (cd "$repo" && tar --exclude=.git -cf - .) | (cd "$dest" && tar -xf -)
  printf '%s\n' "$ref" > "$dest/.go1-source-revision"
  if [[ "$name" == champ ]]; then pin LIBCHAMP_REF > "$dest/.go1-libchamp-revision"; fi
  (cd "$dest" && find . -type f ! -name .go1-source-files.sha256 -print0 | sort -z | xargs -0 sha256sum > .go1-source-files.sha256)
  echo "Prepared pinned source $name $ref"
}
prepare gazebo_models https://github.com/osrf/gazebo_models.git "$(pin GAZEBO_MODELS_REF)" \
  willowgarage playground ground_plane sun asphalt_plane construction_cone construction_barrel \
  jersey_barrier dumpster fire_hydrant lamp_post oak_tree pine_tree grey_wall brick_box_3x1x3 \
  car_wheel suv beer standpipe drc_practice_blue_cylinder drc_practice_orange_jersey_barrier \
  drc_practice_truss drc_practice_yellow_parking_block collapsed_industrial tower_crane
prepare mujoco_menagerie https://github.com/google-deepmind/mujoco_menagerie.git "$(pin MENAGERIE_REF)" unitree_go1
prepare unitree_ros2 https://github.com/unitreerobotics/unitree_ros2.git "$(pin UNITREE_ROS2_REF)" cyclonedds_ws/src/unitree/unitree_go
prepare champ https://github.com/chvmp/champ.git "$(pin CHAMP_REF)"
