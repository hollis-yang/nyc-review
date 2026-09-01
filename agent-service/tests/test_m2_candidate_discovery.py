from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings
from app.domain.business_hours import is_shop_open, parse_visit_time
from app.domain.models import (
    AgentRunRequest,
    BusinessHours,
    CandidateSet,
    ShopCandidate,
    UserConstraints,
)
from app.graph.workflow import WorkflowServices, build_multi_agent_graph, build_single_agent_graph
from app.mcp.service import McpDomainService
from app.rag.candidate_discovery import (
    CandidateDiscoveryError,
    GlobalHybridCandidateDiscovery,
    LegacyCandidateDiscovery,
)
from app.rag.embeddings import EmbeddingProviderError
from app.rag.global_retrieval import (
    ChannelRetrievalResult,
    GlobalDocumentHit,
    GlobalRetrievalResult,
    GlobalRetrievalScope,
    RetrievalChannel,
)
from app.tools.services import HaversineItineraryService, HttpShopToolService, InMemoryRagService

DATA_VERSION = "nyc-real-m2-test"
DATASET_SHA256 = "a" * 64
EMBEDDING_IDENTITY = "b" * 64


def _candidate(
    shop_id: int,
    *,
    category: str = "Food & Dining",
    neighborhood: str = "Midtown",
    avg_price_cents: int | None = 2_500,
    tags: list[str] | None = None,
    business_status: str = "OPERATIONAL",
    data_version: str | None = DATA_VERSION,
    business_hours: list[BusinessHours] | None = None,
) -> ShopCandidate:
    return ShopCandidate(
        shop_id=shop_id,
        name=f"Merchant {shop_id}",
        category=category,
        neighborhood=neighborhood,
        latitude=40.75 + shop_id / 100_000,
        longitude=-73.98,
        avg_price_cents=avg_price_cents,
        score=4.5,
        tags=tags or [],
        business_status=business_status,
        data_version=data_version,
        external_id=f"source:{shop_id}",
        business_hours=business_hours or [],
    )


def _hit(
    shop_id: int,
    channel: RetrievalChannel,
    rank: int,
    *,
    shop_external_id: str | None = None,
) -> GlobalDocumentHit:
    return GlobalDocumentHit(
        point_id=f"{channel.value}-point-{shop_id}",
        shop_id=shop_id,
        shop_external_id=shop_external_id or f"source:{shop_id}",
        channel=channel,
        rank=rank,
        score=1.0 / rank,
        document_id=f"document-{shop_id}",
        source_id=f"source-document-{channel.value}-{shop_id}",
        content_type="shop_description",
        document_kind="evidence",
        text=f"Evidence for merchant {shop_id}",
    )


def _global_result(
    dense_ids: list[int] | None = None,
    sparse_ids: list[int] | None = None,
    *,
    dense_available: bool = True,
    sparse_available: bool = True,
) -> GlobalRetrievalResult:
    dense_ids = dense_ids or []
    sparse_ids = sparse_ids or []
    return GlobalRetrievalResult(
        dense=ChannelRetrievalResult(
            channel=RetrievalChannel.DENSE,
            hits=tuple(
                _hit(shop_id, RetrievalChannel.DENSE, rank)
                for rank, shop_id in enumerate(dense_ids, start=1)
            ),
            available=dense_available,
            fallback_reason=None if dense_available else "qdrant-error",
        ),
        sparse=ChannelRetrievalResult(
            channel=RetrievalChannel.SPARSE,
            hits=tuple(
                _hit(shop_id, RetrievalChannel.SPARSE, rank)
                for rank, shop_id in enumerate(sparse_ids, start=1)
            ),
            available=sparse_available,
            fallback_reason=None if sparse_available else "qdrant-error",
        ),
        embedding_latency_ms=2.0,
        total_latency_ms=4.0,
    )


class _Rag:
    def __init__(self) -> None:
        self.rank_calls = 0
        self.rank_inputs: list[CandidateSet] = []

    async def rank_candidates(
        self,
        constraints: UserConstraints,
        candidates: CandidateSet,
        *,
        limit: int,
    ) -> CandidateSet:
        self.rank_calls += 1
        self.rank_inputs.append(candidates)
        return candidates.model_copy(
            update={
                "candidates": candidates.candidates[:limit],
                "retrieval_metadata": {
                    **candidates.retrieval_metadata,
                    "legacyRanked": True,
                },
            }
        )


class _Shops:
    def __init__(
        self,
        search_result: CandidateSet,
        details: list[ShopCandidate],
        *,
        search_error: Exception | None = None,
    ) -> None:
        self.search_result = search_result
        self.by_id = {candidate.shop_id: candidate for candidate in details}
        self.search_error = search_error
        self.search_calls = 0
        self.detail_calls = 0
        self.details_requests: list[list[int]] = []
        self.started: asyncio.Event | None = None
        self.peer_started: asyncio.Event | None = None

    async def search(self, constraints: UserConstraints) -> CandidateSet:
        self.search_calls += 1
        if self.started is not None:
            self.started.set()
        if self.peer_started is not None:
            await self.peer_started.wait()
        if self.search_error is not None:
            raise self.search_error
        return self.search_result

    async def details(self, shop_ids: list[int]) -> list[ShopCandidate]:
        self.details_requests.append(list(shop_ids))
        return [self.by_id[shop_id] for shop_id in shop_ids if shop_id in self.by_id]

    async def detail(self, shop_id: int) -> ShopCandidate | None:
        self.detail_calls += 1
        return self.by_id.get(shop_id)


class _Global:
    def __init__(
        self,
        result: GlobalRetrievalResult,
        *,
        error: Exception | None = None,
    ) -> None:
        self.scope = GlobalRetrievalScope(
            collection_name="m2-test",
            data_version=DATA_VERSION,
            dataset_sha256=DATASET_SHA256,
            retrieval_version="m2-global-v1",
            embedding_identity=EMBEDDING_IDENTITY,
        )
        self.result = result
        self.error = error
        self.calls = 0
        self.queries: list[str] = []
        self.started: asyncio.Event | None = None
        self.peer_started: asyncio.Event | None = None

    async def search_documents(
        self,
        query: str,
        *,
        document_limit: int | None = None,
        category: str | None = None,
        neighborhood: str | None = None,
    ) -> GlobalRetrievalResult:
        self.calls += 1
        self.queries.append(query)
        if self.started is not None:
            self.started.set()
        if self.peer_started is not None:
            await self.peer_started.wait()
        if self.error is not None:
            raise self.error
        return self.result


def _discovery(
    shops,
    rag: _Rag,
    global_retriever: _Global,
    **kwargs,
) -> GlobalHybridCandidateDiscovery:
    kwargs.setdefault(
        "fusion_pool_limit",
        min(30, int(kwargs.get("hydration_limit", 60))),
    )
    return GlobalHybridCandidateDiscovery(
        shops,
        rag,
        global_retriever,
        branch_timeout_seconds=1,
        **kwargs,
    )


async def test_legacy_discovery_preserves_search_then_rank_contract_exactly():
    pool = CandidateSet(
        candidates=[_candidate(1), _candidate(2)],
        applied_constraints=["category"],
        retrieval_metadata={"exactCandidateIds": [1, 2]},
    )
    shops = _Shops(pool, pool.candidates)
    rag = _Rag()

    result = await LegacyCandidateDiscovery(shops, rag).discover(
        UserConstraints(query="dinner"),
        limit=1,
    )

    assert shops.search_calls == 1
    assert rag.rank_calls == 1
    assert [candidate.shop_id for candidate in result.candidates] == [1]
    assert result.applied_constraints == ["category"]
    assert result.retrieval_metadata == {
        "exactCandidateIds": [1, 2],
        "legacyRanked": True,
    }


def test_global_retrieval_settings_default_off_and_enforce_monotonic_bounds(tmp_path):
    defaults = Settings()
    assert defaults.global_retrieval_enabled is False
    assert defaults.global_retrieval_fusion_pool_limit == 30

    with pytest.raises(ValueError, match="requires rag_adapter=qdrant"):
        Settings(global_retrieval_enabled=True, rag_data_directory=tmp_path)
    with pytest.raises(ValueError, match="document_limit >= hydration_limit"):
        Settings(
            global_retrieval_enabled=True,
            rag_adapter="qdrant",
            rag_data_directory=tmp_path,
            global_retrieval_document_limit=20,
            global_retrieval_hydration_limit=21,
        )
    with pytest.raises(ValueError, match="hydration_limit >= max_candidates"):
        Settings(
            global_retrieval_enabled=True,
            rag_adapter="qdrant",
            rag_data_directory=tmp_path,
            max_candidates=10,
            global_retrieval_document_limit=20,
            global_retrieval_hydration_limit=9,
        )
    with pytest.raises(ValueError, match="fusion_pool_limit >= max_candidates"):
        Settings(
            global_retrieval_enabled=True,
            rag_adapter="qdrant",
            rag_data_directory=tmp_path,
            max_candidates=10,
            global_retrieval_document_limit=20,
            global_retrieval_hydration_limit=20,
            global_retrieval_fusion_pool_limit=9,
        )
    with pytest.raises(ValueError, match="fusion_pool_limit <= hydration_limit"):
        Settings(
            global_retrieval_enabled=True,
            rag_adapter="qdrant",
            rag_data_directory=tmp_path,
            max_candidates=5,
            global_retrieval_document_limit=20,
            global_retrieval_hydration_limit=10,
            global_retrieval_fusion_pool_limit=11,
        )
    with pytest.raises(ValueError, match="documents_per_merchant <= document_limit"):
        Settings(
            global_retrieval_enabled=True,
            rag_adapter="qdrant",
            rag_data_directory=tmp_path,
            max_candidates=1,
            global_retrieval_document_limit=2,
            global_retrieval_hydration_limit=1,
            global_retrieval_fusion_pool_limit=1,
            global_retrieval_documents_per_merchant=3,
        )


async def test_enabled_discovery_runs_two_branches_then_shared_candidate_ranker():
    structured_started = asyncio.Event()
    global_started = asyncio.Event()
    pool = CandidateSet(candidates=[_candidate(1)])
    shops = _Shops(pool, [_candidate(1), _candidate(2)])
    shops.started = structured_started
    shops.peer_started = global_started
    global_retriever = _Global(_global_result([2], [2]))
    global_retriever.started = global_started
    global_retriever.peer_started = structured_started
    rag = _Rag()

    result = await asyncio.wait_for(
        _discovery(shops, rag, global_retriever).discover(
            UserConstraints(query="quiet dinner"),
            limit=2,
        ),
        timeout=1,
    )

    assert [candidate.shop_id for candidate in result.candidates] == [2, 1]
    assert shops.search_calls == 1
    assert global_retriever.calls == 1
    assert rag.rank_calls == 1
    assert shops.details_requests == [[2]]
    assert result.retrieval_metadata["candidateDiscoveryMode"] == "global-hybrid"
    assert result.retrieval_metadata["structuredBranchCandidates"] == 1
    assert result.retrieval_metadata["structuredBranchExternalIds"] == ["source:1"]
    assert result.retrieval_metadata["structuredCandidates"] == 1
    assert result.retrieval_metadata["qdrantOnlyMerchants"] == 1
    assert result.retrieval_metadata["structuredFallback"] is False
    assert result.retrieval_metadata["candidateRankingFallback"] is False
    assert result.retrieval_metadata["candidateRankingLatencyMs"] >= 0


async def test_enabled_discovery_makes_only_one_paid_query_embedding_call():
    provider_calls = 0

    class ProviderCountingGlobal(_Global):
        async def search_documents(self, *args, **kwargs) -> GlobalRetrievalResult:
            nonlocal provider_calls
            provider_calls += 1
            return await super().search_documents(*args, **kwargs)

    pool = CandidateSet(candidates=[_candidate(1)])
    rag = _Rag()
    result = await _discovery(
        _Shops(pool, [_candidate(1), _candidate(2)]),
        rag,
        ProviderCountingGlobal(_global_result([2])),
    ).discover(UserConstraints(query="dinner"), limit=2)

    assert len(result.candidates) == 2
    assert provider_calls == 1
    assert rag.rank_calls == 1


async def test_qdrant_only_full_tag_match_is_exact_for_shared_ranker():
    rag = _Rag()
    shops = _Shops(
        CandidateSet(candidates=[_candidate(1, tags=["quiet"])]),
        [
            _candidate(1, tags=["quiet"]),
            _candidate(2, tags=["quiet", "outdoor_seating"]),
            _candidate(3, tags=["quiet"]),
        ],
    )

    await _discovery(
        shops,
        rag,
        _Global(_global_result([2, 3])),
    ).discover(
        UserConstraints(
            query="quiet patio",
            desired_tags=["quiet", "outdoor_seating"],
        ),
        limit=3,
    )

    assert rag.rank_inputs[0].retrieval_metadata["exactCandidateIds"] == [2]


async def test_hydration_is_capped_and_hard_constraints_fail_closed():
    ids = [2, 3, 4, 5, 6]
    details = [
        _candidate(2, tags=["wheelchair_accessible"]),
        _candidate(3, category="Bars & Nightlife", tags=["wheelchair_accessible"]),
        _candidate(4, avg_price_cents=9_000, tags=["wheelchair_accessible"]),
        _candidate(5, tags=["quiet"]),
        _candidate(6, tags=["wheelchair_accessible"], data_version="other-version"),
    ]
    shops = _Shops(CandidateSet(candidates=[]), details)
    rag = _Rag()
    global_retriever = _Global(_global_result(ids, ids))

    result = await _discovery(
        shops,
        rag,
        global_retriever,
        hydration_limit=5,
    ).discover(
        UserConstraints(
            query="accessible dinner",
            category="Food & Dining",
            neighborhood="Midtown",
            budget_cents=5_000,
            desired_tags=["wheelchair_accessible"],
        ),
        limit=5,
    )

    assert shops.details_requests == [ids]
    assert [candidate.shop_id for candidate in result.candidates] == [2]
    assert result.retrieval_metadata["hardConstraintFiltered"] == 4
    assert result.retrieval_metadata["hardConstraintFilteredByReason"] == {
        "budget": 1,
        "category": 1,
        "dataVersion": 1,
        "requiredTags": 1,
    }
    assert result.retrieval_metadata["globalDenseLatencyMs"] == 0.0
    assert result.retrieval_metadata["globalSparseLatencyMs"] == 0.0
    assert result.retrieval_metadata["globalDenseReturnedPoints"] == 0
    assert result.retrieval_metadata["globalSparseRejectedPoints"] == 0
    assert result.retrieval_metadata["identityConflicts"] == 0
    assert result.retrieval_metadata["identityConflictShopIds"] == []


async def test_qdrant_only_candidate_with_mismatched_external_identity_is_rejected():
    global_result = GlobalRetrievalResult(
        dense=ChannelRetrievalResult(
            channel=RetrievalChannel.DENSE,
            hits=(
                _hit(
                    2,
                    RetrievalChannel.DENSE,
                    1,
                    shop_external_id="source:expected",
                ),
            ),
        ),
        sparse=ChannelRetrievalResult(channel=RetrievalChannel.SPARSE),
    )
    shops = _Shops(CandidateSet(candidates=[]), [_candidate(2)])

    result = await _discovery(shops, _Rag(), _Global(global_result)).discover(
        UserConstraints(query="dinner"),
        limit=1,
    )

    assert result.candidates == []
    assert result.retrieval_metadata["identityMismatches"] == 1
    assert result.retrieval_metadata["hardConstraintFilteredByReason"] == {
        "externalIdentity": 1
    }


async def test_overlap_identity_mismatch_is_removed_from_both_fusion_channels():
    mismatched = _candidate(1).model_copy(update={"external_id": "source:wrong"})
    shops = _Shops(CandidateSet(candidates=[mismatched]), [mismatched])

    result = await _discovery(
        shops,
        _Rag(),
        _Global(_global_result([1], [1])),
    ).discover(UserConstraints(query="dinner"), limit=1)

    assert result.candidates == []
    assert shops.details_requests == []
    assert result.retrieval_metadata["identityMismatches"] == 1
    assert result.retrieval_metadata["structuredCandidates"] == 0
    assert result.retrieval_metadata["missingHydratedCandidates"] == 1


async def test_m2_structured_candidates_require_the_active_data_version():
    stale = _candidate(1, data_version="stale-data-version")
    shops = _Shops(
        CandidateSet(candidates=[stale]),
        [stale, _candidate(2)],
    )

    result = await _discovery(
        shops,
        _Rag(),
        _Global(_global_result([2])),
    ).discover(UserConstraints(query="dinner"), limit=2)

    assert [candidate.shop_id for candidate in result.candidates] == [2]
    assert result.retrieval_metadata["hardConstraintFilteredByReason"] == {
        "dataVersion": 1
    }


async def test_visit_time_without_business_hours_fails_closed():
    shops = _Shops(CandidateSet(candidates=[_candidate(1)]), [_candidate(1)])

    result = await _discovery(
        shops,
        _Rag(),
        _Global(_global_result()),
    ).discover(
        UserConstraints(
            query="late dinner",
            visit_time="2026-09-01T20:00:00-04:00",
        ),
        limit=1,
    )

    assert result.candidates == []
    assert result.retrieval_metadata["hardConstraintFilteredByReason"] == {
        "visitTime": 1
    }


@pytest.mark.parametrize(
    ("visit_time", "day_of_week", "opening", "closing"),
    [
        ("Sunday at 10:30 AM", 7, "09:00", "12:00"),
        ("Friday at 8:30 PM", 5, "18:00", "23:00"),
        ("Wednesday at 7:30 PM", 3, "18:00", "22:00"),
        ("Saturday at 9:30 PM", 6, "20:00", "23:30"),
    ],
)
def test_frozen_eval_visit_times_share_the_runtime_hours_contract(
    visit_time: str,
    day_of_week: int,
    opening: str,
    closing: str,
):
    parsed = parse_visit_time(visit_time)
    candidate = _candidate(
        1,
        business_hours=[
            BusinessHours(
                day_of_week=day_of_week,
                open_time=opening,
                close_time=closing,
            )
        ],
    )

    assert parsed is not None
    assert parsed.day_of_week == day_of_week
    assert is_shop_open(candidate, visit_time) is True


async def test_natural_visit_time_filters_closed_and_malformed_hours_without_crashing():
    open_candidate = _candidate(
        1,
        business_hours=[
            BusinessHours(day_of_week=7, open_time="09:00", close_time="12:00")
        ],
    )
    closed_candidate = _candidate(
        2,
        business_hours=[
            BusinessHours(day_of_week=7, open_time="18:00", close_time="23:00")
        ],
    )
    malformed_candidate = _candidate(
        3,
        business_hours=[
            BusinessHours(day_of_week=7, open_time="not-a-time", close_time="12:00")
        ],
    )
    shops = _Shops(
        CandidateSet(candidates=[open_candidate, closed_candidate, malformed_candidate]),
        [open_candidate, closed_candidate, malformed_candidate],
    )

    result = await _discovery(
        shops,
        _Rag(),
        _Global(_global_result()),
    ).discover(
        UserConstraints(query="Sunday brunch", visit_time="Sunday at 10:30 AM"),
        limit=3,
    )

    assert [candidate.shop_id for candidate in result.candidates] == [1]
    assert "visit_time" in result.applied_constraints
    assert result.retrieval_metadata["hardConstraintFilteredByReason"] == {
        "visitTime": 2
    }


async def test_conflicting_qdrant_external_identities_are_suppressed_and_traced():
    global_result = GlobalRetrievalResult(
        dense=ChannelRetrievalResult(
            channel=RetrievalChannel.DENSE,
            hits=(
                _hit(
                    2,
                    RetrievalChannel.DENSE,
                    1,
                    shop_external_id="source:first",
                ),
            ),
        ),
        sparse=ChannelRetrievalResult(
            channel=RetrievalChannel.SPARSE,
            hits=(
                _hit(
                    2,
                    RetrievalChannel.SPARSE,
                    1,
                    shop_external_id="source:second",
                ),
            ),
        ),
    )
    shops = _Shops(CandidateSet(candidates=[]), [_candidate(2)])

    result = await _discovery(shops, _Rag(), _Global(global_result)).discover(
        UserConstraints(query="dinner"),
        limit=1,
    )

    assert result.candidates == []
    assert shops.details_requests == []
    assert result.retrieval_metadata["identityConflicts"] == 1
    assert result.retrieval_metadata["identityConflictShopIds"] == [2]


@pytest.mark.parametrize("status_code", [401, 403])
async def test_structured_authorization_failure_is_fail_closed_even_with_global_results(
    status_code: int,
):
    request = httpx.Request("POST", "http://spring/internal/agent/tools/shops/search")
    authorization_error = httpx.HTTPStatusError(
        "authorization failed",
        request=request,
        response=httpx.Response(status_code, request=request),
    )
    shops = _Shops(
        CandidateSet(candidates=[]),
        [_candidate(2)],
        search_error=authorization_error,
    )

    with pytest.raises(CandidateDiscoveryError, match="authorization failed"):
        await _discovery(
            shops,
            _Rag(),
            _Global(_global_result([2])),
        ).discover(UserConstraints(query="dinner"), limit=1)

    assert shops.details_requests == []


async def test_hydration_authorization_failure_does_not_fallback_to_structured_results():
    request = httpx.Request("POST", "http://spring/internal/agent/tools/shops/details")
    authorization_error = httpx.HTTPStatusError(
        "authorization failed",
        request=request,
        response=httpx.Response(403, request=request),
    )

    class ForbiddenDetailsShops(_Shops):
        async def details(self, shop_ids: list[int]) -> list[ShopCandidate]:
            raise authorization_error

    rag = _Rag()
    shops = ForbiddenDetailsShops(
        CandidateSet(candidates=[_candidate(1)]),
        [_candidate(1), _candidate(2)],
    )

    with pytest.raises(CandidateDiscoveryError, match="authorization failed"):
        await _discovery(
            shops,
            rag,
            _Global(_global_result([2])),
        ).discover(UserConstraints(query="dinner"), limit=2)

    assert rag.rank_calls == 0


async def test_hydration_limit_bounds_batch_size_and_reports_unhydrated_merchants():
    ids = list(range(1, 31))
    shops = _Shops(CandidateSet(candidates=[]), [_candidate(shop_id) for shop_id in ids])
    rag = _Rag()
    result = await _discovery(
        shops,
        rag,
        _Global(_global_result(ids)),
        document_limit=30,
        hydration_limit=10,
        fusion_pool_limit=7,
    ).discover(UserConstraints(query="dinner"), limit=5)

    assert len(shops.details_requests) == 1
    assert len(shops.details_requests[0]) == 10
    assert result.retrieval_metadata["hydrationRequested"] == 10
    assert result.retrieval_metadata["missingHydratedCandidates"] == 20
    assert len(rag.rank_inputs[0].candidates) == 7
    assert result.retrieval_metadata["fusionPoolLimit"] == 7
    assert result.retrieval_metadata["fusionPoolCandidates"] == 7


async def test_individual_hydration_fallback_has_bounded_concurrency():
    class DetailOnlyShops:
        def __init__(self) -> None:
            self.active = 0
            self.maximum_active = 0

        async def search(self, constraints: UserConstraints) -> CandidateSet:
            return CandidateSet(candidates=[])

        async def detail(self, shop_id: int) -> ShopCandidate:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            try:
                await asyncio.sleep(0.01)
                return _candidate(shop_id)
            finally:
                self.active -= 1

    shops = DetailOnlyShops()
    ids = list(range(1, 13))
    result = await _discovery(
        shops,
        _Rag(),
        _Global(_global_result(ids)),
        document_limit=12,
        hydration_limit=12,
        hydration_concurrency=3,
    ).discover(UserConstraints(query="dinner"), limit=5)

    assert shops.maximum_active == 3
    assert len(result.candidates) == 5


async def test_global_failure_returns_structured_order_without_retrying_qdrant_ranker():
    class ExplodingRag(_Rag):
        async def rank_candidates(self, *args, **kwargs) -> CandidateSet:
            self.rank_calls += 1
            raise RuntimeError("the candidate-filtered Qdrant path is also unavailable")

    structured = CandidateSet(candidates=[_candidate(1)])
    rag = ExplodingRag()
    fallback = await _discovery(
        _Shops(structured, structured.candidates),
        rag,
        _Global(_global_result(dense_available=False, sparse_available=False)),
    ).discover(UserConstraints(query="dinner"), limit=1)

    assert rag.rank_calls == 0
    assert [candidate.shop_id for candidate in fallback.candidates] == [1]
    assert fallback.retrieval_metadata["candidateDiscoveryMode"] == "structured-fallback"
    assert fallback.retrieval_metadata["globalFallback"] is True


async def test_structured_failure_uses_global_then_shared_candidate_ranker():
    global_only_rag = _Rag()

    global_only = await _discovery(
        _Shops(
            CandidateSet(candidates=[]),
            [_candidate(2)],
            search_error=RuntimeError("structured unavailable"),
        ),
        global_only_rag,
        _Global(_global_result([2])),
    ).discover(UserConstraints(query="dinner"), limit=1)

    assert global_only_rag.rank_calls == 1
    assert [candidate.shop_id for candidate in global_only.candidates] == [2]
    assert global_only.retrieval_metadata["structuredFallback"] is True


async def test_candidate_ranking_failure_falls_back_to_fused_order_and_is_traced():
    class ExplodingRag(_Rag):
        async def rank_candidates(self, *args, **kwargs) -> CandidateSet:
            self.rank_calls += 1
            raise RuntimeError("candidate ranking unavailable")

    rag = ExplodingRag()
    result = await _discovery(
        _Shops(
            CandidateSet(candidates=[_candidate(1)]),
            [_candidate(1), _candidate(2)],
        ),
        rag,
        _Global(_global_result([2], [2])),
    ).discover(UserConstraints(query="dinner"), limit=2)

    assert rag.rank_calls == 1
    assert [candidate.shop_id for candidate in result.candidates] == [2, 1]
    assert result.retrieval_metadata["globalFallback"] is False
    assert result.retrieval_metadata["candidateRankingFallback"] is True
    assert (
        result.retrieval_metadata["candidateRankingFallbackReason"]
        == "candidate-ranking-error"
    )
    assert result.retrieval_metadata["candidateRankingLatencyMs"] >= 0


@pytest.mark.parametrize("status_code", [401, 403])
async def test_candidate_ranking_authorization_failure_is_fail_closed(status_code: int):
    authorization_error = EmbeddingProviderError(
        "embedding authorization failed",
        provider="test",
        retryable=False,
        status_code=status_code,
    )

    class ForbiddenRag(_Rag):
        async def rank_candidates(self, *args, **kwargs) -> CandidateSet:
            raise authorization_error

    with pytest.raises(CandidateDiscoveryError, match="ranking authorization failed"):
        await _discovery(
            _Shops(CandidateSet(candidates=[_candidate(1)]), [_candidate(1)]),
            ForbiddenRag(),
            _Global(_global_result([1])),
        ).discover(UserConstraints(query="dinner"), limit=1)


async def test_caller_cancellation_cancels_both_discovery_branches():
    structured_started = asyncio.Event()
    global_started = asyncio.Event()
    structured_cancelled = asyncio.Event()
    global_cancelled = asyncio.Event()

    class BlockingShops:
        async def search(self, constraints: UserConstraints) -> CandidateSet:
            structured_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                structured_cancelled.set()
                raise

    class BlockingGlobal(_Global):
        async def search_documents(self, *args, **kwargs) -> GlobalRetrievalResult:
            global_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                global_cancelled.set()
                raise

    task = asyncio.create_task(
        _discovery(
            BlockingShops(),
            _Rag(),
            BlockingGlobal(_global_result()),
        ).discover(UserConstraints(query="dinner"), limit=1)
    )
    await asyncio.gather(structured_started.wait(), global_started.wait())
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert structured_cancelled.is_set()
    assert global_cancelled.is_set()


async def test_single_multi_and_mcp_share_candidate_discovery_contract():
    class RecordingDiscovery:
        def __init__(self) -> None:
            self.calls: list[int] = []

        async def discover(
            self,
            constraints: UserConstraints,
            *,
            limit: int,
        ) -> CandidateSet:
            self.calls.append(limit)
            return CandidateSet(candidates=[_candidate(1, data_version=None)])

    discovery = RecordingDiscovery()
    services = WorkflowServices(
        shops=SimpleNamespace(),
        rag=InMemoryRagService(),
        itinerary=HaversineItineraryService(),
        final_candidate_limit=5,
        candidate_discovery=discovery,
    )
    request = AgentRunRequest(constraints=UserConstraints(query="dinner", result_limit=1))
    await build_single_agent_graph(services).ainvoke({"request": request, "events": []})
    await build_multi_agent_graph(services).ainvoke({"request": request, "events": []})

    runtime = SimpleNamespace(
        shop_service=SimpleNamespace(),
        rag_service=SimpleNamespace(),
        candidate_discovery=discovery,
        settings=SimpleNamespace(max_candidates=7),
    )
    result = await McpDomainService(runtime).search_shops(query="dinner")

    assert discovery.calls == [1, 1, 7]
    assert [candidate["shop_id"] for candidate in result["candidates"]] == [1]


async def test_http_shop_details_uses_one_bounded_order_preserving_request(monkeypatch):
    requests: list[httpx.Request] = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url: str, *, headers: dict, json: dict):
            request = httpx.Request("POST", url, headers=headers, json=json)
            requests.append(request)
            rows = [
                {
                    "shopId": shop_id,
                    "name": f"Merchant {shop_id}",
                    "category": "Food & Dining",
                    "neighborhood": "Midtown",
                    "latitude": 40.75,
                    "longitude": -73.98,
                }
                for shop_id in json["shopIds"]
            ]
            return httpx.Response(200, request=request, json={"data": rows})

    monkeypatch.setattr("app.tools.services.httpx.AsyncClient", Client)
    service = HttpShopToolService("http://spring:8081", auth_token="token")

    candidates = await service.details([3, 1, 3, 2])

    assert len(requests) == 1
    assert requests[0].url.path == "/internal/agent/tools/shops/details"
    assert requests[0].headers["authorization"] == "token"
    assert requests[0].read() == b'{"shopIds":[3,1,2]}'
    assert [candidate.shop_id for candidate in candidates] == [3, 1, 2]
