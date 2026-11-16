#!/usr/bin/env bash
# Verify the current shell really talks to the emulator (not real AWS).
set -euo pipefail

fail=0

check() { # check <description> <command...>
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "ok   - $desc"
  else
    echo "FAIL - $desc"
    fail=1
  fi
}

EMU_DIR="$HOME/.aws/emulator/${EMULATOR_PORT:-9297}"
CA="$EMU_DIR/ca.pem"

if [ -f "$CA" ]; then
  echo "ok   - CA bundle exists: $CA"
else
  echo "FAIL - CA bundle missing: $CA (is the emulator running?)"
  fail=1
fi

if [ -f "$CA" ]; then
  if curl -sf --cacert "$CA" "https://127.0.0.1:${EMULATOR_PORT:-9297}/__admin/health" | grep -q '^ok$'; then
    echo "ok   - emulator health check returns 'ok'"
  else
    echo "FAIL - emulator health check did not return 'ok'"
    fail=1
  fi
fi

for var in AWS_SHARED_CREDENTIALS_FILE AWS_CONFIG_FILE AWS_CA_BUNDLE AWS_REGION; do
  if [ -n "${!var:-}" ]; then
    echo "ok   - $var is set"
  else
    echo "FAIL - $var is not set (run: source scripts/env.sh)"
    fail=1
  fi
done

if command -v aws >/dev/null 2>&1; then
  account="$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)"
  if [ "$account" = "000000000000" ]; then
    echo "ok   - sts get-caller-identity account is 000000000000 (emulator)"
  else
    echo "FAIL - sts account is '${account:-<error>}' (want 000000000000)"
    fail=1
  fi
else
  echo "FAIL - 'aws' CLI not found on PATH"
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo "environment NOT ready" >&2
  exit 1
fi
echo "environment ready: this shell talks to the emulator"
