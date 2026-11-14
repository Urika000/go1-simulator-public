#!/bin/bash
# Restore only the stock go1-full desktop/debug packages; no dependency upgrades.
set -euo pipefail
apt-get update
mapfile -t tools < <(apt-cache --names-only search '^ros-humble-rqt' | awk '{print $1}' | grep -v -E -- '-(dbgsym|dbg)$' | sort -u)
((${#tools[@]}))
tools+=(ros-humble-teleop-twist-keyboard ros-humble-plotjuggler-ros mesa-utils x11-apps)
plan=$(mktemp)
trap 'rm -f "$plan"' EXIT
apt-get -s install --no-upgrade --no-install-recommends "${tools[@]}" > "$plan"
cat "$plan"
# Existing packages are rendered as `Inst package [old-version] (new-version...)`.
if grep -E '^Inst [^ ]+ \[' "$plan"; then
    echo 'Refusing dependency upgrades while restoring original tools' >&2
    exit 1
fi
apt-get install -y --no-upgrade --no-install-recommends "${tools[@]}"
mkdir -p /usr/local/share/go1-standalone
dpkg-query -W "${tools[@]}" > /usr/local/share/go1-standalone/original-tools.txt
rm -rf /var/lib/apt/lists/*
