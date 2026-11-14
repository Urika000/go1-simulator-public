#!/usr/bin/env bash
# One standalone image. SIM_IMAGE/SIM_DOCKERFILE override the local dev defaults.
# Optional .env retains host version/build settings; no push is performed.
set -euo pipefail
# Avoid fetching a Dockerfile frontend; use the approved locally available base.
export DOCKER_BUILDKIT=${DOCKER_BUILDKIT:-0}
cd "$(dirname "$0")"
if [[ -f ./.env ]]; then set -a; source ./.env; set +a; fi
IMAGE="${SIM_IMAGE:-go1-sim:public}"
BASE_IMAGE="registry.cookcloud.ru/base_images/ros2-base-humble-amd64:${BASE_VERSION:-v1.0.1}"
echo "Образ: ${IMAGE}  база: ${BASE_IMAGE}"
docker build --pull=false --platform linux/amd64 -f "${SIM_DOCKERFILE:-Dockerfile}" -t "${IMAGE}" \
    --build-arg BASE_IMAGE="${BASE_IMAGE}" \
    --build-arg BUILD_JOBS="${BUILD_JOBS:-1}" \
    .
