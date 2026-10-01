#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
export BACKEND_IMAGE=ghcr.io/auronforge/pastoral-juventude-backend:dev-ci
export MIGRATION_IMAGE=ghcr.io/auronforge/pastoral-juventude-backend:dev-ci-migrations
export FRONTEND_IMAGE=ghcr.io/auronforge/pastoral-juventude-frontend:dev-ci
: "${SECRETS_DIR:?Set SECRETS_DIR to the generated CI secrets directory}"

compose=(docker compose --project-name pastoral-redis-ci -f compose.development.yaml)
cleanup() {
  result=$?
  trap - EXIT
  if (( result != 0 )); then
    "${compose[@]}" logs --no-color redis >&2 || true
  fi
  # Only this isolated CI project owns these disposable volumes.
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  exit "$result"
}
trap cleanup EXIT

"${compose[@]}" up -d --no-deps --wait --wait-timeout 90 redis
# Expand these variables inside the container, not on the CI host.
# shellcheck disable=SC2016
"${compose[@]}" exec -T redis sh -ec '
  redis_uid=$(id -u redis)
  test "$(stat -c %a /tmp/pastoral-redis.conf)" = 600
  test "$(stat -c %u /tmp/pastoral-redis.conf)" = "$redis_uid"
  test "$(awk "/^Uid:/ {print \$2}" /proc/1/status)" = "$redis_uid"
  REDISCLI_AUTH=$(cat /run/secrets/redis_password) redis-cli ping | grep -qx PONG
  redis-cli ping | grep -q NOAUTH
'

# A restart also must regenerate and read the private config successfully.
"${compose[@]}" restart redis
"${compose[@]}" up -d --no-deps --wait --wait-timeout 90 redis
# Expand these variables inside the container, not on the CI host.
# shellcheck disable=SC2016
"${compose[@]}" exec -T redis sh -ec '
  REDISCLI_AUTH=$(cat /run/secrets/redis_password) redis-cli ping | grep -qx PONG
'
echo "Redis startup, authentication, non-root process and restart passed."
