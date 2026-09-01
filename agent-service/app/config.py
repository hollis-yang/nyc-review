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
    rag_sync_mode: Literal["sync", "verify"] = "sync"
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
    global_retrieval_enabled: bool = False
    global_retrieval_document_limit: int = Field(default=200, ge=1, le=1_000)
    global_retrieval_hydration_limit: int = Field(default=60, ge=1, le=100)
    global_retrieval_fusion_pool_limit: int = Field(default=30, ge=1, le=100)
    global_retrieval_hydration_concurrency: int = Field(default=8, ge=1, le=32)
    global_retrieval_branch_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    global_retrieval_documents_per_merchant: int = Field(default=3, ge=1, le=10)
    global_retrieval_rrf_k: int = Field(default=60, ge=1, le=1_000)
    global_retrieval_brand_cap: int = Field(default=2, ge=1, le=10)
    query_rewrite_provider: Literal["disabled", "openai", "deepseek"] = "disabled"
    query_rewrite_base_url: str = ""
    query_rewrite_api_key: SecretStr = SecretStr("")
    query_rewrite_model: str = ""
    query_rewrite_prompt_version: str = "m3-query-rewrite-v1"
    query_rewrite_max_queries: int = Field(default=3, ge=1, le=3)
    query_rewrite_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    query_rewrite_max_concurrency: int = Field(default=2, ge=1, le=8)
    query_rewrite_cache_size: int = Field(default=512, ge=0, le=10_000)
    query_rewrite_cache_ttl_seconds: float = Field(default=900.0, ge=0, le=86_400)
    query_rewrite_max_input_characters: int = Field(default=2_000, ge=1, le=2_000)
    query_rewrite_max_output_tokens: int = Field(default=300, ge=64, le=2_000)
    # M4 reranking is query-side only and remains opt-in until the production
    # migration.  The dedicated secret may fall back to the existing
    # DashScope credential without ever serializing it into trace metadata.
    reranker_provider: Literal["disabled", "qwen"] = "disabled"
    reranker_base_url: str = ""
    reranker_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices(
            "NYC_REVIEW_AGENT_RERANKER_API_KEY",
            "DASHSCOPE_API_KEY",
        ),
    )
    reranker_model: str = "qwen3-rerank"
    reranker_version: str = ""
    reranker_instruct: str = (
        "Given a local-business search query, rank merchants by satisfaction of the user's "
        "stated preferences. Canonical tags and source-backed evidence are authoritative: "
        "matching all requested preferences must outrank matching only some, while rating and "
        "distance are tie-breakers rather than substitutes for intent."
    )
    reranker_candidate_limit: int = Field(default=30, ge=1, le=100)
    reranker_max_document_characters: int = Field(default=1_600, ge=256, le=8_000)
    reranker_max_evidence_excerpts: int = Field(default=2, ge=0, le=5)
    reranker_max_evidence_characters: int = Field(default=500, ge=64, le=2_000)
    reranker_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    reranker_max_concurrency: int = Field(default=2, ge=1, le=8)
    reranker_max_retries: int = Field(default=0, ge=0, le=2)
    reranker_cache_size: int = Field(default=512, ge=0, le=10_000)
    reranker_cache_ttl_seconds: float = Field(default=900.0, ge=0, le=86_400)
    reranker_circuit_failure_threshold: int = Field(default=3, ge=1, le=20)
    reranker_circuit_cooldown_seconds: float = Field(default=30.0, gt=0, le=600)
    reranker_input_price_usd_per_million_tokens: float = Field(
        default=0.11,
        ge=0,
        le=100,
    )
    max_agent_steps: int = Field(default=12, ge=3, le=50)
    max_parallel_agents: int = Field(default=2, ge=1, le=4)
    max_recovery_attempts: int = Field(default=2, ge=0, le=5)
    runs_per_minute: int = Field(default=10, ge=1, le=120)
    metrics_token: str = ""
    mcp_enabled: bool = True
    mcp_api_key: str = ""

    @model_validator(mode="after")
    def reject_unapproved_production_hash_embeddings(self) -> Settings:
        if self.rag_sync_mode == "verify":
            if self.rag_adapter != "qdrant":
                raise ValueError("RAG verify mode requires rag_adapter=qdrant.")
            if self.rag_data_directory is None:
                raise ValueError(
                    "RAG verify mode requires rag_data_directory so the desired corpus can be verified."
                )
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
        if self.global_retrieval_enabled:
            if self.rag_adapter != "qdrant":
                raise ValueError("Global retrieval requires rag_adapter=qdrant.")
            if self.rag_data_directory is None:
                raise ValueError(
                    "Global retrieval requires rag_data_directory so its corpus scope can be verified."
                )
            if self.global_retrieval_document_limit < self.global_retrieval_hydration_limit:
                raise ValueError(
                    "Global retrieval requires document_limit >= hydration_limit."
                )
            if self.global_retrieval_hydration_limit < self.max_candidates:
                raise ValueError(
                    "Global retrieval requires hydration_limit >= max_candidates."
                )
            if self.global_retrieval_fusion_pool_limit < self.max_candidates:
                raise ValueError(
                    "Global retrieval requires fusion_pool_limit >= max_candidates."
                )
            if (
                self.global_retrieval_fusion_pool_limit
                > self.global_retrieval_hydration_limit
            ):
                raise ValueError(
                    "Global retrieval requires fusion_pool_limit <= hydration_limit."
                )
            if (
                self.global_retrieval_documents_per_merchant
                > self.global_retrieval_document_limit
            ):
                raise ValueError(
                    "Global retrieval requires documents_per_merchant <= document_limit."
                )
        if self.query_rewrite_provider != "disabled" and not self.global_retrieval_enabled:
            raise ValueError("Query rewrite requires global retrieval to be enabled.")
        if self.reranker_provider != "disabled":
            if not self.global_retrieval_enabled:
                raise ValueError("Cross-Encoder reranking requires global retrieval to be enabled.")
            if self.reranker_model != "qwen3-rerank":
                raise ValueError("The qwen reranker provider requires reranker_model=qwen3-rerank.")
            if self.reranker_candidate_limit < self.max_candidates:
                raise ValueError("Reranker candidate_limit must be at least max_candidates.")
            if self.reranker_candidate_limit > self.global_retrieval_fusion_pool_limit:
                raise ValueError(
                    "Reranker candidate_limit cannot exceed global retrieval fusion_pool_limit."
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
