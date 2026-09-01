from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from qdrant_client import models

from app.rag.embeddings import EmbeddingError, EmbeddingService
from app.rag.lexical import sparse_vector


class RetrievalChannel(StrEnum):
    DENSE = "dense"
    SPARSE = "sparse"


class QueryVariantSource(StrEnum):
    ORIGINAL = "original"
    RULES = "rules"
    LLM = "llm"


class VariantRetrievalStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"


MAX_QUERY_VARIANTS = 5
MAX_LLM_QUERY_VARIANTS = 3
MAX_QUERY_VARIANT_LENGTH = 2_000
MAX_QUERY_VARIANT_ID_LENGTH = 64
DEFAULT_QUERY_VARIANT_TIMEOUT_SECONDS = 10.0
MAX_VARIANT_TIMEOUT_SECONDS = 120.0
_EMBED_QUERY = object()


class GlobalQueryVariant(BaseModel):
    """One bounded query with provenance retained through global retrieval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    variant_id: str = Field(min_length=1, max_length=MAX_QUERY_VARIANT_ID_LENGTH)
    source: QueryVariantSource
    query: str = Field(min_length=1, max_length=MAX_QUERY_VARIANT_LENGTH)

    @field_validator("variant_id")
    @classmethod
    def _normalize_variant_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Query variant fields cannot be blank.")
        return value.strip()

    @field_validator("query")
    @classmethod
    def _reject_blank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Query variant fields cannot be blank.")
        return value


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


class VariantGlobalRetrievalResult(GlobalRetrievalResult):
    """A backwards-compatible retrieval result paired with query provenance."""

    variant: GlobalQueryVariant
    status: VariantRetrievalStatus = VariantRetrievalStatus.COMPLETE
    fallback_reason: str | None = None


class VariantHitProvenance(BaseModel):
    """Connect one raw channel hit to the variant that retrieved it."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    variant_id: str = Field(min_length=1, max_length=MAX_QUERY_VARIANT_ID_LENGTH)
    source: QueryVariantSource
    channel: RetrievalChannel
    point_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    shop_id: int = Field(gt=0)
    variant_rank: int = Field(ge=1)
    score: float


class MultiQueryRetrievalTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_variant_ids: tuple[str, ...]
    completed_variant_ids: tuple[str, ...]
    partial_failure_variant_ids: tuple[str, ...] = ()
    timed_out_variant_ids: tuple[str, ...] = ()
    failed_variant_ids: tuple[str, ...] = ()


class MultiQueryGlobalRetrievalResult(GlobalRetrievalResult):
    """Merged M2-compatible view plus ordered, provenance-safe variant results."""

    variants: tuple[VariantGlobalRetrievalResult, ...] = Field(
        min_length=1,
        max_length=MAX_QUERY_VARIANTS,
    )
    provenance: tuple[VariantHitProvenance, ...] = ()
    trace: MultiQueryRetrievalTrace

    def result_for(self, variant_id: str) -> VariantGlobalRetrievalResult:
        for result in self.variants:
            if result.variant.variant_id == variant_id:
                return result
        raise KeyError(f"No retrieval result exists for query variant {variant_id!r}.")


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
    "neighborhood",
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
        neighborhood: str | None = None,
    ) -> GlobalRetrievalResult:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Global retrieval query cannot be empty.")
        limit = self._document_limit if document_limit is None else document_limit
        if limit < 1:
            raise ValueError("Global document limit must be positive.")

        started = time.perf_counter()
        query_filter = build_global_scope_filter(
            self._scope,
            category=category,
            neighborhood=neighborhood,
        )
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
                neighborhood=neighborhood,
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
                neighborhood=neighborhood,
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

    async def search_query_variants(
        self,
        variants: Sequence[GlobalQueryVariant],
        *,
        document_limit: int | None = None,
        category: str | None = None,
        neighborhood: str | None = None,
        variant_timeout_seconds: float = DEFAULT_QUERY_VARIANT_TIMEOUT_SECONDS,
    ) -> MultiQueryGlobalRetrievalResult:
        """Retrieve every query variant independently while sharing one scope.

        Dense and sparse retrieval remain paired within each variant, so one
        paid query embedding is reused for both channels. The merged top-level
        channels retain the M2 ``GlobalRetrievalResult`` contract; callers that
        implement query-level RRF should consume ``variants`` instead.
        """

        normalized_variants = _validated_query_variants(variants)
        if (
            isinstance(variant_timeout_seconds, bool)
            or not isinstance(variant_timeout_seconds, (int, float))
            or not math.isfinite(variant_timeout_seconds)
            or variant_timeout_seconds <= 0
            or variant_timeout_seconds > MAX_VARIANT_TIMEOUT_SECONDS
        ):
            raise ValueError(
                "Query variant timeout must be positive and no greater than "
                f"{MAX_VARIANT_TIMEOUT_SECONDS:g} seconds."
            )

        started = time.perf_counter()
        batch_embedding_latency_ms = 0.0
        precomputed_vectors: tuple[list[float] | None, ...] | None = None
        batch_embedder = getattr(self._embeddings, "embed_queries", None)
        if callable(batch_embedder):
            embedding_started = time.perf_counter()
            try:
                async with asyncio.timeout(float(variant_timeout_seconds)):
                    embedded = await batch_embedder(
                        [variant.query for variant in normalized_variants]
                    )
                if len(embedded) != len(normalized_variants):
                    raise ValueError("Query embedding batch returned an invalid vector count.")
                precomputed_vectors = tuple(embedded)
            except TimeoutError:
                batch_embedding_latency_ms = (
                    time.perf_counter() - embedding_started
                ) * 1_000
                variant_results = tuple(
                    _failed_variant_result(
                        variant,
                        status=VariantRetrievalStatus.TIMEOUT,
                        reason="timeout",
                        total_latency_ms=batch_embedding_latency_ms,
                    )
                    for variant in normalized_variants
                )
                return _multi_query_result(
                    normalized_variants,
                    variant_results,
                    embedding_latency_ms=batch_embedding_latency_ms,
                    total_latency_ms=(time.perf_counter() - started) * 1_000,
                )
            except Exception as exc:
                if _is_authorization_failure(exc):
                    raise
                # One failed provider batch must not fan out into one paid retry
                # per variant. Continue once with sparse-only retrieval instead.
                precomputed_vectors = tuple(None for _ in normalized_variants)
            finally:
                if batch_embedding_latency_ms == 0.0:
                    batch_embedding_latency_ms = (
                        time.perf_counter() - embedding_started
                    ) * 1_000

        elapsed_seconds = time.perf_counter() - started
        remaining_timeout_seconds = max(
            0.001,
            float(variant_timeout_seconds) - elapsed_seconds,
        )
        tasks = [
            asyncio.create_task(
                self._search_query_variant(
                    variant,
                    document_limit=document_limit,
                    category=category,
                    neighborhood=neighborhood,
                    timeout_seconds=remaining_timeout_seconds,
                    precomputed_dense_vector=(
                        precomputed_vectors[index]
                        if precomputed_vectors is not None
                        else _EMBED_QUERY
                    ),
                )
            )
            for index, variant in enumerate(normalized_variants)
        ]
        try:
            variant_results = tuple(await asyncio.gather(*tasks))
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        return _multi_query_result(
            normalized_variants,
            variant_results,
            embedding_latency_ms=(
                batch_embedding_latency_ms
                if precomputed_vectors is not None
                else max(
                    (result.embedding_latency_ms for result in variant_results),
                    default=0.0,
                )
            ),
            total_latency_ms=(time.perf_counter() - started) * 1_000,
        )

    async def _search_query_variant(
        self,
        variant: GlobalQueryVariant,
        *,
        document_limit: int | None,
        category: str | None,
        neighborhood: str | None,
        timeout_seconds: float,
        precomputed_dense_vector: list[float] | None | object = _EMBED_QUERY,
    ) -> VariantGlobalRetrievalResult:
        started = time.perf_counter()
        try:
            async with asyncio.timeout(timeout_seconds):
                if precomputed_dense_vector is _EMBED_QUERY:
                    result = await self.search_documents(
                        variant.query,
                        document_limit=document_limit,
                        category=category,
                        neighborhood=neighborhood,
                    )
                else:
                    result = await self._search_documents_with_dense_vector(
                        variant.query,
                        dense_vector=precomputed_dense_vector,
                        document_limit=document_limit,
                        category=category,
                        neighborhood=neighborhood,
                    )
        except TimeoutError:
            return _failed_variant_result(
                variant,
                status=VariantRetrievalStatus.TIMEOUT,
                reason="timeout",
                total_latency_ms=(time.perf_counter() - started) * 1_000,
            )
        except Exception as exc:
            if _is_authorization_failure(exc):
                raise
            return _failed_variant_result(
                variant,
                status=VariantRetrievalStatus.UNAVAILABLE,
                reason="variant-error",
                total_latency_ms=(time.perf_counter() - started) * 1_000,
            )

        status, fallback_reason = _variant_status(result)
        return VariantGlobalRetrievalResult(
            dense=result.dense,
            sparse=result.sparse,
            embedding_latency_ms=result.embedding_latency_ms,
            total_latency_ms=result.total_latency_ms,
            variant=variant,
            status=status,
            fallback_reason=fallback_reason,
        )

    async def _search_documents_with_dense_vector(
        self,
        query: str,
        *,
        dense_vector: list[float] | None | object,
        document_limit: int | None,
        category: str | None,
        neighborhood: str | None,
    ) -> GlobalRetrievalResult:
        if dense_vector is not None and not isinstance(dense_vector, list):
            raise TypeError("Precomputed dense vectors must be lists or None.")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Global retrieval query cannot be empty.")
        limit = self._document_limit if document_limit is None else document_limit
        if limit < 1:
            raise ValueError("Global document limit must be positive.")

        started = time.perf_counter()
        query_filter = build_global_scope_filter(
            self._scope,
            category=category,
            neighborhood=neighborhood,
        )
        lexical = sparse_vector(query)
        dense_request = (
            self._search_channel(
                channel=RetrievalChannel.DENSE,
                query=dense_vector,
                vector_name=self._dense_vector_name,
                query_filter=query_filter,
                limit=limit,
                category=category,
                neighborhood=neighborhood,
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
                neighborhood=neighborhood,
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
            dense = _unavailable_channel(RetrievalChannel.DENSE, "embedding-error")
            sparse = await sparse_request
        else:
            dense = _unavailable_channel(RetrievalChannel.DENSE, "embedding-error")
            sparse = _unavailable_channel(RetrievalChannel.SPARSE, "empty-sparse-query")
        return GlobalRetrievalResult(
            dense=dense,
            sparse=sparse,
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
        neighborhood: str | None,
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
                neighborhood=neighborhood,
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


def _validated_query_variants(
    variants: Sequence[GlobalQueryVariant],
) -> tuple[GlobalQueryVariant, ...]:
    if isinstance(variants, (str, bytes)):
        raise TypeError("Query variants must be a sequence of variant objects.")
    try:
        raw_variants = tuple(variants)
    except TypeError as exc:
        raise TypeError("Query variants must be a finite sequence.") from exc
    if not raw_variants:
        raise ValueError("At least one query variant is required.")
    if len(raw_variants) > MAX_QUERY_VARIANTS:
        raise ValueError(f"At most {MAX_QUERY_VARIANTS} query variants are allowed.")

    if any(not isinstance(item, GlobalQueryVariant) for item in raw_variants):
        raise TypeError("Every query variant must be a GlobalQueryVariant instance.")
    normalized = raw_variants
    variant_ids = [variant.variant_id for variant in normalized]
    if len(set(variant_ids)) != len(variant_ids):
        raise ValueError("Query variant IDs must be unique.")

    normalized_queries = [" ".join(variant.query.split()).casefold() for variant in normalized]
    if len(set(normalized_queries)) != len(normalized_queries):
        raise ValueError("Query variant texts must be unique after normalization.")

    source_counts = {
        source: sum(variant.source is source for variant in normalized) for source in QueryVariantSource
    }
    if source_counts[QueryVariantSource.ORIGINAL] != 1:
        raise ValueError("Exactly one original query variant is required.")
    if source_counts[QueryVariantSource.RULES] > 1:
        raise ValueError("At most one rules query variant is allowed.")
    if source_counts[QueryVariantSource.LLM] > MAX_LLM_QUERY_VARIANTS:
        raise ValueError(f"At most {MAX_LLM_QUERY_VARIANTS} LLM query variants are allowed.")
    return normalized


def _variant_status(
    result: GlobalRetrievalResult,
) -> tuple[VariantRetrievalStatus, str | None]:
    unavailable = tuple(channel for channel in (result.dense, result.sparse) if not channel.available)
    if not unavailable:
        return VariantRetrievalStatus.COMPLETE, None
    reason = ",".join(
        f"{channel.channel.value}:{channel.fallback_reason or 'unavailable'}" for channel in unavailable
    )
    if len(unavailable) == 1:
        return VariantRetrievalStatus.PARTIAL, reason
    return VariantRetrievalStatus.UNAVAILABLE, reason


def _failed_variant_result(
    variant: GlobalQueryVariant,
    *,
    status: VariantRetrievalStatus,
    reason: str,
    total_latency_ms: float,
) -> VariantGlobalRetrievalResult:
    return VariantGlobalRetrievalResult(
        dense=_unavailable_channel(RetrievalChannel.DENSE, reason),
        sparse=_unavailable_channel(RetrievalChannel.SPARSE, reason),
        total_latency_ms=total_latency_ms,
        variant=variant,
        status=status,
        fallback_reason=reason,
    )


def _multi_query_result(
    requested_variants: tuple[GlobalQueryVariant, ...],
    variant_results: tuple[VariantGlobalRetrievalResult, ...],
    *,
    embedding_latency_ms: float,
    total_latency_ms: float,
) -> MultiQueryGlobalRetrievalResult:
    timed_out_ids = tuple(
        result.variant.variant_id
        for result in variant_results
        if result.status is VariantRetrievalStatus.TIMEOUT
    )
    failed_ids = tuple(
        result.variant.variant_id
        for result in variant_results
        if result.fallback_reason == "variant-error"
    )
    non_completed_ids = {*timed_out_ids, *failed_ids}
    completed_ids = tuple(
        result.variant.variant_id
        for result in variant_results
        if result.variant.variant_id not in non_completed_ids
    )
    partial_failure_ids = tuple(
        result.variant.variant_id
        for result in variant_results
        if result.status is not VariantRetrievalStatus.COMPLETE
    )
    return MultiQueryGlobalRetrievalResult(
        dense=_merge_variant_channels(variant_results, RetrievalChannel.DENSE),
        sparse=_merge_variant_channels(variant_results, RetrievalChannel.SPARSE),
        embedding_latency_ms=embedding_latency_ms,
        total_latency_ms=total_latency_ms,
        variants=variant_results,
        provenance=_variant_hit_provenance(variant_results),
        trace=MultiQueryRetrievalTrace(
            requested_variant_ids=tuple(
                variant.variant_id for variant in requested_variants
            ),
            completed_variant_ids=completed_ids,
            partial_failure_variant_ids=partial_failure_ids,
            timed_out_variant_ids=timed_out_ids,
            failed_variant_ids=failed_ids,
        ),
    )


def _merge_variant_channels(
    results: tuple[VariantGlobalRetrievalResult, ...],
    channel: RetrievalChannel,
) -> ChannelRetrievalResult:
    channel_results = tuple(
        result.dense if channel is RetrievalChannel.DENSE else result.sparse for result in results
    )
    available_results = tuple(result for result in channel_results if result.available)
    ranked_hits = [
        (hit.rank, variant_index, -hit.score, hit.point_id, hit)
        for variant_index, result in enumerate(channel_results)
        for hit in result.hits
    ]
    ranked_hits.sort(key=lambda item: item[:-1])

    if not available_results:
        available = False
        fallback_reason = "all-variants-unavailable"
    elif len(available_results) < len(channel_results):
        available = True
        fallback_reason = "partial-variant-fallback"
    else:
        available = True
        fallback_reason = None
    return ChannelRetrievalResult(
        channel=channel,
        hits=tuple(item[-1] for item in ranked_hits),
        available=available,
        fallback_reason=fallback_reason,
        returned_points=sum(result.returned_points for result in channel_results),
        rejected_points=sum(result.rejected_points for result in channel_results),
        latency_ms=max((result.latency_ms for result in channel_results), default=0.0),
    )


def _variant_hit_provenance(
    results: tuple[VariantGlobalRetrievalResult, ...],
) -> tuple[VariantHitProvenance, ...]:
    return tuple(
        VariantHitProvenance(
            variant_id=result.variant.variant_id,
            source=result.variant.source,
            channel=channel.channel,
            point_id=hit.point_id,
            document_id=hit.document_id,
            shop_id=hit.shop_id,
            variant_rank=hit.rank,
            score=hit.score,
        )
        for result in results
        for channel in (result.dense, result.sparse)
        for hit in channel.hits
    )


def build_global_scope_filter(
    scope: GlobalRetrievalScope,
    *,
    category: str | None = None,
    neighborhood: str | None = None,
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
    if neighborhood:
        must.append(_keyword_condition("neighborhood", neighborhood))
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
    neighborhood: str | None,
) -> GlobalDocumentHit | None:
    payload = getattr(point, "payload", None)
    if not isinstance(payload, Mapping) or not _payload_matches_scope(
        payload,
        scope=scope,
        category=category,
        neighborhood=neighborhood,
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
    neighborhood: str | None,
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
    if neighborhood and str(payload.get("neighborhood") or "") != neighborhood:
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
