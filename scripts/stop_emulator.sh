#!/usr/bin/env bash
# Stop the emulator this project started (tracked via .run/emulator.pid).
# Never touches an emulator started by hand or by another project.
set -euo pipefail

cd "$(dirname "$0")/.."
PIDFILE=".run/emulator.pid"

if [ ! -f "$PIDFILE" ]; then
  echo "no PID file ($PIDFILE): this project did not start an emulator."
  echo "If an emulator is running, it was started outside this project; stop it there."
  exit 0
fi

pid="$(cat "$PIDFILE")"
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  for _ in $(seq 10); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "ERROR: pid $pid did not stop; refusing to SIGKILL blindly." >&2
    exit 1
  fi
  echo "stopped emulator (pid $pid). Emulator state is wiped."
else
  echo "pid $pid is not running; cleaning up stale PID file."
fi
rm -f "$PIDFILE"
