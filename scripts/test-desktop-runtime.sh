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
  docker volume rm "$volume" "$volume-copy" pastoral-dev_runtime-secrets pastoral-dev_observability-secrets >/dev/null 2>&1 || true
  docker image rm "$image" >/dev/null 2>&1 || true
  [[ "$network_created" != true ]] || docker network rm pastoral-dev_app >/dev/null 2>&1 || true
  rm -rf "$stage"
}
# This runs only on the isolated GitHub-hosted CI daemon.
if docker volume inspect pastoral-dev_runtime-secrets >/dev/null 2>&1 ||
  docker volume inspect pastoral-dev_observability-secrets >/dev/null 2>&1; then
  echo 'Refusing to use an existing development secrets volume in this test.' >&2
  exit 1
fi
trap cleanup EXIT
mkdir -p "$stage/release/scripts" "$stage/release/traefik" "$stage/release/prometheus" "$stage/release/loki" "$stage/release/alloy" "$stage/release/grafana" "$stage/secrets"
cp "$repo/scripts/backend-entrypoint.sh" "$stage/release/scripts/"
cp "$repo/traefik/"*.yml "$stage/release/traefik/"
cp "$repo/prometheus/prometheus.development.yml" "$stage/release/prometheus/"
cp "$repo/loki/loki.yml" "$stage/release/loki/"
cp "$repo/alloy/config.development.alloy" "$stage/release/alloy/"
cp -R "$repo/grafana/provisioning" "$stage/release/grafana/"
for name in postgres_password redis_password jwt_private_key.pem jwt_public_key.pem grafana_admin_password; do
  printf 'fixture-only\n' > "$stage/secrets/$name"
done
DEV_OBSERVABILITY_ENABLED=true bash "$repo/scripts/sync-development-runtime.sh" "$stage/release" "$volume" "$stage/secrets"
docker run --rm --network none --user 1001:1001 \
  --mount type=volume,src=pastoral-dev_runtime-secrets,dst=/run/secrets,readonly \
  --mount "type=volume,src=$volume,dst=/etc/pastoral,readonly" alpine:3.22.1 \
  sh -c 'test -r /run/secrets/jwt_private_key && test -r /run/secrets/postgres_password && test -r /etc/pastoral/scripts/backend-entrypoint.sh && test -r /etc/pastoral/traefik/dynamic/dynamic.yml'
# Grafana reads only its own secret; the application UID cannot read it.
docker run --rm --network none --user 472:0 \
  --mount type=volume,src=pastoral-dev_observability-secrets,dst=/run/secrets,readonly \
  --mount "type=volume,src=$volume,dst=/etc/pastoral,readonly" alpine:3.22.1 \
  sh -c 'test -r /run/secrets/grafana_admin_password && test ! -e /run/secrets/postgres_password && test -r /etc/pastoral/prometheus/prometheus.yml && test -r /etc/pastoral/loki/loki.yml && test -r /etc/pastoral/alloy/config.alloy && test -r /etc/pastoral/grafana/provisioning/datasources/datasources.yml'
if docker run --rm --network none --user 1001:1001 \
  --mount type=volume,src=pastoral-dev_observability-secrets,dst=/run/secrets,readonly alpine:3.22.1 \
  test -r /run/secrets/grafana_admin_password; then
  echo 'Application UID can read the Grafana secret.' >&2
  exit 1
fi
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
echo 'Runtime/secrets, observability secret isolation, non-root E2E report copy, failed-test propagation and volume transfer passed.'
