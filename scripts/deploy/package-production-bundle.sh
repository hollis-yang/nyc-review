#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
export COPYFILE_DISABLE=1

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
OUTPUT="${1:-$PROJECT_ROOT/dist/nyc-review-production-bundle.tar.gz}"

mkdir -p "$(dirname -- "$OUTPUT")"

tar -czf "$OUTPUT" \
  -C "$PROJECT_ROOT" \
  compose.production.yml \
  .env.production.example \
  deploy/production \
  scripts/deploy/check-production-config.sh \
  scripts/deploy/apply-production-release.sh \
  scripts/deploy/update-production.sh \
  src/main/resources/db

echo "Created production bundle: $OUTPUT"
echo "Generated database changes and full P13 data are intentionally excluded from this bundle."
