#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${1:-$PROJECT_ROOT/.env.production}"
MODE="actual"

if [[ "${1:-}" == "--example" ]]; then
  ENV_FILE="$PROJECT_ROOT/.env.production.example"
  MODE="example"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Environment file not found: $ENV_FILE" >&2
  echo "Copy .env.production.example to .env.production and fill every placeholder." >&2
  exit 1
fi

umask 077
RENDERED_CONFIG="$(mktemp "${TMPDIR:-/tmp}/nyc-review-compose.XXXXXX.json")"
trap 'rm -f "$RENDERED_CONFIG"' EXIT

docker compose \
  --env-file "$ENV_FILE" \
  -f "$PROJECT_ROOT/compose.production.yml" \
  config --format json > "$RENDERED_CONFIG"

python3 - "$RENDERED_CONFIG" "$ENV_FILE" "$MODE" <<'PY'
import json
import re
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
env_path = Path(sys.argv[2])
mode = sys.argv[3]

config = json.loads(config_path.read_text(encoding="utf-8"))
services = config.get("services", {})

expected_services = {
    "gateway",
    "web",
    "spring",
    "agent-service",
    "mysql",
    "redis",
    "redis-seed",
    "rabbitmq",
    "qdrant",
}
missing_services = sorted(expected_services - set(services))
if missing_services:
    raise SystemExit(f"Missing production services: {', '.join(missing_services)}")

build_services = sorted(name for name, service in services.items() if service.get("build"))
if build_services:
    raise SystemExit(f"Production must pull images, but build is set for: {', '.join(build_services)}")

published = []
for name, service in services.items():
    for port in service.get("ports") or []:
        published.append(
            (
                name,
                int(port["published"]),
                str(port.get("protocol", "tcp")),
            )
        )

expected_ports = {
    ("gateway", 80, "tcp"),
    ("gateway", 443, "tcp"),
    ("gateway", 443, "udp"),
}
if set(published) != expected_ports:
    raise SystemExit(f"Unexpected host-published ports: {published}")

long_lived = expected_services - {"redis-seed"}
bad_restart = sorted(
    name
    for name in long_lived
    if services[name].get("restart") != "unless-stopped"
)
if bad_restart:
    raise SystemExit(f"Missing restart policy: {', '.join(bad_restart)}")

def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values

env = parse_env(env_path)
if mode == "actual":
    required = [
        "APP_SITE_ADDRESS",
        "SPRING_IMAGE",
        "AGENT_IMAGE",
        "WEB_IMAGE",
        "IMAGE_TAG",
        "NYC_REVIEW_DATA_DIR",
        "MYSQL_ROOT_PASSWORD",
        "NYC_REVIEW_DB_PASSWORD",
        "NYC_REVIEW_REDIS_PASSWORD",
        "NYC_REVIEW_RABBITMQ_USERNAME",
        "NYC_REVIEW_RABBITMQ_PASSWORD",
        "NYC_REVIEW_RABBITMQ_VHOST",
        "DEEPSEEK_API_KEY",
        "NYC_REVIEW_AGENT_METRICS_TOKEN",
        "NYC_REVIEW_AGENT_MCP_API_KEY",
    ]
    missing = [key for key in required if not env.get(key)]
    if missing:
        raise SystemExit(f"Missing required production values: {', '.join(missing)}")

    placeholders = [
        key
        for key, value in env.items()
        if any(marker in value for marker in ("REPLACE_", "example.com", "YOUR_"))
    ]
    if placeholders:
        raise SystemExit(f"Replace placeholders before deployment: {', '.join(sorted(placeholders))}")

    if not re.fullmatch(r"sha-[0-9a-f]{40}", env["IMAGE_TAG"]):
        raise SystemExit("IMAGE_TAG must be sha- followed by the full 40-character Git commit SHA.")

    secret_keys = [
        "MYSQL_ROOT_PASSWORD",
        "NYC_REVIEW_DB_PASSWORD",
        "NYC_REVIEW_REDIS_PASSWORD",
        "NYC_REVIEW_RABBITMQ_PASSWORD",
        "NYC_REVIEW_AGENT_METRICS_TOKEN",
        "NYC_REVIEW_AGENT_MCP_API_KEY",
    ]
    secrets = [env[key] for key in secret_keys]
    short = [key for key in secret_keys if len(env[key]) < 32]
    if short:
        raise SystemExit(f"Secrets must be at least 32 characters: {', '.join(short)}")
    if len(set(secrets)) != len(secrets):
        raise SystemExit("Use a different random value for every production secret.")

    data_dir = Path(env["NYC_REVIEW_DATA_DIR"])
    required_data = [
        "mysql_import.sql",
        "p7_neighborhood_import.sql",
        "redis_seed.resp",
        "shops.json",
        "shop_reviews.json",
        "blogs.json",
        "blog_comments.json",
        "import_manifest.json",
    ]
    missing_data = [name for name in required_data if not (data_dir / name).is_file()]
    if missing_data:
        raise SystemExit(
            f"P13 data directory is incomplete ({data_dir}): {', '.join(missing_data)}"
        )

    unreadable_data = [
        name
        for name in required_data
        if not ((data_dir / name).stat().st_mode & 0o004)
    ]
    if unreadable_data:
        raise SystemExit(
            "P13 files must be readable by the non-root Agent container: "
            + ", ".join(unreadable_data)
        )

print("Production Compose validation passed: pull-only images, one Agent service, only 80/443 published.")
PY
