from __future__ import annotations

import pytest

import app.runtime as runtime_module
from app.config import Settings
from app.rag.embeddings import EmbeddingMetadata, EmbeddingUsage
from app.runtime import AgentRuntime


class _FakeQdrantClient:
    def __init__(self, *, close_error: Exception | None = None):
        self.closed = False
        self._close_error = close_error

    async def close(self) -> None:
        self.closed = True
        if self._close_error is not None:
            raise self._close_error


class _FakeEmbeddingService:
    def __init__(self, *, close_error: Exception | None = None):
        self.metadata = EmbeddingMetadata(
            provider="hash",
            model="deterministic-token-sha256",
            dimensions=64,
            version="hash-v1",
            query_mode="symmetric",
            document_mode="symmetric",
        )
        self.closed = False
        self._close_error = close_error

    @property
    def dimensions(self) -> int:
        return self.metadata.dimensions

    async def embed_query(self, _text: str) -> list[float]:
        return [1.0] * self.dimensions

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] * self.dimensions for _text in texts]

    def usage_snapshot(self) -> EmbeddingUsage:
        return EmbeddingUsage()

    def clear_query_cache(self) -> None:
        return None

    async def aclose(self) -> None:
        self.closed = True
        if self._close_error is not None:
            raise self._close_error


async def test_provider_construction_failure_closes_qdrant_and_preserves_original_error(
    monkeypatch,
):
    client = _FakeQdrantClient(close_error=RuntimeError("secondary close failure"))

    monkeypatch.setattr(
        runtime_module,
        "_build_qdrant_client",
        lambda _location, *, api_key="": client,
    )

    def fail_embedding(_settings):
        raise RuntimeError("provider construction failed")

    monkeypatch.setattr(runtime_module, "_build_embedding_service", fail_embedding)

    with pytest.raises(RuntimeError, match="provider construction failed"):
        await AgentRuntime.create(
            Settings(
                rag_adapter="qdrant",
                qdrant_location=":memory:",
                run_store_path=":memory:",
            )
        )

    assert client.closed is True


async def test_recovery_failure_closes_manager_embedding_and_qdrant(monkeypatch):
    client = _FakeQdrantClient()
    embedding = _FakeEmbeddingService()
    manager_state = {"closed": False}

    class FailingRunManager:
        def __init__(self, _runtime, store, _model_gateway, **_kwargs):
            self._store = store

        async def recover(self) -> int:
            raise RuntimeError("recovery failed")

        async def close(self) -> None:
            manager_state["closed"] = True
            await self._store.close()

    monkeypatch.setattr(
        runtime_module,
        "_build_qdrant_client",
        lambda _location, *, api_key="": client,
    )
    monkeypatch.setattr(runtime_module, "_build_embedding_service", lambda _settings: embedding)
    monkeypatch.setattr(runtime_module, "AgentRunManager", FailingRunManager)

    with pytest.raises(RuntimeError, match="recovery failed"):
        await AgentRuntime.create(
            Settings(
                rag_adapter="qdrant",
                qdrant_location=":memory:",
                run_store_path=":memory:",
            )
        )

    assert manager_state["closed"] is True
    assert embedding.closed is True
    assert client.closed is True


async def test_runtime_close_attempts_every_resource_and_is_idempotent():
    events: list[str] = []

    class Manager:
        async def close(self) -> None:
            events.append("manager")
            raise RuntimeError("manager close failed")

    class Embedding(_FakeEmbeddingService):
        async def aclose(self) -> None:
            events.append("embedding")

    class Qdrant(_FakeQdrantClient):
        async def close(self) -> None:
            events.append("qdrant")

    runtime = AgentRuntime(
        workflow=None,
        workflows={},
        adapter_name="mock",
        rag_name="qdrant",
        run_manager=Manager(),
        embedding_service=Embedding(),
        qdrant_client=Qdrant(),
    )

    with pytest.raises(RuntimeError, match="manager close failed"):
        await runtime.close()

    assert events == ["manager", "embedding", "qdrant"]
    assert runtime._closed is True

    await runtime.close()
    assert events == ["manager", "embedding", "qdrant"]
