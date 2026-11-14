#!/usr/bin/env bash
# Reuse existing pinned-source preparation, never build Judge/Participant/Simulator.
set -euo pipefail
cd "$(dirname "$0")/.."
export DOCKER_BUILDKIT=${DOCKER_BUILDKIT:-0}
base=${BASE_IMAGE:-registry.cookcloud.ru/base_images/ros2-base-humble-amd64:v1.0.1}
mkdir -p .dependency-cache/{sources,wheels,pip,git}
verify() {
    local name pin revision cache=${1:-.dependency-cache}
    for name in gazebo_models mujoco_menagerie unitree_ros2 champ; do
        case "$name" in
            gazebo_models) pin=GAZEBO_MODELS_REF;; mujoco_menagerie) pin=MENAGERIE_REF;;
            unitree_ros2) pin=UNITREE_ROS2_REF;; champ) pin=CHAMP_REF;;
        esac
        revision=$(sed -n "s/^ARG $pin=//p" Dockerfile)
        test "$(cat "$cache/sources/$name/.go1-source-revision")" = "$revision"
        (cd "$cache/sources/$name" && sha256sum --quiet -c .go1-source-files.sha256)
        printf 'Verified source %s %s\n' "$name" "$revision"
    done
    test "$(cat "$cache/sources/champ/.go1-libchamp-revision")" = "$(sed -n 's/^ARG LIBCHAMP_REF=//p' Dockerfile)"
    python3 - "$cache" <<'PY'
from pathlib import Path
import hashlib,re,sys
required=re.findall(r'--hash=sha256:([0-9a-f]{64})',Path('config/standalone-python.lock').read_text())
available={hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(sys.argv[1])/'wheels').glob('*.whl')}
if not required or set(required)-available:
    raise SystemExit('Missing/invalid pinned wheels; run without CACHE_OFFLINE=1 or provide the documented wheelhouse')
print('Verified all standalone wheel hashes')
PY
}
# Optional import from a trusted, previously prepared dependency bundle. Only
# dependency inputs are copied; the source checkout remains this repository.
if [[ -n "${SOURCE_CACHE:-}" ]]; then
    imported=$(realpath "$SOURCE_CACHE")
    [[ "$imported" != "$(realpath .dependency-cache)" ]] || { echo 'SOURCE_CACHE must be external' >&2; exit 1; }
    verify "$imported"
    for input in sources wheels; do
        [[ ! -e ".dependency-cache/$input" || -z "$(ls -A ".dependency-cache/$input")" ]] || {
            echo "Refusing to overwrite .dependency-cache/$input; use the existing cache or a fresh checkout" >&2; exit 1;
        }
    done
    cp -a "$imported/sources" "$imported/wheels" .dependency-cache/
    verify
    exit
fi
if [[ "${CACHE_OFFLINE:-0}" == 1 ]]; then verify; exit; fi
# Both helper images are built here from approved base + existing Dockerfiles.
# No pre-existing go1-sim:* / integration runtime is a required input.
docker image inspect "$base" >/dev/null
docker build --pull=false -f Dockerfile.dependencies-base --build-arg ROS_BASE="$base" -t go1-source-cache-base:local .
docker build --pull=false -f Dockerfile.dependencies-download --build-arg RAGEOS_BASE=go1-source-cache-base:local -t go1-source-download:local .
docker run --rm --user "$(id -u):$(id -g)" --entrypoint python3 \
    -v "$PWD/.dependency-cache:/dependency-cache" -v "$PWD/config/standalone-python.lock:/requirements.txt:ro" \
    go1-source-download:local -m pip download --timeout 120 --retries 3 --only-binary=:all: --no-deps \
    --cache-dir /dependency-cache/pip --dest /dependency-cache/wheels --require-hashes -r /requirements.txt
docker run --rm --user "$(id -u):$(id -g)" --entrypoint /bin/bash \
    -v "$PWD/.dependency-cache:/dependency-cache" -v "$PWD/Dockerfile:/Dockerfile:ro" \
    -v "$PWD/scripts/prepare-rageos-sources.sh:/prepare.sh:ro" go1-source-download:local /prepare.sh
verify
