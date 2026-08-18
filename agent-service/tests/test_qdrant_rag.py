from qdrant_client import AsyncQdrantClient

from app.domain.models import CandidateSet, ShopCandidate, UserConstraints
from app.rag.embeddings import DeterministicHashEmbeddingService
from app.rag.models import RagDocument
from app.rag.qdrant_store import QdrantRagService


async def test_qdrant_rag_filters_by_shop_and_returns_traceable_citations():
    client = AsyncQdrantClient(location=":memory:")
    rag = QdrantRagService(
        client=client,
        embeddings=DeterministicHashEmbeddingService(dimensions=64),
        collection_name="test_hmdp_content",
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
        collection_name="test_hmdp_versioned_content",
    )
    await rag.index(
        [
            RagDocument(
                document_id="review:v1:1",
                shop_id=101,
                content_type="shop_review",
                source_id="shop_review:v1:1",
                text="Old dataset evidence.",
                data_version="nyc-mock-v0",
            ),
            RagDocument(
                document_id="review:v2:1",
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
    await client.close()
