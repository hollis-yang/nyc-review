#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env.production"
COMPOSE_FILE="$PROJECT_ROOT/compose.production.yml"
MANIFEST_RELATIVE="deploy/production/database-release.tsv"

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy/apply-production-release.sh <40-character-git-sha> <database-release.tar.gz>

Applies each unrecorded database/Redis change from a verified release archive,
then deploys the immutable GHCR images for the same Git commit. This script is
run on the Lightsail server by release-production.sh.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 2 ]]; then
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

release_archive="$2"
if [[ ! -f "$release_archive" || ! -r "$release_archive" ]]; then
  echo "Database release archive is missing or unreadable: $release_archive" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" || ! -f "$COMPOSE_FILE" ]]; then
  echo "Production Compose configuration is incomplete under $PROJECT_ROOT" >&2
  exit 1
fi
if [[ ! -x "$PROJECT_ROOT/scripts/deploy/update-production.sh" ]]; then
  echo "Production image updater is missing or not executable." >&2
  exit 1
fi
if [[ ! -x "$PROJECT_ROOT/scripts/deploy/check-production-config.sh" ]]; then
  echo "Production configuration checker is missing or not executable." >&2
  exit 1
fi

# Fail before stopping services or applying irreversible database changes.
"$PROJECT_ROOT/scripts/deploy/check-production-config.sh" "$ENV_FILE"

release_dir="$(mktemp -d /tmp/nyc-review-db-release.XXXXXX)"
app_layer_stopped=0

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

mysql_client() {
  compose exec -T mysql sh -lc \
    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -D nyc_review --batch --skip-column-names'
}

restore_running_release() {
  local exit_status="$?"
  trap - EXIT
  rm -rf -- "$release_dir"

  if [[ $exit_status -ne 0 && $app_layer_stopped -eq 1 ]]; then
    echo "Release failed. Restarting the previously configured application images..." >&2
    set +e
    compose up -d --wait --wait-timeout 900
    set -e
  fi
  exit "$exit_status"
}
trap restore_running_release EXIT

while IFS= read -r archive_member; do
  case "$archive_member" in
    /*|../*|*/../*|*/..)
      echo "Unsafe path in database release archive: $archive_member" >&2
      exit 1
      ;;
  esac
done < <(tar -tzf "$release_archive")

tar -xzf "$release_archive" -C "$release_dir"
if find "$release_dir" -type l -print -quit | grep -q .; then
  echo "Symbolic links are not allowed in a database release archive." >&2
  exit 1
fi

manifest="$release_dir/$MANIFEST_RELATIVE"
if [[ ! -f "$manifest" ]]; then
  echo "Database release manifest is missing from the archive." >&2
  exit 1
fi

declare -a change_ids=()
declare -a change_kinds=()
declare -a sql_files=()
declare -a redis_files=()
declare -a change_checksums=()
seen_change_ids="|"

while IFS=$'\t' read -r change_id kind sql_relative redis_relative extra; do
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
  if [[ "$sql_relative" == "-" ]]; then
    echo "Every database change requires a SQL file: $change_id" >&2
    exit 1
  fi
  if [[ -z "$sql_relative" || "$sql_relative" == /* || "$sql_relative" == *".."* ]]; then
    echo "Unsafe SQL path for $change_id: $sql_relative" >&2
    exit 1
  fi
  if [[ "$redis_relative" != "-" && ( -z "$redis_relative" || "$redis_relative" == /* || "$redis_relative" == *".."* ) ]]; then
    echo "Unsafe Redis path for $change_id: $redis_relative" >&2
    exit 1
  fi

  sql_file="$release_dir/$sql_relative"
  if [[ ! -f "$sql_file" || ! -r "$sql_file" ]]; then
    echo "SQL file is missing or unreadable for $change_id: $sql_relative" >&2
    exit 1
  fi

  redis_file="-"
  redis_checksum="-"
  if [[ "$redis_relative" != "-" ]]; then
    redis_file="$release_dir/$redis_relative"
    if [[ ! -f "$redis_file" || ! -r "$redis_file" ]]; then
      echo "Redis RESP file is missing or unreadable for $change_id: $redis_relative" >&2
      exit 1
    fi
    redis_checksum="$(sha256sum "$redis_file" | awk '{print $1}')"
  fi

  sql_checksum="$(sha256sum "$sql_file" | awk '{print $1}')"
  combined_checksum="$(printf '%s\n%s\n' "$sql_checksum" "$redis_checksum" | sha256sum | awk '{print $1}')"

  change_ids+=("$change_id")
  change_kinds+=("$kind")
  sql_files+=("$sql_file")
  redis_files+=("$redis_file")
  change_checksums+=("$combined_checksum")
done < "$manifest"

if [[ ${#change_ids[@]} -eq 0 ]]; then
  echo "Database release manifest contains no changes." >&2
  exit 1
fi

echo "Pre-pulling target Spring, Agent, and Web images before database changes..."
(
  export IMAGE_TAG="sha-$raw_sha"
  export AGENT_IMAGE_TAG="sha-$raw_sha"
  compose pull spring web agent-service
)

mysql_client <<'SQL'
CREATE TABLE IF NOT EXISTS tb_production_change (
    change_id VARCHAR(128) NOT NULL,
    change_kind VARCHAR(32) NOT NULL,
    content_checksum CHAR(64) NOT NULL,
    release_sha CHAR(40) NOT NULL,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (change_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
SQL

declare -a pending_indexes=()
for index in "${!change_ids[@]}"; do
  change_id="${change_ids[$index]}"
  expected_checksum="${change_checksums[$index]}"
  recorded_checksum="$(printf "SELECT content_checksum FROM tb_production_change WHERE change_id = '%s';\n" "$change_id" | mysql_client)"

  if [[ -z "$recorded_checksum" ]]; then
    pending_indexes+=("$index")
  elif [[ "$recorded_checksum" == "$expected_checksum" ]]; then
    echo "Already applied, skipping: $change_id"
  else
    echo "Refusing changed contents for previously applied change: $change_id" >&2
    echo "Add a new manifest row with a new change_id instead of editing history." >&2
    exit 1
  fi
done

if [[ ${#pending_indexes[@]} -gt 0 ]]; then
  echo "Pending database changes: ${#pending_indexes[@]}"
  echo "No automatic database backup will be created."

  app_layer_stopped=1
  compose stop gateway web agent-service

  queue_ready=0
  for _ in {1..16}; do
    queue_counts="$(compose exec -T rabbitmq sh -c \
      '/opt/rabbitmq/sbin/rabbitmqctl -q list_queues -p "$RABBITMQ_DEFAULT_VHOST" name messages messages_unacknowledged' \
      | awk '$1 == "nyc-review.voucher.order.queue" {print $2 + 0, $3 + 0}')"
    [[ -n "$queue_counts" ]] || queue_counts="0 0"
    pending_orders="$(compose exec -T redis redis-cli --no-auth-warning ZCARD seckill:pending:orders | tr -d '\r')"

    read -r queued_orders unacknowledged_orders <<< "$queue_counts"
    if [[ "$queued_orders" == "0" && "$unacknowledged_orders" == "0" && "$pending_orders" == "0" ]]; then
      queue_ready=1
      break
    fi
    echo "Waiting for voucher orders to drain (queued=$queued_orders, active=$unacknowledged_orders, pending=$pending_orders)..."
    sleep 2
  done

  if [[ $queue_ready -ne 1 ]]; then
    echo "Voucher orders did not drain. Database release was not started." >&2
    exit 1
  fi

  compose stop spring

  for index in "${pending_indexes[@]}"; do
    change_id="${change_ids[$index]}"
    change_kind="${change_kinds[$index]}"
    sql_file="${sql_files[$index]}"
    redis_file="${redis_files[$index]}"
    expected_checksum="${change_checksums[$index]}"

    echo "Applying MySQL change: $change_id"
    mysql_client < "$sql_file"

    if [[ "$redis_file" != "-" ]]; then
      echo "Applying Redis change: $change_id"
      redis_result="$(compose exec -T redis sh -lc 'redis-cli --no-auth-warning --pipe' < "$redis_file")"
      echo "$redis_result"
      if [[ ! "$redis_result" =~ errors:[[:space:]]0 ]]; then
        echo "Redis reported an error while applying: $change_id" >&2
        exit 1
      fi
    fi

    printf \
      "INSERT INTO tb_production_change (change_id, change_kind, content_checksum, release_sha) VALUES ('%s', '%s', '%s', '%s');\n" \
      "$change_id" "$change_kind" "$expected_checksum" "$raw_sha" | mysql_client
    echo "Recorded database change: $change_id"
  done
else
  echo "No pending database changes."
fi

"$PROJECT_ROOT/scripts/deploy/update-production.sh" "$raw_sha"
app_layer_stopped=0
echo "Database and application release completed for: $raw_sha"
