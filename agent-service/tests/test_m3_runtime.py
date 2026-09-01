from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.runtime as runtime_module
from app.config import Settings
from app.rag.embeddings import EmbeddingMetadata, EmbeddingUsage
from app.rag.query_rewriter import DisabledQueryRewriter, RewriteUsage
from app.runtime import AgentRuntime, _build_query_rewriter


def _global_settings(tmp_path, **overrides) -> Settings:
    values = {
        "rag_adapter": "qdrant",
        "rag_data_directory": tmp_path,
        "global_retrieval_enabled": True,
        "query_rewrite_provider": "openai",
        "run_store_path": ":memory:",
    }
    values.update(overrides)
    return Settings(**values)


def test_query_rewriter_is_absent_when_feature_is_disabled():
    assert _build_query_rewriter(Settings()) is None


def test_query_rewrite_defaults_off_and_requires_global_retrieval():
    defaults = Settings()

    assert defaults.query_rewrite_provider == "disabled"
    with pytest.raises(ValueError, match="requires global retrieval"):
        Settings(query_rewrite_provider="openai")


def test_openai_rewriter_uses_fixed_defaults_and_openai_key_fallback(
    monkeypatch,
    tmp_path,
):
    captured = {}

    def capture(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(runtime_module, "OpenAICompatibleQueryRewriter", capture)

    result = _build_query_rewriter(
        _global_settings(
            tmp_path,
            openai_embedding_api_key="openai-fallback",
            query_rewrite_prompt_version="prompt-v2",
            query_rewrite_max_queries=2,
            query_rewrite_timeout_seconds=3.5,
            query_rewrite_max_concurrency=1,
            query_rewrite_cache_size=17,
            query_rewrite_cache_ttl_seconds=45,
            query_rewrite_max_input_characters=777,
            query_rewrite_max_output_tokens=123,
        )
    )

    assert result is not None
    assert captured == {
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "openai-fallback",
        "model": "gpt-4o-mini-2024-07-18",
        "fallback": captured["fallback"],
        "prompt_version": "prompt-v2",
        "max_queries": 2,
        "timeout_seconds": 3.5,
        "max_concurrency": 1,
        "cache_size": 17,
        "cache_ttl_seconds": 45,
        "max_input_characters": 777,
        "max_output_tokens": 123,
    }
    assert isinstance(captured["fallback"], DisabledQueryRewriter)


@pytest.mark.parametrize(
    ("provider", "overrides", "expected"),
    [
        (
            "openai",
            {
                "query_rewrite_api_key": "dedicated",
                "openai_embedding_api_key": "fallback",
                "query_rewrite_base_url": "https://rewrite.example/v1/",
                "query_rewrite_model": "rewrite-model",
            },
            ("https://rewrite.example/v1/", "dedicated", "rewrite-model"),
        ),
        (
            "deepseek",
            {
                "model_base_url": "https://deepseek.example/v1",
                "model_api_key": "model-key",
                "model_name": "deepseek-model",
            },
            ("https://deepseek.example/v1", "model-key", "deepseek-model"),
        ),
    ],
)
def test_query_rewriter_provider_precedence(
    monkeypatch,
    tmp_path,
    provider,
    overrides,
    expected,
):
    captured = {}

    def capture(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(runtime_module, "OpenAICompatibleQueryRewriter", capture)

    _build_query_rewriter(
        _global_settings(
            tmp_path,
            query_rewrite_provider=provider,
            **overrides,
        )
    )

    assert (
        captured["base_url"],
        captured["api_key"],
        captured["model"],
    ) == expected


class _FakeQdrantClient:
    def __init__(self):
        self.close_count = 0

    async def close(self) -> None:
        self.close_count += 1


class _FakeEmbeddingService:
    metadata = EmbeddingMetadata(
        provider="openai",
        model="embedding-model",
        dimensions=1_024,
        version="embedding-v1",
        query_mode="symmetric",
        document_mode="symmetric",
    )

    def __init__(self):
        self.close_count = 0

    async def aclose(self) -> None:
        self.close_count += 1

    def usage_snapshot(self) -> EmbeddingUsage:
        return EmbeddingUsage()


class _FakeQueryRewriter:
    def __init__(self):
        self.close_count = 0

    def usage_snapshot(self) -> RewriteUsage:
        return RewriteUsage()

    def reset(self) -> None:
        return None

    async def aclose(self) -> None:
        self.close_count += 1


class _FakeRagService:
    async def sync(self, _documents, *, data_version):
        return SimpleNamespace(total_documents=0, as_metadata=lambda: {})


class _FakeRunManager:
    def __init__(self, _runtime, store, _model_gateway, **_kwargs):
        self._store = store
        self.close_count = 0

    async def recover(self) -> int:
        return 0

    async def close(self) -> None:
        self.close_count += 1
        await self._store.close()


async def test_runtime_injects_and_idempotently_closes_query_rewriter(
    monkeypatch,
    tmp_path,
):
    qdrant = _FakeQdrantClient()
    embedding = _FakeEmbeddingService()
    rewriter = _FakeQueryRewriter()
    candidate = object()
    injected = {}
    rag_kwargs = {}

    monkeypatch.setattr(runtime_module, "_build_shop_service", lambda _settings: object())
    monkeypatch.setattr(
        runtime_module,
        "_validate_data_directory",
        lambda _path: ("data-v1", "d" * 64, {}),
    )
    monkeypatch.setattr(
        runtime_module,
        "_build_qdrant_client",
        lambda _location, *, api_key="": qdrant,
    )
    monkeypatch.setattr(runtime_module, "_build_embedding_service", lambda _settings: embedding)
    def build_rag(**kwargs):
        rag_kwargs.update(kwargs)
        return _FakeRagService()

    monkeypatch.setattr(runtime_module, "QdrantRagService", build_rag)
    monkeypatch.setattr(runtime_module, "_build_query_rewriter", lambda _settings: rewriter)

    def build_discovery(*_args, **kwargs):
        injected.update(kwargs)
        return candidate

    monkeypatch.setattr(runtime_module, "GlobalHybridCandidateDiscovery", build_discovery)
    monkeypatch.setattr(runtime_module, "build_single_agent_graph", lambda _services: "single")
    monkeypatch.setattr(runtime_module, "build_multi_agent_graph", lambda _services: "multi")
    monkeypatch.setattr(runtime_module, "AgentRunManager", _FakeRunManager)

    runtime = await AgentRuntime.create(
        _global_settings(
            tmp_path,
            openai_embedding_api_key="unused",
            rag_sync_mode="verify",
        )
    )

    assert runtime.query_rewriter is rewriter
    assert runtime.candidate_discovery is candidate
    assert injected["query_rewriter"] is rewriter
    assert rag_kwargs["sync_mode"] == "verify"

    await runtime.close()
    await runtime.close()

    assert runtime.run_manager.close_count == 1
    assert rewriter.close_count == 1
    assert embedding.close_count == 1
    assert qdrant.close_count == 1


async def test_runtime_creation_failure_closes_query_rewriter_and_other_clients(
    monkeypatch,
    tmp_path,
):
    qdrant = _FakeQdrantClient()
    embedding = _FakeEmbeddingService()
    rewriter = _FakeQueryRewriter()

    monkeypatch.setattr(runtime_module, "_build_shop_service", lambda _settings: object())
    monkeypatch.setattr(
        runtime_module,
        "_validate_data_directory",
        lambda _path: ("data-v1", "d" * 64, {}),
    )
    monkeypatch.setattr(
        runtime_module,
        "_build_qdrant_client",
        lambda _location, *, api_key="": qdrant,
    )
    monkeypatch.setattr(runtime_module, "_build_embedding_service", lambda _settings: embedding)
    monkeypatch.setattr(runtime_module, "QdrantRagService", lambda **_kwargs: _FakeRagService())
    monkeypatch.setattr(runtime_module, "_build_query_rewriter", lambda _settings: rewriter)

    def fail_discovery(*_args, **_kwargs):
        raise RuntimeError("candidate construction failed")

    monkeypatch.setattr(runtime_module, "GlobalHybridCandidateDiscovery", fail_discovery)

    with pytest.raises(RuntimeError, match="candidate construction failed"):
        await AgentRuntime.create(_global_settings(tmp_path))

    assert rewriter.close_count == 1
    assert embedding.close_count == 1
    assert qdrant.close_count == 1
