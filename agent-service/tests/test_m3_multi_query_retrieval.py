from __future__ import annotations

import asyncio
from collections import Counter
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.rag.embeddings import (
    DeterministicHashEmbeddingService,
    EmbeddingError,
    EmbeddingMetadata,
    EmbeddingProviderError,
)
from app.rag.global_retrieval import (
    MAX_QUERY_VARIANT_LENGTH,
    GlobalQueryVariant,
    GlobalRetrievalResult,
    GlobalRetrievalScope,
    MultiQueryGlobalRetrievalResult,
    QdrantGlobalDocumentRetriever,
    QueryVariantSource,
    RetrievalChannel,
    VariantRetrievalStatus,
)
from app.rag.merchant_aggregation import aggregate_merchants


class RecordingEmbedding:
    def __init__(self, delegate: DeterministicHashEmbeddingService) -> None:
        self._delegate = delegate
        self.queries: list[str] = []

    @property
    def metadata(self) -> EmbeddingMetadata:
        return self._delegate.metadata

    @property
    def dimensions(self) -> int:
        return self._delegate.dimensions

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return await self._delegate.embed_query(text)


class BatchRecordingEmbedding(RecordingEmbedding):
    def __init__(self, delegate: DeterministicHashEmbeddingService) -> None:
        super().__init__(delegate)
        self.query_batches: list[list[str]] = []

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        self.query_batches.append(list(texts))
        self.queries.extend(texts)
        return await self._delegate.embed_queries(texts)


class RecordingQdrantClient:
    def __init__(self, point) -> None:
        self._point = point
        self.calls: list[dict] = []

    async def query_points(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(points=[self._point])


def _scope(embedding) -> GlobalRetrievalScope:
    return GlobalRetrievalScope(
        collection_name="m3-global-fixture",
        data_version="nyc-real-v1",
        dataset_sha256="a" * 64,
        retrieval_version="p12-rag-v1",
        embedding_identity=embedding.metadata.identity,
    )


def _point(scope: GlobalRetrievalScope):
    return SimpleNamespace(
        id="point-101",
        score=0.9,
        payload={
            "shop_id": 101,
            "shop_external_id": "node:101",
            "document_id": "review:point-101",
            "source_id": "source:point-101",
            "root_id": 10_101,
            "content_type": "shop_review_thread",
            "document_kind": "evidence",
            "text": "A calm, wheelchair-accessible dining room.",
            "category": "Food & Dining",
            "neighborhood": "Midtown",
            "data_version": scope.data_version,
            "dataset_sha256": scope.dataset_sha256,
            "retrieval_version": scope.retrieval_version,
            "embedding_identity": scope.embedding_identity,
            "index_scope": scope.index_scope,
            "security_test": False,
        },
    )


def _variants() -> tuple[GlobalQueryVariant, ...]:
    return (
        GlobalQueryVariant(
            variant_id="original",
            source=QueryVariantSource.ORIGINAL,
            query="安静的无障碍餐厅",
        ),
        GlobalQueryVariant(
            variant_id="rules",
            source=QueryVariantSource.RULES,
            query="quiet wheelchair accessible restaurant",
        ),
        GlobalQueryVariant(
            variant_id="llm-1",
            source=QueryVariantSource.LLM,
            query="calm step-free dining",
        ),
    )


async def test_multi_query_retrieves_every_variant_independently_with_shared_scope():
    delegate = DeterministicHashEmbeddingService(dimensions=64)
    embedding = BatchRecordingEmbedding(delegate)
    scope = _scope(embedding)
    client = RecordingQdrantClient(_point(scope))
    retriever = QdrantGlobalDocumentRetriever(client, embedding, scope)

    result = await retriever.search_query_variants(
        _variants(),
        document_limit=37,
        category="Food & Dining",
        neighborhood="Midtown",
    )

    assert isinstance(result, MultiQueryGlobalRetrievalResult)
    assert isinstance(result, GlobalRetrievalResult)
    assert [item.variant.variant_id for item in result.variants] == [
        "original",
        "rules",
        "llm-1",
    ]
    assert Counter(embedding.queries) == Counter(variant.query for variant in _variants())
    assert all(embedding.queries.count(variant.query) == 1 for variant in _variants())
    assert embedding.query_batches == [[variant.query for variant in _variants()]]
    assert Counter(call["using"] for call in client.calls) == {
        "dense": 3,
        "lexical": 3,
    }
    assert all(item.status is VariantRetrievalStatus.COMPLETE for item in result.variants)
    assert all(item.dense.hits and item.sparse.hits for item in result.variants)

    expected_filter = {
        "index_scope": scope.index_scope,
        "retrieval_version": scope.retrieval_version,
        "data_version": scope.data_version,
        "dataset_sha256": scope.dataset_sha256,
        "embedding_identity": scope.embedding_identity,
        "security_test": False,
        "category": "Food & Dining",
        "neighborhood": "Midtown",
    }
    for call in client.calls:
        assert call["collection_name"] == scope.collection_name
        assert call["limit"] == 37
        assert {
            condition.key: condition.match.value for condition in call["query_filter"].must
        } == expected_filter
        assert not call["query_filter"].must_not

    assert len(result.dense.hits) == 3
    assert len(result.sparse.hits) == 3
    assert {(item.variant_id, item.source, item.channel) for item in result.provenance} == {
        (variant.variant_id, variant.source, channel)
        for variant in _variants()
        for channel in (RetrievalChannel.DENSE, RetrievalChannel.SPARSE)
    }
    assert result.trace.requested_variant_ids == ("original", "rules", "llm-1")
    assert result.trace.completed_variant_ids == ("original", "rules", "llm-1")
    assert result.trace.partial_failure_variant_ids == ()

    # The merged top-level view deliberately remains consumable by the M2 API.
    assert aggregate_merchants(result).unique_merchants == 1


async def test_single_query_api_retains_the_original_result_contract():
    delegate = DeterministicHashEmbeddingService(dimensions=64)
    embedding = RecordingEmbedding(delegate)
    scope = _scope(embedding)
    client = RecordingQdrantClient(_point(scope))

    result = await QdrantGlobalDocumentRetriever(client, embedding, scope).search_documents("quiet dinner")

    assert type(result) is GlobalRetrievalResult
    assert result.model_fields_set == {
        "dense",
        "sparse",
        "embedding_latency_ms",
        "total_latency_ms",
    }
    assert embedding.queries == ["quiet dinner"]
    assert Counter(call["using"] for call in client.calls) == {
        "dense": 1,
        "lexical": 1,
    }


async def test_failed_query_batch_degrades_once_to_sparse_without_paid_fanout():
    delegate = DeterministicHashEmbeddingService(dimensions=64)

    class BatchFailureEmbedding(RecordingEmbedding):
        def __init__(self, inner: DeterministicHashEmbeddingService) -> None:
            super().__init__(inner)
            self.batch_calls = 0

        async def embed_queries(self, texts: list[str]) -> list[list[float]]:
            self.batch_calls += 1
            raise EmbeddingError("temporary provider failure")

        async def embed_query(self, text: str) -> list[float]:
            raise AssertionError("A failed batch must not fan out into per-query retries.")

    embedding = BatchFailureEmbedding(delegate)
    scope = _scope(embedding)
    client = RecordingQdrantClient(_point(scope))

    result = await QdrantGlobalDocumentRetriever(
        client,
        embedding,
        scope,
    ).search_query_variants(_variants())

    assert embedding.batch_calls == 1
    assert Counter(call["using"] for call in client.calls) == {"lexical": 3}
    assert all(
        item.status is VariantRetrievalStatus.PARTIAL
        and item.dense.fallback_reason == "embedding-error"
        and item.sparse.available
        for item in result.variants
    )
    assert result.trace.partial_failure_variant_ids == (
        "original",
        "rules",
        "llm-1",
    )


async def test_multi_query_traces_partial_non_authorization_failures():
    delegate = DeterministicHashEmbeddingService(dimensions=64)

    class SelectiveFailureEmbedding(RecordingEmbedding):
        async def embed_query(self, text: str) -> list[float]:
            self.queries.append(text)
            if text == "quiet wheelchair accessible restaurant":
                raise EmbeddingError("temporary provider failure")
            if text == "calm step-free dining":
                raise RuntimeError("unexpected provider failure")
            return await self._delegate.embed_query(text)

    embedding = SelectiveFailureEmbedding(delegate)
    scope = _scope(embedding)
    client = RecordingQdrantClient(_point(scope))

    result = await QdrantGlobalDocumentRetriever(
        client,
        embedding,
        scope,
    ).search_query_variants(_variants())

    assert result.result_for("original").status is VariantRetrievalStatus.COMPLETE
    rules = result.result_for("rules")
    assert rules.status is VariantRetrievalStatus.PARTIAL
    assert rules.dense.fallback_reason == "embedding-error"
    assert rules.sparse.available is True
    llm = result.result_for("llm-1")
    assert llm.status is VariantRetrievalStatus.UNAVAILABLE
    assert llm.fallback_reason == "variant-error"
    assert result.trace.completed_variant_ids == ("original", "rules")
    assert result.trace.partial_failure_variant_ids == ("rules", "llm-1")
    assert result.trace.failed_variant_ids == ("llm-1",)
    assert result.trace.timed_out_variant_ids == ()
    assert result.dense.available is True
    assert result.dense.fallback_reason == "partial-variant-fallback"
    assert result.sparse.available is True
    assert result.sparse.fallback_reason == "partial-variant-fallback"


async def test_multi_query_times_out_one_variant_without_losing_healthy_results():
    delegate = DeterministicHashEmbeddingService(dimensions=64)
    blocked_started = asyncio.Event()
    blocked_cancelled = asyncio.Event()

    class BlockingEmbedding(RecordingEmbedding):
        async def embed_query(self, text: str) -> list[float]:
            self.queries.append(text)
            if text != "calm step-free dining":
                return await self._delegate.embed_query(text)
            blocked_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                blocked_cancelled.set()
                raise

    embedding = BlockingEmbedding(delegate)
    scope = _scope(embedding)
    client = RecordingQdrantClient(_point(scope))
    variants = (_variants()[0], _variants()[2])

    result = await QdrantGlobalDocumentRetriever(
        client,
        embedding,
        scope,
    ).search_query_variants(variants, variant_timeout_seconds=0.02)

    assert blocked_started.is_set()
    assert blocked_cancelled.is_set()
    assert result.result_for("original").status is VariantRetrievalStatus.COMPLETE
    assert result.result_for("llm-1").status is VariantRetrievalStatus.TIMEOUT
    assert result.trace.completed_variant_ids == ("original",)
    assert result.trace.partial_failure_variant_ids == ("llm-1",)
    assert result.trace.timed_out_variant_ids == ("llm-1",)


@pytest.mark.parametrize("status_code", [401, 403])
async def test_multi_query_fails_closed_on_embedding_authorization_and_cancels_peers(
    status_code: int,
):
    delegate = DeterministicHashEmbeddingService(dimensions=64)
    original_started = asyncio.Event()
    original_cancelled = asyncio.Event()

    class AuthorizationEmbedding(RecordingEmbedding):
        async def embed_query(self, text: str) -> list[float]:
            self.queries.append(text)
            if text == "calm step-free dining":
                await original_started.wait()
                raise EmbeddingProviderError(
                    "invalid credentials",
                    provider="test",
                    retryable=False,
                    status_code=status_code,
                )
            original_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                original_cancelled.set()
                raise

    embedding = AuthorizationEmbedding(delegate)
    scope = _scope(embedding)
    client = RecordingQdrantClient(_point(scope))
    variants = (_variants()[0], _variants()[2])

    with pytest.raises(EmbeddingProviderError, match="invalid credentials") as error:
        await QdrantGlobalDocumentRetriever(
            client,
            embedding,
            scope,
        ).search_query_variants(variants)

    assert error.value.status_code == status_code
    assert original_cancelled.is_set()
    assert client.calls == []


async def test_multi_query_propagates_caller_cancellation_to_all_variants():
    delegate = DeterministicHashEmbeddingService(dimensions=64)
    all_started = asyncio.Event()
    started = 0
    cancelled = 0

    class BlockingEmbedding(RecordingEmbedding):
        async def embed_query(self, text: str) -> list[float]:
            nonlocal started, cancelled
            self.queries.append(text)
            started += 1
            if started == 2:
                all_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled += 1
                raise

    embedding = BlockingEmbedding(delegate)
    scope = _scope(embedding)
    client = RecordingQdrantClient(_point(scope))
    variants = (_variants()[0], _variants()[2])
    task = asyncio.create_task(
        QdrantGlobalDocumentRetriever(
            client,
            embedding,
            scope,
        ).search_query_variants(variants)
    )
    await asyncio.wait_for(all_started.wait(), timeout=1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cancelled == 2
    assert client.calls == []


async def test_multi_query_enforces_variant_count_identity_text_and_timeout_bounds():
    delegate = DeterministicHashEmbeddingService(dimensions=64)
    embedding = RecordingEmbedding(delegate)
    scope = _scope(embedding)
    retriever = QdrantGlobalDocumentRetriever(
        RecordingQdrantClient(_point(scope)),
        embedding,
        scope,
    )
    too_many = (
        _variants()[0],
        _variants()[1],
        *(
            GlobalQueryVariant(
                variant_id=f"llm-{index}",
                source=QueryVariantSource.LLM,
                query=f"rewrite {index}",
            )
            for index in range(4)
        ),
    )

    with pytest.raises(ValueError, match="At most 5"):
        await retriever.search_query_variants(too_many)
    with pytest.raises(ValueError, match="Exactly one original"):
        await retriever.search_query_variants((_variants()[1],))
    with pytest.raises(ValueError, match="texts must be unique"):
        await retriever.search_query_variants(
            (
                _variants()[0],
                GlobalQueryVariant(
                    variant_id="llm-duplicate",
                    source=QueryVariantSource.LLM,
                    query="  安静的无障碍餐厅  ",
                ),
            )
        )
    with pytest.raises(ValueError, match="timeout"):
        await retriever.search_query_variants((_variants()[0],), variant_timeout_seconds=0)
    with pytest.raises(ValidationError):
        GlobalQueryVariant(
            variant_id="too-long",
            source=QueryVariantSource.ORIGINAL,
            query="x" * (MAX_QUERY_VARIANT_LENGTH + 1),
        )

    assert embedding.queries == []
