#!/bin/sh
set -eu

interval="${BACKUP_INTERVAL_SECONDS:-86400}"
case "$interval" in
  ""|*[!0-9]*)
    echo "BACKUP_INTERVAL_SECONDS deve ser um inteiro positivo." >&2
    exit 1
    ;;
esac

if [ "$interval" -lt 1 ]; then
  echo "BACKUP_INTERVAL_SECONDS deve ser maior que zero." >&2
  exit 1
fi

PGPASSWORD="$(tr -d '\r\n' < /run/secrets/postgres_password)"
export PGPASSWORD
mkdir -p /backups/daily /backups/weekly /backups/monthly

prune_keep() {
  directory="$1"
  keep="$2"
  find "$directory" -maxdepth 1 -type f -name '*.dump' | sort -r | awk "NR > $keep" | while IFS= read -r old_file; do
    rm -f -- "$old_file"
  done
}

run_backup() {
  timestamp="$(date -u +%Y-%m-%dT%H%M%SZ)"
  daily_file="/backups/daily/pastoral-${timestamp}.dump"
  temporary_file="${daily_file}.tmp"

  pg_dump \
    --host "$POSTGRES_HOST" \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --format custom \
    --compress 9 \
    --file "$temporary_file"

  mv "$temporary_file" "$daily_file"

  if [ "$(date -u +%u)" = "7" ]; then
    cp "$daily_file" "/backups/weekly/$(basename "$daily_file")"
  fi
  if [ "$(date -u +%d)" = "01" ]; then
    cp "$daily_file" "/backups/monthly/$(basename "$daily_file")"
  fi

  prune_keep /backups/daily 7
  prune_keep /backups/weekly 4
  prune_keep /backups/monthly 12
  touch /tmp/last-backup-success
  echo "Backup PostgreSQL concluído em $timestamp."
}

while true; do
  run_backup
  sleep "$interval"
done
