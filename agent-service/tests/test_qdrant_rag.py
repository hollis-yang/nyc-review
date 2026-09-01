from types import SimpleNamespace

import pytest
from qdrant_client import AsyncQdrantClient, models

from app.domain.models import CandidateSet, ShopCandidate, UserConstraints
from app.rag.embeddings import (
    DeterministicHashEmbeddingService,
    EmbeddingError,
    EmbeddingMetadata,
    EmbeddingUsage,
)
from app.rag.models import RagDocument
from app.rag.qdrant_store import (
    REQUIRED_PAYLOAD_INDEXES,
    QdrantRagService,
    _point_id,
    _with_content_hash,
)


class RecordingEmbeddingService:
    def __init__(self, dimensions: int = 64, *, version: str = "recording-v1"):
        self._delegate = DeterministicHashEmbeddingService(
            dimensions=dimensions,
            version=version,
        )
        self.document_batches: list[list[str]] = []
        self.queries: list[str] = []
        self.fail_documents = False
        self.fail_queries = False

    @property
    def metadata(self) -> EmbeddingMetadata:
        return self._delegate.metadata

    @property
    def dimensions(self) -> int:
        return self._delegate.dimensions

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        if self.fail_queries:
            raise EmbeddingError("embedding failed")
        return await self._delegate.embed_query(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_batches.append(list(texts))
        if self.fail_documents:
            raise EmbeddingError("embedding failed")
        return await self._delegate.embed_documents(texts)

    def usage_snapshot(self) -> EmbeddingUsage:
        return self._delegate.usage_snapshot()

    def clear_query_cache(self) -> None:
        self._delegate.clear_query_cache()

    async def aclose(self) -> None:
        await self._delegate.aclose()


class VerifyOnlyQdrantClient:
    init_options = {"url": "http://qdrant:6333"}

    def __init__(
        self,
        records=(),
        *,
        collection_exists: bool = True,
        payload_schema=None,
    ):
        self.records = list(records)
        self.collection_is_present = collection_exists
        self.payload_schema = (
            dict(REQUIRED_PAYLOAD_INDEXES) if payload_schema is None else payload_schema
        )
        self.write_calls: list[str] = []

    async def collection_exists(self, _collection_name):
        return self.collection_is_present

    async def get_collection(self, _collection_name):
        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors={
                        "dense": models.VectorParams(
                            size=64,
                            distance=models.Distance.COSINE,
                        )
                    },
                    sparse_vectors={
                        "lexical": models.SparseVectorParams(modifier=models.Modifier.IDF)
                    },
                )
            ),
            payload_schema=self.payload_schema,
        )

    async def scroll(self, **_kwargs):
        return self.records, None

    async def create_collection(self, **_kwargs):
        self._reject_write("create_collection")

    async def create_payload_index(self, **_kwargs):
        self._reject_write("create_payload_index")

    async def delete_collection(self, _collection_name):
        self._reject_write("delete_collection")

    async def upsert(self, **_kwargs):
        self._reject_write("upsert")

    async def delete(self, **_kwargs):
        self._reject_write("delete")

    def _reject_write(self, operation: str) -> None:
        self.write_calls.append(operation)
        raise AssertionError(f"verify mode attempted Qdrant write: {operation}")


def _verify_record(
    document: RagDocument,
    embeddings: RecordingEmbeddingService,
    *,
    dataset_sha256: str | None = None,
    retrieval_version: str = "p12-rag-v1",
):
    bound = (
        document
        if dataset_sha256 is None or document.dataset_sha256 == dataset_sha256
        else document.model_copy(update={"dataset_sha256": dataset_sha256})
    )
    normalized = _with_content_hash(bound)
    return SimpleNamespace(
        id=_point_id(normalized, embeddings.metadata.identity, retrieval_version),
        payload={
            "content_sha256": normalized.content_sha256,
            "document_id": normalized.document_id,
        },
    )


async def test_qdrant_rag_filters_by_shop_and_returns_traceable_citations():
    client = AsyncQdrantClient(location=":memory:")
    rag = QdrantRagService(
        client=client,
        embeddings=DeterministicHashEmbeddingService(dimensions=64),
        collection_name="test_nyc_review_content",
    )
    await rag.index(
        [
            RagDocument(
                document_id="review:1",
                shop_id=101,
                content_type="shop_review",
                source_id="shop_review:1",
                text="The dining room was quiet and the vegan options were clearly marked.",
                evidence_tags=["quiet", "vegan_options"],
            ),
            RagDocument(
                document_id="review:2",
                shop_id=102,
                content_type="shop_review",
                source_id="shop_review:2",
                text="The music was loud and the room became crowded.",
                evidence_tags=["late_night"],
            ),
        ]
    )
    candidates = CandidateSet(
        candidates=[
            ShopCandidate(
                shop_id=101,
                name="Quiet Fixture",
                category="Food & Dining",
                neighborhood="Midtown",
                latitude=40.76,
                longitude=-73.98,
                avg_price_cents=4_000,
                score=4.7,
                tags=["quiet", "vegan_options"],
            ),
            ShopCandidate(
                shop_id=102,
                name="Loud Fixture",
                category="Bars & Nightlife",
                neighborhood="Midtown",
                latitude=40.75,
                longitude=-73.99,
                avg_price_cents=3_000,
                score=4.2,
                tags=["late_night"],
            ),
        ]
    )

    result = await rag.retrieve(
        UserConstraints(
            query="quiet vegan dinner",
            desired_tags=["quiet", "vegan_options"],
        ),
        candidates,
    )

    by_shop = {item.shop_id: item for item in result.evidence}
    assert by_shop[101].supported_tags == ["quiet", "vegan_options"]
    assert by_shop[101].citations[0].source_id == "shop_review:1"
    assert by_shop[101].citations[0].untrusted_content is True
    assert all(citation.shop_id == 102 for citation in by_shop[102].citations)
    await client.close()


async def test_qdrant_rag_filters_same_shop_id_by_data_version():
    client = AsyncQdrantClient(location=":memory:")
    rag = QdrantRagService(
        client=client,
        embeddings=DeterministicHashEmbeddingService(dimensions=64),
        collection_name="test_nyc_review_versioned_content",
    )
    await rag.index(
        [
            RagDocument(
                document_id="review:1",
                shop_id=101,
                content_type="shop_review",
                source_id="shop_review:v1:1",
                text="Old dataset evidence.",
                data_version="nyc-mock-v0",
            ),
            RagDocument(
                document_id="review:1",
                shop_id=101,
                content_type="shop_review",
                source_id="shop_review:v2:1",
                text="Current dataset evidence.",
                data_version="nyc-mock-v1",
            ),
        ]
    )
    result = await rag.retrieve(
        UserConstraints(query="current evidence"),
        CandidateSet(
            candidates=[
                ShopCandidate(
                    shop_id=101,
                    name="Versioned Fixture",
                    category="Food & Dining",
                    neighborhood="Midtown",
                    latitude=40.76,
                    longitude=-73.98,
                    avg_price_cents=4000,
                    score=4.7,
                    data_version="nyc-mock-v1",
                )
            ]
        ),
    )

    assert [citation.source_id for citation in result.evidence[0].citations] == ["shop_review:v2:1"]
    assert (await client.count("test_nyc_review_versioned_content", exact=True)).count == 2
    await client.close()


async def test_qdrant_rag_isolates_same_version_and_document_id_by_dataset_sha256():
    client = AsyncQdrantClient(location=":memory:")
    collection = "test_nyc_review_dataset_hash_content"
    old_rag = QdrantRagService(
        client=client,
        embeddings=DeterministicHashEmbeddingService(dimensions=64),
        collection_name=collection,
        dataset_sha256="a" * 64,
    )
    current_rag = QdrantRagService(
        client=client,
        embeddings=DeterministicHashEmbeddingService(dimensions=64),
        collection_name=collection,
        dataset_sha256="b" * 64,
    )
    old = RagDocument(
        document_id="review:1",
        shop_id=101,
        content_type="shop_review",
        source_id="shop_review:old:1",
        text="Evidence from the old dataset.",
        data_version="nyc-real-v1-same",
    )
    current = old.model_copy(
        update={
            "source_id": "shop_review:current:1",
            "text": "Evidence from the current dataset.",
        }
    )

    await old_rag.sync([old], data_version="nyc-real-v1-same")
    await current_rag.sync([current], data_version="nyc-real-v1-same")
    result = await current_rag.retrieve(
        UserConstraints(query="current dataset evidence"),
        CandidateSet(
            candidates=[
                ShopCandidate(
                    shop_id=101,
                    name="Dataset Fixture",
                    category="Food & Dining",
                    neighborhood="Midtown",
                    latitude=40.76,
                    longitude=-73.98,
                    data_version="nyc-real-v1-same",
                )
            ]
        ),
    )

    assert [citation.source_id for citation in result.evidence[0].citations] == ["shop_review:current:1"]
    assert result.evidence[0].citations[0].dataset_sha256 == "b" * 64
    assert (await client.count(collection, exact=True)).count == 2
    await client.close()


async def test_qdrant_sync_batches_embeddings_reuses_unchanged_points_and_deletes_stale_last():
    client = AsyncQdrantClient(location=":memory:")
    embeddings = RecordingEmbeddingService()
    rag = QdrantRagService(
        client=client,
        embeddings=embeddings,
        collection_name="test_incremental_content",
        index_batch_size=2,
    )
    documents = [
        RagDocument(
            document_id=f"review:{index}",
            shop_id=100 + index,
            content_type="shop_review_thread",
            source_id=f"shop_review_thread:{index}",
            text=f"Synthetic review thread {index}",
            data_version="nyc-real-v1",
            root_id=index,
        )
        for index in range(1, 4)
    ]

    first = await rag.sync(documents, data_version="nyc-real-v1")
    second = await rag.sync(documents, data_version="nyc-real-v1")
    changed = documents[1].model_copy(update={"text": "Changed synthetic review thread"})
    third = await rag.sync([documents[0], changed], data_version="nyc-real-v1")

    assert first.as_metadata() == {"total": 3, "upserted": 3, "unchanged": 0, "deleted": 0}
    assert second.as_metadata() == {"total": 3, "upserted": 0, "unchanged": 3, "deleted": 0}
    assert third.as_metadata() == {"total": 2, "upserted": 1, "unchanged": 1, "deleted": 1}
    assert [len(batch) for batch in embeddings.document_batches] == [2, 1, 1]
    assert (await client.count("test_incremental_content", exact=True)).count == 2
    await client.close()


async def test_qdrant_sync_does_not_delete_stale_points_when_embedding_fails():
    client = AsyncQdrantClient(location=":memory:")
    embeddings = RecordingEmbeddingService()
    rag = QdrantRagService(
        client=client,
        embeddings=embeddings,
        collection_name="test_safe_stale_deletion",
        index_batch_size=2,
    )
    first = RagDocument(
        document_id="review:1",
        shop_id=101,
        content_type="shop_review_thread",
        source_id="shop_review_thread:1",
        text="Original thread one",
        data_version="nyc-real-v1",
    )
    second = RagDocument(
        document_id="review:2",
        shop_id=102,
        content_type="shop_review_thread",
        source_id="shop_review_thread:2",
        text="Original thread two",
        data_version="nyc-real-v1",
    )
    await rag.sync([first, second], data_version="nyc-real-v1")
    embeddings.fail_documents = True

    with pytest.raises(RuntimeError, match="embedding failed"):
        await rag.sync(
            [first.model_copy(update={"text": "Changed thread one"})],
            data_version="nyc-real-v1",
        )

    assert (await client.count("test_safe_stale_deletion", exact=True)).count == 2
    await client.close()


async def test_qdrant_verify_accepts_an_exact_corpus_without_embeddings_or_writes():
    embeddings = RecordingEmbeddingService()
    embeddings.fail_documents = True
    dataset_sha256 = "e" * 64
    documents = [
        RagDocument(
            document_id=f"review:verify:{index}",
            shop_id=200 + index,
            content_type="shop_review_thread",
            source_id=f"shop_review_thread:verify:{index}",
            text=f"Verified review thread {index}",
            data_version="nyc-real-v1",
        )
        for index in range(2)
    ]
    client = VerifyOnlyQdrantClient(
        [
            _verify_record(
                document,
                embeddings,
                dataset_sha256=dataset_sha256,
            )
            for document in documents
        ]
    )
    rag = QdrantRagService(
        client=client,
        embeddings=embeddings,
        collection_name="prebuilt_verified_content",
        dataset_sha256=dataset_sha256,
        sync_mode="verify",
    )

    stats = await rag.sync(documents, data_version="nyc-real-v1")

    assert stats.as_metadata() == {
        "total": 2,
        "upserted": 0,
        "unchanged": 2,
        "deleted": 0,
    }
    assert embeddings.document_batches == []
    assert client.write_calls == []


@pytest.mark.parametrize(
    ("case_name", "expected_mismatch"),
    [
        ("missing", "missing=1"),
        ("changed", "changed=1"),
        ("stale", "stale=1"),
    ],
)
async def test_qdrant_verify_fails_closed_for_corpus_drift_without_embeddings_or_writes(
    case_name,
    expected_mismatch,
):
    embeddings = RecordingEmbeddingService()
    embeddings.fail_documents = True
    indexed_documents = [
        RagDocument(
            document_id=f"review:drift:{index}",
            shop_id=300 + index,
            content_type="shop_review_thread",
            source_id=f"shop_review_thread:drift:{index}",
            text=f"Indexed review thread {index}",
            data_version="nyc-real-v1",
        )
        for index in range(2)
    ]
    desired_documents = list(indexed_documents)
    if case_name == "missing":
        desired_documents.append(
            RagDocument(
                document_id="review:drift:missing",
                shop_id=399,
                content_type="shop_review_thread",
                source_id="shop_review_thread:drift:missing",
                text="This desired point is missing from Qdrant.",
                data_version="nyc-real-v1",
            )
        )
    elif case_name == "changed":
        desired_documents[0] = desired_documents[0].model_copy(
            update={"text": "This desired content changed after indexing."}
        )
    else:
        desired_documents.pop()

    client = VerifyOnlyQdrantClient(
        [_verify_record(document, embeddings) for document in indexed_documents]
    )
    rag = QdrantRagService(
        client=client,
        embeddings=embeddings,
        collection_name="drifted_prebuilt_content",
        sync_mode="verify",
    )

    with pytest.raises(ValueError, match=expected_mismatch):
        await rag.sync(desired_documents, data_version="nyc-real-v1")

    assert embeddings.document_batches == []
    assert client.write_calls == []


@pytest.mark.parametrize("schema_failure", ["collection", "payload_index"])
async def test_qdrant_verify_requires_prebuilt_collection_and_payload_indexes_without_writes(
    schema_failure,
):
    payload_schema = dict(REQUIRED_PAYLOAD_INDEXES)
    if schema_failure == "payload_index":
        payload_schema.pop("shop_id")
    client = VerifyOnlyQdrantClient(
        collection_exists=schema_failure != "collection",
        payload_schema=payload_schema,
    )
    rag = QdrantRagService(
        client=client,
        embeddings=RecordingEmbeddingService(),
        collection_name="required_prebuilt_content",
        sync_mode="verify",
    )
    expected = "already exist" if schema_failure == "collection" else "payload index 'shop_id'"

    with pytest.raises(ValueError, match=expected):
        await rag.sync([], data_version="nyc-real-v1")

    assert client.write_calls == []


async def test_qdrant_verify_rejects_direct_indexing_before_any_qdrant_call():
    client = VerifyOnlyQdrantClient()
    rag = QdrantRagService(
        client=client,
        embeddings=RecordingEmbeddingService(),
        collection_name="read_only_content",
        sync_mode="verify",
    )

    with pytest.raises(RuntimeError, match="read-only"):
        await rag.index([])

    assert client.write_calls == []


async def test_qdrant_sync_scopes_payload_and_reuse_by_embedding_identity():
    client = AsyncQdrantClient(location=":memory:")
    collection = "test_embedding_identity_scope"
    first_embeddings = RecordingEmbeddingService(version="embedding-v1")
    second_embeddings = RecordingEmbeddingService(version="embedding-v2")
    first_rag = QdrantRagService(
        client=client,
        embeddings=first_embeddings,
        collection_name=collection,
        dataset_sha256="c" * 64,
    )
    second_rag = QdrantRagService(
        client=client,
        embeddings=second_embeddings,
        collection_name=collection,
        dataset_sha256="c" * 64,
    )
    document = RagDocument(
        document_id="review:identity",
        shop_id=701,
        content_type="shop_review_thread",
        source_id="shop_review_thread:identity",
        text="Quiet tables and clearly marked vegan options.",
        data_version="nyc-real-v1",
    )

    first = await first_rag.sync([document], data_version="nyc-real-v1")
    second = await second_rag.sync([document], data_version="nyc-real-v1")
    repeated = await second_rag.sync([document], data_version="nyc-real-v1")
    records, _ = await client.scroll(
        collection_name=collection,
        limit=10,
        with_payload=True,
        with_vectors=False,
    )
    payloads = [record.payload or {} for record in records]

    assert first.as_metadata() == {"total": 1, "upserted": 1, "unchanged": 0, "deleted": 0}
    assert second.as_metadata() == {"total": 1, "upserted": 1, "unchanged": 0, "deleted": 0}
    assert repeated.as_metadata() == {"total": 1, "upserted": 0, "unchanged": 1, "deleted": 0}
    assert len(first_embeddings.document_batches) == 1
    assert len(second_embeddings.document_batches) == 1
    assert {payload["embedding_identity"] for payload in payloads} == {
        first_embeddings.metadata.identity,
        second_embeddings.metadata.identity,
    }
    assert {payload["embedding_version"] for payload in payloads} == {
        "embedding-v1",
        "embedding-v2",
    }
    assert len({payload["index_scope"] for payload in payloads}) == 2
    assert (await client.count(collection, exact=True)).count == 2
    await client.close()


async def test_qdrant_sync_scopes_points_and_fact_lookup_by_retrieval_version():
    client = AsyncQdrantClient(location=":memory:")
    collection = "test_retrieval_version_scope"
    embeddings = RecordingEmbeddingService()
    dataset_sha256 = "d" * 64
    old_rag = QdrantRagService(
        client=client,
        embeddings=embeddings,
        collection_name=collection,
        dataset_sha256=dataset_sha256,
        retrieval_version="retrieval-v1",
    )
    current_rag = QdrantRagService(
        client=client,
        embeddings=embeddings,
        collection_name=collection,
        dataset_sha256=dataset_sha256,
        retrieval_version="retrieval-v2",
    )
    old_fact = RagDocument(
        document_id="shop_identity_fact:702",
        shop_id=702,
        content_type="shop_identity",
        document_kind="fact",
        source_id="shop_identity:old:702",
        text="Old retrieval identity fact.",
        data_version="nyc-real-v1",
    )
    current_fact = old_fact.model_copy(
        update={
            "source_id": "shop_identity:current:702",
            "text": "Current retrieval identity fact.",
        }
    )

    old_stats = await old_rag.sync([old_fact], data_version="nyc-real-v1")
    current_stats = await current_rag.sync([current_fact], data_version="nyc-real-v1")
    candidate = ShopCandidate(
        shop_id=702,
        name="Versioned Fact Fixture",
        category="Food & Dining",
        neighborhood="Midtown",
        latitude=40.75,
        longitude=-73.98,
        data_version="nyc-real-v1",
    )
    old_result = await old_rag.retrieve(
        UserConstraints(query="old retrieval identity"),
        CandidateSet(candidates=[candidate]),
    )
    current_result = await current_rag.retrieve(
        UserConstraints(query="current retrieval identity"),
        CandidateSet(candidates=[candidate]),
    )
    records, _ = await client.scroll(
        collection_name=collection,
        limit=10,
        with_payload=True,
        with_vectors=False,
    )

    assert old_stats.upserted_documents == 1
    assert current_stats.upserted_documents == 1
    assert (await client.count(collection, exact=True)).count == 2
    assert {str((record.payload or {})["retrieval_version"]) for record in records} == {
        "retrieval-v1",
        "retrieval-v2",
    }
    assert len({str((record.payload or {})["index_scope"]) for record in records}) == 2
    assert old_result.evidence[0].citations[0].source_id == "shop_identity:old:702"
    assert current_result.evidence[0].citations[0].source_id == "shop_identity:current:702"
    await client.close()


@pytest.mark.parametrize(
    ("case_name", "vectors_config", "sparse_vectors_config", "error"),
    [
        (
            "unnamed-dense",
            models.VectorParams(size=64, distance=models.Distance.COSINE),
            {"lexical": models.SparseVectorParams(modifier=models.Modifier.IDF)},
            "named 'dense' vector",
        ),
        (
            "dot-distance",
            {"dense": models.VectorParams(size=64, distance=models.Distance.DOT)},
            {"lexical": models.SparseVectorParams(modifier=models.Modifier.IDF)},
            "Cosine distance",
        ),
        (
            "missing-sparse",
            {"dense": models.VectorParams(size=64, distance=models.Distance.COSINE)},
            {},
            "named 'lexical' sparse vector",
        ),
        (
            "missing-idf",
            {"dense": models.VectorParams(size=64, distance=models.Distance.COSINE)},
            {"lexical": models.SparseVectorParams()},
            "IDF modifier",
        ),
    ],
)
async def test_qdrant_rejects_incompatible_existing_vector_schema(
    case_name,
    vectors_config,
    sparse_vectors_config,
    error,
):
    client = AsyncQdrantClient(location=":memory:")
    collection = f"test_incompatible_schema_{case_name}"
    await client.create_collection(
        collection_name=collection,
        vectors_config=vectors_config,
        sparse_vectors_config=sparse_vectors_config,
    )
    rag = QdrantRagService(
        client=client,
        embeddings=RecordingEmbeddingService(),
        collection_name=collection,
    )

    with pytest.raises(ValueError, match=error):
        await rag.ensure_collection()

    await client.close()


class StaticRemoteSchemaClient:
    init_options = {"url": "http://qdrant:6333"}

    def __init__(self, payload_schema):
        self.payload_schema = payload_schema

    async def collection_exists(self, collection_name):
        return True

    async def get_collection(self, collection_name):
        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors={
                        "dense": models.VectorParams(
                            size=64,
                            distance=models.Distance.COSINE,
                        )
                    },
                    sparse_vectors={"lexical": models.SparseVectorParams(modifier=models.Modifier.IDF)},
                )
            ),
            payload_schema=self.payload_schema,
        )

    async def create_payload_index(self, **kwargs):
        return None


async def test_qdrant_server_requires_payload_index_schema_after_creation_attempts():
    rag = QdrantRagService(
        client=StaticRemoteSchemaClient(payload_schema={}),
        embeddings=RecordingEmbeddingService(),
        collection_name="test_missing_payload_schema",
    )

    with pytest.raises(ValueError, match="payload index 'shop_id'"):
        await rag.ensure_collection()


async def test_rank_then_retrieve_reuses_query_embedding_and_ranking_points():
    client = AsyncQdrantClient(location=":memory:")
    embeddings = RecordingEmbeddingService()
    rag = QdrantRagService(
        client=client,
        embeddings=embeddings,
        collection_name="test_ranking_query_embedding_cache",
    )
    await rag.index(
        [
            RagDocument(
                document_id="review:cache",
                shop_id=801,
                content_type="shop_review_thread",
                source_id="shop_review_thread:cache",
                text="A quiet dining room with vegan dinner options.",
                data_version="nyc-real-v1",
                evidence_tags=["quiet", "vegan_options"],
            )
        ]
    )
    constraints = UserConstraints(
        query="quiet vegan dinner",
        desired_tags=["quiet", "vegan_options"],
    )
    candidates = CandidateSet(
        candidates=[
            ShopCandidate(
                shop_id=801,
                name="Cache Fixture",
                category="Food & Dining",
                neighborhood="Midtown",
                latitude=40.75,
                longitude=-73.98,
                data_version="nyc-real-v1",
            )
        ]
    )

    ranked = await rag.rank_candidates(constraints, candidates, limit=1)
    result = await rag.retrieve(constraints, ranked)

    assert len(embeddings.queries) == 1
    assert result.retrieval_metadata["rankingCacheHit"] is True
    assert result.retrieval_metadata["denseAvailable"] is True
    assert result.evidence[0].citations[0].source_id == "shop_review_thread:cache"
    await client.close()


async def test_query_embedding_error_falls_back_to_sparse_retrieval():
    client = AsyncQdrantClient(location=":memory:")
    embeddings = RecordingEmbeddingService()
    rag = QdrantRagService(
        client=client,
        embeddings=embeddings,
        collection_name="test_sparse_embedding_fallback",
    )
    await rag.index(
        [
            RagDocument(
                document_id="review:fallback",
                shop_id=901,
                content_type="shop_review_thread",
                source_id="shop_review_thread:fallback",
                text="The dining room is quiet and has vegan options.",
                data_version="nyc-real-v1",
            )
        ]
    )
    embeddings.fail_queries = True

    result = await rag.retrieve(
        UserConstraints(query="quiet vegan dining"),
        CandidateSet(
            candidates=[
                ShopCandidate(
                    shop_id=901,
                    name="Fallback Fixture",
                    category="Food & Dining",
                    neighborhood="Midtown",
                    latitude=40.75,
                    longitude=-73.98,
                    data_version="nyc-real-v1",
                )
            ]
        ),
    )

    assert result.retrieval_metadata["denseAvailable"] is False
    assert result.retrieval_metadata["embeddingFallback"] == "sparse-only"
    assert result.evidence[0].citations[0].source_id == "shop_review_thread:fallback"
    await client.close()


async def test_query_embedding_error_fails_closed_when_sparse_fallback_is_disabled():
    client = AsyncQdrantClient(location=":memory:")
    embeddings = RecordingEmbeddingService()
    rag = QdrantRagService(
        client=client,
        embeddings=embeddings,
        collection_name="test_embedding_fail_closed",
        allow_sparse_fallback=False,
    )
    await rag.index(
        [
            RagDocument(
                document_id="review:fail-closed",
                shop_id=902,
                content_type="shop_review_thread",
                source_id="shop_review_thread:fail-closed",
                text="Quiet dinner evidence.",
                data_version="nyc-real-v1",
            )
        ]
    )
    embeddings.fail_queries = True

    with pytest.raises(EmbeddingError, match="embedding failed"):
        await rag.retrieve(
            UserConstraints(query="quiet dinner"),
            CandidateSet(
                candidates=[
                    ShopCandidate(
                        shop_id=902,
                        name="Fail Closed Fixture",
                        category="Food & Dining",
                        neighborhood="Midtown",
                        latitude=40.75,
                        longitude=-73.98,
                        data_version="nyc-real-v1",
                    )
                ]
            ),
        )

    await client.close()


async def test_qdrant_citation_preserves_content_provenance_and_thread_metadata():
    client = AsyncQdrantClient(location=":memory:")
    rag = QdrantRagService(
        client=client,
        embeddings=DeterministicHashEmbeddingService(dimensions=64),
        collection_name="test_content_provenance",
    )
    await rag.index(
        [
            RagDocument(
                document_id="shop:501",
                shop_id=501,
                content_type="shop_description",
                source_id="shop:501",
                text="A source-backed museum profile.",
                data_version="nyc-real-v1",
                content_source_type="OVERTURE",
                content_source_name="Overture Maps Foundation",
                content_source_url="https://example.test/merchant/501",
                synthetic=False,
            )
        ]
    )
    result = await rag.retrieve(
        UserConstraints(query="museum profile"),
        CandidateSet(
            candidates=[
                ShopCandidate(
                    shop_id=501,
                    name="Real Museum",
                    category="Entertainment & Attractions",
                    neighborhood="Flushing",
                    latitude=40.75,
                    longitude=-73.84,
                    data_version="nyc-real-v1",
                )
            ]
        ),
    )

    citation = result.evidence[0].citations[0]
    assert citation.source_type == "OVERTURE"
    assert citation.source_name == "Overture Maps Foundation"
    assert citation.source_url == "https://example.test/merchant/501"
    assert citation.synthetic is False
    assert citation.data_version == "nyc-real-v1"
    assert result.evidence[0].cautions == []
    await client.close()


async def test_qdrant_citation_hides_legacy_generator_and_thread_markup():
    client = AsyncQdrantClient(location=":memory:")
    rag = QdrantRagService(
        client=client,
        embeddings=DeterministicHashEmbeddingService(dimensions=64),
        collection_name="test_clean_display_excerpt",
    )
    await rag.index(
        [
            RagDocument(
                document_id="review:900",
                shop_id=900,
                content_type="shop_review_thread",
                source_id="shop_review_thread:900",
                text=(
                    "[Level 1 | USER | rating=4/5] [Synthetic demo review] "
                    "The room was calm.\n"
                    "[Level 2 | reply_to_review=900] [Synthetic demo reply] "
                    "I had the same experience."
                ),
                data_version="nyc-real-v1",
            )
        ]
    )
    result = await rag.retrieve(
        UserConstraints(query="calm room"),
        CandidateSet(
            candidates=[
                ShopCandidate(
                    shop_id=900,
                    name="Clean Excerpt Fixture",
                    category="Food & Dining",
                    neighborhood="Midtown",
                    latitude=40.75,
                    longitude=-73.98,
                    data_version="nyc-real-v1",
                )
            ]
        ),
    )

    excerpt = result.evidence[0].citations[0].excerpt
    assert excerpt == "The room was calm.\nI had the same experience."
    assert "Synthetic" not in excerpt
    assert "Level" not in excerpt
    await client.close()


async def test_qdrant_prefers_distinct_review_threads_over_duplicate_blog_templates():
    client = AsyncQdrantClient(location=":memory:")
    rag = QdrantRagService(
        client=client,
        embeddings=DeterministicHashEmbeddingService(dimensions=64),
        collection_name="test_evidence_diversity",
        citations_per_shop=2,
    )
    await rag.index(
        [
            RagDocument(
                document_id="blog:1",
                shop_id=901,
                content_type="blog",
                source_id="blog:1",
                text="A practical visit to Example Bar\nA neighborhood spot with quiet seating.",
            ),
            RagDocument(
                document_id="blog:2",
                shop_id=901,
                content_type="blog",
                source_id="blog:2",
                text="A practical visit to Example Bar\nA neighborhood spot with quiet seating.",
            ),
            RagDocument(
                document_id="review:1",
                shop_id=901,
                content_type="shop_review_thread",
                source_id="shop_review_thread:1",
                text="The room stayed calm enough for conversation.",
                evidence_tags=["quiet"],
            ),
            RagDocument(
                document_id="review:2",
                shop_id=901,
                content_type="shop_review_thread",
                source_id="shop_review_thread:2",
                text="The late closing time worked well for our evening plans.",
                evidence_tags=["late_night"],
            ),
        ]
    )
    result = await rag.retrieve(
        UserConstraints(query="quiet late night bar", desired_tags=["quiet", "late_night"]),
        CandidateSet(
            candidates=[
                ShopCandidate(
                    shop_id=901,
                    name="Example Bar",
                    category="Bars & Nightlife",
                    neighborhood="East Village",
                    latitude=40.73,
                    longitude=-73.98,
                )
            ]
        ),
    )

    citations = result.evidence[0].citations
    assert [citation.content_type for citation in citations] == [
        "shop_review_thread",
        "shop_review_thread",
    ]
    assert len({citation.excerpt for citation in citations}) == 2
    assert all("A practical visit" not in citation.excerpt for citation in citations)
    await client.close()
