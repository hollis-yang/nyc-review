#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env.production"
COMPOSE_FILE="$PROJECT_ROOT/compose.production.yml"
QDRANT_VOLUME="nyc-review-production_qdrant-m3-data"
SNAPSHOT_SHA256="13cbf7ea033d6801df374e823432318107944568d8fcf76560872049e8eef574"

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy/promote-m3-production.sh <40-character-git-sha>

Atomically switches a released Agent from the legacy hash/64d profile to the
checksum-pinned M3 quality profile. A failed startup, index verification, or
paid end-to-end canary restores the complete previous environment and legacy
Qdrant volume.
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

raw_sha="$1"
if [[ "$raw_sha" == sha-* ]]; then
  raw_sha="${raw_sha#sha-}"
fi
if [[ ! "$raw_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Release must be a full 40-character lowercase Git commit SHA." >&2
  exit 2
fi
if [[ ! -f "$ENV_FILE" || ! -f "$COMPOSE_FILE" ]]; then
  echo "Production configuration is incomplete under $PROJECT_ROOT" >&2
  exit 1
fi
if [[ ! -x "$SCRIPT_DIR/check-production-config.sh" ]]; then
  echo "Production configuration checker is missing or not executable." >&2
  exit 1
fi

expected_tag="sha-$raw_sha"
image_tag="$(awk -F= '$1 == "IMAGE_TAG" {print substr($0, index($0, "=") + 1); exit}' "$ENV_FILE")"
agent_tag="$(awk -F= '$1 == "AGENT_IMAGE_TAG" {print substr($0, index($0, "=") + 1); exit}' "$ENV_FILE")"
if [[ "$image_tag" != "$expected_tag" || "$agent_tag" != "$expected_tag" ]]; then
  echo "Deploy all application images for $expected_tag before promoting M3." >&2
  exit 1
fi

for provider_key in OPENAI_API_KEY DASHSCOPE_API_KEY DASHSCOPE_BASE_URL; do
  provider_value="$(awk -F= -v key="$provider_key" '$1 == key {print substr($0, index($0, "=") + 1); exit}' "$ENV_FILE")"
  if [[ -z "$provider_value" || "$provider_value" == REPLACE_* ]]; then
    echo "Missing production provider setting: $provider_key" >&2
    exit 1
  fi
done

if ! docker volume inspect "$QDRANT_VOLUME" >/dev/null 2>&1; then
  echo "The staged M3 Qdrant volume does not exist: $QDRANT_VOLUME" >&2
  exit 1
fi
volume_profile="$(docker volume inspect --format '{{ index .Labels "com.nyc-review.rag-profile" }}' "$QDRANT_VOLUME")"
volume_snapshot="$(docker volume inspect --format '{{ index .Labels "com.nyc-review.snapshot-sha256" }}' "$QDRANT_VOLUME")"
if [[ "$volume_profile" != "m3-quality-v1" || "$volume_snapshot" != "$SNAPSHOT_SHA256" ]]; then
  echo "The staged M3 Qdrant volume identity does not match this release." >&2
  exit 1
fi

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

current_profile="$(awk -F= '$1 == "NYC_REVIEW_RAG_RELEASE_PROFILE" {print substr($0, index($0, "=") + 1); exit}' "$ENV_FILE")"
current_profile="${current_profile:-legacy-v1}"
if [[ "$current_profile" != "legacy-v1" && "$current_profile" != "m3-quality-v1" ]]; then
  echo "Unsupported current RAG release profile: $current_profile" >&2
  exit 1
fi

backup_file=""
activation_started=0
rollback_on_failure() {
  local exit_status="$?"
  trap - EXIT
  if [[ $exit_status -ne 0 && $activation_started -eq 1 && -n "$backup_file" ]]; then
    echo "M3 promotion failed; restoring the complete previous RAG profile..." >&2
    cp -p "$backup_file" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    set +e
    "$SCRIPT_DIR/check-production-config.sh" "$ENV_FILE"
    compose up -d --wait --wait-timeout 900
    rollback_status="$?"
    set -e
    if [[ $rollback_status -eq 0 ]]; then
      echo "Legacy RAG profile rollback completed." >&2
    else
      echo "CRITICAL: automatic legacy RAG rollback also failed." >&2
      echo "Preserved environment backup: $backup_file" >&2
    fi
  fi
  exit "$exit_status"
}
trap rollback_on_failure EXIT

if [[ "$current_profile" == "legacy-v1" ]]; then
  "$SCRIPT_DIR/check-production-config.sh" "$ENV_FILE"
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  backup_file="$PROJECT_ROOT/.env.production.pre-m3-$timestamp"
  cp -p "$ENV_FILE" "$backup_file"
  chmod 600 "$backup_file"
  activation_started=1

  python3 - "$ENV_FILE" <<'PY'
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
updates = {
    "NYC_REVIEW_RAG_RELEASE_PROFILE": "m3-quality-v1",
    "NYC_REVIEW_QDRANT_IMAGE": "qdrant/qdrant:v1.19.0",
    "NYC_REVIEW_QDRANT_VOLUME": "nyc-review-production_qdrant-m3-data",
    "NYC_REVIEW_QDRANT_MEMORY_LIMIT": "1536m",
    "NYC_REVIEW_AGENT_QDRANT_COLLECTION": "nyc_review_content_v3_dashscope_qwen37_1024_v1",
    "NYC_REVIEW_AGENT_RETRIEVAL_VERSION": "p12-rag-v1",
    "NYC_REVIEW_AGENT_RAG_INDEX_BATCH_SIZE": "64",
    "NYC_REVIEW_AGENT_RAG_SYNC_MODE": "verify",
    "NYC_REVIEW_AGENT_EMBEDDING_PROVIDER": "qwen",
    "NYC_REVIEW_AGENT_EMBEDDING_MODEL": "qwen3.7-text-embedding",
    "NYC_REVIEW_AGENT_EMBEDDING_DIMENSIONS": "1024",
    "NYC_REVIEW_AGENT_EMBEDDING_VERSION": "qwen3.7-text-embedding-1024-m1-v1",
    "NYC_REVIEW_AGENT_EMBEDDING_BATCH_SIZE": "64",
    "NYC_REVIEW_AGENT_EMBEDDING_MAX_CONCURRENCY": "2",
    "NYC_REVIEW_AGENT_EMBEDDING_TIMEOUT_SECONDS": "30",
    "NYC_REVIEW_AGENT_EMBEDDING_MAX_RETRIES": "4",
    "NYC_REVIEW_AGENT_EMBEDDING_MAX_BATCH_CHARACTERS": "250000",
    "NYC_REVIEW_AGENT_EMBEDDING_QUERY_CACHE_SIZE": "512",
    "NYC_REVIEW_AGENT_EMBEDDING_QUERY_CACHE_TTL_SECONDS": "900",
    "NYC_REVIEW_AGENT_EMBEDDING_SPARSE_FALLBACK": "false",
    "NYC_REVIEW_AGENT_ALLOW_HASH_EMBEDDINGS": "false",
    "NYC_REVIEW_AGENT_MAX_CANDIDATES": "10",
    "NYC_REVIEW_AGENT_DISCOVERY_POOL_SIZE": "30",
    "NYC_REVIEW_AGENT_GLOBAL_RETRIEVAL_ENABLED": "true",
    "NYC_REVIEW_AGENT_GLOBAL_RETRIEVAL_DOCUMENT_LIMIT": "200",
    "NYC_REVIEW_AGENT_GLOBAL_RETRIEVAL_HYDRATION_LIMIT": "60",
    "NYC_REVIEW_AGENT_GLOBAL_RETRIEVAL_FUSION_POOL_LIMIT": "30",
    "NYC_REVIEW_AGENT_GLOBAL_RETRIEVAL_HYDRATION_CONCURRENCY": "8",
    "NYC_REVIEW_AGENT_GLOBAL_RETRIEVAL_BRANCH_TIMEOUT_SECONDS": "30",
    "NYC_REVIEW_AGENT_GLOBAL_RETRIEVAL_DOCUMENTS_PER_MERCHANT": "3",
    "NYC_REVIEW_AGENT_GLOBAL_RETRIEVAL_RRF_K": "60",
    "NYC_REVIEW_AGENT_GLOBAL_RETRIEVAL_BRAND_CAP": "2",
    "NYC_REVIEW_AGENT_QUERY_REWRITE_PROVIDER": "openai",
    "NYC_REVIEW_AGENT_QUERY_REWRITE_BASE_URL": "https://api.openai.com/v1",
    "NYC_REVIEW_AGENT_QUERY_REWRITE_MODEL": "gpt-4o-mini-2024-07-18",
    "NYC_REVIEW_AGENT_QUERY_REWRITE_PROMPT_VERSION": "m3-query-rewrite-v1",
    "NYC_REVIEW_AGENT_QUERY_REWRITE_MAX_QUERIES": "3",
    "NYC_REVIEW_AGENT_QUERY_REWRITE_TIMEOUT_SECONDS": "8",
    "NYC_REVIEW_AGENT_QUERY_REWRITE_MAX_CONCURRENCY": "2",
    "NYC_REVIEW_AGENT_QUERY_REWRITE_CACHE_SIZE": "512",
    "NYC_REVIEW_AGENT_QUERY_REWRITE_CACHE_TTL_SECONDS": "900",
    "NYC_REVIEW_AGENT_QUERY_REWRITE_MAX_INPUT_CHARACTERS": "2000",
    "NYC_REVIEW_AGENT_QUERY_REWRITE_MAX_OUTPUT_TOKENS": "300",
}
lines = path.read_text(encoding="utf-8").splitlines()
written: set[str] = set()
result: list[str] = []
for line in lines:
    if "=" not in line or line.lstrip().startswith("#"):
        result.append(line)
        continue
    key = line.split("=", 1)[0].strip()
    if key not in updates:
        result.append(line)
        continue
    if key not in written:
        result.append(f"{key}={updates[key]}")
        written.add(key)
for key, value in updates.items():
    if key not in written:
        result.append(f"{key}={value}")
temporary = path.with_name(f".{path.name}.m3-tmp")
temporary.write_text("\n".join(result) + "\n", encoding="utf-8")
os.chmod(temporary, 0o600)
os.replace(temporary, path)
PY
fi

"$SCRIPT_DIR/check-production-config.sh" "$ENV_FILE"
compose pull qdrant agent-service
compose up -d --wait --wait-timeout 900

compose exec -T agent-service \
  python - --url http://qdrant:6333 < "$SCRIPT_DIR/verify-m3-qdrant.py"
compose exec -T agent-service \
  python - --url http://127.0.0.1:8090 < "$SCRIPT_DIR/verify-m3-runtime.py"

activation_started=0
if ! docker stats --no-stream \
  "$(compose ps -q qdrant)" \
  "$(compose ps -q agent-service)"; then
  echo "Warning: M3 passed readiness and canary checks, but resource stats failed." >&2
fi

echo "M3 quality profile promotion completed: $expected_tag"
if [[ -n "$backup_file" ]]; then
  echo "Rollback environment preserved at: $backup_file"
fi
