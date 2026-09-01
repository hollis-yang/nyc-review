#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SNAPSHOT_SHA256="13cbf7ea033d6801df374e823432318107944568d8fcf76560872049e8eef574"
COLLECTION="nyc_review_content_v3_dashscope_qwen37_1024_v1"
QDRANT_IMAGE="qdrant/qdrant:v1.19.0"
QDRANT_VOLUME="nyc-review-production_qdrant-m3-data"
STAGE_CONTAINER="nyc-review-m3-qdrant-stage"
STAGE_URL="http://127.0.0.1:16333"

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy/stage-m3-qdrant.sh <m3-collection.snapshot>

Restores the checksum-pinned M3 Qdrant snapshot into a dedicated production
volume without modifying the active legacy Qdrant volume. The staging server is
bound only to 127.0.0.1 and is removed after exact collection verification.
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

snapshot="$1"
if [[ ! -f "$snapshot" || ! -r "$snapshot" ]]; then
  echo "M3 Qdrant snapshot is missing or unreadable: $snapshot" >&2
  exit 1
fi
actual_sha256="$(sha256sum "$snapshot" | awk '{print $1}')"
if [[ "$actual_sha256" != "$SNAPSHOT_SHA256" ]]; then
  echo "M3 Qdrant snapshot checksum mismatch." >&2
  echo "Expected: $SNAPSHOT_SHA256" >&2
  echo "Actual:   $actual_sha256" >&2
  exit 1
fi
if docker container inspect "$STAGE_CONTAINER" >/dev/null 2>&1; then
  echo "Refusing to reuse existing staging container: $STAGE_CONTAINER" >&2
  exit 1
fi

if docker volume inspect "$QDRANT_VOLUME" >/dev/null 2>&1; then
  volume_profile="$(docker volume inspect --format '{{ index .Labels "com.nyc-review.rag-profile" }}' "$QDRANT_VOLUME")"
  volume_snapshot="$(docker volume inspect --format '{{ index .Labels "com.nyc-review.snapshot-sha256" }}' "$QDRANT_VOLUME")"
  if [[ "$volume_profile" != "m3-quality-v1" || "$volume_snapshot" != "$SNAPSHOT_SHA256" ]]; then
    echo "Existing M3 volume is not labeled for this checksum-pinned release." >&2
    exit 1
  fi
else
  docker volume create \
    --label com.nyc-review.rag-profile=m3-quality-v1 \
    --label "com.nyc-review.snapshot-sha256=$SNAPSHOT_SHA256" \
    "$QDRANT_VOLUME" >/dev/null
fi

cleanup() {
  local exit_status="$?"
  trap - EXIT
  docker rm -f "$STAGE_CONTAINER" >/dev/null 2>&1 || true
  exit "$exit_status"
}
trap cleanup EXIT

docker pull "$QDRANT_IMAGE"
docker run -d \
  --name "$STAGE_CONTAINER" \
  --memory 1536m \
  --pids-limit 256 \
  --restart no \
  -p 127.0.0.1:16333:6333 \
  -v "$QDRANT_VOLUME:/qdrant/storage" \
  -e QDRANT__LOG_LEVEL=WARN \
  -e QDRANT__TELEMETRY_DISABLED=true \
  "$QDRANT_IMAGE" >/dev/null

ready=0
for _ in {1..60}; do
  if curl --fail --silent "$STAGE_URL/" >/dev/null; then
    ready=1
    break
  fi
  sleep 2
done
if [[ $ready -ne 1 ]]; then
  echo "The temporary M3 Qdrant server did not become ready." >&2
  docker logs "$STAGE_CONTAINER" >&2
  exit 1
fi

if curl --fail --silent "$STAGE_URL/collections/$COLLECTION" >/dev/null 2>&1; then
  echo "M3 collection already exists in the staged volume; verifying without overwrite."
else
  echo "Restoring the checksum-pinned M3 Qdrant snapshot..."
  curl \
    --fail \
    --silent \
    --show-error \
    --max-time 1800 \
    -X POST \
    "$STAGE_URL/collections/$COLLECTION/snapshots/upload?priority=snapshot" \
    -F "snapshot=@$snapshot" >/dev/null
fi

python3 "$SCRIPT_DIR/verify-m3-qdrant.py" --url "$STAGE_URL"
docker stats --no-stream "$STAGE_CONTAINER"
echo "M3 Qdrant volume staged successfully: $QDRANT_VOLUME"
echo "The active legacy Qdrant volume was not modified."
