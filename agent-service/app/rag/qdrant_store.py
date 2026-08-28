from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections import OrderedDict
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
from app.rag.lexical import normalized_merchant_name, sparse_vector
from app.rag.models import RagDocument
from app.rag.query_plan import build_retrieval_plan

LOGGER = logging.getLogger(__name__)


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
        collection_name: str = "nyc_review_content_v2",
        citations_per_shop: int = 3,
        index_batch_size: int = 128,
        dataset_sha256: str | None = None,
        retrieval_version: str = "p12-rag-v1",
    ):
        if index_batch_size < 1:
            raise ValueError("index_batch_size must be positive")
        self._client = client
        self._embeddings = embeddings
        self._collection_name = collection_name
        self._citations_per_shop = citations_per_shop
        self._index_batch_size = index_batch_size
        self._dataset_sha256 = dataset_sha256
        self._retrieval_version = retrieval_version
        self._collection_ready = False
        self._ranking_cache: OrderedDict[tuple[str, tuple[int, ...]], list] = OrderedDict()

    async def ensure_collection(self) -> None:
        if self._collection_ready:
            return
        if not await self._client.collection_exists(self._collection_name):
            await self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config={
                    "dense": models.VectorParams(
                        size=self._embeddings.dimensions,
                        distance=models.Distance.COSINE,
                    ),
                },
                sparse_vectors_config={
                    "lexical": models.SparseVectorParams(modifier=models.Modifier.IDF),
                },
            )
        await self._ensure_payload_indexes()
        self._collection_ready = True

    async def _ensure_payload_indexes(self) -> None:
        indexes = {
            "shop_id": models.PayloadSchemaType.INTEGER,
            "data_version": models.PayloadSchemaType.KEYWORD,
            "dataset_sha256": models.PayloadSchemaType.KEYWORD,
            "content_type": models.PayloadSchemaType.KEYWORD,
            "document_kind": models.PayloadSchemaType.KEYWORD,
            "category": models.PayloadSchemaType.KEYWORD,
            "borough": models.PayloadSchemaType.KEYWORD,
            "neighborhood": models.PayloadSchemaType.KEYWORD,
            "security_test": models.PayloadSchemaType.BOOL,
            "retrieval_version": models.PayloadSchemaType.KEYWORD,
            "shop_external_id": models.PayloadSchemaType.KEYWORD,
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
            processed = len(desired_ids)
            if processed % 5_000 < len(batch):
                LOGGER.info(
                    "RAG sync progress: processed=%s upserted=%s unchanged=%s",
                    processed,
                    upserted,
                    unchanged,
                )

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
            payload["retrieval_version"] = self._retrieval_version
            payload["index_scope"] = scope or _index_scope(
                document.data_version, document.dataset_sha256
            )
            points.append(
                models.PointStruct(
                    id=_point_id(document),
                    vector={
                        "dense": vector,
                        "lexical": sparse_vector(document.text),
                    },
                    payload=payload,
                )
            )
        await self._client.upsert(
            collection_name=self._collection_name,
            points=points,
            wait=True,
        )

    async def rank_candidates(
        self,
        constraints: UserConstraints,
        candidates: CandidateSet,
        *,
        limit: int,
    ) -> CandidateSet:
        if not candidates.candidates or limit < 1:
            return candidates.model_copy(update={"candidates": []})
        started = time.perf_counter()
        data_versions = {item.data_version for item in candidates.candidates if item.data_version}
        data_version = next(iter(data_versions), None) if len(data_versions) == 1 else None
        plan = build_retrieval_plan(
            constraints,
            retrieval_version=self._retrieval_version,
            data_version=data_version,
            dataset_sha256=self._dataset_sha256,
        )
        candidate_ids = [candidate.shop_id for candidate in candidates.candidates]
        query_filter = self._query_filter(
            shop_ids=candidate_ids,
            data_version=data_version,
            exclude_security=True,
        )
        points = await self._hybrid_query(
            plan.expanded_query,
            query_filter,
            limit=max(60, len(candidate_ids) * 8),
        )
        best_by_shop: dict[int, float] = {}
        hit_documents: dict[int, int] = {}
        for point in points:
            payload = point.payload or {}
            shop_id = int(payload.get("shop_id") or 0)
            if shop_id not in candidate_ids:
                continue
            best_by_shop[shop_id] = max(best_by_shop.get(shop_id, 0.0), float(point.score))
            hit_documents[shop_id] = hit_documents.get(shop_id, 0) + 1
        maximum_hybrid = max(best_by_shop.values(), default=0.0)

        exact_candidate_ids = {
            int(shop_id) for shop_id in candidates.retrieval_metadata.get("exactCandidateIds", [])
        }

        def score(candidate) -> tuple[int, float, float, float, int]:
            hybrid = best_by_shop.get(candidate.shop_id, 0.0)
            normalized_hybrid = hybrid / maximum_hybrid if maximum_hybrid else 0.0
            desired = set(plan.semantic_tags)
            tag_ratio = len(desired.intersection(candidate.tags)) / len(desired) if desired else 1.0
            distance_score = (
                1.0 / (1.0 + candidate.distance_meters / 2_000)
                if candidate.distance_meters is not None
                else 0.5
            )
            rating_score = (candidate.score or 0.0) / 5.0
            combined = (
                normalized_hybrid * 0.45
                + tag_ratio * 0.35
                + distance_score * 0.10
                + rating_score * 0.10
            )
            exact_match = 1 if not exact_candidate_ids or candidate.shop_id in exact_candidate_ids else 0
            return exact_match, combined, normalized_hybrid, rating_score, -candidate.shop_id

        ordered = sorted(candidates.candidates, key=score, reverse=True)
        selected = []
        duplicate_brands_suppressed = 0
        brand_counts: dict[str, int] = {}
        for candidate in ordered:
            brand = normalized_merchant_name(candidate.name) or f"shop-{candidate.shop_id}"
            if brand_counts.get(brand, 0) >= 2:
                duplicate_brands_suppressed += 1
                continue
            brand_counts[brand] = brand_counts.get(brand, 0) + 1
            selected.append(candidate)
            if len(selected) >= limit:
                break
        if len(selected) < min(limit, len(ordered)):
            selected_ids = {candidate.shop_id for candidate in selected}
            selected.extend(
                candidate
                for candidate in ordered
                if candidate.shop_id not in selected_ids
            )
            selected = selected[:limit]
        self._remember_ranking_points(plan.expanded_query, selected, points)
        elapsed_ms = round((time.perf_counter() - started) * 1_000, 3)
        return candidates.model_copy(
            update={
                "candidates": selected,
                "retrieval_metadata": {
                    **candidates.retrieval_metadata,
                    "retrievalVersion": self._retrieval_version,
                    "candidatePool": len(candidate_ids),
                    "hybridDocuments": len(points),
                    "hybridShopHits": len(best_by_shop),
                    "finalCandidates": len(selected),
                    "duplicateBrandsSuppressed": duplicate_brands_suppressed,
                    "latencyMs": elapsed_ms,
                    "queryPlan": plan.model_dump(mode="json"),
                    "documentHitsByShop": dict(sorted(hit_documents.items())),
                },
            }
        )

    async def _hybrid_query(
        self,
        query_text: str,
        query_filter: models.Filter,
        *,
        limit: int,
    ):
        await self.ensure_collection()
        query_vector = (await self._embeddings.embed([query_text]))[0]
        lexical = sparse_vector(query_text)
        if not lexical.indices:
            response = await self._client.query_points(
                collection_name=self._collection_name,
                query=query_vector,
                using="dense",
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
            return response.points
        response = await self._client.query_points(
            collection_name=self._collection_name,
            prefetch=[
                models.Prefetch(
                    query=query_vector,
                    using="dense",
                    filter=query_filter,
                    limit=limit,
                ),
                models.Prefetch(
                    query=lexical,
                    using="lexical",
                    filter=query_filter,
                    limit=limit,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=True,
        )
        return response.points

    def _query_filter(
        self,
        *,
        shop_ids: list[int],
        data_version: str | None,
        exclude_security: bool,
    ) -> models.Filter:
        must: list[models.Condition] = [
            models.FieldCondition(
                key="shop_id",
                match=models.MatchAny(any=shop_ids),
            ),
            models.FieldCondition(
                key="retrieval_version",
                match=models.MatchValue(value=self._retrieval_version),
            ),
        ]
        if data_version:
            must.append(
                models.FieldCondition(
                    key="data_version",
                    match=models.MatchValue(value=data_version),
                )
            )
        if self._dataset_sha256:
            must.append(
                models.FieldCondition(
                    key="dataset_sha256",
                    match=models.MatchValue(value=self._dataset_sha256),
                )
            )
        must_not: list[models.Condition] = []
        if exclude_security:
            must_not.append(
                models.FieldCondition(
                    key="security_test",
                    match=models.MatchValue(value=True),
                )
            )
        return models.Filter(must=must, must_not=must_not)

    async def retrieve(
        self,
        constraints: UserConstraints,
        candidates: CandidateSet,
    ) -> EvidencePack:
        if not candidates.candidates:
            return EvidencePack(evidence=[])
        await self.ensure_collection()
        data_versions = {item.data_version for item in candidates.candidates if item.data_version}
        data_version = next(iter(data_versions), None) if len(data_versions) == 1 else None
        plan = build_retrieval_plan(
            constraints,
            retrieval_version=self._retrieval_version,
            data_version=data_version,
            dataset_sha256=self._dataset_sha256,
        )
        query_vector = (await self._embeddings.embed([plan.expanded_query]))[0]
        query_sparse = sparse_vector(plan.expanded_query)
        started = time.perf_counter()
        search_points = self._take_ranking_points(
            plan.expanded_query,
            candidates.candidates,
        )
        ranking_cache_hit = search_points is not None
        if search_points is None:
            query_filter = self._query_filter(
                shop_ids=[candidate.shop_id for candidate in candidates.candidates],
                data_version=data_version,
                exclude_security=True,
            )
            search_limit = max(120, len(candidates.candidates) * 48)
            response = await self._client.query_points(
                collection_name=self._collection_name,
                prefetch=[
                    models.Prefetch(
                        query=query_vector,
                        using="dense",
                        filter=query_filter,
                        limit=search_limit,
                    ),
                    models.Prefetch(
                        query=query_sparse,
                        using="lexical",
                        filter=query_filter,
                        limit=search_limit,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=search_limit,
                with_payload=True,
            )
            search_points = response.points
        fact_ids = [
            _document_point_id(
                f"shop_{kind}_fact:{candidate.shop_id}",
                candidate.data_version,
                self._dataset_sha256,
            )
            for candidate in candidates.candidates
            for kind in ("identity", "attribute")
        ]
        fact_points = await self._client.retrieve(
            collection_name=self._collection_name,
            ids=fact_ids,
            with_payload=True,
            with_vectors=False,
        )
        points_by_shop: dict[int, list] = {
            candidate.shop_id: [] for candidate in candidates.candidates
        }
        seen_point_ids: set[str] = set()
        for point in [*fact_points, *search_points]:
            point_key = str(point.id)
            payload = point.payload or {}
            shop_id = int(payload.get("shop_id") or 0)
            if shop_id in points_by_shop and point_key not in seen_point_ids:
                points_by_shop[shop_id].append(point)
                seen_point_ids.add(point_key)
        results = [
            self._select_shop_evidence(
                points_by_shop[candidate.shop_id],
                shop_id=candidate.shop_id,
                desired_tags=plan.semantic_tags,
            )
            for candidate in candidates.candidates
        ]
        return EvidencePack(
            evidence=results,
            retrieval_metadata={
                "retrievalVersion": self._retrieval_version,
                "shops": len(results),
                "citations": sum(len(item.citations) for item in results),
                "rankingCacheHit": ranking_cache_hit,
                "latencyMs": round((time.perf_counter() - started) * 1_000, 3),
            },
        )

    def _remember_ranking_points(self, query: str, candidates, points: list) -> None:
        key = self._ranking_cache_key(query, candidates)
        shop_ids = {candidate.shop_id for candidate in candidates}
        self._ranking_cache[key] = [
            point
            for point in points
            if int((point.payload or {}).get("shop_id") or 0) in shop_ids
            and not bool((point.payload or {}).get("security_test", False))
        ]
        self._ranking_cache.move_to_end(key)
        while len(self._ranking_cache) > 32:
            self._ranking_cache.popitem(last=False)

    def _take_ranking_points(self, query: str, candidates):
        return self._ranking_cache.pop(self._ranking_cache_key(query, candidates), None)

    @staticmethod
    def _ranking_cache_key(query: str, candidates) -> tuple[str, tuple[int, ...]]:
        return query, tuple(candidate.shop_id for candidate in candidates)

    def _select_shop_evidence(
        self,
        points,
        *,
        shop_id: int,
        desired_tags: list[str],
    ) -> ShopEvidence:
        prepared = []
        seen_excerpts: set[str] = set()
        seen_sources: set[str] = set()
        seen_roots: set[int] = set()
        for position, point in enumerate(points):
            payload = point.payload or {}
            excerpt = clean_display_text(str(payload.get("text") or ""))[:600]
            normalized_excerpt = " ".join(excerpt.casefold().split())
            source_id = str(payload.get("source_id") or point.id)
            root_id = payload.get("root_id")
            if (
                not normalized_excerpt
                or normalized_excerpt in seen_excerpts
                or source_id in seen_sources
                or (isinstance(root_id, int) and root_id in seen_roots)
                or bool(payload.get("security_test", False))
            ):
                continue
            seen_excerpts.add(normalized_excerpt)
            seen_sources.add(source_id)
            if isinstance(root_id, int):
                seen_roots.add(root_id)
            prepared.append((position, point, payload, excerpt, source_id))

        facts = [item for item in prepared if item[2].get("document_kind") == "fact"]
        reviews = [
            item for item in prepared
            if item[2].get("content_type") in {"shop_review_thread", "shop_review"}
        ]
        selected = []
        if facts:
            selected.append(facts[0])
        if reviews and reviews[0] not in selected:
            selected.append(reviews[0])
        for item in sorted(
            prepared,
            key=lambda value: (
                _evidence_type_priority(value[2].get("content_type")),
                value[0],
            ),
        ):
            if item not in selected:
                selected.append(item)
            if len(selected) >= self._citations_per_shop:
                break

        citations: list[EvidenceCitation] = []
        supported_tags: set[str] = set()
        for _, point, payload, excerpt, source_id in selected[: self._citations_per_shop]:
            supported_tags.update(set(payload.get("evidence_tags") or []).intersection(desired_tags))
            citations.append(
                EvidenceCitation(
                    citation_id=str(payload.get("document_id") or point.id),
                    shop_id=shop_id,
                    content_type=str(payload.get("content_type") or "unknown"),
                    document_kind=str(payload.get("document_kind") or "evidence"),
                    excerpt=excerpt,
                    source_id=source_id,
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
                    security_test=bool(payload.get("security_test", False)),
                )
            )
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
    return _document_point_id(
        document.document_id,
        document.data_version,
        document.dataset_sha256,
    )


def _document_point_id(
    document_id: str,
    data_version: str | None,
    dataset_sha256: str | None,
) -> str:
    scope = _index_scope(data_version, dataset_sha256)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{scope}:{document_id}"))


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
