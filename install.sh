#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run this installer as root: sudo bash install.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/server-backup-agent"
CONFIG_DIR="/etc/server-backup-agent"
BACKUP_DIR="/var/backups/server-backup-agent"

if [[ "$SCRIPT_DIR" != "$INSTALL_DIR" ]]; then
  echo "Expected repository at $INSTALL_DIR" >&2
  echo "Clone it with:" >&2
  echo "  git clone <repo-url> $INSTALL_DIR" >&2
  echo "Then run: sudo bash $INSTALL_DIR/install.sh" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  default-mysql-client \
  tar \
  gzip \
  ca-certificates

python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
"$INSTALL_DIR/.venv/bin/pip" install "$INSTALL_DIR"

install -d -m 700 "$CONFIG_DIR" "$BACKUP_DIR"

if [[ ! -f "$CONFIG_DIR/config.toml" ]]; then
  install -m 600 "$INSTALL_DIR/config.example.toml" "$CONFIG_DIR/config.toml"
  echo "Created $CONFIG_DIR/config.toml"
else
  echo "Keeping existing $CONFIG_DIR/config.toml"
fi

if [[ ! -f "$CONFIG_DIR/secrets.env" ]]; then
  install -m 600 "$INSTALL_DIR/secrets.env.example" "$CONFIG_DIR/secrets.env"
  echo "Created $CONFIG_DIR/secrets.env"
else
  chmod 600 "$CONFIG_DIR/secrets.env"
  echo "Keeping existing $CONFIG_DIR/secrets.env"
fi

install -m 644 "$INSTALL_DIR/systemd/server-backup-agent.service" /etc/systemd/system/server-backup-agent.service
install -m 644 "$INSTALL_DIR/systemd/server-backup-agent.timer" /etc/systemd/system/server-backup-agent.timer
systemctl daemon-reload

cat <<'EOF'

Installation complete.

Next steps:
  1) nano /etc/server-backup-agent/secrets.env
  2) nano /etc/server-backup-agent/config.toml
  3) Test Telegram:
     /opt/server-backup-agent/.venv/bin/server-backup-agent --config /etc/server-backup-agent/config.toml --test-telegram
  4) Test Mirza backup manually:
     /opt/server-backup-agent/.venv/bin/server-backup-agent --config /etc/server-backup-agent/config.toml --job mirza-hk
  5) Enable the 6-hour timer after the manual test passes:
     systemctl enable --now server-backup-agent.timer

For age encryption, install age and set agent.encryption.enabled=true plus a public recipient in config.toml.
EOF
