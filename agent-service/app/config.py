from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_RUN_STORE_PATH = str(Path(__file__).resolve().parents[1] / ".local" / "agent-runs.sqlite3")
QWEN37_SUPPORTED_DIMENSIONS = frozenset({256, 512, 768, 1_024, 1_536, 2_048, 2_560})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NYC_REVIEW_AGENT_", extra="ignore", populate_by_name=True)

    app_name: str = "nyc-review-agent-service"
    environment: str = "development"
    adapter: Literal["mock", "http"] = "mock"
    backend_base_url: str = "http://127.0.0.1:8081"
    backend_auth_token: str = ""
    rag_adapter: Literal["memory", "qdrant"] = "memory"
    qdrant_location: str = "http://127.0.0.1:6333"
    qdrant_api_key: SecretStr = SecretStr("")
    qdrant_collection: str = "nyc_review_content_v2"
    retrieval_version: str = "p12-rag-v1"
    rag_data_directory: Path | None = None
    rag_index_batch_size: int = Field(default=128, ge=1, le=2_048)
    embedding_provider: Literal["hash", "openai", "qwen"] = "hash"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: SecretStr = SecretStr("")
    openai_embedding_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices(
            "NYC_REVIEW_AGENT_OPENAI_EMBEDDING_API_KEY",
            "OPENAI_API_KEY",
        ),
    )
    qwen_embedding_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices(
            "NYC_REVIEW_AGENT_QWEN_EMBEDDING_API_KEY",
            "DASHSCOPE_API_KEY",
        ),
    )
    qwen_embedding_base_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "NYC_REVIEW_AGENT_QWEN_EMBEDDING_BASE_URL",
            "DASHSCOPE_BASE_URL",
        ),
    )
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=64, ge=8, le=4096)
    embedding_version: str = ""
    embedding_batch_size: int = Field(default=64, ge=1, le=2_048)
    embedding_max_concurrency: int = Field(default=2, ge=1, le=16)
    embedding_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    embedding_max_retries: int = Field(default=4, ge=0, le=10)
    embedding_max_batch_characters: int = Field(default=250_000, ge=1, le=2_000_000)
    embedding_query_cache_size: int = Field(default=512, ge=0, le=100_000)
    embedding_query_cache_ttl_seconds: float = Field(default=900.0, ge=0, le=86_400)
    embedding_query_prefix: str = ""
    embedding_document_prefix: str = ""
    embedding_query_instruct: str = ""
    embedding_max_total_tokens: int | None = Field(default=None, ge=1)
    allow_hash_embeddings: bool = False
    embedding_sparse_fallback: bool = True
    model_provider: Literal["heuristic", "deepseek", "openai"] = "heuristic"
    model_base_url: str = "https://api.deepseek.com/v1"
    model_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("NYC_REVIEW_AGENT_MODEL_API_KEY", "DEEPSEEK_API_KEY"),
    )
    model_name: str = Field(
        default="deepseek-chat",
        validation_alias=AliasChoices("NYC_REVIEW_AGENT_MODEL_NAME", "DEEPSEEK_MODEL"),
    )
    model_fallback_to_heuristic: bool = True
    run_store_path: str = DEFAULT_RUN_STORE_PATH
    # The natural-language request defaults to five results and can explicitly
    # request up to ten. This setting is only the server-side safety ceiling.
    max_candidates: int = Field(default=10, ge=1, le=20)
    discovery_pool_size: int = Field(default=50, ge=5, le=100)
    max_agent_steps: int = Field(default=12, ge=3, le=50)
    max_parallel_agents: int = Field(default=2, ge=1, le=4)
    max_recovery_attempts: int = Field(default=2, ge=0, le=5)
    runs_per_minute: int = Field(default=10, ge=1, le=120)
    metrics_token: str = ""
    mcp_enabled: bool = True
    mcp_api_key: str = ""

    @model_validator(mode="after")
    def reject_unapproved_production_hash_embeddings(self) -> Settings:
        if (
            self.environment.strip().casefold() in {"production", "prod", "staging"}
            and self.embedding_provider == "hash"
            and not self.allow_hash_embeddings
        ):
            raise ValueError(
                "Hash embeddings are test-only; explicitly set "
                "NYC_REVIEW_AGENT_ALLOW_HASH_EMBEDDINGS=true to override."
            )
        if self.embedding_provider == "qwen":
            if self.embedding_model != "qwen3.7-text-embedding":
                raise ValueError(
                    "The qwen provider requires embedding_model=qwen3.7-text-embedding."
                )
            if self.embedding_dimensions not in QWEN37_SUPPORTED_DIMENSIONS:
                supported = ", ".join(map(str, sorted(QWEN37_SUPPORTED_DIMENSIONS)))
                raise ValueError(
                    "qwen3.7-text-embedding requires embedding_dimensions to be one of: "
                    f"{supported}."
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
