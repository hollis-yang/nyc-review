from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from qdrant_client import AsyncQdrantClient

from app.domain.models import ShopCandidate
from app.rag.candidate_fusion import FusionChannel, fuse_candidates
from app.rag.embeddings import (
    DeterministicHashEmbeddingService,
    EmbeddingError,
    EmbeddingMetadata,
    EmbeddingProviderError,
)
from app.rag.global_retrieval import (
    ChannelRetrievalResult,
    GlobalDocumentHit,
    GlobalRetrievalResult,
    GlobalRetrievalScope,
    QdrantGlobalDocumentRetriever,
    RetrievalChannel,
)
from app.rag.merchant_aggregation import aggregate_merchants
from app.rag.models import RagDocument
from app.rag.qdrant_store import QdrantRagService


class FakeQdrantClient:
    def __init__(self, points_by_vector=None, *, failing_vectors=()):
        self.points_by_vector = points_by_vector or {}
        self.failing_vectors = set(failing_vectors)
        self.calls: list[dict] = []

    async def query_points(self, **kwargs):
        self.calls.append(kwargs)
        vector_name = kwargs["using"]
        if vector_name in self.failing_vectors:
            raise RuntimeError("qdrant unavailable")
        return SimpleNamespace(points=list(self.points_by_vector.get(vector_name, ())))


class FailingQueryEmbedding:
    def __init__(self, delegate: DeterministicHashEmbeddingService):
        self._delegate = delegate

    @property
    def metadata(self) -> EmbeddingMetadata:
        return self._delegate.metadata

    @property
    def dimensions(self) -> int:
        return self._delegate.dimensions

    async def embed_query(self, text: str) -> list[float]:
        raise EmbeddingError("provider failed")


def _scope(embedding: DeterministicHashEmbeddingService) -> GlobalRetrievalScope:
    return GlobalRetrievalScope(
        collection_name="m2-global-fixture",
        data_version="nyc-real-v1",
        dataset_sha256="a" * 64,
        retrieval_version="p12-rag-v1",
        embedding_identity=embedding.metadata.identity,
    )


def _point(
    scope: GlobalRetrievalScope,
    *,
    point_id: str,
    shop_id: int,
    score: float,
    category: str = "Food & Dining",
    security_test: bool = False,
    dataset_sha256: str | None = None,
    shop_external_id: str | None = None,
):
    return SimpleNamespace(
        id=point_id,
        score=score,
        payload={
            "shop_id": shop_id,
            "shop_external_id": shop_external_id or f"node:{shop_id}",
            "document_id": f"review:{point_id}",
            "source_id": f"source:{point_id}",
            "root_id": shop_id * 100,
            "content_type": "shop_review_thread",
            "document_kind": "evidence",
            "text": f"Evidence for shop {shop_id}",
            "category": category,
            "data_version": scope.data_version,
            "dataset_sha256": dataset_sha256 or scope.dataset_sha256,
            "retrieval_version": scope.retrieval_version,
            "embedding_identity": scope.embedding_identity,
            "index_scope": scope.index_scope,
            "security_test": security_test,
        },
    )


async def test_global_retriever_runs_separate_channels_with_fail_closed_scope_filter():
    embedding = DeterministicHashEmbeddingService(dimensions=64)
    scope = _scope(embedding)
    client = FakeQdrantClient(
        {
            "dense": [
                _point(
                    scope,
                    point_id="d1",
                    shop_id=101,
                    score=0.9,
                    shop_external_id="node:101",
                ),
                _point(
                    scope,
                    point_id="wrong-dataset",
                    shop_id=102,
                    score=0.8,
                    dataset_sha256="b" * 64,
                ),
                _point(
                    scope,
                    point_id="security",
                    shop_id=103,
                    score=0.7,
                    security_test=True,
                ),
            ],
            "lexical": [_point(scope, point_id="s1", shop_id=104, score=1.5)],
        }
    )
    retriever = QdrantGlobalDocumentRetriever(
        client,
        embedding,
        scope,
        document_limit=120,
    )

    result = await retriever.search_documents(
        "quiet vegan dinner",
        document_limit=75,
        category="Food & Dining",
    )

    assert [hit.shop_id for hit in result.dense.hits] == [101]
    assert result.dense.hits[0].shop_external_id == "node:101"
    assert [hit.shop_id for hit in result.sparse.hits] == [104]
    assert result.dense.returned_points == 3
    assert result.dense.rejected_points == 2
    assert result.sparse.returned_points == 1
    assert result.embedding_latency_ms >= 0
    assert result.total_latency_ms >= result.embedding_latency_ms

    calls = {call["using"]: call for call in client.calls}
    assert set(calls) == {"dense", "lexical"}
    for call in calls.values():
        assert call["collection_name"] == scope.collection_name
        assert call["limit"] == 75
        conditions = {condition.key: condition.match.value for condition in call["query_filter"].must}
        assert conditions == {
            "index_scope": scope.index_scope,
            "retrieval_version": scope.retrieval_version,
            "data_version": scope.data_version,
            "dataset_sha256": scope.dataset_sha256,
            "embedding_identity": scope.embedding_identity,
            "security_test": False,
            "category": "Food & Dining",
        }
        assert not call["query_filter"].must_not


async def test_global_retriever_preserves_sparse_when_dense_embedding_or_qdrant_fails():
    embedding = DeterministicHashEmbeddingService(dimensions=64)
    scope = _scope(embedding)
    sparse_point = _point(scope, point_id="sparse", shop_id=201, score=2.0)
    embedding_failure_client = FakeQdrantClient({"lexical": [sparse_point]})
    embedding_failure = QdrantGlobalDocumentRetriever(
        embedding_failure_client,
        FailingQueryEmbedding(embedding),
        scope,
    )

    result = await embedding_failure.search_documents("late night cafe")

    assert result.dense.available is False
    assert result.dense.fallback_reason == "embedding-error"
    assert [hit.shop_id for hit in result.sparse.hits] == [201]
    assert [call["using"] for call in embedding_failure_client.calls] == ["lexical"]

    qdrant_failure_client = FakeQdrantClient(
        {"lexical": [sparse_point]},
        failing_vectors={"dense"},
    )
    qdrant_failure = QdrantGlobalDocumentRetriever(
        qdrant_failure_client,
        embedding,
        scope,
    )
    result = await qdrant_failure.search_documents("late night cafe")

    assert result.dense.available is False
    assert result.dense.fallback_reason == "qdrant-error"
    assert result.sparse.available is True
    assert [hit.shop_id for hit in result.sparse.hits] == [201]


async def test_global_retriever_fails_closed_on_provider_authorization_errors():
    embedding = DeterministicHashEmbeddingService(dimensions=64)
    scope = _scope(embedding)

    class UnauthorizedEmbedding(FailingQueryEmbedding):
        async def embed_query(self, text: str) -> list[float]:
            raise EmbeddingProviderError(
                "invalid embedding credentials",
                provider="test",
                retryable=False,
                status_code=401,
            )

    with pytest.raises(EmbeddingProviderError, match="invalid embedding credentials"):
        await QdrantGlobalDocumentRetriever(
            FakeQdrantClient(),
            UnauthorizedEmbedding(embedding),
            scope,
        ).search_documents("quiet dinner")

    class UnauthorizedQdrant(FakeQdrantClient):
        async def query_points(self, **kwargs):
            error = RuntimeError("invalid qdrant credentials")
            error.status_code = 403
            raise error

    with pytest.raises(RuntimeError, match="invalid qdrant credentials"):
        await QdrantGlobalDocumentRetriever(
            UnauthorizedQdrant(),
            embedding,
            scope,
        ).search_documents("quiet dinner")


async def test_global_retriever_cancels_peer_channel_after_authorization_failure():
    embedding = DeterministicHashEmbeddingService(dimensions=64)
    scope = _scope(embedding)
    sparse_started = asyncio.Event()
    sparse_cancelled = asyncio.Event()

    class PartiallyUnauthorizedQdrant(FakeQdrantClient):
        async def query_points(self, **kwargs):
            if kwargs["using"] == "dense":
                await sparse_started.wait()
                error = RuntimeError("invalid qdrant credentials")
                error.status_code = 401
                raise error
            sparse_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                sparse_cancelled.set()
                raise

    with pytest.raises(RuntimeError, match="invalid qdrant credentials"):
        await QdrantGlobalDocumentRetriever(
            PartiallyUnauthorizedQdrant(),
            embedding,
            scope,
        ).search_documents("quiet dinner")

    assert sparse_cancelled.is_set()


async def test_global_retriever_rejects_ambiguous_safety_or_merchant_identity_payloads():
    embedding = DeterministicHashEmbeddingService(dimensions=64)
    scope = _scope(embedding)
    valid = _point(scope, point_id="valid", shop_id=1, score=1.0)
    malformed = []
    for index, security_value in enumerate((None, 0, "false"), start=2):
        point = _point(scope, point_id=f"security-{index}", shop_id=index, score=0.5)
        point.payload["security_test"] = security_value
        malformed.append(point)
    missing_security = _point(scope, point_id="missing-security", shop_id=5, score=0.4)
    del missing_security.payload["security_test"]
    missing_identity = _point(scope, point_id="missing-identity", shop_id=6, score=0.3)
    del missing_identity.payload["shop_external_id"]
    client = FakeQdrantClient(
        {"dense": [valid, *malformed, missing_security, missing_identity]}
    )

    result = await QdrantGlobalDocumentRetriever(
        client,
        embedding,
        scope,
    ).search_documents("quiet dinner")

    assert [hit.shop_id for hit in result.dense.hits] == [1]
    assert result.dense.rejected_points == 5


async def test_global_retriever_matches_the_existing_qdrant_index_scope_contract():
    client = AsyncQdrantClient(location=":memory:")
    embedding = DeterministicHashEmbeddingService(dimensions=64)
    current_sha = "c" * 64
    other_sha = "d" * 64
    current = QdrantRagService(
        client=client,
        embeddings=embedding,
        collection_name="m2-real-qdrant-contract",
        dataset_sha256=current_sha,
        retrieval_version="p12-rag-v1",
    )
    other = QdrantRagService(
        client=client,
        embeddings=embedding,
        collection_name="m2-real-qdrant-contract",
        dataset_sha256=other_sha,
        retrieval_version="p12-rag-v1",
    )
    await current.sync(
        [
            RagDocument(
                document_id="review:current",
                shop_id=301,
                content_type="shop_review",
                source_id="source:current",
                text="A quiet vegan dining room.",
                category="Food & Dining",
                data_version="nyc-real-v1",
                shop_external_id="node:301",
            ),
            RagDocument(
                document_id="review:security",
                shop_id=302,
                content_type="shop_review",
                source_id="source:security",
                text="A quiet security fixture.",
                category="Food & Dining",
                data_version="nyc-real-v1",
                shop_external_id="node:302",
                security_test=True,
            ),
        ],
        data_version="nyc-real-v1",
    )
    await other.sync(
        [
            RagDocument(
                document_id="review:other",
                shop_id=303,
                content_type="shop_review",
                source_id="source:other",
                text="A quiet record from another corpus.",
                category="Food & Dining",
                data_version="nyc-real-v1",
                shop_external_id="node:303",
            )
        ],
        data_version="nyc-real-v1",
    )
    retriever = QdrantGlobalDocumentRetriever(
        client,
        embedding,
        GlobalRetrievalScope(
            collection_name="m2-real-qdrant-contract",
            data_version="nyc-real-v1",
            dataset_sha256=current_sha,
            retrieval_version="p12-rag-v1",
            embedding_identity=embedding.metadata.identity,
        ),
    )

    result = await retriever.search_documents(
        "quiet vegan dining",
        category="Food & Dining",
    )

    assert {hit.shop_id for hit in result.dense.hits} == {301}
    assert {hit.shop_id for hit in result.sparse.hits} == {301}
    await client.close()


def _hit(
    *,
    point_id: str,
    shop_id: int,
    channel: RetrievalChannel,
    rank: int,
    score: float,
    source_id: str | None = None,
    root_id: int | None = None,
    text: str | None = None,
    content_type: str = "shop_review_thread",
    document_kind: str = "evidence",
    shop_external_id: str | None = None,
) -> GlobalDocumentHit:
    return GlobalDocumentHit(
        point_id=point_id,
        shop_id=shop_id,
        shop_external_id=shop_external_id or f"node:{shop_id}",
        channel=channel,
        rank=rank,
        score=score,
        document_id=f"document:{point_id}",
        source_id=source_id or f"source:{point_id}",
        root_id=root_id,
        content_type=content_type,
        document_kind=document_kind,
        text=text or f"Text for {point_id}",
    )


def _retrieval_result(
    dense_hits: list[GlobalDocumentHit],
    sparse_hits: list[GlobalDocumentHit] | None = None,
) -> GlobalRetrievalResult:
    return GlobalRetrievalResult(
        dense=ChannelRetrievalResult(
            channel=RetrievalChannel.DENSE,
            hits=tuple(dense_hits),
            returned_points=len(dense_hits),
        ),
        sparse=ChannelRetrievalResult(
            channel=RetrievalChannel.SPARSE,
            hits=tuple(sparse_hits or []),
            returned_points=len(sparse_hits or []),
        ),
    )


def test_merchant_aggregation_deduplicates_each_key_caps_documents_and_is_stable():
    hits = [
        _hit(
            point_id="p1",
            shop_id=1,
            channel=RetrievalChannel.DENSE,
            rank=1,
            score=0.9,
            source_id="source-1",
            root_id=10,
            text="Calm room",
        ),
        _hit(
            point_id="p1",
            shop_id=1,
            channel=RetrievalChannel.DENSE,
            rank=2,
            score=0.8,
            source_id="source-2",
            root_id=11,
            text="Different point duplicate",
        ),
        _hit(
            point_id="p2",
            shop_id=1,
            channel=RetrievalChannel.DENSE,
            rank=3,
            score=0.7,
            source_id="source-1",
            root_id=12,
            text="Different source duplicate",
        ),
        _hit(
            point_id="p3",
            shop_id=1,
            channel=RetrievalChannel.DENSE,
            rank=4,
            score=0.6,
            source_id="source-3",
            root_id=10,
            text="Different root duplicate",
        ),
        _hit(
            point_id="p4",
            shop_id=1,
            channel=RetrievalChannel.DENSE,
            rank=5,
            score=0.55,
            source_id="source-4",
            root_id=14,
            text="  CALM   room ",
        ),
        _hit(
            point_id="p5",
            shop_id=1,
            channel=RetrievalChannel.DENSE,
            rank=6,
            score=0.5,
            source_id="source-5",
            root_id=15,
            text="Second unique document",
        ),
        _hit(
            point_id="p6",
            shop_id=1,
            channel=RetrievalChannel.DENSE,
            rank=7,
            score=0.4,
            source_id="source-6",
            root_id=16,
            text="Capped unique document",
        ),
        _hit(
            point_id="p7",
            shop_id=2,
            channel=RetrievalChannel.DENSE,
            rank=8,
            score=0.3,
            root_id=20,
        ),
    ]

    aggregated = aggregate_merchants(
        _retrieval_result(list(reversed(hits))),
        documents_per_merchant=2,
    )
    repeated = aggregate_merchants(
        _retrieval_result(hits),
        documents_per_merchant=2,
    )

    assert aggregated == repeated
    dense = aggregated.ranking(RetrievalChannel.DENSE)
    assert [merchant.shop_id for merchant in dense.merchants] == [1, 2]
    first = dense.merchants[0]
    assert [item.point_id for item in first.retained_documents] == ["p1", "p5"]
    assert first.best_document_rank == 1
    assert first.best_score == pytest.approx(0.9)
    assert first.top_k_mean == pytest.approx(0.7)
    assert aggregated.unique_merchants == 2
    assert aggregated.suppression.model_dump() == {
        "duplicate_points": 1,
        "duplicate_sources": 1,
        "duplicate_roots": 1,
        "duplicate_excerpts": 1,
        "document_cap": 1,
    }
    assert aggregated.suppression.duplicate_documents == 4


def test_merchant_aggregation_prioritizes_facts_but_keeps_original_best_rank():
    hits = [
        _hit(
            point_id="top-review",
            shop_id=1,
            channel=RetrievalChannel.DENSE,
            rank=1,
            score=0.9,
        ),
        _hit(
            point_id="second-review",
            shop_id=1,
            channel=RetrievalChannel.DENSE,
            rank=2,
            score=0.8,
        ),
        _hit(
            point_id="identity-fact",
            shop_id=1,
            channel=RetrievalChannel.DENSE,
            rank=10,
            score=0.2,
            content_type="shop_identity_fact",
            document_kind="fact",
        ),
    ]

    aggregated = aggregate_merchants(
        _retrieval_result(hits),
        documents_per_merchant=2,
    )

    merchant = aggregated.ranking(RetrievalChannel.DENSE).merchants[0]
    assert merchant.best_document_rank == 1
    assert merchant.top_k_mean == pytest.approx(0.85)
    assert [item.point_id for item in merchant.retained_documents] == [
        "identity-fact",
        "top-review",
    ]
    assert aggregated.suppression.document_cap == 1


def test_merchant_aggregation_all_duplicate_hits_still_retain_one_document():
    first = _hit(
        point_id="same",
        shop_id=1,
        channel=RetrievalChannel.DENSE,
        rank=1,
        score=0.9,
        source_id="same-source",
        root_id=1,
        text="same excerpt",
    )
    duplicate = first.model_copy(update={"rank": 2, "score": 0.8})

    aggregated = aggregate_merchants(_retrieval_result([duplicate, first]))

    merchant = aggregated.ranking(RetrievalChannel.DENSE).merchants[0]
    assert merchant.best_document_rank == 1
    assert [item.point_id for item in merchant.retained_documents] == ["same"]
    assert aggregated.suppression.duplicate_points == 1


def test_merchant_aggregation_fails_closed_on_conflicting_external_identities():
    dense_hits = [
        _hit(
            point_id="conflict-dense",
            shop_id=1,
            shop_external_id="node:one",
            channel=RetrievalChannel.DENSE,
            rank=1,
            score=0.9,
        ),
        _hit(
            point_id="valid-dense",
            shop_id=2,
            shop_external_id="node:two",
            channel=RetrievalChannel.DENSE,
            rank=2,
            score=0.8,
        ),
    ]
    sparse_hits = [
        _hit(
            point_id="conflict-sparse",
            shop_id=1,
            shop_external_id="node:other",
            channel=RetrievalChannel.SPARSE,
            rank=1,
            score=2.0,
        ),
        _hit(
            point_id="valid-sparse",
            shop_id=2,
            shop_external_id="node:two",
            channel=RetrievalChannel.SPARSE,
            rank=2,
            score=1.0,
        ),
    ]

    aggregated = aggregate_merchants(_retrieval_result(dense_hits, sparse_hits))

    assert aggregated.identity_conflict_shop_ids == (1,)
    assert aggregated.identity_conflicts == 1
    assert aggregated.unique_merchants == 1
    assert [merchant.shop_id for merchant in aggregated.ranking(RetrievalChannel.DENSE).merchants] == [2]
    assert [merchant.shop_id for merchant in aggregated.ranking(RetrievalChannel.SPARSE).merchants] == [2]
    assert aggregated.ranking(RetrievalChannel.DENSE).rejected_documents == 1
    assert aggregated.ranking(RetrievalChannel.SPARSE).rejected_documents == 1
    dense_signal = aggregated.ranking(RetrievalChannel.DENSE).merchants[0]
    assert dense_signal.shop_external_ids == ("node:two",)
    assert dense_signal.retained_documents[0].shop_external_id == "node:two"
    assert aggregated.expected_external_id(2) == "node:two"
    with pytest.raises(ValueError, match="conflicting external identities"):
        aggregated.expected_external_id(1)


def _candidate(
    shop_id: int,
    name: str,
    *,
    external_id: str | None = None,
    score: float = 4.5,
) -> ShopCandidate:
    return ShopCandidate(
        shop_id=shop_id,
        name=name,
        category="Food & Dining",
        neighborhood="Midtown",
        latitude=40.75,
        longitude=-73.98,
        score=score,
        external_id=external_id or f"node:{shop_id}",
    )


def test_candidate_fusion_uses_merchant_rrf_deterministic_ties_and_brand_cap():
    dense_hits = [
        _hit(
            point_id=f"dense-{shop_id}",
            shop_id=shop_id,
            channel=RetrievalChannel.DENSE,
            rank=rank,
            score=1.0 / rank,
        )
        for rank, shop_id in enumerate((2, 3, 4, 5, 6), start=1)
    ]
    sparse_hits = [
        _hit(
            point_id=f"sparse-{shop_id}",
            shop_id=shop_id,
            channel=RetrievalChannel.SPARSE,
            rank=rank,
            score=5.0 - rank,
        )
        for rank, shop_id in enumerate((2, 3, 4, 5, 6), start=1)
    ]
    merchants = aggregate_merchants(_retrieval_result(dense_hits, sparse_hits))
    structured = [_candidate(1, "Structured One"), _candidate(2, "Overlap Two")]
    hydrated = {
        6: _candidate(6, "Other Merchant"),
        5: _candidate(5, "Nova Queens"),
        4: _candidate(4, "Nova Brooklyn"),
        3: _candidate(3, "Nova NYC"),
    }

    result = fuse_candidates(
        structured,
        merchants,
        hydrated,
        limit=5,
        rrf_k=60,
        brand_cap=2,
    )
    repeated = fuse_candidates(
        structured,
        merchants,
        dict(reversed(list(hydrated.items()))),
        limit=5,
        rrf_k=60,
        brand_cap=2,
    )

    assert result == repeated
    assert [candidate.shop_id for candidate in result.candidates] == [2, 3, 4, 6, 1]
    assert result.stats.model_dump() == {
        "structured_candidates": 2,
        "global_merchants": 5,
        "fusion_candidates": 6,
        "structured_only_merchants": 1,
        "qdrant_only_merchants": 4,
        "overlap_merchants": 1,
        "missing_hydrated_candidates": 0,
        "duplicate_shop_ids_suppressed": 0,
        "duplicate_merchants_suppressed": 0,
        "duplicate_brands_suppressed": 1,
        "returned_candidates": 5,
    }
    assert result.ranked_merchants[0].shop_id == 2
    assert [rank.channel for rank in result.ranked_merchants[0].source_ranks] == [
        FusionChannel.STRUCTURED,
        FusionChannel.DENSE,
        FusionChannel.SPARSE,
    ]


def test_candidate_fusion_drops_missing_hydration_and_duplicate_external_merchants():
    hits = [
        _hit(
            point_id=f"dense-{shop_id}",
            shop_id=shop_id,
            channel=RetrievalChannel.DENSE,
            rank=rank,
            score=1.0,
        )
        for rank, shop_id in enumerate((10, 11, 12), start=1)
    ]
    merchants = aggregate_merchants(_retrieval_result(hits))
    hydrated = {
        10: _candidate(10, "First", external_id="node:shared"),
        11: _candidate(11, "Second", external_id="node:shared"),
    }

    result = fuse_candidates([], merchants, hydrated, limit=3)

    assert [candidate.shop_id for candidate in result.candidates] == [10]
    assert result.stats.missing_hydrated_candidates == 1
    assert result.stats.duplicate_merchants_suppressed == 1

    with pytest.raises(ValueError, match="keys must match"):
        fuse_candidates([], merchants, {99: hydrated[10]}, limit=3)


def test_candidate_fusion_backfills_brand_overflow_to_preserve_result_limit():
    hits = [
        _hit(
            point_id=f"brand-{shop_id}",
            shop_id=shop_id,
            channel=RetrievalChannel.DENSE,
            rank=rank,
            score=1.0 / rank,
        )
        for rank, shop_id in enumerate((21, 22, 23), start=1)
    ]
    merchants = aggregate_merchants(_retrieval_result(hits))
    hydrated = {
        21: _candidate(21, "Nova NYC"),
        22: _candidate(22, "Nova Brooklyn"),
        23: _candidate(23, "Nova Queens"),
    }

    result = fuse_candidates(
        [],
        merchants,
        hydrated,
        limit=3,
        brand_cap=2,
    )

    assert [candidate.shop_id for candidate in result.candidates] == [21, 22, 23]
    assert result.stats.duplicate_brands_suppressed == 1
