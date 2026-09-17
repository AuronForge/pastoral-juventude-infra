#!/bin/sh
set -eu

password="$(tr -d '\r\n' < /run/secrets/redis_password)"
case "$password" in
  ""|*[!A-Za-z0-9]*)
    echo "O secret do Redis deve ser alfanumérico e não vazio." >&2
    exit 1
    ;;
esac

umask 077
cat > /tmp/pastoral-redis.conf <<EOF
bind 0.0.0.0
protected-mode yes
port 6379
dir /data
appendonly yes
appendfsync everysec
requirepass $password
maxmemory 512mb
maxmemory-policy volatile-lru
EOF

exec docker-entrypoint.sh redis-server /tmp/pastoral-redis.conf
