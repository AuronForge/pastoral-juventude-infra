#!/usr/bin/env bash
# Source this file before login, deployment, migration or diagnostics.
development_docker() {
  local endpoint_file="${1:-/opt/pastoral/dev/docker-host}"
  export DOCKER_HOST=unix:///var/run/docker.sock
  if [[ -f "$endpoint_file" ]]; then
    DOCKER_HOST="$(cat "$endpoint_file")"
  fi
  [[ "$DOCKER_HOST" =~ ^unix:///[^[:space:]]+$ ]] || return 1
  unset DOCKER_CONTEXT
  docker info --format '{{.ID}}' >/dev/null
}
