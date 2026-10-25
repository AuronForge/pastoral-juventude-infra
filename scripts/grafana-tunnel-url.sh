#!/usr/bin/env bash
# Print the current quick tunnel URL of the development Grafana.
set -Eeuo pipefail
if [[ -r /opt/pastoral/dev/docker-host ]]; then
  # shellcheck disable=SC1091
  source "$(dirname "${BASH_SOURCE[0]}")/development-docker.sh"
  development_docker
fi
container="$(docker ps --quiet \
  --filter label=com.docker.compose.project=pastoral-dev \
  --filter label=com.docker.compose.service=grafana-tunnel)"
if [[ -z "$container" ]]; then
  echo 'Grafana tunnel is not running; check DEV_OBSERVABILITY_ENABLED and the last deploy.' >&2
  exit 1
fi
url="$(docker logs "$container" 2>&1 | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -n 1 || true)"
if [[ -z "$url" ]]; then
  echo 'Tunnel URL not published yet; retry in a few seconds.' >&2
  exit 1
fi
echo "$url"
