#!/usr/bin/env bash
# Exercise runtime/secrets and report copying with Docker; no Desktop VM needed.
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
stage="$(mktemp -d)"
id="ci-$RANDOM-$$"
volume="pastoral-dev_runtime-$id"
image="pastoral-e2e-fixture:$id"
network_created=false
cleanup() {
  docker volume rm "$volume" "$volume-copy" pastoral-dev_runtime-secrets >/dev/null 2>&1 || true
  docker image rm "$image" >/dev/null 2>&1 || true
  [[ "$network_created" != true ]] || docker network rm pastoral-dev_app >/dev/null 2>&1 || true
  rm -rf "$stage"
}
# This runs only on the isolated GitHub-hosted CI daemon.
if docker volume inspect pastoral-dev_runtime-secrets >/dev/null 2>&1; then
  echo 'Refusing to use an existing development secrets volume in this test.' >&2
  exit 1
fi
trap cleanup EXIT
mkdir -p "$stage/release/scripts" "$stage/release/traefik" "$stage/secrets"
cp "$repo/scripts/backend-entrypoint.sh" "$stage/release/scripts/"
cp "$repo/traefik/"*.yml "$stage/release/traefik/"
for name in postgres_password redis_password jwt_private_key.pem jwt_public_key.pem; do
  printf 'fixture-only\n' > "$stage/secrets/$name"
done
bash "$repo/scripts/sync-development-runtime.sh" "$stage/release" "$volume" "$stage/secrets"
docker run --rm --network none --user 1001:1001 \
  --mount type=volume,src=pastoral-dev_runtime-secrets,dst=/run/secrets,readonly \
  --mount "type=volume,src=$volume,dst=/etc/pastoral,readonly" alpine:3.22.1 \
  sh -c 'test -r /run/secrets/jwt_private_key && test -r /run/secrets/postgres_password && test -r /etc/pastoral/scripts/backend-entrypoint.sh && test -r /etc/pastoral/traefik/dynamic/dynamic.yml'
if ! docker network inspect pastoral-dev_app >/dev/null 2>&1; then
  docker network create pastoral-dev_app >/dev/null
  network_created=true
fi
cat > "$stage/Dockerfile" <<'EOF'
FROM alpine:3.22.1
WORKDIR /app
RUN printf '#!/bin/sh\nid -u > /app/test-results/uid\nprintf report > /app/playwright-report/index.html\nexit 7\n' > /usr/local/bin/npm && chmod +x /usr/local/bin/npm
EOF
docker build -q -t "$image" "$stage" >/dev/null
result=0
bash "$repo/scripts/run-development-e2e.sh" "$image" "$stage/reports" || result=$?
[[ "$result" == 7 && "$(cat "$stage/reports/test-results/uid")" == 1001 ]]
test -f "$stage/reports/playwright-report/index.html"
# Copy a stopped named volume between distinct volumes, preserving UID/data.
docker volume create "$volume-copy" >/dev/null
docker run --rm --network none --mount "type=volume,src=$volume,dst=/data,readonly" alpine:3.22.1 tar -C /data -cf - . |
  docker run --rm -i --network none --mount "type=volume,src=$volume-copy,dst=/data" alpine:3.22.1 tar -C /data -xpf -
docker run --rm --network none --user 1001:1001 --mount "type=volume,src=$volume-copy,dst=/data,readonly" alpine:3.22.1 test -r /data/scripts/backend-entrypoint.sh
docker volume rm "$volume-copy" >/dev/null
echo 'Runtime/secrets, non-root E2E report copy, failed-test propagation and volume transfer passed.'
