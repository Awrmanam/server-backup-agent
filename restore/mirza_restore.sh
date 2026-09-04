#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  RESTORE_DB_PASSWORD='...' bash restore/mirza_restore.sh \
    <backup.tar.gz> <bot-parent-dir> <db-host> <db-name> <db-user> --execute

Example:
  RESTORE_DB_PASSWORD='secret' bash restore/mirza_restore.sh \
    mirza-hk-20260904-200000Z.tar.gz /var/www/html 127.0.0.1 mirza mirza_user --execute

Notes:
- If your backup is split, concatenate the parts first.
- If your backup is encrypted with age, decrypt it first.
- The database and DB user must already exist.
- Existing bot directory is moved aside before extraction.
EOF
}

if [[ $# -ne 6 || "$6" != "--execute" ]]; then
  usage
  exit 2
fi

ARCHIVE="$1"
BOT_PARENT="$2"
DB_HOST="$3"
DB_NAME="$4"
DB_USER="$5"

if [[ ! -f "$ARCHIVE" ]]; then
  echo "Backup archive not found: $ARCHIVE" >&2
  exit 1
fi
if [[ -z "${RESTORE_DB_PASSWORD:-}" ]]; then
  echo "RESTORE_DB_PASSWORD environment variable is required" >&2
  exit 1
fi

for cmd in tar gzip mysql; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing command: $cmd" >&2; exit 1; }
done

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

tar -tzf "$ARCHIVE" >/dev/null
tar -xzf "$ARCHIVE" -C "$TMP"

[[ -f "$TMP/database.sql.gz" ]] || { echo "database.sql.gz missing from backup" >&2; exit 1; }
[[ -f "$TMP/bot-files.tar.gz" ]] || { echo "bot-files.tar.gz missing from backup" >&2; exit 1; }

gzip -t "$TMP/database.sql.gz"
tar -tzf "$TMP/bot-files.tar.gz" >/dev/null

BOT_BASENAME="$(tar -tzf "$TMP/bot-files.tar.gz" | head -n1 | cut -d/ -f1)"
if [[ -z "$BOT_BASENAME" ]]; then
  echo "Could not determine bot directory name from bot-files.tar.gz" >&2
  exit 1
fi

mkdir -p "$BOT_PARENT"
TARGET="$BOT_PARENT/$BOT_BASENAME"
if [[ -e "$TARGET" ]]; then
  MOVED="$TARGET.pre-restore-$(date +%Y%m%d-%H%M%S)"
  echo "Moving existing bot directory to: $MOVED"
  mv "$TARGET" "$MOVED"
fi

echo "Restoring bot files to $BOT_PARENT ..."
tar -xzpf "$TMP/bot-files.tar.gz" -C "$BOT_PARENT"

echo "Restoring database $DB_NAME on $DB_HOST ..."
export MYSQL_PWD="$RESTORE_DB_PASSWORD"
gzip -dc "$TMP/database.sql.gz" | mysql -h "$DB_HOST" -u "$DB_USER" "$DB_NAME"
unset MYSQL_PWD

echo "Restore completed. Review file ownership, Nginx/PHP/systemd configs, then start the bot deliberately."
