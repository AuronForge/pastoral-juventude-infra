#!/bin/sh
set -eu

password="$(tr -d '\r\n' < /run/secrets/redis_password)"
case "$password" in
  *[!A-Za-z0-9]*)
    echo "O secret do Redis deve conter somente caracteres alfanuméricos." >&2
    exit 1
    ;;
esac

export REDIS_ADDR="redis://${REDIS_HOST}:6379"
export REDIS_PASSWORD="$password"
exec /redis_exporter
