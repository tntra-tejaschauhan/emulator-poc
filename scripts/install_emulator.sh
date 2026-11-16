#!/usr/bin/env bash
# Install AWS Emulator on Debian/Ubuntu (amd64 or arm64).
# Usage: scripts/install_emulator.sh [--verify]
#   --verify  also download the .sig file and check the GPG signature.
set -euo pipefail

VERIFY=0
if [ "${1:-}" = "--verify" ]; then VERIFY=1; fi

if command -v aws-emulator >/dev/null 2>&1; then
  echo "aws-emulator is already installed: $(command -v aws-emulator)"
  aws-emulator -v || true
  exit 0
fi

if [ ! -f /etc/os-release ]; then
  echo "ERROR: cannot detect OS (no /etc/os-release). This script supports Debian/Ubuntu only." >&2
  exit 1
fi
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-} ${ID_LIKE:-}" in
  *debian* | *ubuntu*) ;;
  *)
    echo "ERROR: unsupported OS '$ID'. This script supports Debian/Ubuntu only." >&2
    echo "On macOS/Windows, run the emulator in Docker from an image built with" >&2
    echo "the Dockerfile in the AWS docs. See README.md." >&2
    exit 1
    ;;
esac

arch="$(uname -m)"
case "$arch" in
  x86_64)  pkg="aws-emulator_amd64.deb" ;;
  aarch64) pkg="aws-emulator_arm64.deb" ;;
  *)
    echo "ERROR: unsupported CPU architecture '$arch' (need x86_64 or aarch64)." >&2
    exit 1
    ;;
esac

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
echo "downloading $pkg ..."
curl -fsSLo "$tmp/$pkg" "https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/latest/$pkg"

if [ "$VERIFY" = "1" ]; then
  echo "downloading signature ..."
  curl -fsSLo "$tmp/$pkg.sig" "https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/latest/$pkg.sig"
  curl -fsSLo "$tmp/aws-publishing.asc" "https://downloads.aws.com/keys/gpg/current.asc"
  gpg --import "$tmp/aws-publishing.asc"
  echo "expect fingerprint: 98BC F336 A3BE 53B7 34E9 67C5 2E5B F49B D940 F624"
  gpg --fingerprint ssm-publishing@amazon.com
  gpg --verify "$tmp/$pkg.sig" "$tmp/$pkg"
fi

echo "installing (needs sudo) ..."
sudo apt-get install -y "$tmp/$pkg"
aws-emulator -v
