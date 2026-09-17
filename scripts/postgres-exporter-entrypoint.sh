#!/bin/sh
set -eu

password="$(tr -d '\r\n' < /run/secrets/postgres_password)"
case "$password" in
  *[!A-Za-z0-9]*)
    echo "O secret do PostgreSQL deve conter somente caracteres alfanuméricos." >&2
    exit 1
    ;;
esac

export DATA_SOURCE_NAME="postgresql://${POSTGRES_USER}:${password}@${POSTGRES_HOST}:5432/${POSTGRES_DB}?sslmode=disable"
exec /bin/postgres_exporter
