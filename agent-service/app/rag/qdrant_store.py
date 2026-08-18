from __future__ import annotations

import asyncio
import uuid

from qdrant_client import AsyncQdrantClient, models

from app.domain.models import (
    CandidateSet,
    EvidenceCitation,
    EvidencePack,
    ShopEvidence,
    UserConstraints,
)
from app.rag.embeddings import EmbeddingService
from app.rag.models import RagDocument


class QdrantRagService:
    def __init__(
        self,
        client: AsyncQdrantClient,
        embeddings: EmbeddingService,
        collection_name: str = "hmdp_content_v1",
        citations_per_shop: int = 3,
    ):
        self._client = client
        self._embeddings = embeddings
        self._collection_name = collection_name
        self._citations_per_shop = citations_per_shop

    async def ensure_collection(self) -> None:
        if await self._client.collection_exists(self._collection_name):
            return
        await self._client.create_collection(
            collection_name=self._collection_name,
            vectors_config=models.VectorParams(
                size=self._embeddings.dimensions,
                distance=models.Distance.COSINE,
            ),
        )

    async def index(self, documents: list[RagDocument]) -> int:
        if not documents:
            return 0
        await self.ensure_collection()
        vectors = await self._embeddings.embed([document.text for document in documents])
        points = []
        for document, vector in zip(documents, vectors, strict=True):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, document.document_id))
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=document.model_dump(mode="json"),
                )
            )
        await self._client.upsert(
            collection_name=self._collection_name,
            points=points,
            wait=True,
        )
        return len(points)

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
        desired_tags: list[str],
    ) -> ShopEvidence:
        response = await self._client.query_points(
            collection_name=self._collection_name,
            query=query_vector,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="shop_id",
                        match=models.MatchValue(value=shop_id),
                    )
                ]
            ),
            limit=self._citations_per_shop,
            with_payload=True,
        )
        citations: list[EvidenceCitation] = []
        supported_tags: set[str] = set()
        for point in response.points:
            payload = point.payload or {}
            evidence_tags = set(payload.get("evidence_tags") or [])
            supported_tags.update(evidence_tags.intersection(desired_tags))
            citations.append(
                EvidenceCitation(
                    citation_id=str(payload.get("document_id") or point.id),
                    shop_id=shop_id,
                    content_type=str(payload.get("content_type") or "unknown"),
                    excerpt=str(payload.get("text") or "")[:600],
                    source_id=str(payload.get("source_id") or point.id),
                    created_at=payload.get("created_at"),
                    untrusted_content=bool(payload.get("untrusted_content", True)),
                )
            )
        return ShopEvidence(
            shop_id=shop_id,
            supported_tags=sorted(supported_tags),
            citations=citations,
        )
