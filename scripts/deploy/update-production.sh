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
the successful GitHub Actions run for that commit. Spring, Agent, and Web move
to the same immutable commit tag as one application release. Qdrant index/profile
promotion remains a separate, reversible operation.
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

old_agent_tag="$(awk -F= '$1 == "AGENT_IMAGE_TAG" { print substr($0, index($0, "=") + 1); exit }' "$ENV_FILE")"
if [[ ! "$old_agent_tag" =~ ^sha-[0-9a-f]{40}$ ]]; then
  echo "AGENT_IMAGE_TAG is missing or invalid in $ENV_FILE" >&2
  exit 1
fi

restore_old_tags() {
  sed -i.bak "s|^IMAGE_TAG=.*|IMAGE_TAG=$old_tag|" "$ENV_FILE"
  sed -i.bak "s|^AGENT_IMAGE_TAG=.*|AGENT_IMAGE_TAG=$old_agent_tag|" "$ENV_FILE"
  rm -f -- "$ENV_FILE.bak"
}

cd "$PROJECT_ROOT"
sed -i.bak "s|^IMAGE_TAG=.*|IMAGE_TAG=$new_tag|" "$ENV_FILE"
sed -i.bak "s|^AGENT_IMAGE_TAG=.*|AGENT_IMAGE_TAG=$new_tag|" "$ENV_FILE"
rm -f -- "$ENV_FILE.bak"

if ! ./scripts/deploy/check-production-config.sh "$ENV_FILE"; then
  restore_old_tags
  echo "Validation failed; application image tags were restored." >&2
  exit 1
fi

if ! docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" pull; then
  restore_old_tags
  echo "Image pull failed; application image tags were restored." >&2
  exit 1
fi

if ! docker compose \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  up -d --wait --wait-timeout 900; then
  restore_old_tags
  echo "Release startup failed; application image tags were restored." >&2
  echo "Restoring containers from the previous application release..." >&2
  if docker compose \
    --env-file "$ENV_FILE" \
    -f "$COMPOSE_FILE" \
    up -d --wait --wait-timeout 900; then
    echo "Container rollback completed: $old_tag" >&2
  else
    echo "CRITICAL: automatic container rollback to $old_tag also failed." >&2
    echo "Inspect docker compose logs before attempting another release." >&2
  fi
  exit 1
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps -a
echo "Production release completed: $new_tag"
echo "Previous Spring/Web release: $old_tag"
echo "Previous Agent release: $old_agent_tag"
