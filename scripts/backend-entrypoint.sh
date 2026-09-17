#!/bin/sh
set -eu

read_secret() {
  tr -d '\r\n' < "$1"
}

postgres_password="$(read_secret /run/secrets/postgres_password)"
redis_password="$(read_secret /run/secrets/redis_password)"

case "$postgres_password$redis_password" in
  *[!A-Za-z0-9]*)
    echo "Os secrets de PostgreSQL e Redis devem conter somente caracteres alfanuméricos." >&2
    exit 1
    ;;
esac

export DATABASE_URL="postgresql://${POSTGRES_USER}:${postgres_password}@${POSTGRES_HOST}:5432/${POSTGRES_DB}?schema=public"
export REDIS_URL="redis://:${redis_password}@${REDIS_HOST}:6379/0"

exec node dist/main.js
