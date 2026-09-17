#!/bin/sh
set -eu

secrets_dir="${1:-/opt/pastoral/secrets}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Execute este script como root para proteger os secrets." >&2
  exit 1
fi

install -d -m 0700 "$secrets_dir"

generate_password() {
  target="$1"
  if [ ! -e "$target" ]; then
    openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | cut -c1-40 > "$target"
  fi
  chmod 0600 "$target"
}

generate_password "$secrets_dir/postgres_password"
generate_password "$secrets_dir/redis_password"
generate_password "$secrets_dir/grafana_admin_password"

if [ ! -e "$secrets_dir/jwt_private_key.pem" ]; then
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out "$secrets_dir/jwt_private_key.pem"
fi
if [ ! -e "$secrets_dir/jwt_public_key.pem" ]; then
  openssl pkey -in "$secrets_dir/jwt_private_key.pem" -pubout -out "$secrets_dir/jwt_public_key.pem"
fi

for placeholder in tailscale_auth_key smtp_password; do
  if [ ! -e "$secrets_dir/$placeholder" ]; then
    : > "$secrets_dir/$placeholder"
  fi
done

chmod 0600 "$secrets_dir"/*
echo "Secrets preparados em $secrets_dir. Preencha tailscale_auth_key e smtp_password."
