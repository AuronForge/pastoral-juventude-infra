#!/usr/bin/env bash
# Archive a stopped, pre-cutover candidate before freeing its names for retry.
set -Eeuo pipefail
umask 077
target="${1:?Desktop socket URL}"
[[ "$target" =~ ^unix:///home/[^[:space:]]+/[.]docker/desktop/docker[.]sock$ ]]
root=/opt/pastoral/dev
unset DOCKER_CONTEXT
exec 9>"$root/deploy.lock"
flock -w 600 9
[[ ! -f "$root/docker-host" || "$(cat "$root/docker-host")" == unix:///var/run/docker.sock ]] || {
  echo 'Desktop is already authoritative; refusing candidate cleanup.' >&2; exit 1;
}
src() { docker --host unix:///var/run/docker.sock "$@"; }
dst() { docker --host "$target" "$@"; }
[[ "$(src info --format '{{.ID}}')" != "$(dst info --format '{{.ID}}')" ]]
source_backend="$(src ps -q --filter label=com.docker.compose.project=pastoral-dev --filter label=com.docker.compose.service=backend)"
[[ -n "$source_backend" && "$source_backend" != *$'\n'* ]]
src exec "$source_backend" node -e "fetch('http://127.0.0.1:3000/health/ready').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"
mapfile -t containers < <(dst ps -aq --filter label=com.docker.compose.project=pastoral-dev)
for container in "${containers[@]}"; do
  [[ "$(dst inspect --format '{{.State.Running}}' "$container")" == false ]] || {
    echo 'A candidate container is running; refusing cleanup.' >&2; exit 1;
  }
done
helper=alpine:3.22.1
dst image inspect "$helper" >/dev/null
backup="$root/backups/desktop-failed-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup"
volumes=()
for key in postgres-data redis-data; do
  volume="pastoral-dev_$key"
  if dst volume inspect "$volume" >/dev/null 2>&1; then
    [[ "$(dst volume inspect --format '{{index .Labels "com.docker.compose.project"}}' "$volume")" == pastoral-dev ]]
    dst run --rm --network none --mount "type=volume,src=$volume,dst=/data,readonly" "$helper" tar -C /data -cf - . > "$backup/$key.tar"
    test -s "$backup/$key.tar"
    volumes+=("$volume")
  fi
done
# Every candidate volume is archived before removing any stopped container.
for container in "${containers[@]}"; do dst rm "$container" >/dev/null; done
for volume in "${volumes[@]}"; do dst volume rm "$volume" >/dev/null; done
printf 'target=%s\nstatus=archived-pre-cutover-candidate\n' "$target" > "$backup/candidate.txt"
echo "Stopped candidate archived; fresh migration can run. Backup: $backup"
