#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
release="${1:?Release directory}"
volume="${2:?Release-specific volume}"
secrets_dir="${3:?Secrets directory}"
[[ "$volume" =~ ^pastoral-dev_runtime-[a-zA-Z0-9-]+$ ]]
helper=alpine:3.22.1
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/runtime/scripts" "$stage/runtime/traefik/dynamic" "$stage/secrets"
cp "$release/scripts/backend-entrypoint.sh" "$stage/runtime/scripts/"
cp "$release/traefik/traefik.yml" "$stage/runtime/traefik/"
cp "$release/traefik/dynamic.development.yml" "$stage/runtime/traefik/dynamic/dynamic.yml"
for secret in postgres_password redis_password jwt_private_key jwt_public_key; do
  source_file="$secrets_dir/$secret"
  [[ "$secret" != jwt_* ]] || source_file="$source_file.pem"
  cp "$source_file" "$stage/secrets/$secret"
done
# Tar extracts with daemon-local ownership; no VirtioFS/host UID mapping.
chmod -R a+rX "$stage/runtime"
chmod 0440 "$stage/secrets/"*
docker image inspect "$helper" >/dev/null 2>&1 || docker pull "$helper" >/dev/null
docker volume create --label com.docker.compose.project=pastoral-dev "$volume" >/dev/null
docker volume create --label com.docker.compose.project=pastoral-dev pastoral-dev_runtime-secrets >/dev/null
tar -C "$stage/runtime" -cf - . | docker run --rm -i --network none --mount "type=volume,src=$volume,dst=/data" "$helper" tar -C /data -xf -
tar -C "$stage/secrets" -cf - . | docker run --rm -i --network none --mount type=volume,src=pastoral-dev_runtime-secrets,dst=/data "$helper" sh -c 'tar -C /data -xf - && chown -R 0:1001 /data && chmod 0750 /data && chmod 0440 /data/*'
