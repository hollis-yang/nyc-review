from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.business_hours import is_shop_open
from app.domain.models import CandidateSet, ShopCandidate, UserConstraints
from app.rag.candidate_fusion import CandidateFusionResult, fuse_candidates
from app.rag.global_retrieval import (
    GlobalQueryVariant,
    GlobalRetrievalResult,
    MultiQueryGlobalRetrievalResult,
    QueryVariantSource,
    RetrievalChannel,
)
from app.rag.merchant_aggregation import (
    MerchantAggregationResult,
    aggregate_merchants,
    aggregate_query_variant_merchants,
)
from app.rag.query_plan import build_retrieval_plan
from app.rag.query_rewriter import QueryRewritePlan, QueryRewriteProvider
from app.rag.reranker import (
    CandidateReranker,
    MerchantRerankTextBuilder,
    RerankCandidate,
    RerankerConfigurationError,
    RerankEvidence,
    RerankResult,
    RerankStatus,
    rerank_input_fingerprint,
)
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
        neighborhood: str | None = None,
    ) -> GlobalRetrievalResult: ...

    async def search_query_variants(
        self,
        variants: list[GlobalQueryVariant],
        *,
        document_limit: int | None = None,
        category: str | None = None,
        neighborhood: str | None = None,
        variant_timeout_seconds: float = 10.0,
    ) -> MultiQueryGlobalRetrievalResult: ...


class CandidateDiscoveryError(RuntimeError):
    """Raised when neither candidate-discovery branch can return a safe result."""


@dataclass(frozen=True)
class _BranchOutcome:
    value: Any | None
    error: Exception | None
    reason: str | None
    latency_ms: float


@dataclass(frozen=True)
class _GlobalBranchValue:
    result: GlobalRetrievalResult
    rewrite_plan: QueryRewritePlan | None = None
    rewrite_error: str | None = None


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
        fusion_pool_limit: int = 30,
        hydration_concurrency: int = 8,
        branch_timeout_seconds: float = 15.0,
        documents_per_merchant: int = 3,
        rrf_k: int = 60,
        brand_cap: int = 2,
        query_rewriter: QueryRewriteProvider | None = None,
        reranker: CandidateReranker | None = None,
        rerank_text_builder: MerchantRerankTextBuilder | None = None,
        reranker_candidate_limit: int | None = None,
    ) -> None:
        if document_limit < 1:
            raise ValueError("Global document limit must be positive.")
        if hydration_limit < 1 or hydration_limit > 100:
            raise ValueError("Hydration limit must be between 1 and 100.")
        if fusion_pool_limit < 1 or fusion_pool_limit > hydration_limit:
            raise ValueError(
                "Fusion pool limit must be positive and no greater than hydration limit."
            )
        if hydration_concurrency < 1:
            raise ValueError("Hydration concurrency must be positive.")
        if branch_timeout_seconds <= 0:
            raise ValueError("Candidate branch timeout must be positive.")
        if documents_per_merchant < 1:
            raise ValueError("Documents per merchant must be positive.")
        if rrf_k < 1 or brand_cap < 1:
            raise ValueError("Fusion bounds must be positive.")
        resolved_reranker_limit = (
            fusion_pool_limit if reranker_candidate_limit is None else reranker_candidate_limit
        )
        if resolved_reranker_limit < 1 or resolved_reranker_limit > fusion_pool_limit:
            raise ValueError(
                "Reranker candidate limit must be positive and no greater than the fusion pool."
            )
        self._shops = shops
        # The same candidate ranker is applied after M2 fusion as in the legacy
        # control. A global Qdrant outage still does not retry that ranker because
        # it uses the same unavailable dependency.
        self._rag = rag
        self._global = global_retriever
        self._document_limit = document_limit
        self._hydration_limit = hydration_limit
        self._fusion_pool_limit = fusion_pool_limit
        self._hydration_concurrency = hydration_concurrency
        self._branch_timeout_seconds = branch_timeout_seconds
        self._documents_per_merchant = documents_per_merchant
        self._rrf_k = rrf_k
        self._brand_cap = brand_cap
        self._query_rewriter = query_rewriter
        self._reranker = reranker
        self._rerank_text_builder = rerank_text_builder or MerchantRerankTextBuilder()
        self._reranker_candidate_limit = resolved_reranker_limit

    async def discover(
        self,
        constraints: UserConstraints,
        *,
        limit: int,
    ) -> CandidateSet:
        if limit < 1:
            raise ValueError("Candidate limit must be positive.")
        if limit > self._fusion_pool_limit:
            raise ValueError("Candidate limit cannot exceed fusion pool limit.")
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
                self._search_global(constraints, rule_query=plan.expanded_query),
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
        structured_external_ids = _structured_branch_external_ids(structured_pool)
        global_branch = (
            global_outcome.value
            if isinstance(global_outcome.value, _GlobalBranchValue)
            else None
        )
        global_result = global_branch.result if global_branch is not None else None
        rewrite_plan = global_branch.rewrite_plan if global_branch is not None else None
        rewrite_metadata = _query_rewrite_metadata(
            rewrite_plan,
            enabled=self._query_rewriter is not None,
            error=global_branch.rewrite_error if global_branch is not None else None,
        )
        excluded_tags = rewrite_plan.excluded_tags if rewrite_plan is not None else ()
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
                excluded_tags=excluded_tags,
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
                    structured_external_ids=structured_external_ids,
                    query_metadata=rewrite_metadata,
                ),
            )

        aggregation_started = time.perf_counter()
        aggregation = (
            aggregate_query_variant_merchants(
                global_result,
                documents_per_merchant=self._documents_per_merchant,
                rrf_k=self._rrf_k,
            )
            if isinstance(global_result, MultiQueryGlobalRetrievalResult)
            else aggregate_merchants(
                global_result,
                documents_per_merchant=self._documents_per_merchant,
            )
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
            excluded_tags=excluded_tags,
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
                    structured_external_ids=structured_external_ids,
                    query_metadata=rewrite_metadata,
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
            excluded_tags=excluded_tags,
        )
        filtered_global_by_id = {candidate.shop_id: candidate for candidate in filtered_global}
        hard_filter_stats = _merge_counts(structured_filter_stats, global_filter_stats)

        fusion_started = time.perf_counter()
        try:
            fusion = fuse_candidates(
                filtered_structured,
                aggregation,
                filtered_global_by_id,
                limit=self._fusion_pool_limit,
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
                    structured_external_ids=structured_external_ids,
                    query_metadata=rewrite_metadata,
                ),
            )
        fusion_latency_ms = _elapsed_ms(fusion_started)
        fusion_pool = self._candidate_set(
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
            structured_external_ids=structured_external_ids,
            query_metadata=rewrite_metadata,
        )
        ranking_constraints = _ranking_constraints(constraints, rewrite_plan)
        return await self._rank_fusion_pool(
            ranking_constraints,
            fusion_pool,
            limit=limit,
            discovery_started=started,
            hard_constraints=constraints,
            excluded_tags=excluded_tags,
            aggregation=aggregation,
        )

    async def _search_global(
        self,
        constraints: UserConstraints,
        *,
        rule_query: str,
    ) -> _GlobalBranchValue:
        if self._query_rewriter is None:
            result = await self._global.search_documents(
                rule_query,
                document_limit=self._document_limit,
                category=constraints.category,
                neighborhood=constraints.neighborhood,
            )
            return _GlobalBranchValue(result=result)

        try:
            rewrite_plan = await self._query_rewriter.rewrite(
                constraints,
                rule_query=rule_query,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            result = await self._global.search_documents(
                rule_query,
                document_limit=self._document_limit,
                category=constraints.category,
                neighborhood=constraints.neighborhood,
            )
            return _GlobalBranchValue(
                result=result,
                rewrite_error="rewriter-error",
            )

        variants = _global_query_variants(rewrite_plan)
        result = await self._global.search_query_variants(
            variants,
            document_limit=self._document_limit,
            category=constraints.category,
            neighborhood=constraints.neighborhood,
            variant_timeout_seconds=self._branch_timeout_seconds,
        )
        return _GlobalBranchValue(result=result, rewrite_plan=rewrite_plan)

    async def _rank_fusion_pool(
        self,
        constraints: UserConstraints,
        fusion_pool: CandidateSet,
        *,
        limit: int,
        discovery_started: float,
        hard_constraints: UserConstraints,
        excluded_tags: tuple[str, ...],
        aggregation: MerchantAggregationResult,
    ) -> CandidateSet:
        rerank_query = _reranker_query(constraints)
        rerank_candidates = self._rerank_candidates(
            fusion_pool,
            aggregation,
            limit=self._reranker_candidate_limit,
        )
        pre_rerank_metadata = _pre_rerank_metadata(
            fusion_pool,
            rerank_query=rerank_query,
            rerank_candidates=rerank_candidates,
        )
        if self._reranker is not None:
            reranking_started = time.perf_counter()
            try:
                result = await self._reranker.rerank(rerank_query, rerank_candidates)
            except asyncio.CancelledError:
                raise
            except RerankerConfigurationError as exc:
                raise CandidateDiscoveryError(
                    "Cross-Encoder reranker authorization failed."
                ) from exc
            except Exception:
                result = None
            reranking_latency_ms = _elapsed_ms(reranking_started)
            if result is not None and result.trace.status is RerankStatus.APPLIED:
                try:
                    ranked = self._apply_rerank_result(
                        fusion_pool,
                        result,
                        rerank_candidates=rerank_candidates,
                        expected_input_fingerprint=str(
                            pre_rerank_metadata["rerankerInputFingerprint"]
                        ),
                        limit=limit,
                        hard_constraints=hard_constraints,
                        excluded_tags=excluded_tags,
                    )
                except Exception:
                    result = None
                else:
                    return ranked.model_copy(
                        update={
                            "retrieval_metadata": self._candidate_ranking_metadata(
                                fusion_pool,
                                ranked,
                                ranking_latency_ms=reranking_latency_ms,
                                total_latency_ms=_elapsed_ms(discovery_started),
                                fallback_reason=None,
                                extra_metadata={
                                    **pre_rerank_metadata,
                                    **_reranker_trace_metadata(result, enabled=True),
                                },
                            )
                        }
                    )

            fallback_reason = (
                result.trace.fallback_reason
                if result is not None
                else "reranker-error"
            )
            return await self._rank_with_m3_fallback(
                constraints,
                fusion_pool,
                limit=limit,
                discovery_started=discovery_started,
                pre_rerank_metadata=pre_rerank_metadata,
                rerank_result=result,
                reranking_latency_ms=reranking_latency_ms,
                reranker_fallback_reason=fallback_reason,
            )

        return await self._rank_with_m3_fallback(
            constraints,
            fusion_pool,
            limit=limit,
            discovery_started=discovery_started,
            pre_rerank_metadata=pre_rerank_metadata,
            rerank_result=None,
            reranking_latency_ms=0.0,
            reranker_fallback_reason=None,
        )

    async def _rank_with_m3_fallback(
        self,
        constraints: UserConstraints,
        fusion_pool: CandidateSet,
        *,
        limit: int,
        discovery_started: float,
        pre_rerank_metadata: Mapping[str, Any],
        rerank_result: RerankResult | None,
        reranking_latency_ms: float,
        reranker_fallback_reason: str | None,
    ) -> CandidateSet:
        ranking_started = time.perf_counter()
        try:
            ranked = await rank_candidates(
                self._rag,
                constraints,
                fusion_pool,
                limit=limit,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _is_authorization_failure(exc):
                raise CandidateDiscoveryError(
                    "Candidate ranking authorization failed."
                ) from exc
            ranking_latency_ms = _elapsed_ms(ranking_started)
            fallback = fusion_pool.model_copy(
                update={
                    "candidates": fusion_pool.candidates[:limit],
                    "warnings": list(
                        dict.fromkeys(
                            [
                                *fusion_pool.warnings,
                                "Candidate reranking was unavailable; using fused retrieval order.",
                            ]
                        )
                    ),
                }
            )
            return fallback.model_copy(
                update={
                    "retrieval_metadata": self._candidate_ranking_metadata(
                        fusion_pool,
                        fallback,
                        ranking_latency_ms=ranking_latency_ms,
                        total_latency_ms=_elapsed_ms(discovery_started),
                        fallback_reason="candidate-ranking-error",
                        extra_metadata={
                            **pre_rerank_metadata,
                            **_reranker_trace_metadata(
                                rerank_result,
                                enabled=self._reranker is not None,
                                fallback_reason=reranker_fallback_reason,
                                latency_ms=reranking_latency_ms,
                                candidate_count=len(
                                    pre_rerank_metadata["preRerankCandidateExternalIds"]
                                ),
                            ),
                        },
                    )
                }
            )

        ranking_latency_ms = _elapsed_ms(ranking_started)
        return ranked.model_copy(
            update={
                "retrieval_metadata": self._candidate_ranking_metadata(
                    fusion_pool,
                    ranked,
                    ranking_latency_ms=ranking_latency_ms,
                    total_latency_ms=_elapsed_ms(discovery_started),
                    fallback_reason=None,
                    extra_metadata={
                        **pre_rerank_metadata,
                        **_reranker_trace_metadata(
                            rerank_result,
                            enabled=self._reranker is not None,
                            fallback_reason=reranker_fallback_reason,
                            latency_ms=reranking_latency_ms,
                            candidate_count=len(
                                pre_rerank_metadata["preRerankCandidateExternalIds"]
                            ),
                        ),
                    },
                )
            }
        )

    @staticmethod
    def _candidate_ranking_metadata(
        fusion_pool: CandidateSet,
        ranked: CandidateSet,
        *,
        ranking_latency_ms: float,
        total_latency_ms: float,
        fallback_reason: str | None,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        base_metadata = dict(fusion_pool.retrieval_metadata)
        stage_latency = dict(base_metadata.get("candidateDiscoveryLatencyMs") or {})
        stage_latency.update(
            {
                "candidateRanking": round(ranking_latency_ms, 3),
                "total": round(total_latency_ms, 3),
            }
        )
        return {
            **base_metadata,
            **ranked.retrieval_metadata,
            "globalRetrievalEnabled": True,
            "candidateDiscoveryMode": "global-hybrid",
            "candidateRankingLatencyMs": round(ranking_latency_ms, 3),
            "candidateRankingFallback": fallback_reason is not None,
            "candidateRankingFallbackReason": fallback_reason,
            "candidateDiscoveryLatencyMs": stage_latency,
            "candidatePool": len(fusion_pool.candidates),
            "finalCandidates": len(ranked.candidates),
            **dict(extra_metadata or {}),
        }

    def _rerank_candidates(
        self,
        fusion_pool: CandidateSet,
        aggregation: MerchantAggregationResult,
        *,
        limit: int,
    ) -> tuple[RerankCandidate, ...]:
        evidence_by_shop = _rerank_evidence_by_shop(aggregation)
        return tuple(
            RerankCandidate(
                shop_id=candidate.shop_id,
                original_rank=rank,
                rerank_text=self._rerank_text_builder.build(
                    candidate,
                    evidence_by_shop.get(candidate.shop_id, ()),
                ),
            )
            for rank, candidate in enumerate(fusion_pool.candidates[:limit], start=1)
        )

    def _apply_rerank_result(
        self,
        fusion_pool: CandidateSet,
        result: RerankResult,
        *,
        rerank_candidates: tuple[RerankCandidate, ...],
        expected_input_fingerprint: str,
        limit: int,
        hard_constraints: UserConstraints,
        excluded_tags: tuple[str, ...],
    ) -> CandidateSet:
        candidates_by_id = {candidate.shop_id: candidate for candidate in fusion_pool.candidates}
        rerank_inputs_by_id = {candidate.shop_id: candidate for candidate in rerank_candidates}
        expected_ids = set(rerank_inputs_by_id)
        ordered_ids = list(result.ordered_shop_ids)
        if (
            len(ordered_ids) != len(set(ordered_ids))
            or len(ordered_ids) != len(rerank_candidates)
            or set(ordered_ids) != expected_ids
            or result.trace.candidate_count != len(rerank_candidates)
            or result.trace.input_fingerprint != expected_input_fingerprint
        ):
            raise ValueError("Reranker output must contain its complete bounded input exactly once.")
        if any(
            score.input_sha256
            != rerank_inputs_by_id[score.shop_id].rerank_text.input_sha256
            for score in result.scores
        ):
            raise ValueError("Reranker output does not match the submitted candidate documents.")
        ordered = [candidates_by_id[shop_id] for shop_id in ordered_ids]
        verified, rejected = _hard_filter_candidates(
            ordered,
            hard_constraints,
            required_data_version=self._global.scope.data_version,
            expected_external_ids={
                candidate.shop_id: candidate.external_id for candidate in fusion_pool.candidates
            },
            excluded_tags=excluded_tags,
        )
        if len(verified) != len(ordered) or any(rejected.values()):
            raise ValueError("Reranker output failed the post-ranking hard-constraint check.")
        return fusion_pool.model_copy(update={"candidates": verified[:limit]})

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
        structured_external_ids: list[str | None],
        query_metadata: Mapping[str, Any],
    ) -> CandidateSet:
        candidates = list(fusion.candidates)
        desired_tags = set(constraints.desired_tags)
        exact_candidate_ids = [
            candidate.shop_id
            for candidate in candidates
            if desired_tags.issubset(candidate.tags)
        ]
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
            "structuredBranchCandidates": len(structured_external_ids),
            "structuredBranchExternalIds": structured_external_ids,
            "structuredCandidates": fusion.stats.structured_candidates,
            "globalDenseDocuments": len(global_result.dense.hits),
            "globalSparseDocuments": len(global_result.sparse.hits),
            "globalMerchants": fusion.stats.global_merchants,
            "fusionCandidates": fusion.stats.fusion_candidates,
            "fusionPoolLimit": self._fusion_pool_limit,
            "fusionPoolCandidates": len(candidates),
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
            "fusionDuplicateBrandsSuppressed": fusion.stats.duplicate_brands_suppressed,
            "identityConflicts": aggregation.identity_conflicts,
            "identityConflictShopIds": list(aggregation.identity_conflict_shop_ids),
            "identityMismatches": hard_filter_stats.get("externalIdentity", 0),
            "hardConstraintFiltered": sum(hard_filter_stats.values()),
            "hardConstraintFilteredByReason": hard_filter_stats,
            "structuredFallback": structured_outcome.error is not None,
            "globalFallback": False,
            "candidateRankingFallback": False,
            "candidateRankingFallbackReason": None,
            "exactCandidateIds": exact_candidate_ids,
            **_global_trace_metadata(global_result),
            **query_metadata,
            "globalEmbeddingLatencyMs": round(global_result.embedding_latency_ms, 3),
            "candidateDiscoveryLatencyMs": {
                "structured": round(structured_outcome.latency_ms, 3),
                "global": round(global_outcome.latency_ms, 3),
                "queryRewrite": float(query_metadata.get("queryRewriteLatencyMs") or 0.0),
                "aggregation": round(aggregation_latency_ms, 3),
                "hydration": round(hydration_latency_ms, 3),
                "fusion": round(fusion_latency_ms, 3),
                "total": round(total_latency_ms, 3),
            },
            "candidatePool": len(candidates),
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


def _rerank_evidence_by_shop(
    aggregation: MerchantAggregationResult,
) -> dict[int, tuple[RerankEvidence, ...]]:
    """Convert retained retrieval hits without another Qdrant read."""

    rows: dict[int, list[tuple[int, int, int, str, Any]]] = {}
    for channel_order, channel in enumerate(
        (RetrievalChannel.DENSE, RetrievalChannel.SPARSE)
    ):
        ranking = aggregation.ranking(channel)
        for merchant in ranking.merchants:
            for document in merchant.retained_documents:
                rows.setdefault(merchant.shop_id, []).append(
                    (
                        channel_order,
                        merchant.merchant_rank,
                        document.document_rank,
                        document.document_id,
                        document,
                    )
                )

    result: dict[int, tuple[RerankEvidence, ...]] = {}
    for shop_id, documents in rows.items():
        ordered = sorted(documents, key=lambda item: item[:4])
        converted: list[RerankEvidence] = []
        for rank, row in enumerate(ordered, start=1):
            document = row[-1]
            converted.append(
                RerankEvidence(
                    rank=rank,
                    shop_id=shop_id,
                    document_id=document.document_id,
                    source_id=document.source_id,
                    root_id=document.root_id,
                    content_type=document.content_type,
                    document_kind=document.document_kind,
                    excerpt=document.text,
                    untrusted_content=document.untrusted_content,
                    source_type=document.content_source_type,
                    source_name=document.content_source_name,
                    synthetic=document.synthetic,
                    security_test=document.security_test,
                )
            )
        result[shop_id] = tuple(converted)
    return result


def _reranker_query(constraints: UserConstraints) -> str:
    lines = [constraints.query.strip()]
    if constraints.category:
        lines.append(f"category: {constraints.category}")
    if constraints.neighborhood:
        lines.append(f"neighborhood: {constraints.neighborhood}")
    if constraints.desired_tags:
        lines.append(
            "preferred_canonical_tags: "
            + ", ".join(sorted(set(constraints.desired_tags)))
        )
    if constraints.budget_cents is not None:
        per_person = constraints.budget_cents // constraints.party_size
        lines.append(f"maximum_price_per_person_cents: {per_person}")
    if constraints.visit_time:
        lines.append(f"visit_time: {constraints.visit_time}")
    return "\n".join(lines)


def _pre_rerank_metadata(
    fusion_pool: CandidateSet,
    *,
    rerank_query: str,
    rerank_candidates: tuple[RerankCandidate, ...],
) -> dict[str, Any]:
    by_id = {candidate.shop_id: candidate for candidate in fusion_pool.candidates}
    external_ids = [by_id[item.shop_id].external_id for item in rerank_candidates]
    document_ids = {
        str(item.shop_id): list(item.rerank_text.document_ids)
        for item in rerank_candidates
    }
    return {
        "preRerankCandidateExternalIds": external_ids,
        "preRerankPoolFingerprint": _sha256_json(external_ids),
        "rerankerInputExternalIds": external_ids,
        "rerankerInputFingerprint": rerank_input_fingerprint(
            rerank_query,
            rerank_candidates,
        ),
        "rerankerInputDocumentIds": document_ids,
        "rerankerInputTruncatedCount": sum(
            item.rerank_text.truncated for item in rerank_candidates
        ),
    }


def _reranker_trace_metadata(
    result: RerankResult | None,
    *,
    enabled: bool,
    fallback_reason: str | None = None,
    latency_ms: float = 0.0,
    candidate_count: int = 0,
) -> dict[str, Any]:
    if result is None:
        return {
            "rerankerEnabled": enabled,
            "rerankerProvider": "unknown" if enabled else "heuristic",
            "rerankerModel": "unknown" if enabled else "m3-heuristic-multi-signal",
            "rerankerModelVersion": "m4-cross-encoder-v1",
            "rerankerStatus": "unavailable" if enabled else "disabled",
            "rerankerCandidates": candidate_count,
            "rerankerLatencyMs": round(latency_ms, 3),
            "rerankerNetworkRequests": 0,
            "rerankerTokens": 0,
            "rerankerEstimatedCostUsd": 0.0,
            "rerankerRetryCount": 0,
            "rerankerFailureCount": int(enabled and fallback_reason is not None),
            "rerankerFallback": fallback_reason is not None,
            "rerankerFallbackReason": fallback_reason,
            "rerankerCacheHit": False,
            "rerankerCircuitState": "closed",
        }
    trace = result.trace
    return {
        "rerankerEnabled": enabled,
        "rerankerProvider": trace.provider,
        "rerankerModel": trace.model,
        "rerankerModelVersion": trace.version,
        "rerankerStatus": trace.status.value,
        "rerankerCandidates": trace.candidate_count,
        "rerankerLatencyMs": round(trace.latency_ms, 3),
        "rerankerNetworkRequests": trace.network_requests,
        "rerankerTokens": trace.tokens,
        "rerankerEstimatedCostUsd": trace.estimated_cost_usd,
        "rerankerRetryCount": trace.retries,
        "rerankerFailureCount": trace.failures,
        "rerankerFallback": trace.fallback_used,
        "rerankerFallbackReason": trace.fallback_reason,
        "rerankerCacheHit": trace.cache_hit,
        "rerankerCircuitState": trace.circuit_state.value,
    }


def _sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
    structured_external_ids: list[str | None] | None = None,
    query_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    structured_external_ids = list(structured_external_ids or [])
    dense_reason = global_result.dense.fallback_reason if global_result else None
    sparse_reason = global_result.sparse.fallback_reason if global_result else None
    return {
        "globalRetrievalEnabled": True,
        "candidateDiscoveryMode": "structured-fallback",
        "structuredBranchCandidates": len(structured_external_ids),
        "structuredBranchExternalIds": structured_external_ids,
        "structuredFallback": structured_outcome.error is not None,
        "globalFallback": True,
        "globalFallbackReason": reason or global_outcome.reason or dense_reason or sparse_reason,
        **_global_trace_metadata(global_result),
        **dict(query_metadata or {}),
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
            "queryRewrite": float(
                (query_metadata or {}).get("queryRewriteLatencyMs") or 0.0
            ),
            "total": round(total_latency_ms, 3),
        },
    }


def _structured_branch_external_ids(
    candidate_pool: CandidateSet | None,
) -> list[str | None]:
    """Preserve the raw structured branch pool for reproducible diagnostics."""

    if candidate_pool is None:
        return []
    return [candidate.external_id for candidate in candidate_pool.candidates]


def _global_query_variants(plan: QueryRewritePlan) -> list[GlobalQueryVariant]:
    variants = (plan.original, plan.rule, *plan.rewrites)
    mapped_sources = {
        "original": QueryVariantSource.ORIGINAL,
        "rule": QueryVariantSource.RULES,
        "llm": QueryVariantSource.LLM,
    }
    source_counters = {"original": 0, "rule": 0, "llm": 0}
    seen_queries: set[str] = set()
    result: list[GlobalQueryVariant] = []
    for variant in variants:
        normalized = " ".join(variant.text.split()).casefold()
        if normalized in seen_queries:
            continue
        seen_queries.add(normalized)
        source_counters[variant.source] += 1
        if variant.source == "original":
            variant_id = "original"
        elif variant.source == "rule":
            variant_id = "rules"
        else:
            variant_id = f"llm-{source_counters['llm']}"
        result.append(
            GlobalQueryVariant(
                variant_id=variant_id,
                source=mapped_sources[variant.source],
                query=variant.text,
            )
        )
    return result


def _query_rewrite_metadata(
    plan: QueryRewritePlan | None,
    *,
    enabled: bool,
    error: str | None,
) -> dict[str, Any]:
    if not enabled:
        return {}
    if plan is None:
        return {
            "queryRewriteEnabled": True,
            "queryRewriteProvider": "unknown",
            "queryRewriteModel": "unknown",
            "queryRewriteLanguage": "unknown",
            "queryRewriteCount": 0,
            "queryRewriteNetworkRequests": 0,
            "queryRewriteInputTokens": 0,
            "queryRewriteOutputTokens": 0,
            "queryRewriteCacheHit": False,
            "queryRewriteFallback": True,
            "queryRewriteFallbackReason": error or "rewriter-unavailable",
            "queryRewriteLatencyMs": 0.0,
            "queryRewriteSemanticTags": [],
            "queryRewriteExcludedTags": [],
        }
    trace = plan.trace
    return {
        "queryRewriteEnabled": True,
        "queryRewriteProvider": trace.requested_provider,
        "queryRewriteEffectiveProvider": trace.provider,
        "queryRewriteModel": trace.requested_model,
        "queryRewriteEffectiveModel": trace.model,
        "queryRewritePromptVersion": trace.prompt_version,
        "queryRewriteLanguage": plan.language,
        "queryRewriteCount": trace.rewrite_count,
        "queryRewriteNetworkRequests": trace.network_requests,
        "queryRewriteInputTokens": trace.input_tokens,
        "queryRewriteOutputTokens": trace.output_tokens,
        "queryRewriteCacheHit": trace.cache_hit,
        "queryRewriteFallback": trace.fallback_used or error is not None,
        "queryRewriteFallbackReason": error or trace.fallback_reason,
        "queryRewriteLatencyMs": round(trace.latency_ms, 3),
        "queryRewriteSemanticTags": list(plan.semantic_tags),
        "queryRewriteExcludedTags": list(plan.excluded_tags),
    }


def _ranking_constraints(
    constraints: UserConstraints,
    rewrite_plan: QueryRewritePlan | None,
) -> UserConstraints:
    if rewrite_plan is None:
        return constraints
    explicit_tags = list(constraints.desired_tags)
    inferred_tags = [
        tag
        for tag in rewrite_plan.semantic_tags
        if tag not in rewrite_plan.excluded_tags and tag not in explicit_tags
    ][: max(0, 20 - len(explicit_tags))]
    if not inferred_tags:
        return constraints
    return constraints.model_copy(
        update={"desired_tags": [*explicit_tags, *inferred_tags]}
    )


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
    metadata = {
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
    if not isinstance(result, MultiQueryGlobalRetrievalResult):
        return metadata

    provenance_by_shop: dict[int, dict[str, set[str]]] = {}
    for hit in result.provenance:
        variants = provenance_by_shop.setdefault(hit.shop_id, {})
        variants.setdefault(hit.variant_id, set()).add(hit.channel.value)
    variant_source = {
        item.variant.variant_id: item.variant.source.value for item in result.variants
    }
    merchant_provenance = {
        str(shop_id): [
            {
                "variantId": variant_id,
                "source": variant_source[variant_id],
                "channels": sorted(channels),
            }
            for variant_id, channels in sorted(variants.items())
        ]
        for shop_id, variants in sorted(provenance_by_shop.items())
    }
    return {
        **metadata,
        "globalQueryVariantCount": len(result.variants),
        "globalQueryVariants": [
            {
                "variantId": item.variant.variant_id,
                "source": item.variant.source.value,
                "status": item.status.value,
                "fallbackReason": item.fallback_reason,
            }
            for item in result.variants
        ],
        "globalQueryVariantCompletedIds": list(result.trace.completed_variant_ids),
        "globalQueryVariantPartialFailureIds": list(
            result.trace.partial_failure_variant_ids
        ),
        "globalQueryVariantTimedOutIds": list(result.trace.timed_out_variant_ids),
        "globalQueryVariantFailedIds": list(result.trace.failed_variant_ids),
        "merchantQueryVariantProvenance": merchant_provenance,
    }


def _hard_filter_candidates(
    candidates: list[ShopCandidate],
    constraints: UserConstraints,
    *,
    required_data_version: str | None,
    expected_external_ids: Mapping[int, str | None] | None,
    excluded_tags: tuple[str, ...] | list[str] = (),
) -> tuple[list[ShopCandidate], dict[str, int]]:
    retained: list[ShopCandidate] = []
    rejected: dict[str, int] = {}
    per_person_budget = (
        constraints.budget_cents // constraints.party_size
        if constraints.budget_cents is not None
        else None
    )
    hard_tags = set(constraints.desired_tags) & HARD_DESIRED_TAGS
    forbidden_tags = set(excluded_tags)
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
        elif forbidden_tags.intersection(candidate.tags):
            reason = "excludedTags"
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
