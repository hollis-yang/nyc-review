from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.rag.embeddings import DeterministicHashEmbeddingService
from app.rag.global_retrieval import (
    PAYLOAD_FIELDS,
    ChannelRetrievalResult,
    GlobalDocumentHit,
    GlobalRetrievalResult,
    GlobalRetrievalScope,
    QdrantGlobalDocumentRetriever,
    RetrievalChannel,
)
from app.rag.merchant_aggregation import RetainedDocument, aggregate_merchants


class _RecordingClient:
    def __init__(self, points: list[SimpleNamespace]) -> None:
        self._points = points
        self.calls: list[dict] = []

    async def query_points(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(points=list(self._points))


def _scope(embedding: DeterministicHashEmbeddingService) -> GlobalRetrievalScope:
    return GlobalRetrievalScope(
        collection_name="m4-provenance-fixture",
        data_version="nyc-real-v1",
        dataset_sha256="a" * 64,
        retrieval_version="p12-rag-v1",
        embedding_identity=embedding.metadata.identity,
    )


def _payload(scope: GlobalRetrievalScope, **updates) -> dict:
    payload = {
        "shop_id": 101,
        "shop_external_id": "node:101",
        "document_id": "review:101:1",
        "source_id": "review-source:101:1",
        "root_id": 10_101,
        "content_type": "shop_review_thread",
        "document_kind": "evidence",
        "text": "A calm dining room with an accessible entrance.",
        "created_at": "2026-08-01T12:00:00Z",
        "content_source_type": "USER_SUBMITTED",
        "content_source_name": "NYC Review user submission",
        "content_source_url": "https://example.test/reviews/101/1",
        "untrusted_content": True,
        "synthetic": False,
        "category": "Food & Dining",
        "neighborhood": "Midtown",
        "data_version": scope.data_version,
        "dataset_sha256": scope.dataset_sha256,
        "retrieval_version": scope.retrieval_version,
        "embedding_identity": scope.embedding_identity,
        "index_scope": scope.index_scope,
        "security_test": False,
    }
    payload.update(updates)
    return payload


def _hit(
    *,
    point_id: str,
    rank: int,
    root_id: int,
    text: str,
    content_source_type: str,
    synthetic: bool,
) -> GlobalDocumentHit:
    return GlobalDocumentHit(
        point_id=point_id,
        shop_id=101,
        shop_external_id="node:101",
        channel=RetrievalChannel.DENSE,
        rank=rank,
        score=1.0 / rank,
        document_id=f"document:{point_id}",
        source_id=f"source:{point_id}",
        root_id=root_id,
        content_type="shop_review_thread",
        document_kind="evidence",
        text=text,
        created_at="2026-08-01T12:00:00Z",
        content_source_type=content_source_type,
        content_source_name="Fixture source",
        content_source_url=f"https://example.test/{point_id}",
        untrusted_content=True,
        synthetic=synthetic,
        data_version="nyc-real-v1",
        dataset_sha256="a" * 64,
        security_test=False,
    )


async def test_global_retrieval_carries_strict_evidence_provenance_from_payload():
    embedding = DeterministicHashEmbeddingService(dimensions=64)
    scope = _scope(embedding)
    valid = SimpleNamespace(id="valid", score=0.9, payload=_payload(scope))
    malformed = SimpleNamespace(
        id="malformed",
        score=0.8,
        payload=_payload(
            scope,
            document_id="review:101:2",
            source_id="review-source:101:2",
            root_id=10_102,
            synthetic="false",
        ),
    )
    client = _RecordingClient([valid, malformed])

    result = await QdrantGlobalDocumentRetriever(client, embedding, scope).search_documents(
        "quiet accessible dinner"
    )

    for channel in (result.dense, result.sparse):
        assert channel.returned_points == 2
        assert channel.rejected_points == 1
        assert len(channel.hits) == 1
        hit = channel.hits[0]
        assert hit.created_at == "2026-08-01T12:00:00Z"
        assert hit.content_source_type == "USER_SUBMITTED"
        assert hit.content_source_name == "NYC Review user submission"
        assert hit.content_source_url == "https://example.test/reviews/101/1"
        assert hit.untrusted_content is True
        assert hit.synthetic is False
        assert hit.data_version == scope.data_version
        assert hit.dataset_sha256 == scope.dataset_sha256
        assert hit.security_test is False

    assert client.calls
    assert all(call["with_payload"] == list(PAYLOAD_FIELDS) for call in client.calls)
    for field in (
        "created_at",
        "content_source_type",
        "content_source_name",
        "content_source_url",
        "untrusted_content",
        "synthetic",
        "security_test",
    ):
        assert field in PAYLOAD_FIELDS


def test_merchant_aggregation_retains_text_and_provenance_without_regressing_root_dedup():
    first = _hit(
        point_id="first",
        rank=1,
        root_id=9001,
        text="Original root evidence.",
        content_source_type="USER_SUBMITTED",
        synthetic=False,
    )
    duplicate_root = _hit(
        point_id="duplicate-root",
        rank=2,
        root_id=9001,
        text="A reply from the same review root.",
        content_source_type="SYNTHETIC",
        synthetic=True,
    )
    second_root = _hit(
        point_id="second-root",
        rank=3,
        root_id=9002,
        text="Evidence from another review root.",
        content_source_type="SYNTHETIC",
        synthetic=True,
    )
    result = GlobalRetrievalResult(
        dense=ChannelRetrievalResult(
            channel=RetrievalChannel.DENSE,
            hits=(first, duplicate_root, second_root),
            returned_points=3,
        ),
        sparse=ChannelRetrievalResult(channel=RetrievalChannel.SPARSE),
    )

    aggregated = aggregate_merchants(result, documents_per_merchant=3)

    retained = aggregated.ranking(RetrievalChannel.DENSE).merchants[0].retained_documents
    assert [document.point_id for document in retained] == ["first", "second-root"]
    assert [document.text for document in retained] == [
        "Original root evidence.",
        "Evidence from another review root.",
    ]
    assert retained[0].content_source_type == "USER_SUBMITTED"
    assert retained[0].synthetic is False
    assert retained[0].untrusted_content is True
    assert retained[0].security_test is False
    assert retained[1].content_source_type == "SYNTHETIC"
    assert retained[1].synthetic is True
    assert aggregated.suppression.duplicate_roots == 1


def test_provenance_models_are_strict_frozen_and_fail_closed_for_security_documents():
    hit = _hit(
        point_id="frozen",
        rank=1,
        root_id=9101,
        text="Frozen evidence.",
        content_source_type="USER_SUBMITTED",
        synthetic=False,
    )
    with pytest.raises(ValidationError, match="frozen"):
        hit.synthetic = True

    invalid_hit = hit.model_dump()
    invalid_hit["synthetic"] = "false"
    with pytest.raises(ValidationError):
        GlobalDocumentHit.model_validate(invalid_hit)

    retained = RetainedDocument(
        point_id="retained",
        shop_external_id="node:101",
        document_id="document:retained",
        source_id="source:retained",
        root_id=9102,
        content_type="shop_review_thread",
        document_kind="evidence",
        text="Retained evidence.",
        document_rank=1,
        score=0.9,
    )
    with pytest.raises(ValidationError, match="frozen"):
        retained.text = "mutated"

    invalid_retained = retained.model_dump()
    invalid_retained["security_test"] = True
    with pytest.raises(ValidationError, match="Security-test"):
        RetainedDocument.model_validate(invalid_retained)

    invalid_retained = retained.model_dump()
    invalid_retained["unexpected"] = "forbidden"
    with pytest.raises(ValidationError, match="Extra inputs"):
        RetainedDocument.model_validate(invalid_retained)
