#!/usr/bin/env bash
# End-to-end demo: upload a sample file via the API, poll until PROCESSED,
# print the result. Requires the API and the worker to be running
# (separate terminals: `make api` and `make worker`).
set -euo pipefail

API="${API_BASE:-http://127.0.0.1:${API_PORT:-8000}}"
TIMEOUT="${DEMO_TIMEOUT:-120}"

echo "== demo against $API =="
health="$(curl -sf "$API/health")" || {
  echo "ERROR: API not reachable at $API. Start it with 'make api'." >&2
  exit 1
}
echo "health: $health"

sample="$(mktemp).txt"
cat >"$sample" <<'EOF'
hello emulator
this is a small demo file
with three lines and a few words
EOF

echo "uploading $sample ..."
upload="$(curl -sf -F "file=@$sample;type=text/plain" "$API/files")"
echo "upload response: $upload"
file_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["file_id"])' <<<"$upload")"
echo "file_id: $file_id (status should flip PENDING -> PROCESSED)"

deadline=$((SECONDS + TIMEOUT))
status=""
while [ "$SECONDS" -lt "$deadline" ]; do
  status="$(curl -sf "$API/files/$file_id" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  echo "  status: $status"
  if [ "$status" = "PROCESSED" ] || [ "$status" = "FAILED" ]; then
    break
  fi
  sleep 2
done

result="$(curl -sf "$API/files/$file_id")"
echo "final: $result"
rm -f "$sample"

if [ "$status" = "PROCESSED" ]; then
  echo "DEMO OK: PENDING -> PROCESSED"
else
  echo "DEMO FAILED: last status '$status'" >&2
  exit 1
fi
