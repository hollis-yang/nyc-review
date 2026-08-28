import pytest
from qdrant_client import AsyncQdrantClient

from app.domain.models import CandidateSet, ShopCandidate, UserConstraints
from app.rag.embeddings import DeterministicHashEmbeddingService
from app.rag.models import RagDocument
from app.rag.qdrant_store import QdrantRagService


class RecordingEmbeddingService:
    def __init__(self, dimensions: int = 64):
        self._delegate = DeterministicHashEmbeddingService(dimensions=dimensions)
        self.batches: list[list[str]] = []
        self.fail = False

    @property
    def dimensions(self) -> int:
        return self._delegate.dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        if self.fail:
            raise RuntimeError("embedding failed")
        return await self._delegate.embed(texts)


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

    assert [citation.source_id for citation in result.evidence[0].citations] == [
        "shop_review:current:1"
    ]
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
    assert [len(batch) for batch in embeddings.batches] == [2, 1, 1]
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
    embeddings.fail = True

    with pytest.raises(RuntimeError, match="embedding failed"):
        await rag.sync(
            [first.model_copy(update={"text": "Changed thread one"})],
            data_version="nyc-real-v1",
        )

    assert (await client.count("test_safe_stale_deletion", exact=True)).count == 2
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
