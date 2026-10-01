#!/usr/bin/env bash
set -Eeuo pipefail
image="${1:?E2E image}"
report_dir="${2:?Report directory}"
container="$(docker create --network pastoral-dev_app \
  -e HOME=/tmp -e CI=true -e E2E_FRONTEND_BASE_URL=http://traefik \
  -e E2E_BACKEND_BASE_URL=http://backend:3000 \
  --entrypoint sleep "$image" infinity)"
trap 'docker rm -f "$container" >/dev/null' EXIT
docker start "$container" >/dev/null
docker exec --user 0 "$container" mkdir -p /app/playwright-report /app/test-results
docker exec --user 0 "$container" chown -R 1001:1001 /app/playwright-report /app/test-results
result=0
docker exec --user 1001:1001 "$container" npm run test:e2e || result=$?
mkdir -p "$report_dir/playwright-report" "$report_dir/test-results"
docker cp "$container:/app/playwright-report/." "$report_dir/playwright-report/"
docker cp "$container:/app/test-results/." "$report_dir/test-results/"
exit "$result"
