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

redis_seed_command = " ".join(
    str(item) for item in services["redis-seed"].get("command", [])
)
redis_seed_marker = "nyc-review:redis:base-seed:nyc-real-p13-full-v1"
if redis_seed_command.count(redis_seed_marker) < 2:
    raise SystemExit("Redis seed must check and set the stable base-dataset marker.")
if "$marker" in redis_seed_command or 'SET ""' in redis_seed_command:
    raise SystemExit("Redis seed marker must not depend on Compose variable interpolation.")

mysql_healthcheck = " ".join(
    str(item) for item in services["mysql"].get("healthcheck", {}).get("test", [])
)
if "tb_data_import" not in mysql_healthcheck or "p13-full" not in mysql_healthcheck:
    raise SystemExit("MySQL healthcheck must verify that the P13 full import completed.")

mysql_init_targets = sorted(
    str(volume.get("target"))
    for volume in services["mysql"].get("volumes", [])
    if isinstance(volume, dict)
    and str(volume.get("target", "")).startswith("/docker-entrypoint-initdb.d/")
)
expected_mysql_init_targets = [
    "/docker-entrypoint-initdb.d/01-schema.sql",
    "/docker-entrypoint-initdb.d/02-dataset.sql",
    "/docker-entrypoint-initdb.d/03-map.sql",
]
if mysql_init_targets != expected_mysql_init_targets:
    raise SystemExit(
        "MySQL initialization must contain exactly schema, dataset, and map SQL: "
        + repr(mysql_init_targets)
    )

web_volumes = {
    str(volume.get("target")): volume
    for volume in services["web"].get("volumes", [])
    if isinstance(volume, dict)
}
spring_volumes = {
    str(volume.get("target")): volume
    for volume in services["spring"].get("volumes", [])
    if isinstance(volume, dict)
}
if "/usr/share/nginx/html/imgs" in web_volumes:
    raise SystemExit(
        "The upload volume must not hide static Web image assets under /usr/share/nginx/html/imgs."
    )
web_uploads = web_volumes.get("/data/imgs")
spring_uploads = spring_volumes.get("/data/uploads")
if not web_uploads or not spring_uploads:
    raise SystemExit("Web and Spring must both mount the persistent uploads volume.")
if not web_uploads.get("read_only"):
    raise SystemExit("The Web uploads volume must be read-only.")
if web_uploads.get("source") != spring_uploads.get("source"):
    raise SystemExit("Web and Spring must use the same persistent uploads volume.")

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
profile = env.get("NYC_REVIEW_RAG_RELEASE_PROFILE") or "legacy-v1"
if profile not in {"legacy-v1", "m3-quality-v1"}:
    raise SystemExit(f"Unsupported NYC_REVIEW_RAG_RELEASE_PROFILE: {profile!r}")

if mode == "actual":
    required = [
        "APP_SITE_ADDRESS",
        "SPRING_IMAGE",
        "AGENT_IMAGE",
        "WEB_IMAGE",
        "IMAGE_TAG",
        "AGENT_IMAGE_TAG",
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
    if profile == "m3-quality-v1":
        required.extend(
            [
                "OPENAI_API_KEY",
                "DASHSCOPE_API_KEY",
                "DASHSCOPE_BASE_URL",
                "NYC_REVIEW_QDRANT_IMAGE",
                "NYC_REVIEW_QDRANT_VOLUME",
                "NYC_REVIEW_QDRANT_MEMORY_LIMIT",
            ]
        )
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

    for tag_key in ("IMAGE_TAG", "AGENT_IMAGE_TAG"):
        if not re.fullmatch(r"sha-[0-9a-f]{40}", env[tag_key]):
            raise SystemExit(
                f"{tag_key} must be sha- followed by the full 40-character Git commit SHA."
            )
    if profile == "m3-quality-v1" and env["AGENT_IMAGE_TAG"] != env["IMAGE_TAG"]:
        raise SystemExit("The M3 quality profile requires AGENT_IMAGE_TAG=IMAGE_TAG.")
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

image_contracts = {
    "spring": ("SPRING_IMAGE", "IMAGE_TAG"),
    "web": ("WEB_IMAGE", "IMAGE_TAG"),
    "agent-service": ("AGENT_IMAGE", "AGENT_IMAGE_TAG"),
}
for service_name, (image_key, tag_key) in image_contracts.items():
    expected_image = f'{env[image_key]}:{env[tag_key]}'
    actual_image = services[service_name].get("image")
    if actual_image != expected_image:
        raise SystemExit(
            f"{service_name} must use {tag_key}; expected {expected_image!r}, "
            f"got {actual_image!r}."
        )

agent_environment = services["agent-service"].get("environment") or {}
legacy_rag_contract = {
    "NYC_REVIEW_AGENT_ENVIRONMENT": "production",
    "NYC_REVIEW_AGENT_RAG_ADAPTER": "qdrant",
    "NYC_REVIEW_AGENT_QDRANT_LOCATION": "http://qdrant:6333",
    "NYC_REVIEW_AGENT_QDRANT_COLLECTION": "nyc_review_content_v2",
    "NYC_REVIEW_AGENT_RAG_DATA_DIRECTORY": "/data/nyc-real-p13-full",
    "NYC_REVIEW_AGENT_RAG_SYNC_MODE": "sync",
    "NYC_REVIEW_AGENT_EMBEDDING_PROVIDER": "hash",
    "NYC_REVIEW_AGENT_EMBEDDING_DIMENSIONS": "64",
    "NYC_REVIEW_AGENT_ALLOW_HASH_EMBEDDINGS": "true",
    "NYC_REVIEW_AGENT_GLOBAL_RETRIEVAL_ENABLED": "false",
    "NYC_REVIEW_AGENT_QUERY_REWRITE_PROVIDER": "disabled",
    "NYC_REVIEW_AGENT_RERANKER_PROVIDER": "disabled",
    "NYC_REVIEW_AGENT_RETRIEVAL_VERSION": "p12-rag-v1",
}
m3_rag_contract = {
    "NYC_REVIEW_AGENT_ENVIRONMENT": "production",
    "NYC_REVIEW_AGENT_RAG_ADAPTER": "qdrant",
    "NYC_REVIEW_AGENT_QDRANT_LOCATION": "http://qdrant:6333",
    "NYC_REVIEW_AGENT_QDRANT_COLLECTION": "nyc_review_content_v3_dashscope_qwen37_1024_v1",
    "NYC_REVIEW_AGENT_RETRIEVAL_VERSION": "p12-rag-v1",
    "NYC_REVIEW_AGENT_RAG_DATA_DIRECTORY": "/data/nyc-real-p13-full",
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
    "NYC_REVIEW_AGENT_RERANKER_PROVIDER": "disabled",
}

expected_rag_contract = m3_rag_contract if profile == "m3-quality-v1" else legacy_rag_contract
rag_mismatches = {
    key: agent_environment.get(key)
    for key, expected in expected_rag_contract.items()
    if str(agent_environment.get(key)) != expected
}
if rag_mismatches:
    raise SystemExit(
        f"The {profile} Agent/RAG contract has mismatches: {rag_mismatches}"
    )

qdrant_service = services["qdrant"]
qdrant_volume_config = (config.get("volumes") or {}).get("qdrant-data") or {}
if qdrant_volume_config.get("external") is not True:
    raise SystemExit("Qdrant storage must be an explicitly external rollback-safe volume.")
qdrant_volumes = qdrant_service.get("volumes") or []
qdrant_storage = next(
    (
        volume
        for volume in qdrant_volumes
        if isinstance(volume, dict) and volume.get("target") == "/qdrant/storage"
    ),
    None,
)
if not qdrant_storage:
    raise SystemExit("Qdrant must mount a named volume at /qdrant/storage.")

if profile == "m3-quality-v1":
    if qdrant_service.get("image") != "qdrant/qdrant:v1.19.0":
        raise SystemExit("M3 quality requires qdrant/qdrant:v1.19.0.")
    if qdrant_volume_config.get("name") != "nyc-review-production_qdrant-m3-data":
        raise SystemExit("M3 quality requires the checksum-pinned M3 Qdrant volume.")
    memory_limit = int(qdrant_service.get("mem_limit") or 0)
    if memory_limit < 1_610_612_736:
        raise SystemExit("M3 quality requires a Qdrant memory limit of at least 1536 MiB.")
    if agent_environment.get("NYC_REVIEW_AGENT_QWEN_EMBEDDING_API_KEY") != env.get(
        "DASHSCOPE_API_KEY"
    ):
        raise SystemExit("The DashScope credential was not injected into the Agent container.")
    if agent_environment.get("NYC_REVIEW_AGENT_QWEN_EMBEDDING_BASE_URL") != env.get(
        "DASHSCOPE_BASE_URL"
    ):
        raise SystemExit("The DashScope endpoint was not injected into the Agent container.")
    if agent_environment.get("NYC_REVIEW_AGENT_QUERY_REWRITE_API_KEY") != env.get(
        "OPENAI_API_KEY"
    ):
        raise SystemExit("The OpenAI rewrite credential was not injected into the Agent container.")
    dashscope_url = env.get("DASHSCOPE_BASE_URL", "").rstrip("/")
    allowed_suffixes = (
        "/compatible-mode/v1",
        "/api/v1",
        "/services/embeddings/text-embedding/text-embedding",
    )
    if not dashscope_url.startswith("https://") or not dashscope_url.endswith(allowed_suffixes):
        raise SystemExit("DASHSCOPE_BASE_URL must be an HTTPS Qwen-compatible endpoint.")
else:
    if qdrant_service.get("image") != "qdrant/qdrant:v1.15.3":
        raise SystemExit("The legacy profile requires qdrant/qdrant:v1.15.3.")
    if qdrant_volume_config.get("name") != "nyc-review-production_qdrant-data":
        raise SystemExit("The legacy profile must retain the original Qdrant volume.")

print(
    f"Production Compose validation passed: profile={profile}, pull-only images, "
    "only 80/443 published."
)
PY
