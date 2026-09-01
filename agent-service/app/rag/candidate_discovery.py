from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.business_hours import is_shop_open
from app.domain.models import CandidateSet, ShopCandidate, UserConstraints
from app.rag.candidate_fusion import CandidateFusionResult, fuse_candidates
from app.rag.global_retrieval import GlobalRetrievalResult, RetrievalChannel
from app.rag.merchant_aggregation import MerchantAggregationResult, aggregate_merchants
from app.rag.query_plan import build_retrieval_plan
from app.tools.services import (
    HARD_DESIRED_TAGS,
    RagService,
    ShopToolService,
    haversine_meters,
    neighborhood_matches,
)


class CandidateDiscovery(Protocol):
    """Single candidate-discovery entry point shared by Agent and MCP paths."""

    async def discover(
        self,
        constraints: UserConstraints,
        *,
        limit: int,
    ) -> CandidateSet: ...


class GlobalDocumentRetriever(Protocol):
    @property
    def scope(self): ...

    async def search_documents(
        self,
        query: str,
        *,
        document_limit: int | None = None,
        category: str | None = None,
    ) -> GlobalRetrievalResult: ...


class CandidateDiscoveryError(RuntimeError):
    """Raised when neither candidate-discovery branch can return a safe result."""


@dataclass(frozen=True)
class _BranchOutcome:
    value: Any | None
    error: Exception | None
    reason: str | None
    latency_ms: float


class LegacyCandidateDiscovery:
    """Preserve the pre-M2 structured-search then candidate-filtered RAG path."""

    def __init__(self, shops: ShopToolService, rag: RagService):
        self._shops = shops
        self._rag = rag

    async def discover(
        self,
        constraints: UserConstraints,
        *,
        limit: int,
    ) -> CandidateSet:
        candidate_pool = await self._shops.search(constraints)
        return await rank_candidates(
            self._rag,
            constraints,
            candidate_pool,
            limit=limit,
        )


class GlobalHybridCandidateDiscovery:
    """Orchestrate structured and global retrieval behind the M2 feature flag."""

    def __init__(
        self,
        shops: ShopToolService,
        rag: RagService,
        global_retriever: GlobalDocumentRetriever,
        *,
        document_limit: int = 200,
        hydration_limit: int = 60,
        hydration_concurrency: int = 8,
        branch_timeout_seconds: float = 15.0,
        documents_per_merchant: int = 3,
        rrf_k: int = 60,
        brand_cap: int = 2,
    ) -> None:
        if document_limit < 1:
            raise ValueError("Global document limit must be positive.")
        if hydration_limit < 1 or hydration_limit > 100:
            raise ValueError("Hydration limit must be between 1 and 100.")
        if hydration_concurrency < 1:
            raise ValueError("Hydration concurrency must be positive.")
        if branch_timeout_seconds <= 0:
            raise ValueError("Candidate branch timeout must be positive.")
        if documents_per_merchant < 1:
            raise ValueError("Documents per merchant must be positive.")
        if rrf_k < 1 or brand_cap < 1:
            raise ValueError("Fusion bounds must be positive.")
        self._shops = shops
        # Keep the RAG argument in the constructor so runtime/eval factories share
        # one stable signature. M2 fallback deliberately never calls it: a global
        # Qdrant outage must not be retried through candidate-filtered Qdrant.
        self._rag = rag
        self._global = global_retriever
        self._document_limit = document_limit
        self._hydration_limit = hydration_limit
        self._hydration_concurrency = hydration_concurrency
        self._branch_timeout_seconds = branch_timeout_seconds
        self._documents_per_merchant = documents_per_merchant
        self._rrf_k = rrf_k
        self._brand_cap = brand_cap

    async def discover(
        self,
        constraints: UserConstraints,
        *,
        limit: int,
    ) -> CandidateSet:
        if limit < 1:
            raise ValueError("Candidate limit must be positive.")
        started = time.perf_counter()
        scope = self._global.scope
        plan = build_retrieval_plan(
            constraints,
            retrieval_version=scope.retrieval_version,
            data_version=scope.data_version,
            dataset_sha256=scope.dataset_sha256,
        )
        structured_task = asyncio.create_task(
            _run_branch(
                self._shops.search(constraints),
                timeout_seconds=self._branch_timeout_seconds,
            )
        )
        global_task = asyncio.create_task(
            _run_branch(
                self._global.search_documents(
                    plan.expanded_query,
                    document_limit=self._document_limit,
                    category=constraints.category,
                ),
                timeout_seconds=self._branch_timeout_seconds,
            )
        )
        try:
            structured_outcome, global_outcome = await asyncio.gather(
                structured_task,
                global_task,
            )
        except BaseException:
            for task in (structured_task, global_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(structured_task, global_task, return_exceptions=True)
            raise

        authorization_error = next(
            (
                error
                for error in (structured_outcome.error, global_outcome.error)
                if _is_authorization_failure(error)
            ),
            None,
        )
        if authorization_error is not None:
            raise CandidateDiscoveryError(
                "Candidate discovery authorization failed."
            ) from authorization_error

        structured_pool = (
            structured_outcome.value
            if isinstance(structured_outcome.value, CandidateSet)
            else None
        )
        global_result = (
            global_outcome.value
            if isinstance(global_outcome.value, GlobalRetrievalResult)
            else None
        )
        global_available = bool(
            global_result is not None
            and (global_result.dense.available or global_result.sparse.available)
        )
        if not global_available:
            if structured_pool is None:
                raise CandidateDiscoveryError(
                    "Structured and global candidate discovery are unavailable."
                ) from (structured_outcome.error or global_outcome.error)
            filtered_structured, hard_filter_stats = _hard_filter_candidates(
                list(structured_pool.candidates),
                constraints,
                required_data_version=scope.data_version,
                expected_external_ids=None,
            )
            safe_structured_pool = structured_pool.model_copy(
                update={
                    "candidates": filtered_structured,
                    "applied_constraints": list(
                        dict.fromkeys(
                            [
                                *structured_pool.applied_constraints,
                                *_applied_constraints(constraints),
                            ]
                        )
                    ),
                }
            )
            return self._structured_fallback(
                safe_structured_pool,
                limit=limit,
                fallback_metadata=_fallback_metadata(
                    structured_outcome=structured_outcome,
                    global_outcome=global_outcome,
                    total_latency_ms=_elapsed_ms(started),
                    global_result=global_result,
                    hard_filter_stats=hard_filter_stats,
                ),
            )

        aggregation_started = time.perf_counter()
        aggregation = aggregate_merchants(
            global_result,
            documents_per_merchant=self._documents_per_merchant,
        )
        aggregation_latency_ms = _elapsed_ms(aggregation_started)

        structured_candidates = list(
            structured_pool.candidates if structured_pool is not None else ()
        )
        structured_by_id = {candidate.shop_id: candidate for candidate in structured_candidates}
        global_signal_ids = {
            merchant.shop_id
            for channel in (RetrievalChannel.DENSE, RetrievalChannel.SPARSE)
            for merchant in aggregation.ranking(channel).merchants
        }
        expected_external_ids = {
            shop_id: aggregation.expected_external_id(shop_id)
            for shop_id in global_signal_ids
        }
        filtered_structured, structured_filter_stats = _hard_filter_candidates(
            structured_candidates,
            constraints,
            required_data_version=scope.data_version,
            expected_external_ids=expected_external_ids,
        )
        safe_structured_pool = (
            structured_pool.model_copy(
                update={
                    "candidates": filtered_structured,
                    "applied_constraints": list(
                        dict.fromkeys(
                            [
                                *structured_pool.applied_constraints,
                                *_applied_constraints(constraints),
                            ]
                        )
                    ),
                }
            )
            if structured_pool is not None
            else None
        )
        requested_global_ids = self._global_hydration_ids(aggregation)
        missing_ids = [
            shop_id for shop_id in requested_global_ids if shop_id not in structured_by_id
        ]
        hydration_started = time.perf_counter()
        try:
            hydrated_rows = await self._hydrate(missing_ids)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _is_authorization_failure(exc):
                raise CandidateDiscoveryError(
                    "Candidate hydration authorization failed."
                ) from exc
            if safe_structured_pool is None:
                raise CandidateDiscoveryError(
                    "Global candidates could not be hydrated and structured retrieval is unavailable."
                ) from exc
            return self._structured_fallback(
                safe_structured_pool,
                limit=limit,
                fallback_metadata=_fallback_metadata(
                    structured_outcome=structured_outcome,
                    global_outcome=global_outcome,
                    total_latency_ms=_elapsed_ms(started),
                    global_result=global_result,
                    aggregation=aggregation,
                    hard_filter_stats=structured_filter_stats,
                    reason="hydration-error",
                ),
            )
        hydration_latency_ms = _elapsed_ms(hydration_started)

        global_hydrated = {
            candidate.shop_id: _with_query_distance(candidate, constraints)
            for candidate in hydrated_rows
        }
        filtered_global, global_filter_stats = _hard_filter_candidates(
            list(global_hydrated.values()),
            constraints,
            required_data_version=scope.data_version,
            expected_external_ids=expected_external_ids,
        )
        filtered_global_by_id = {candidate.shop_id: candidate for candidate in filtered_global}
        hard_filter_stats = _merge_counts(structured_filter_stats, global_filter_stats)

        fusion_started = time.perf_counter()
        try:
            fusion = fuse_candidates(
                filtered_structured,
                aggregation,
                filtered_global_by_id,
                limit=limit,
                rrf_k=self._rrf_k,
                brand_cap=self._brand_cap,
            )
        except Exception as exc:
            if safe_structured_pool is None:
                raise CandidateDiscoveryError(
                    "Candidate fusion failed and structured retrieval is unavailable."
                ) from exc
            return self._structured_fallback(
                safe_structured_pool,
                limit=limit,
                fallback_metadata=_fallback_metadata(
                    structured_outcome=structured_outcome,
                    global_outcome=global_outcome,
                    total_latency_ms=_elapsed_ms(started),
                    global_result=global_result,
                    aggregation=aggregation,
                    hard_filter_stats=hard_filter_stats,
                    reason="fusion-error",
                ),
            )
        fusion_latency_ms = _elapsed_ms(fusion_started)
        return self._candidate_set(
            constraints=constraints,
            structured_pool=safe_structured_pool,
            fusion=fusion,
            aggregation=aggregation,
            global_result=global_result,
            structured_outcome=structured_outcome,
            global_outcome=global_outcome,
            hydration_requested=len(missing_ids),
            hydration_returned=len(hydrated_rows),
            hard_filter_stats=hard_filter_stats,
            aggregation_latency_ms=aggregation_latency_ms,
            hydration_latency_ms=hydration_latency_ms,
            fusion_latency_ms=fusion_latency_ms,
            total_latency_ms=_elapsed_ms(started),
        )

    def _structured_fallback(
        self,
        structured_pool: CandidateSet,
        *,
        limit: int,
        fallback_metadata: Mapping[str, Any],
    ) -> CandidateSet:
        candidates = structured_pool.candidates[:limit]
        return structured_pool.model_copy(
            update={
                "candidates": candidates,
                "retrieval_metadata": {
                    **structured_pool.retrieval_metadata,
                    **fallback_metadata,
                    "retrievalVersion": self._global.scope.retrieval_version,
                    "candidatePool": len(structured_pool.candidates),
                    "finalCandidates": len(candidates),
                },
            }
        )

    def _global_hydration_ids(
        self,
        aggregation: MerchantAggregationResult,
    ) -> list[int]:
        channel_ranks: dict[int, list[int]] = {}
        for channel in (RetrievalChannel.DENSE, RetrievalChannel.SPARSE):
            for merchant in aggregation.ranking(channel).merchants:
                channel_ranks.setdefault(merchant.shop_id, []).append(merchant.merchant_rank)
        ordered = sorted(
            channel_ranks,
            key=lambda shop_id: (
                -sum(1.0 / (self._rrf_k + rank) for rank in channel_ranks[shop_id]),
                min(channel_ranks[shop_id]),
                shop_id,
            ),
        )
        return ordered[: self._hydration_limit]

    async def _hydrate(self, shop_ids: list[int]) -> list[ShopCandidate]:
        if not shop_ids:
            return []
        batch_loader = getattr(self._shops, "details", None)
        if batch_loader is not None:
            async with asyncio.timeout(self._branch_timeout_seconds):
                return list(await batch_loader(shop_ids))

        semaphore = asyncio.Semaphore(self._hydration_concurrency)

        async def load(shop_id: int) -> ShopCandidate | None:
            async with semaphore:
                try:
                    return await self._shops.detail(shop_id)
                except Exception as exc:
                    if _is_authorization_failure(exc):
                        raise
                    return None

        tasks = [asyncio.create_task(load(shop_id)) for shop_id in shop_ids]
        try:
            async with asyncio.timeout(self._branch_timeout_seconds):
                rows = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return [row for row in rows if row is not None]

    def _candidate_set(
        self,
        *,
        constraints: UserConstraints,
        structured_pool: CandidateSet | None,
        fusion: CandidateFusionResult,
        aggregation: MerchantAggregationResult,
        global_result: GlobalRetrievalResult,
        structured_outcome: _BranchOutcome,
        global_outcome: _BranchOutcome,
        hydration_requested: int,
        hydration_returned: int,
        hard_filter_stats: dict[str, int],
        aggregation_latency_ms: float,
        hydration_latency_ms: float,
        fusion_latency_ms: float,
        total_latency_ms: float,
    ) -> CandidateSet:
        candidates = list(fusion.candidates)
        relaxed = list(structured_pool.relaxed_constraints if structured_pool else ())
        warnings = list(structured_pool.warnings if structured_pool else ())
        if structured_pool is None:
            warnings.append(
                "Structured retrieval was unavailable; candidates use global Qdrant retrieval."
            )
        if hydration_returned < hydration_requested:
            warnings.append("Some globally retrieved merchants could not be hydrated.")
        if constraints.budget_cents is not None and any(
            candidate.avg_price_cents is None for candidate in candidates
        ):
            relaxed.append("budget")
            warnings.append(
                "Some candidates have no price, so their budget fit could not be verified."
            )
        metadata = {
            **(structured_pool.retrieval_metadata if structured_pool else {}),
            "globalRetrievalEnabled": True,
            "candidateDiscoveryMode": "global-hybrid",
            "retrievalVersion": self._global.scope.retrieval_version,
            "structuredCandidates": fusion.stats.structured_candidates,
            "globalDenseDocuments": len(global_result.dense.hits),
            "globalSparseDocuments": len(global_result.sparse.hits),
            "globalMerchants": fusion.stats.global_merchants,
            "fusionCandidates": fusion.stats.fusion_candidates,
            "structuredOnlyMerchants": fusion.stats.structured_only_merchants,
            "qdrantOnlyMerchants": fusion.stats.qdrant_only_merchants,
            "overlapMerchants": fusion.stats.overlap_merchants,
            "hydrationRequested": hydration_requested,
            "hydratedCandidates": hydration_returned,
            "hydrationMissing": max(0, hydration_requested - hydration_returned),
            "missingHydratedCandidates": fusion.stats.missing_hydrated_candidates,
            "duplicateDocumentsSuppressed": aggregation.suppression.duplicate_documents,
            "duplicateShopIdsSuppressed": fusion.stats.duplicate_shop_ids_suppressed,
            "duplicateMerchantsSuppressed": fusion.stats.duplicate_merchants_suppressed,
            "duplicateBrandsSuppressed": fusion.stats.duplicate_brands_suppressed,
            "identityConflicts": aggregation.identity_conflicts,
            "identityConflictShopIds": list(aggregation.identity_conflict_shop_ids),
            "identityMismatches": hard_filter_stats.get("externalIdentity", 0),
            "hardConstraintFiltered": sum(hard_filter_stats.values()),
            "hardConstraintFilteredByReason": hard_filter_stats,
            "structuredFallback": structured_outcome.error is not None,
            "globalFallback": False,
            **_global_trace_metadata(global_result),
            "globalEmbeddingLatencyMs": round(global_result.embedding_latency_ms, 3),
            "candidateDiscoveryLatencyMs": {
                "structured": round(structured_outcome.latency_ms, 3),
                "global": round(global_outcome.latency_ms, 3),
                "aggregation": round(aggregation_latency_ms, 3),
                "hydration": round(hydration_latency_ms, 3),
                "fusion": round(fusion_latency_ms, 3),
                "total": round(total_latency_ms, 3),
            },
            "candidatePool": fusion.stats.fusion_candidates,
            "finalCandidates": len(candidates),
        }
        return CandidateSet(
            candidates=candidates,
            applied_constraints=(
                structured_pool.applied_constraints
                if structured_pool is not None
                else _applied_constraints(constraints)
            ),
            relaxed_constraints=list(dict.fromkeys(relaxed)),
            warnings=list(dict.fromkeys(warnings)),
            retrieval_metadata=metadata,
        )


async def rank_candidates(
    rag: RagService,
    constraints: UserConstraints,
    candidate_pool: CandidateSet,
    *,
    limit: int,
) -> CandidateSet:
    """Keep lightweight/custom RAG adapters compatible with the P12 contract."""

    ranker = getattr(rag, "rank_candidates", None)
    if ranker is not None:
        return await ranker(constraints, candidate_pool, limit=limit)
    return candidate_pool.model_copy(
        update={
            "candidates": candidate_pool.candidates[:limit],
            "retrieval_metadata": {
                **candidate_pool.retrieval_metadata,
                "retrievalVersion": "legacy-adapter",
                "candidatePool": len(candidate_pool.candidates),
                "finalCandidates": min(limit, len(candidate_pool.candidates)),
            },
        }
    )


async def _run_branch(
    awaitable: Awaitable[Any],
    *,
    timeout_seconds: float,
) -> _BranchOutcome:
    started = time.perf_counter()
    try:
        async with asyncio.timeout(timeout_seconds):
            value = await awaitable
        return _BranchOutcome(
            value=value,
            error=None,
            reason=None,
            latency_ms=_elapsed_ms(started),
        )
    except TimeoutError as exc:
        return _BranchOutcome(
            value=None,
            error=exc,
            reason="timeout",
            latency_ms=_elapsed_ms(started),
        )
    except Exception as exc:
        return _BranchOutcome(
            value=None,
            error=exc,
            reason="error",
            latency_ms=_elapsed_ms(started),
        )


def _fallback_metadata(
    *,
    structured_outcome: _BranchOutcome,
    global_outcome: _BranchOutcome,
    total_latency_ms: float,
    global_result: GlobalRetrievalResult | None,
    aggregation: MerchantAggregationResult | None = None,
    hard_filter_stats: Mapping[str, int] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    dense_reason = global_result.dense.fallback_reason if global_result else None
    sparse_reason = global_result.sparse.fallback_reason if global_result else None
    return {
        "globalRetrievalEnabled": True,
        "candidateDiscoveryMode": "structured-fallback",
        "structuredFallback": structured_outcome.error is not None,
        "globalFallback": True,
        "globalFallbackReason": reason or global_outcome.reason or dense_reason or sparse_reason,
        **_global_trace_metadata(global_result),
        "globalEmbeddingLatencyMs": round(
            global_result.embedding_latency_ms if global_result is not None else 0.0,
            3,
        ),
        "identityConflicts": aggregation.identity_conflicts if aggregation else 0,
        "identityConflictShopIds": (
            list(aggregation.identity_conflict_shop_ids) if aggregation else []
        ),
        "identityMismatches": (
            hard_filter_stats.get("externalIdentity", 0) if hard_filter_stats else 0
        ),
        "hardConstraintFiltered": sum(hard_filter_stats.values()) if hard_filter_stats else 0,
        "hardConstraintFilteredByReason": dict(hard_filter_stats or {}),
        "candidateDiscoveryLatencyMs": {
            "structured": round(structured_outcome.latency_ms, 3),
            "global": round(global_outcome.latency_ms, 3),
            "total": round(total_latency_ms, 3),
        },
    }


def _global_trace_metadata(
    result: GlobalRetrievalResult | None,
) -> dict[str, Any]:
    if result is None:
        return {
            "globalDenseAvailable": False,
            "globalSparseAvailable": False,
            "globalDenseFallbackReason": None,
            "globalSparseFallbackReason": None,
            "globalDenseLatencyMs": 0.0,
            "globalSparseLatencyMs": 0.0,
            "globalDenseReturnedPoints": 0,
            "globalSparseReturnedPoints": 0,
            "globalDenseRejectedPoints": 0,
            "globalSparseRejectedPoints": 0,
        }
    return {
        "globalDenseAvailable": result.dense.available,
        "globalSparseAvailable": result.sparse.available,
        "globalDenseFallbackReason": result.dense.fallback_reason,
        "globalSparseFallbackReason": result.sparse.fallback_reason,
        "globalDenseLatencyMs": round(result.dense.latency_ms, 3),
        "globalSparseLatencyMs": round(result.sparse.latency_ms, 3),
        "globalDenseReturnedPoints": result.dense.returned_points,
        "globalSparseReturnedPoints": result.sparse.returned_points,
        "globalDenseRejectedPoints": result.dense.rejected_points,
        "globalSparseRejectedPoints": result.sparse.rejected_points,
    }


def _hard_filter_candidates(
    candidates: list[ShopCandidate],
    constraints: UserConstraints,
    *,
    required_data_version: str | None,
    expected_external_ids: Mapping[int, str | None] | None,
) -> tuple[list[ShopCandidate], dict[str, int]]:
    retained: list[ShopCandidate] = []
    rejected: dict[str, int] = {}
    per_person_budget = (
        constraints.budget_cents // constraints.party_size
        if constraints.budget_cents is not None
        else None
    )
    hard_tags = set(constraints.desired_tags) & HARD_DESIRED_TAGS
    for candidate in candidates:
        reason = None
        if candidate.business_status != "OPERATIONAL":
            reason = "businessStatus"
        elif constraints.category and candidate.category != constraints.category:
            reason = "category"
        elif constraints.neighborhood and not neighborhood_matches(
            candidate.neighborhood,
            constraints.neighborhood,
        ):
            reason = "neighborhood"
        elif (
            per_person_budget is not None
            and candidate.avg_price_cents is not None
            and candidate.avg_price_cents > per_person_budget
        ):
            reason = "budget"
        elif not hard_tags.issubset(candidate.tags):
            reason = "requiredTags"
        elif constraints.visit_time and (
            not candidate.business_hours
            or not is_shop_open(candidate, constraints.visit_time)
        ):
            reason = "visitTime"
        elif (
            required_data_version is not None
            and candidate.data_version != required_data_version
        ):
            reason = "dataVersion"
        elif (
            expected_external_ids is not None
            and candidate.shop_id in expected_external_ids
            and (
                expected_external_ids[candidate.shop_id] is None
                or candidate.external_id is None
                or candidate.external_id.strip()
                != expected_external_ids[candidate.shop_id]
            )
        ):
            reason = "externalIdentity"
        if reason is None:
            retained.append(candidate)
        else:
            rejected[reason] = rejected.get(reason, 0) + 1
    return retained, rejected


def _is_authorization_failure(error: BaseException | None) -> bool:
    if error is None:
        return False
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code is None:
        status_code = getattr(error, "status_code", None)
    return status_code in {401, 403}


def _with_query_distance(
    candidate: ShopCandidate,
    constraints: UserConstraints,
) -> ShopCandidate:
    if constraints.latitude is None or constraints.longitude is None:
        return candidate
    return candidate.model_copy(
        update={
            "distance_meters": haversine_meters(
                constraints.latitude,
                constraints.longitude,
                candidate.latitude,
                candidate.longitude,
            )
        }
    )


def _applied_constraints(constraints: UserConstraints) -> list[str]:
    return [
        name
        for name, value in (
            ("category", constraints.category),
            ("neighborhood", constraints.neighborhood),
            ("budget", constraints.budget_cents),
            ("desired_tags", constraints.desired_tags),
            ("visit_time", constraints.visit_time),
        )
        if value
    ]


def _merge_counts(*values: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for value in values:
        for key, count in value.items():
            merged[key] = merged.get(key, 0) + count
    return dict(sorted(merged.items()))


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1_000
