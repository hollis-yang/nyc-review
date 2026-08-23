from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient, models

from app.domain.models import (
    CandidateSet,
    EvidenceCitation,
    EvidencePack,
    ShopEvidence,
    UserConstraints,
)
from app.rag.display_text import clean_display_text
from app.rag.embeddings import EmbeddingService
from app.rag.models import RagDocument


@dataclass(frozen=True)
class RagIndexStats:
    total_documents: int = 0
    upserted_documents: int = 0
    unchanged_documents: int = 0
    deleted_documents: int = 0

    def as_metadata(self) -> dict[str, int]:
        return {
            "total": self.total_documents,
            "upserted": self.upserted_documents,
            "unchanged": self.unchanged_documents,
            "deleted": self.deleted_documents,
        }


class QdrantRagService:
    def __init__(
        self,
        client: AsyncQdrantClient,
        embeddings: EmbeddingService,
        collection_name: str = "hmdp_content_v1",
        citations_per_shop: int = 3,
        index_batch_size: int = 128,
        dataset_sha256: str | None = None,
    ):
        if index_batch_size < 1:
            raise ValueError("index_batch_size must be positive")
        self._client = client
        self._embeddings = embeddings
        self._collection_name = collection_name
        self._citations_per_shop = citations_per_shop
        self._index_batch_size = index_batch_size
        self._dataset_sha256 = dataset_sha256
        self._collection_ready = False

    async def ensure_collection(self) -> None:
        if self._collection_ready:
            return
        if not await self._client.collection_exists(self._collection_name):
            await self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=models.VectorParams(
                    size=self._embeddings.dimensions,
                    distance=models.Distance.COSINE,
                ),
            )
        await self._ensure_payload_indexes()
        self._collection_ready = True

    async def _ensure_payload_indexes(self) -> None:
        indexes = {
            "shop_id": models.PayloadSchemaType.INTEGER,
            "data_version": models.PayloadSchemaType.KEYWORD,
            "dataset_sha256": models.PayloadSchemaType.KEYWORD,
            "content_type": models.PayloadSchemaType.KEYWORD,
            "root_id": models.PayloadSchemaType.INTEGER,
            "index_scope": models.PayloadSchemaType.KEYWORD,
        }
        for field_name, field_schema in indexes.items():
            await self._client.create_payload_index(
                collection_name=self._collection_name,
                field_name=field_name,
                field_schema=field_schema,
                wait=True,
            )

    async def index(self, documents: Iterable[RagDocument], *, replace: bool = False) -> int:
        """Batch index documents while preserving the legacy integer return contract."""

        if replace and await self._client.collection_exists(self._collection_name):
            await self._client.delete_collection(self._collection_name)
            self._collection_ready = False
        await self.ensure_collection()
        indexed = 0
        for batch in _batched(documents, self._index_batch_size):
            normalized = [
                _with_content_hash(self._bind_dataset_identity(document)) for document in batch
            ]
            await self._upsert(normalized)
            indexed += len(normalized)
        return indexed

    async def sync(
        self,
        documents: Iterable[RagDocument],
        *,
        data_version: str | None,
    ) -> RagIndexStats:
        """Incrementally reconcile one dataset scope and delete stale points last.

        Existing points are retained until every changed document has been embedded
        and upserted successfully. A failed synchronization therefore never removes
        the last usable copy of an evidence document.
        """

        await self.ensure_collection()
        scope = _index_scope(data_version, self._dataset_sha256)
        existing = await self._existing_points(scope)
        desired_ids: set[str] = set()
        upserted = 0
        unchanged = 0

        for batch in _batched(documents, self._index_batch_size):
            normalized: list[RagDocument] = []
            for document in batch:
                if data_version is not None and document.data_version != data_version:
                    raise ValueError(
                        f"RAG document {document.document_id} does not match data version {data_version}."
                    )
                item = _with_content_hash(self._bind_dataset_identity(document))
                point_id = _point_id(item)
                if point_id in desired_ids:
                    raise ValueError(f"Duplicate RAG document ID: {item.document_id}")
                desired_ids.add(point_id)
                if existing.get(point_id, {}).get("content_sha256") == item.content_sha256:
                    unchanged += 1
                else:
                    normalized.append(item)
            if normalized:
                await self._upsert(normalized, scope=scope)
                upserted += len(normalized)

        stale_ids = sorted(set(existing) - desired_ids)
        for batch in _batched(stale_ids, self._index_batch_size * 4):
            await self._client.delete(
                collection_name=self._collection_name,
                points_selector=models.PointIdsList(points=batch),
                wait=True,
            )
        return RagIndexStats(
            total_documents=len(desired_ids),
            upserted_documents=upserted,
            unchanged_documents=unchanged,
            deleted_documents=len(stale_ids),
        )

    def _bind_dataset_identity(self, document: RagDocument) -> RagDocument:
        if (
            self._dataset_sha256 is not None
            and document.dataset_sha256 is not None
            and document.dataset_sha256 != self._dataset_sha256
        ):
            raise ValueError(
                f"RAG document {document.document_id} does not match the configured dataset SHA-256."
            )
        if self._dataset_sha256 is None or document.dataset_sha256 == self._dataset_sha256:
            return document
        return document.model_copy(update={"dataset_sha256": self._dataset_sha256})

    async def _existing_points(self, scope: str) -> dict[str, dict]:
        records: dict[str, dict] = {}
        offset = None
        while True:
            page, offset = await self._client.scroll(
                collection_name=self._collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="index_scope",
                            match=models.MatchValue(value=scope),
                        )
                    ]
                ),
                limit=max(256, self._index_batch_size * 4),
                offset=offset,
                with_payload=["content_sha256", "document_id"],
                with_vectors=False,
            )
            for record in page:
                records[str(record.id)] = record.payload or {}
            if offset is None:
                return records

    async def _upsert(self, documents: list[RagDocument], scope: str | None = None) -> None:
        if not documents:
            return
        vectors = await self._embeddings.embed([document.text for document in documents])
        points = []
        for document, vector in zip(documents, vectors, strict=True):
            payload = document.model_dump(mode="json")
            payload["index_scope"] = scope or _index_scope(
                document.data_version, document.dataset_sha256
            )
            points.append(
                models.PointStruct(
                    id=_point_id(document),
                    vector=vector,
                    payload=payload,
                )
            )
        await self._client.upsert(
            collection_name=self._collection_name,
            points=points,
            wait=True,
        )

    async def retrieve(
        self,
        constraints: UserConstraints,
        candidates: CandidateSet,
    ) -> EvidencePack:
        if not candidates.candidates:
            return EvidencePack(evidence=[])
        await self.ensure_collection()
        query_vector = (await self._embeddings.embed([constraints.query]))[0]
        results = await asyncio.gather(
            *[
                self._retrieve_for_shop(
                    query_vector=query_vector,
                    shop_id=candidate.shop_id,
                    data_version=candidate.data_version,
                    desired_tags=constraints.desired_tags,
                )
                for candidate in candidates.candidates
            ]
        )
        return EvidencePack(evidence=results)

    async def _retrieve_for_shop(
        self,
        query_vector: list[float],
        shop_id: int,
        data_version: str | None,
        desired_tags: list[str],
    ) -> ShopEvidence:
        must_conditions = [
            models.FieldCondition(
                key="shop_id",
                match=models.MatchValue(value=shop_id),
            )
        ]
        if data_version:
            must_conditions.append(
                models.FieldCondition(
                    key="data_version",
                    match=models.MatchValue(value=data_version),
                )
            )
        if self._dataset_sha256:
            must_conditions.append(
                models.FieldCondition(
                    key="dataset_sha256",
                    match=models.MatchValue(value=self._dataset_sha256),
                )
            )
        response = await self._client.query_points(
            collection_name=self._collection_name,
            query=query_vector,
            query_filter=models.Filter(must=must_conditions),
            # Fetch beyond the display limit so we can prefer review threads and
            # remove duplicate generated posts without losing useful evidence.
            limit=max(24, self._citations_per_shop * 8),
            with_payload=True,
        )
        citations: list[EvidenceCitation] = []
        supported_tags: set[str] = set()
        seen_excerpts: set[str] = set()
        ranked_points = sorted(
            enumerate(response.points),
            key=lambda item: (
                _evidence_type_priority((item[1].payload or {}).get("content_type")),
                item[0],
            ),
        )
        for _, point in ranked_points:
            payload = point.payload or {}
            excerpt = clean_display_text(str(payload.get("text") or ""))[:600]
            normalized_excerpt = " ".join(excerpt.casefold().split())
            if not normalized_excerpt or normalized_excerpt in seen_excerpts:
                continue
            seen_excerpts.add(normalized_excerpt)
            evidence_tags = set(payload.get("evidence_tags") or [])
            supported_tags.update(evidence_tags.intersection(desired_tags))
            citations.append(
                EvidenceCitation(
                    citation_id=str(payload.get("document_id") or point.id),
                    shop_id=shop_id,
                    content_type=str(payload.get("content_type") or "unknown"),
                    excerpt=excerpt,
                    source_id=str(payload.get("source_id") or point.id),
                    created_at=payload.get("created_at"),
                    untrusted_content=bool(payload.get("untrusted_content", True)),
                    source_type=str(payload.get("content_source_type") or "SYNTHETIC"),
                    source_name=payload.get("content_source_name"),
                    source_url=payload.get("content_source_url"),
                    synthetic=bool(payload.get("synthetic", True)),
                    data_version=payload.get("data_version"),
                    dataset_sha256=payload.get("dataset_sha256"),
                    root_id=payload.get("root_id"),
                    max_depth=payload.get("max_depth"),
                    reply_count=int(payload.get("reply_count") or 0),
                )
            )
            if len(citations) >= self._citations_per_shop:
                break
        cautions = []
        if citations and all(citation.synthetic for citation in citations):
            cautions.append(
                "All retrieved review evidence is synthetic demonstration content, "
                "not real customer testimony."
            )
        elif any(citation.synthetic for citation in citations):
            cautions.append(
                "Some retrieved evidence is synthetic demonstration content, "
                "not real customer testimony."
            )
        return ShopEvidence(
            shop_id=shop_id,
            supported_tags=sorted(supported_tags),
            cautions=cautions,
            citations=citations,
        )


def _with_content_hash(document: RagDocument) -> RagDocument:
    payload = document.model_dump(mode="json", exclude={"content_sha256"})
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return document.model_copy(update={"content_sha256": digest})


def _evidence_type_priority(content_type: object) -> int:
    """Prefer firsthand-style review content over generic catalog/post text."""

    return {
        "shop_review_thread": 0,
        "shop_review": 0,
        "blog_comment": 1,
        "nested_comment": 1,
        "blog": 2,
        "shop_description": 3,
    }.get(str(content_type or ""), 4)


def _point_id(document: RagDocument) -> str:
    scope = _index_scope(document.data_version, document.dataset_sha256)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{scope}:{document.document_id}"))


def _index_scope(data_version: str | None, dataset_sha256: str | None) -> str:
    return f"{data_version or '__UNVERSIONED__'}:{dataset_sha256 or '__NO_DATASET_SHA__'}"


def _batched(values: Iterable, size: int) -> Iterator[list]:
    batch = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch
