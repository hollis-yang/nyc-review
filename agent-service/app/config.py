from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_RUN_STORE_PATH = str(Path(__file__).resolve().parents[1] / ".local" / "agent-runs.sqlite3")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HMDP_AGENT_", extra="ignore", populate_by_name=True)

    app_name: str = "hmdp-agent-service"
    environment: str = "development"
    adapter: Literal["mock", "http"] = "mock"
    backend_base_url: str = "http://127.0.0.1:8081"
    backend_auth_token: str = ""
    request_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    rag_adapter: Literal["memory", "qdrant"] = "memory"
    qdrant_location: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "hmdp_content_v1"
    rag_data_directory: Path | None = None
    embedding_provider: Literal["hash", "openai"] = "hash"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=64, ge=8, le=4096)
    model_provider: Literal["heuristic", "deepseek", "openai"] = "heuristic"
    model_base_url: str = "https://api.deepseek.com/v1"
    model_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("HMDP_AGENT_MODEL_API_KEY", "DEEPSEEK_API_KEY"),
    )
    model_name: str = Field(
        default="deepseek-chat",
        validation_alias=AliasChoices("HMDP_AGENT_MODEL_NAME", "DEEPSEEK_MODEL"),
    )
    model_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    model_fallback_to_heuristic: bool = True
    run_store_path: str = DEFAULT_RUN_STORE_PATH
    max_candidates: int = Field(default=5, ge=1, le=20)
    max_agent_steps: int = Field(default=12, ge=3, le=50)
    max_parallel_agents: int = Field(default=2, ge=1, le=4)
    run_timeout_seconds: float = Field(default=45.0, gt=1, le=300)
    max_recovery_attempts: int = Field(default=2, ge=0, le=5)
    runs_per_minute: int = Field(default=10, ge=1, le=120)
    metrics_token: str = ""
    mcp_enabled: bool = True
    mcp_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
