#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# Host configuration and secrets are deliberately outside the checkout.
deploy_root=/opt/pastoral/dev
component="${1:?Usage: deploy-development.sh backend|frontend SHA E2E_CHECKOUT}"
commit_sha="${2:?Missing commit SHA}"
e2e_checkout="${3:?Missing E2E checkout}"
[[ "$component" =~ ^(backend|frontend)$ && "$commit_sha" =~ ^[0-9a-f]{40}$ ]]
test -f "$deploy_root/development.env"
mkdir -p "$deploy_root/releases" "$deploy_root/backups" "$deploy_root/reports"
exec 9>"$deploy_root/deploy.lock"
flock -w 600 9

set -a
# shellcheck disable=SC1091
source "$deploy_root/development.env"
if [[ -f "$deploy_root/current-images.env" ]]; then
  # shellcheck disable=SC1091
  source "$deploy_root/current-images.env"
fi
set +a
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/development-docker.sh"
development_docker
image_prefix=ghcr.io/auronforge/pastoral-juventude
if [[ "$component" == backend ]]; then
  export BACKEND_IMAGE="$image_prefix-backend:dev-$commit_sha"
  export MIGRATION_IMAGE="$BACKEND_IMAGE-migrations"
else
  export FRONTEND_IMAGE="$image_prefix-frontend:dev-$commit_sha"
fi
[[ "$BACKEND_IMAGE" =~ ^ghcr.io/auronforge/pastoral-juventude-backend:dev-[0-9a-f]{40}$ ]]
[[ "$FRONTEND_IMAGE" =~ ^ghcr.io/auronforge/pastoral-juventude-frontend:dev-[0-9a-f]{40}$ ]]
[[ "$MIGRATION_IMAGE" == "$BACKEND_IMAGE-migrations" ]]

release_id="${GITHUB_RUN_ID:-manual}-$(date -u +%Y%m%dT%H%M%SZ)"
release_dir="$deploy_root/releases/$release_id"
mkdir -p "$release_dir/scripts" "$release_dir/traefik"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cp "$repo_root/compose.development.yaml" "$repo_root/compose.development.desktop.yaml" "$release_dir/"
cp "$repo_root/scripts/"*.sh "$repo_root/scripts/"*.py "$release_dir/scripts/"
cp -R "$repo_root/docker" "$release_dir/"
cp "$repo_root/traefik/traefik.yml" "$repo_root/traefik/dynamic.development.yml" "$release_dir/traefik/"
chmod 0644 "$release_dir/scripts/backend-entrypoint.sh" "$release_dir/traefik/traefik.yml" "$release_dir/traefik/dynamic.development.yml"
desktop_mode=false
if [[ "$DOCKER_HOST" != unix:///var/run/docker.sock ]]; then
  desktop_mode=true
  export DEV_RUNTIME_VOLUME="pastoral-dev_runtime-$release_id"
  bash "$repo_root/scripts/sync-development-runtime.sh" "$release_dir" "$DEV_RUNTIME_VOLUME" "${SECRETS_DIR:-$deploy_root/secrets}"
  printf 'DEV_RUNTIME_VOLUME=%s\n' "$DEV_RUNTIME_VOLUME" > "$release_dir/desktop-runtime.env"
fi
compose=(docker compose --project-name pastoral-dev --project-directory "$release_dir" -f "$release_dir/compose.development.yaml")
if [[ "$desktop_mode" == true ]]; then
  compose+=(-f "$release_dir/compose.development.desktop.yaml")
fi
report_dir="$deploy_root/reports/$release_id"
mkdir -p "$report_dir/playwright-report" "$report_dir/test-results"
export DEV_REPORT_DIR="$report_dir"
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "report_dir=$report_dir" >> "$GITHUB_OUTPUT"
fi

diagnose() {
  result=$?
  if (( result != 0 )); then
    "${compose[@]}" ps > "$report_dir/compose-status.txt" 2>&1 || true
    echo "Deploy failed. Candidate: $release_dir. Previous validated state was retained." >&2
  fi
}
trap diagnose EXIT

"${compose[@]}" config --quiet
"${compose[@]}" pull traefik frontend backend migrate postgres
"${compose[@]}" build redis health-report
"${compose[@]}" up -d --wait --wait-timeout 180 postgres redis
# Snapshot before every migration, including the first empty baseline.
# Variables below expand inside the PostgreSQL container.
# shellcheck disable=SC2016
"${compose[@]}" exec -T postgres sh -c 'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$deploy_root/backups/$release_id.dump.tmp"
mv "$deploy_root/backups/$release_id.dump.tmp" "$deploy_root/backups/$release_id.dump"
"${compose[@]}" run --rm --no-deps migrate
"${compose[@]}" up -d --wait --wait-timeout 180 backend frontend health-report traefik
"${compose[@]}" exec -T backend node -e "fetch('http://127.0.0.1:3000/health/ready').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

python3 "$repo_root/scripts/publish-health-report.py"

e2e_sha="$(git -C "$e2e_checkout" rev-parse HEAD)"
e2e_image="pastoral-dev-e2e:$e2e_sha"
docker build --tag "$e2e_image" "$e2e_checkout"
# Reports are copied from the container, avoiding host/VM UID mapping.
bash "$repo_root/scripts/run-development-e2e.sh" "$e2e_image" "$report_dir"
python3 "$repo_root/scripts/health-development.py" > "$report_dir/resources.json" || echo "Resource diagnostics partial; see resources.json."

{
  printf 'BACKEND_IMAGE=%s\n' "$BACKEND_IMAGE"
  printf 'MIGRATION_IMAGE=%s\n' "$MIGRATION_IMAGE"
  printf 'FRONTEND_IMAGE=%s\n' "$FRONTEND_IMAGE"
} > "$deploy_root/current-images.env.tmp"
if [[ -f "$deploy_root/current-images.env" ]]; then
  cp "$deploy_root/current-images.env" "$deploy_root/previous-images.env"
fi
mv "$deploy_root/current-images.env.tmp" "$deploy_root/current-images.env"
ln -sfn "$release_dir" "$deploy_root/current"
{
  printf 'release=%s\ncomponent=%s\ncommit=%s\ne2e=%s\n' "$release_id" "$component" "$commit_sha" "$e2e_sha"
  printf 'infra=%s\n' "$(git -C "$repo_root" rev-parse HEAD)"
  cat "$deploy_root/current-images.env"
} > "$report_dir/deployment.txt"
echo "Development deployment and smoke tests passed: $release_id"

