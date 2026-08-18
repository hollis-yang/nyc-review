from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HMDP_AGENT_", extra="ignore")

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
    max_candidates: int = Field(default=5, ge=1, le=20)
    max_agent_steps: int = Field(default=12, ge=3, le=50)
    max_parallel_agents: int = Field(default=2, ge=1, le=4)


@lru_cache
def get_settings() -> Settings:
    return Settings()
