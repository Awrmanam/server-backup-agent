#!/usr/bin/env bash
set -Eeuo pipefail

REPO="Awrmanam/server-backup-agent"
BRANCH="main"
INSTALL_DIR="/opt/server-backup-agent"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    exec sudo -E bash "$0" "$@"
  fi
  echo "Run as root." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

if ! command -v git >/dev/null 2>&1; then
  apt-get update
  apt-get install -y git ca-certificates
fi

if [[ -d "$INSTALL_DIR/.git" ]]; then
  echo "[1/3] Updating existing installation..."
  git -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH"
  git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
else
  echo "[1/3] Downloading server-backup-agent..."
  if [[ -e "$INSTALL_DIR" ]]; then
    mv "$INSTALL_DIR" "${INSTALL_DIR}.bak.$(date +%s)"
  fi
  git clone --depth 1 --branch "$BRANCH" "https://github.com/${REPO}.git" "$INSTALL_DIR"
fi

chmod +x "$INSTALL_DIR/install.sh"

echo "[2/3] Installing dependencies and service files..."
bash "$INSTALL_DIR/install.sh"

echo "[3/3] Done."
echo
echo "Configure Telegram secrets:"
echo "  nano /etc/server-backup-agent/secrets.env"
echo
echo "Then test Telegram:"
echo "  /opt/server-backup-agent/.venv/bin/server-backup-agent --config /etc/server-backup-agent/config.toml --test-telegram"
