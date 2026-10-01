#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
mode="${1:?Usage: migrate-development-desktop.sh check|migrate unix:///.../docker.sock}"
target="${2:?Desktop socket URL}"
[[ "$mode" =~ ^(check|migrate)$ && "$target" =~ ^unix:///home/[^[:space:]]+/\.docker/desktop/docker\.sock$ ]]
source_host=unix:///var/run/docker.sock
root=/opt/pastoral/dev
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unset DOCKER_CONTEXT
exec 9>"$root/deploy.lock"
flock -w 600 9
if [[ -f "$root/docker-host" ]]; then
  [[ "$(cat "$root/docker-host")" == "$source_host" ]] || { echo 'Already switched; refusing a second migration.' >&2; exit 1; }
fi
set -a
# shellcheck disable=SC1091
source "$root/development.env"
# shellcheck disable=SC1091
source "$root/current-images.env"
set +a
release="$(readlink -f "$root/current")"
[[ "$release" == "$root/releases/"* ]]
test -f "$release/compose.development.yaml"
test -f "$repo/compose.development.desktop.yaml"
for secret in postgres_password redis_password jwt_private_key.pem jwt_public_key.pem; do
  test -r "${SECRETS_DIR:-$root/secrets}/$secret"
done
src() { docker --host "$source_host" "$@"; }
dst() { docker --host "$target" "$@"; }
[[ "$(src info --format '{{.ID}}')" != "$(dst info --format '{{.ID}}')" ]]
[[ -z "$(dst ps -aq --filter label=com.docker.compose.project=pastoral-dev)" ]]
for volume in pastoral-dev_postgres-data pastoral-dev_redis-data; do
  src volume inspect "$volume" >/dev/null
  if dst volume inspect "$volume" >/dev/null 2>&1; then
    echo "Destination volume already exists: $volume. Inspect before retry; never overwrite." >&2
    exit 1
  fi
done
metadata="$root/reports/$(basename "$release")/deployment.txt"
e2e_sha="$(sed -n 's/^e2e=//p' "$metadata")"
[[ "$e2e_sha" =~ ^[0-9a-f]{40}$ ]]
e2e_image="pastoral-dev-e2e:$e2e_sha"
images=("$BACKEND_IMAGE" "$MIGRATION_IMAGE" "$FRONTEND_IMAGE" traefik:v3.7.13 postgres:17.11-alpine pastoral-redis:8.6.6-1 "$e2e_image")
for image in "${images[@]}"; do src image inspect "$image" >/dev/null; done
echo 'Preflight passed: distinct daemons, readable secrets, source images/volumes, clean target.'
[[ "$mode" == migrate ]] || exit 0

helper=alpine:3.22.1
src image inspect "$helper" >/dev/null 2>&1 || src pull "$helper" >/dev/null
src image save "${images[@]}" "$helper" | dst image load >/dev/null
id="desktop-$(date -u +%Y%m%dT%H%M%SZ)"
backup="$root/backups/$id"
mkdir -p "$backup" "$root/reports/$id"
export DEV_RUNTIME_VOLUME="pastoral-dev_runtime-$id"
cp "$repo/compose.development.desktop.yaml" "$release/"
source_compose=(docker --host "$source_host" compose -p pastoral-dev -f "$release/compose.development.yaml")
target_compose=(docker --host "$target" compose -p pastoral-dev -f "$release/compose.development.yaml" -f "$release/compose.development.desktop.yaml")
DOCKER_HOST="$target" bash "$repo/scripts/sync-development-runtime.sh" "$release" "$DEV_RUNTIME_VOLUME" "${SECRETS_DIR:-$root/secrets}"
"${target_compose[@]}" config --quiet
# Retain a logical backup as well as consistent cold volume snapshots.
# shellcheck disable=SC2016
"${source_compose[@]}" exec -T postgres sh -c 'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup/postgres.dump"
stopped=false
target_started=false
recover() {
  result=$?
  if (( result != 0 )) && [[ "$stopped" == true ]]; then
    [[ "$target_started" != true ]] || "${target_compose[@]}" stop || true
    "${source_compose[@]}" up -d --wait --wait-timeout 180 || true
    echo "Migration failed; attempted to restart source. Backups: $backup" >&2
  fi
}
trap recover EXIT
stopped=true
"${source_compose[@]}" stop -t 60
for key in postgres-data redis-data; do
  volume="pastoral-dev_$key"
  src run --rm --network none --mount "type=volume,src=$volume,dst=/data,readonly" "$helper" tar -C /data -cf - . > "$backup/$key.tar"
  test -s "$backup/$key.tar"
  dst volume create --label com.docker.compose.project=pastoral-dev --label "com.docker.compose.volume=$key" "$volume" >/dev/null
  dst run --rm -i --network none --mount "type=volume,src=$volume,dst=/data" "$helper" tar -C /data -xpf - < "$backup/$key.tar"
done
target_started=true
# Quarantine host ports until the smoke succeeds; public tunnel cannot write to the candidate.
DEV_BIND_ADDRESS=127.0.0.1 DEV_HTTP_PORT=18081 DEV_API_TUNNEL_PORT=18082 \
  "${target_compose[@]}" up -d --wait --wait-timeout 180 postgres redis backend frontend traefik
DOCKER_HOST="$target" bash "$repo/scripts/run-development-e2e.sh" "$e2e_image" "$root/reports/$id"
# Switch subsequent workflow logins/deploys/diagnostics only after successful smoke.
printf 'DEV_RUNTIME_VOLUME=%s\n' "$DEV_RUNTIME_VOLUME" > "$release/desktop-runtime.env"
printf 'source=%s\ntarget=%s\nbackup=%s\ne2e=%s\n' "$source_host" "$target" "$backup" "$e2e_sha" > "$root/reports/$id/migration.txt"
printf '%s\n' "$target" > "$root/docker-host.tmp"
mv "$root/docker-host.tmp" "$root/docker-host"
# From this commit point, source data is stale; do not automatically roll it back.
trap - EXIT
"${target_compose[@]}" up -d --wait --wait-timeout 180 traefik
curl --fail --silent --show-error "http://127.0.0.1:${DEV_API_TUNNEL_PORT:-8082}/api/v1/health" > "$root/reports/$id/public-health.json"
echo "Migration passed; pastoral-dev is now visible in Docker Desktop. Evidence: $root/reports/$id"
