#!/usr/bin/env bash
set -e
case "${1:-ping}" in
  ping) printf '%s\n' '{"supported_tasks":["T2","T3","T4","T5"],"example":"interface-only"}'; exit 0;;
  T2|T3|T4|T5) task=$1; shift;;
  *) echo 'Expected ping|T2|T3|T4|T5' >&2; exit 2;;
esac
source /etc/go1_sim_env.sh
exec python3 /opt/participant-example.py "$task" "$@"
