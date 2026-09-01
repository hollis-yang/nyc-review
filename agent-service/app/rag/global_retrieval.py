from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from qdrant_client import models

from app.rag.embeddings import EmbeddingError, EmbeddingService
from app.rag.lexical import sparse_vector


class RetrievalChannel(StrEnum):
    DENSE = "dense"
    SPARSE = "sparse"


class GlobalRetrievalScope(BaseModel):
    """Exact index identity that every global-retrieval point must match."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    collection_name: str = Field(min_length=1)
    data_version: str = Field(min_length=1)
    dataset_sha256: str = Field(min_length=1)
    retrieval_version: str = Field(min_length=1)
    embedding_identity: str = Field(min_length=1)

    @property
    def index_scope(self) -> str:
        return ":".join(
            (
                self.data_version,
                self.dataset_sha256,
                self.embedding_identity,
                self.retrieval_version,
            )
        )


class GlobalDocumentHit(BaseModel):
    """Validated, channel-specific Qdrant hit used only inside retrieval policy."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    point_id: str = Field(min_length=1)
    shop_id: int = Field(gt=0)
    shop_external_id: str = Field(min_length=1)
    channel: RetrievalChannel
    rank: int = Field(ge=1)
    score: float
    document_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    root_id: int | None = Field(default=None, gt=0)
    content_type: str = Field(min_length=1)
    document_kind: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ChannelRetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    channel: RetrievalChannel
    hits: tuple[GlobalDocumentHit, ...] = ()
    available: bool = True
    fallback_reason: str | None = None
    returned_points: int = Field(default=0, ge=0)
    rejected_points: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0)


class GlobalRetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    dense: ChannelRetrievalResult
    sparse: ChannelRetrievalResult
    embedding_latency_ms: float = Field(default=0.0, ge=0)
    total_latency_ms: float = Field(default=0.0, ge=0)


class QdrantQueryClient(Protocol):
    async def query_points(self, **kwargs: Any) -> Any: ...


PAYLOAD_FIELDS = (
    "shop_id",
    "shop_external_id",
    "document_id",
    "source_id",
    "root_id",
    "content_type",
    "document_kind",
    "text",
    "category",
    "data_version",
    "dataset_sha256",
    "retrieval_version",
    "embedding_identity",
    "index_scope",
    "security_test",
)


class QdrantGlobalDocumentRetriever:
    """Run independent dense and sparse searches over one exact corpus scope."""

    def __init__(
        self,
        client: QdrantQueryClient,
        embeddings: EmbeddingService,
        scope: GlobalRetrievalScope,
        *,
        document_limit: int = 200,
        dense_vector_name: str = "dense",
        sparse_vector_name: str = "lexical",
    ) -> None:
        if document_limit < 1:
            raise ValueError("Global document limit must be positive.")
        if not dense_vector_name or not sparse_vector_name:
            raise ValueError("Qdrant vector names cannot be empty.")
        if embeddings.metadata.identity != scope.embedding_identity:
            raise ValueError("Embedding service identity does not match the global retrieval scope.")
        self._client = client
        self._embeddings = embeddings
        self._scope = scope
        self._document_limit = document_limit
        self._dense_vector_name = dense_vector_name
        self._sparse_vector_name = sparse_vector_name

    @property
    def scope(self) -> GlobalRetrievalScope:
        return self._scope

    async def search_documents(
        self,
        query: str,
        *,
        document_limit: int | None = None,
        category: str | None = None,
    ) -> GlobalRetrievalResult:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Global retrieval query cannot be empty.")
        limit = self._document_limit if document_limit is None else document_limit
        if limit < 1:
            raise ValueError("Global document limit must be positive.")

        started = time.perf_counter()
        query_filter = build_global_scope_filter(self._scope, category=category)
        lexical = sparse_vector(query)

        embedding_started = time.perf_counter()
        try:
            dense_vector = await self._embeddings.embed_query(query)
            dense_fallback_reason = None
        except EmbeddingError as exc:
            if _is_authorization_failure(exc):
                raise
            dense_vector = None
            dense_fallback_reason = "embedding-error"
        embedding_latency_ms = (time.perf_counter() - embedding_started) * 1_000

        dense_request = (
            self._search_channel(
                channel=RetrievalChannel.DENSE,
                query=dense_vector,
                vector_name=self._dense_vector_name,
                query_filter=query_filter,
                limit=limit,
                category=category,
            )
            if dense_vector is not None
            else None
        )
        sparse_request = (
            self._search_channel(
                channel=RetrievalChannel.SPARSE,
                query=lexical,
                vector_name=self._sparse_vector_name,
                query_filter=query_filter,
                limit=limit,
                category=category,
            )
            if lexical.indices
            else None
        )

        if dense_request is not None and sparse_request is not None:
            dense_task = asyncio.create_task(dense_request)
            sparse_task = asyncio.create_task(sparse_request)
            try:
                dense, sparse = await asyncio.gather(dense_task, sparse_task)
            except BaseException:
                for task in (dense_task, sparse_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(dense_task, sparse_task, return_exceptions=True)
                raise
        elif dense_request is not None:
            dense = await dense_request
            sparse = _unavailable_channel(RetrievalChannel.SPARSE, "empty-sparse-query")
        elif sparse_request is not None:
            dense = _unavailable_channel(
                RetrievalChannel.DENSE,
                dense_fallback_reason or "dense-unavailable",
            )
            sparse = await sparse_request
        else:
            dense = _unavailable_channel(
                RetrievalChannel.DENSE,
                dense_fallback_reason or "dense-unavailable",
            )
            sparse = _unavailable_channel(RetrievalChannel.SPARSE, "empty-sparse-query")

        return GlobalRetrievalResult(
            dense=dense,
            sparse=sparse,
            embedding_latency_ms=embedding_latency_ms,
            total_latency_ms=(time.perf_counter() - started) * 1_000,
        )

    async def _search_channel(
        self,
        *,
        channel: RetrievalChannel,
        query: list[float] | models.SparseVector,
        vector_name: str,
        query_filter: models.Filter,
        limit: int,
        category: str | None,
    ) -> ChannelRetrievalResult:
        started = time.perf_counter()
        try:
            response = await self._client.query_points(
                collection_name=self._scope.collection_name,
                query=query,
                using=vector_name,
                query_filter=query_filter,
                limit=limit,
                with_payload=list(PAYLOAD_FIELDS),
                with_vectors=False,
            )
        except Exception as exc:
            if _is_authorization_failure(exc):
                raise
            return ChannelRetrievalResult(
                channel=channel,
                available=False,
                fallback_reason="qdrant-error",
                latency_ms=(time.perf_counter() - started) * 1_000,
            )

        points = list(getattr(response, "points", ()) or ())
        hits: list[GlobalDocumentHit] = []
        rejected = 0
        for rank, point in enumerate(points, start=1):
            hit = _validated_hit(
                point,
                channel=channel,
                rank=rank,
                scope=self._scope,
                category=category,
            )
            if hit is None:
                rejected += 1
            else:
                hits.append(hit)
        return ChannelRetrievalResult(
            channel=channel,
            hits=tuple(hits),
            returned_points=len(points),
            rejected_points=rejected,
            latency_ms=(time.perf_counter() - started) * 1_000,
        )


def build_global_scope_filter(
    scope: GlobalRetrievalScope,
    *,
    category: str | None = None,
) -> models.Filter:
    """Build a fail-closed filter for the exact corpus and embedding namespace."""

    must: list[models.Condition] = [
        _keyword_condition("index_scope", scope.index_scope),
        _keyword_condition("retrieval_version", scope.retrieval_version),
        _keyword_condition("data_version", scope.data_version),
        _keyword_condition("dataset_sha256", scope.dataset_sha256),
        _keyword_condition("embedding_identity", scope.embedding_identity),
        models.FieldCondition(
            key="security_test",
            match=models.MatchValue(value=False),
        ),
    ]
    if category:
        must.append(_keyword_condition("category", category))
    return models.Filter(must=must)


def _keyword_condition(key: str, value: str) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchValue(value=value))


def _unavailable_channel(
    channel: RetrievalChannel,
    reason: str,
) -> ChannelRetrievalResult:
    return ChannelRetrievalResult(
        channel=channel,
        available=False,
        fallback_reason=reason,
    )


def _validated_hit(
    point: Any,
    *,
    channel: RetrievalChannel,
    rank: int,
    scope: GlobalRetrievalScope,
    category: str | None,
) -> GlobalDocumentHit | None:
    payload = getattr(point, "payload", None)
    if not isinstance(payload, Mapping) or not _payload_matches_scope(
        payload,
        scope=scope,
        category=category,
    ):
        return None
    shop_id = payload.get("shop_id")
    if isinstance(shop_id, bool) or not isinstance(shop_id, int) or shop_id <= 0:
        return None
    root_id = payload.get("root_id")
    if isinstance(root_id, bool) or not isinstance(root_id, int) or root_id <= 0:
        root_id = None
    score = getattr(point, "score", None)
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
        return None
    try:
        return GlobalDocumentHit(
            point_id=str(getattr(point, "id", "")),
            shop_id=shop_id,
            shop_external_id=_required_string(payload, "shop_external_id"),
            channel=channel,
            rank=rank,
            score=float(score),
            document_id=_required_string(payload, "document_id"),
            source_id=_required_string(payload, "source_id"),
            root_id=root_id,
            content_type=_required_string(payload, "content_type"),
            document_kind=str(payload.get("document_kind") or "evidence"),
            text=_required_string(payload, "text"),
        )
    except (TypeError, ValueError, ValidationError):
        return None


def _payload_matches_scope(
    payload: Mapping[str, Any],
    *,
    scope: GlobalRetrievalScope,
    category: str | None,
) -> bool:
    expected = {
        "index_scope": scope.index_scope,
        "retrieval_version": scope.retrieval_version,
        "data_version": scope.data_version,
        "dataset_sha256": scope.dataset_sha256,
        "embedding_identity": scope.embedding_identity,
    }
    if any(str(payload.get(key) or "") != value for key, value in expected.items()):
        return False
    if category and str(payload.get("category") or "") != category:
        return False
    # Missing, nullable, or stringly-typed safety markers are malformed index
    # payloads. Only the explicit boolean false value is safe to retrieve.
    return payload.get("security_test") is False


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Qdrant payload field {key!r} must be a non-empty string.")
    return value


def _is_authorization_failure(error: BaseException) -> bool:
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code is None:
        status_code = getattr(error, "status_code", None)
    return status_code in {401, 403}
