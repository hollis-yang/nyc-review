#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env.production"
COMPOSE_FILE="$PROJECT_ROOT/compose.production.yml"

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy/update-production.sh <40-character-git-sha>

Updates a running production deployment to immutable GHCR images published by
the successful GitHub Actions run for that commit. This script is for ordinary
Spring, Agent, and Web code releases. Database migrations and P13 data releases
must follow the separate runbook.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 1 ]]; then
  usage >&2
  exit 2
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Production environment file not found: $ENV_FILE" >&2
  exit 1
fi

raw_sha="$1"
if [[ "$raw_sha" == sha-* ]]; then
  raw_sha="${raw_sha#sha-}"
fi
if [[ ! "$raw_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Release must be a full 40-character lowercase Git commit SHA." >&2
  exit 2
fi

new_tag="sha-$raw_sha"
old_tag="$(awk -F= '$1 == "IMAGE_TAG" { print substr($0, index($0, "=") + 1); exit }' "$ENV_FILE")"
if [[ ! "$old_tag" =~ ^sha-[0-9a-f]{40}$ ]]; then
  echo "Current IMAGE_TAG is missing or invalid in $ENV_FILE" >&2
  exit 1
fi

restore_old_tag() {
  sed -i "s|^IMAGE_TAG=.*|IMAGE_TAG=$old_tag|" "$ENV_FILE"
}

cd "$PROJECT_ROOT"
sed -i "s|^IMAGE_TAG=.*|IMAGE_TAG=$new_tag|" "$ENV_FILE"

if ! ./scripts/deploy/check-production-config.sh "$ENV_FILE"; then
  restore_old_tag
  echo "Validation failed; IMAGE_TAG was restored to $old_tag." >&2
  exit 1
fi

if ! docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" pull; then
  restore_old_tag
  echo "Image pull failed; IMAGE_TAG was restored to $old_tag." >&2
  exit 1
fi

if ! docker compose \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  up -d --wait --wait-timeout 900; then
  restore_old_tag
  echo "Release startup failed; IMAGE_TAG was restored to $old_tag." >&2
  echo "Inspect logs, then redeploy the old SHA with this script to roll back containers." >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps -a
echo "Production release completed: $new_tag"
echo "Previous release: $old_tag"
