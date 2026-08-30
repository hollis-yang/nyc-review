#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
export COPYFILE_DISABLE=1

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
MANIFEST="deploy/production/database-release.tsv"

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy/package-database-release.sh <40-character-git-sha>

Creates the database release archive declared by
deploy/production/database-release.tsv. The archive intentionally includes
generated SQL/Redis files that are ignored by Git.
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

cd "$PROJECT_ROOT"
if [[ ! -f "$MANIFEST" ]]; then
  echo "Database release manifest not found: $MANIFEST" >&2
  exit 1
fi

archive_members=("$MANIFEST")
change_count=0
seen_change_ids="|"

while IFS=$'\t' read -r change_id kind sql_path redis_path extra; do
  [[ -z "$change_id" || "$change_id" == \#* ]] && continue

  if [[ -n "${extra:-}" || ! "$change_id" =~ ^[A-Za-z0-9._-]+$ || ${#change_id} -gt 128 ]]; then
    echo "Invalid database release manifest row for change: $change_id" >&2
    exit 1
  fi
  if [[ "$kind" != "schema" && "$kind" != "overlay" ]]; then
    echo "Invalid change kind for $change_id: $kind" >&2
    exit 1
  fi
  if [[ "$seen_change_ids" == *"|$change_id|"* ]]; then
    echo "Duplicate database change ID: $change_id" >&2
    exit 1
  fi
  seen_change_ids+="$change_id|"
  if [[ "$sql_path" == "-" ]]; then
    echo "Every database change requires a SQL file: $change_id" >&2
    exit 1
  fi

  for release_path in "$sql_path" "$redis_path"; do
    [[ "$release_path" == "-" ]] && continue
    if [[ -z "$release_path" || "$release_path" == /* || "$release_path" == *".."* ]]; then
      echo "Unsafe path for $change_id: $release_path" >&2
      exit 1
    fi
    if [[ ! -f "$release_path" || ! -r "$release_path" ]]; then
      echo "Required database release file is missing or unreadable: $release_path" >&2
      exit 1
    fi
    archive_members+=("$release_path")
  done

  change_count=$((change_count + 1))
done < "$MANIFEST"

if [[ $change_count -eq 0 ]]; then
  echo "Database release manifest contains no changes." >&2
  exit 1
fi

output="$PROJECT_ROOT/dist/nyc-review-database-release-$raw_sha.tar.gz"
mkdir -p "$(dirname -- "$output")"
umask 077
tar -czf "$output" -C "$PROJECT_ROOT" "${archive_members[@]}"

echo "Created database release archive: $output"
echo "Included changes: $change_count"
