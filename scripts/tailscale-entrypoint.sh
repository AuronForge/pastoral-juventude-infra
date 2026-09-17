#!/bin/sh
set -eu

TS_AUTHKEY="$(tr -d '\r\n' < /run/secrets/tailscale_auth_key)"
export TS_AUTHKEY

if [ -z "$TS_AUTHKEY" ]; then
  echo "O secret tailscale_auth_key está vazio." >&2
  exit 1
fi

/usr/local/bin/containerboot &
containerboot_pid=$!

cleanup() {
  kill "$containerboot_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

attempt=0
until tailscale status >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ]; then
    echo "Tailscale não ficou disponível no tempo esperado." >&2
    exit 1
  fi
  if ! kill -0 "$containerboot_pid" 2>/dev/null; then
    echo "containerboot encerrou antes de inicializar o Tailscale." >&2
    wait "$containerboot_pid"
  fi
  sleep 2
done

tailscale funnel --bg --yes --https=443 http://127.0.0.1:80
wait "$containerboot_pid"
