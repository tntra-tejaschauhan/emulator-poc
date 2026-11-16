#!/usr/bin/env bash
# Start the AWS Emulator in the background (telemetry off). If it already
# answers the health check (e.g. started by hand), do nothing and exit 0.
set -euo pipefail

cd "$(dirname "$0")/.."
PORT="${EMULATOR_PORT:-9297}"
CA="$HOME/.aws/emulator/$PORT/ca.pem"
mkdir -p .run
LOG=".run/emulator.log"
PIDFILE=".run/emulator.pid"

health_ok() {
  [ -f "$CA" ] && curl -sf --cacert "$CA" "https://127.0.0.1:$PORT/__admin/health" | grep -q '^ok$'
}

if health_ok; then
  echo "emulator already running and healthy on port $PORT; not starting another copy."
  exit 0
fi

if ! command -v aws-emulator >/dev/null 2>&1; then
  echo "ERROR: 'aws-emulator' not found on PATH. Run: make install-emulator" >&2
  exit 1
fi

echo "starting: aws-emulator --telemetry off (log: $LOG)"
nohup aws-emulator --telemetry off >"$LOG" 2>&1 &
echo $! >"$PIDFILE"

for _ in $(seq 30); do
  sleep 1
  if health_ok; then
    echo "emulator is up on port $PORT (pid $(cat "$PIDFILE"))."
    exit 0
  fi
done

echo "ERROR: emulator did not become healthy within 30s. Log:" >&2
tail -20 "$LOG" >&2 || true
exit 1
