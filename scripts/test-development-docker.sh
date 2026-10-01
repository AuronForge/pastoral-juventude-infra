#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/development-docker.sh"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
docker() { [[ "${fail_daemon:-false}" != true ]]; }
DOCKER_CONTEXT=desktop-linux
development_docker "$stage/missing"
[[ "$DOCKER_HOST" == unix:///var/run/docker.sock && -z "${DOCKER_CONTEXT:-}" ]]
printf 'unix:///home/example/.docker/desktop/docker.sock\n' > "$stage/endpoint"
development_docker "$stage/endpoint"
[[ "$DOCKER_HOST" == unix:///home/example/.docker/desktop/docker.sock ]]
printf 'tcp://unapproved:2375\n' > "$stage/endpoint"
if development_docker "$stage/endpoint"; then echo 'Accepted invalid endpoint' >&2; exit 1; fi
printf 'unix:///home/example/.docker/desktop/docker.sock\n' > "$stage/endpoint"
fail_daemon=true
if development_docker "$stage/endpoint"; then echo 'Silently accepted unavailable daemon' >&2; exit 1; fi
[[ "$DOCKER_HOST" == unix:///home/example/.docker/desktop/docker.sock ]]
echo 'Daemon selection, context removal and fail-closed checks passed.'
