#!/bin/sh
set -eu

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker não encontrado." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 não encontrado." >&2
  exit 1
fi

if grep -R --line-number --include='*.yml' --include='*.yaml' ':latest' .; then
  echo "Tags latest não são permitidas." >&2
  exit 1
fi

docker compose config --quiet

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck scripts/*.sh docker/redis/*.sh docker/postgres-backup/*.sh
else
  echo "Aviso: shellcheck não instalado; validação de shell ignorada." >&2
fi

echo "Configuração validada com sucesso."
