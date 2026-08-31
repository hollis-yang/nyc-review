#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"

SSH_KEY="${LIGHTSAIL_SSH_KEY:-/Users/hollisyang/Downloads/LightsailDefaultKey-us-east-1.pem}"
SSH_TARGET="${LIGHTSAIL_SSH_TARGET:-ubuntu@34.194.141.58}"
REMOTE_ROOT="${NYC_REVIEW_REMOTE_ROOT:-/opt/nyc-review}"

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy/release-production.sh <40-character-git-sha>

Run this command on the Mac after all three GitHub Actions image jobs succeed.
It packages deployment files and declared database changes, uploads them to
Lightsail, applies each database change once, and deploys the matching images.

Uncommitted work outside the local release-package inputs is allowed. Committed
release inputs must still match the commit; manifest-declared ignored database
payloads remain supported.

Optional overrides:
  LIGHTSAIL_SSH_KEY       SSH private key path
  LIGHTSAIL_SSH_TARGET    SSH target (default: ubuntu@34.194.141.58)
  NYC_REVIEW_REMOTE_ROOT  Server project path (default: /opt/nyc-review)
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
if [[ ! "$REMOTE_ROOT" =~ ^/[A-Za-z0-9._/-]+$ || "$REMOTE_ROOT" == *".."* ]]; then
  echo "Unsafe remote project path: $REMOTE_ROOT" >&2
  exit 2
fi
if [[ ! -f "$SSH_KEY" || ! -r "$SSH_KEY" ]]; then
  echo "Lightsail SSH key is missing or unreadable: $SSH_KEY" >&2
  exit 1
fi

cd "$PROJECT_ROOT"
head_sha="$(git rev-parse HEAD)"
if [[ "$head_sha" != "$raw_sha" ]]; then
  echo "The requested SHA is not the current local commit." >&2
  echo "Current HEAD: $head_sha" >&2
  echo "Requested:    $raw_sha" >&2
  exit 1
fi

release_input_paths=(
  compose.production.yml
  .env.production.example
  deploy/production
  scripts/deploy/release-production.sh
  scripts/deploy/package-production-bundle.sh
  scripts/deploy/package-database-release.sh
  scripts/deploy/check-production-config.sh
  scripts/deploy/apply-production-release.sh
  scripts/deploy/update-production.sh
  src/main/resources/db
)

# A manifest may declare a tracked SQL/RESP file outside the standard database
# directory. Include every declared path in the dirty check. Files intentionally
# ignored by Git under data/generated remain supported and are packaged locally.
while IFS=$'\t' read -r change_id _kind sql_path redis_path _extra; do
  [[ -z "$change_id" || "$change_id" == \#* ]] && continue
  for release_path in "$sql_path" "$redis_path"; do
    [[ -z "$release_path" || "$release_path" == "-" ]] && continue
    release_input_paths+=(":(literal)$release_path")
  done
done < deploy/production/database-release.tsv

release_input_status="$(git status --porcelain --untracked-files=normal -- "${release_input_paths[@]}")"
if [[ -n "$release_input_status" ]]; then
  echo "Local release-package inputs have uncommitted or untracked files." >&2
  echo "Commit these release inputs before deploying; unrelated working-tree changes are allowed." >&2
  printf '%s\n' "$release_input_status" >&2
  exit 1
fi
origin_sha="$(git rev-parse origin/main)"
if [[ "$origin_sha" != "$raw_sha" ]]; then
  echo "The requested SHA is not the current origin/main commit." >&2
  echo "origin/main: $origin_sha" >&2
  echo "Requested:   $raw_sha" >&2
  exit 1
fi

bundle="$PROJECT_ROOT/dist/nyc-review-production-bundle.tar.gz"
database_archive="$PROJECT_ROOT/dist/nyc-review-database-release-$raw_sha.tar.gz"
remote_bundle="/tmp/nyc-review-production-bundle.tar.gz"
remote_database_archive="/tmp/nyc-review-database-release-$raw_sha.tar.gz"

"$SCRIPT_DIR/package-production-bundle.sh" "$bundle"
"$SCRIPT_DIR/package-database-release.sh" "$raw_sha"

echo "Uploading release files to $SSH_TARGET..."
scp -i "$SSH_KEY" "$bundle" "$database_archive" "$SSH_TARGET:/tmp/"

printf -v remote_command \
  'set -e; tar -xzf %q -C %q; chmod +x %q/scripts/deploy/check-production-config.sh %q/scripts/deploy/update-production.sh %q/scripts/deploy/apply-production-release.sh; cd %q; ./scripts/deploy/apply-production-release.sh %q %q; rm -f %q %q' \
  "$remote_bundle" "$REMOTE_ROOT" \
  "$REMOTE_ROOT" "$REMOTE_ROOT" "$REMOTE_ROOT" "$REMOTE_ROOT" \
  "$raw_sha" "$remote_database_archive" \
  "$remote_bundle" "$remote_database_archive"

echo "Applying release on Lightsail..."
ssh -i "$SSH_KEY" "$SSH_TARGET" "$remote_command"
echo "Production release completed: sha-$raw_sha"
