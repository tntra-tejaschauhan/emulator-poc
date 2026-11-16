#!/usr/bin/env bash
# Point this shell at the local AWS Emulator. SOURCE this file, do not run it:
#   source scripts/env.sh
set -euo pipefail

EMULATOR_PORT="${EMULATOR_PORT:-9297}"
EMULATOR_DIR="$HOME/.aws/emulator/$EMULATOR_PORT"

if [ ! -d "$EMULATOR_DIR" ]; then
  echo "WARNING: $EMULATOR_DIR does not exist yet." >&2
  echo "The emulator has not been started at least once on port $EMULATOR_PORT." >&2
  echo "Start it first: make start-emulator" >&2
fi

# Never let real credentials leak into emulator calls: environment variables
# win over the credentials file, so unset them all first.
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN \
  AWS_PROFILE AWS_DEFAULT_PROFILE \
  AWS_WEB_IDENTITY_TOKEN_FILE AWS_ROLE_ARN AWS_ROLE_SESSION_NAME \
  AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_CONTAINER_CREDENTIALS_FULL_URI \
  AWS_CONTAINER_AUTHORIZATION_TOKEN

export AWS_ENDPOINT_URL="https://127.0.0.1:$EMULATOR_PORT"
export AWS_SHARED_CREDENTIALS_FILE="$EMULATOR_DIR/emulator_credentials"
export AWS_CONFIG_FILE="$EMULATOR_DIR/config"
export AWS_CA_BUNDLE="$EMULATOR_DIR/ca.pem"
export NODE_EXTRA_CA_CERTS="$EMULATOR_DIR/ca.pem"
export AWS_EC2_METADATA_DISABLED=true
export AWS_DISABLE_HOST_PREFIX_INJECTION=true
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
export AWS_PAGER=""

echo "AWS environment now points at the emulator (https://127.0.0.1:$EMULATOR_PORT)."
echo "Verify: scripts/check_env.sh"
