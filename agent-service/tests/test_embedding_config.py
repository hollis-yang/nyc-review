from __future__ import annotations

import pytest

from app.config import Settings
from app.rag.embeddings import OpenAICompatibleEmbeddingService, QwenNativeEmbeddingService
from app.runtime import _build_embedding_service


def test_provider_specific_environment_aliases_are_secret_and_independent(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-secret")
    monkeypatch.setenv(
        "DASHSCOPE_BASE_URL",
        "https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
    )

    settings = Settings()

    assert settings.openai_embedding_api_key.get_secret_value() == "openai-secret"
    assert settings.qwen_embedding_api_key.get_secret_value() == "qwen-secret"
    assert "openai-secret" not in repr(settings)
    assert "qwen-secret" not in repr(settings)


def test_production_hash_requires_explicit_override():
    with pytest.raises(ValueError, match="Hash embeddings are test-only"):
        Settings(environment="production", embedding_provider="hash")

    allowed = Settings(
        environment="production",
        embedding_provider="hash",
        allow_hash_embeddings=True,
    )
    assert allowed.embedding_provider == "hash"

    with pytest.raises(ValueError, match="Hash embeddings are test-only"):
        Settings(environment=" Production ", embedding_provider="hash")


def test_qwen_model_and_dimensions_are_validated_before_any_provider_call():
    with pytest.raises(ValueError, match="requires embedding_model"):
        Settings(embedding_provider="qwen", embedding_model="text-embedding-3-small")

    with pytest.raises(ValueError, match="requires embedding_dimensions"):
        Settings(
            embedding_provider="qwen",
            embedding_model="qwen3.7-text-embedding",
            embedding_dimensions=64,
        )

    settings = Settings(
        embedding_provider="qwen",
        embedding_model="qwen3.7-text-embedding",
        embedding_dimensions=2_560,
    )
    assert settings.embedding_dimensions == 2_560


async def test_runtime_builds_provider_specific_adapters(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-secret")
    monkeypatch.setenv(
        "DASHSCOPE_BASE_URL",
        "https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
    )
    openai = _build_embedding_service(
        Settings(
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1_024,
            embedding_version="openai-small-v1",
        )
    )
    qwen = _build_embedding_service(
        Settings(
            embedding_provider="qwen",
            embedding_model="qwen3.7-text-embedding",
            embedding_dimensions=1_024,
            embedding_version="qwen37-v1",
        )
    )
    try:
        assert isinstance(openai, OpenAICompatibleEmbeddingService)
        assert openai.metadata.provider == "openai"
        assert isinstance(qwen, QwenNativeEmbeddingService)
        assert qwen.metadata.query_mode == "query"
        assert qwen.metadata.document_mode == "document"
    finally:
        await openai.aclose()
        await qwen.aclose()
