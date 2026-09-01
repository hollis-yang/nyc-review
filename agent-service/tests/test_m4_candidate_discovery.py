from __future__ import annotations

import pytest

from app.domain.models import CandidateSet, ShopCandidate, UserConstraints
from app.rag.candidate_discovery import CandidateDiscoveryError, GlobalHybridCandidateDiscovery
from app.rag.global_retrieval import (
    ChannelRetrievalResult,
    GlobalDocumentHit,
    GlobalRetrievalResult,
    GlobalRetrievalScope,
    RetrievalChannel,
)
from app.rag.reranker import (
    CircuitState,
    RerankCandidate,
    RerankerConfigurationError,
    RerankResult,
    RerankScore,
    RerankStatus,
    RerankTrace,
    rerank_input_fingerprint,
)

DATA_VERSION = "nyc-real-m4-test"


def _candidate(shop_id: int, *, tags: list[str] | None = None) -> ShopCandidate:
    return ShopCandidate(
        shop_id=shop_id,
        name=f"Merchant {shop_id}",
        category="Food & Dining",
        neighborhood="Chelsea-Hudson Yards",
        latitude=40.75,
        longitude=-73.99,
        avg_price_cents=2_000,
        score=4.5,
        tags=tags or [],
        external_id=f"osm:{shop_id}",
        source_type="OPENSTREETMAP",
        data_version=DATA_VERSION,
    )


def _hit(shop_id: int, channel: RetrievalChannel, rank: int) -> GlobalDocumentHit:
    return GlobalDocumentHit(
        point_id=f"{channel.value}-{shop_id}",
        shop_id=shop_id,
        shop_external_id=f"osm:{shop_id}",
        channel=channel,
        rank=rank,
        score=1.0 / rank,
        document_id=f"document-{shop_id}",
        source_id=f"source-{shop_id}",
        root_id=shop_id,
        content_type="review",
        document_kind="evidence",
        text=f"Merchant {shop_id} has quiet seating.",
        data_version=DATA_VERSION,
        dataset_sha256="d" * 64,
    )


class _Shops:
    def __init__(self, candidates: list[ShopCandidate]) -> None:
        self.candidates = candidates

    async def search(self, _constraints: UserConstraints) -> CandidateSet:
        return CandidateSet(candidates=list(self.candidates))

    async def details(self, shop_ids: list[int]) -> list[ShopCandidate]:
        by_id = {candidate.shop_id: candidate for candidate in self.candidates}
        return [by_id[shop_id] for shop_id in shop_ids]


class _Rag:
    def __init__(self) -> None:
        self.calls = 0

    async def rank_candidates(
        self,
        _constraints: UserConstraints,
        candidates: CandidateSet,
        *,
        limit: int,
    ) -> CandidateSet:
        self.calls += 1
        return candidates.model_copy(update={"candidates": candidates.candidates[:limit]})


class _Global:
    scope = GlobalRetrievalScope(
        collection_name="m4-test",
        data_version=DATA_VERSION,
        dataset_sha256="d" * 64,
        retrieval_version="m4-test-v1",
        embedding_identity="e" * 64,
    )

    async def search_documents(self, _query: str, **_kwargs) -> GlobalRetrievalResult:
        dense = ChannelRetrievalResult(
            channel=RetrievalChannel.DENSE,
            hits=(_hit(1, RetrievalChannel.DENSE, 1), _hit(2, RetrievalChannel.DENSE, 2)),
            returned_points=2,
        )
        sparse = ChannelRetrievalResult(
            channel=RetrievalChannel.SPARSE,
            hits=(_hit(1, RetrievalChannel.SPARSE, 1), _hit(2, RetrievalChannel.SPARSE, 2)),
            returned_points=2,
        )
        return GlobalRetrievalResult(dense=dense, sparse=sparse)


class _FakeReranker:
    def __init__(
        self,
        *,
        unavailable: bool = False,
        authorization_error: bool = False,
        contract_violation: str | None = None,
    ) -> None:
        self.unavailable = unavailable
        self.authorization_error = authorization_error
        self.contract_violation = contract_violation
        self.calls: list[tuple[str, tuple[RerankCandidate, ...]]] = []

    async def rerank(
        self,
        query: str,
        candidates: tuple[RerankCandidate, ...],
    ) -> RerankResult:
        if self.authorization_error:
            raise RerankerConfigurationError("denied")
        rows = tuple(candidates)
        self.calls.append((query, rows))
        fingerprint = rerank_input_fingerprint(query, rows)
        if self.unavailable:
            ordered = rows
            status = RerankStatus.UNAVAILABLE
            fallback_reason = "timeout"
        else:
            ordered = tuple(reversed(rows))
            status = RerankStatus.APPLIED
            fallback_reason = None
        if self.contract_violation == "partial":
            ordered = ordered[:1]
        scores = tuple(
            RerankScore(
                shop_id=item.shop_id,
                original_rank=item.original_rank,
                rank=rank,
                score=None if self.unavailable else float(len(rows) - rank + 1),
                input_sha256=(
                    "f" * 64
                    if self.contract_violation == "input-sha"
                    else item.rerank_text.input_sha256
                ),
            )
            for rank, item in enumerate(ordered, start=1)
        )
        if self.contract_violation == "substitute":
            scores = (
                RerankScore(
                    shop_id=2,
                    original_rank=1,
                    rank=1,
                    score=1.0,
                    input_sha256=rows[0].rerank_text.input_sha256,
                ),
            )
        return RerankResult(
            scores=scores,
            trace=RerankTrace(
                status=status,
                provider="qwen",
                model="qwen3-rerank",
                version="m4-v1",
                candidate_count=len(scores),
                input_fingerprint=(
                    "f" * 64
                    if self.contract_violation == "fingerprint"
                    else fingerprint
                ),
                network_requests=1,
                failures=int(self.unavailable),
                fallback_used=self.unavailable,
                fallback_reason=fallback_reason,
                circuit_state=CircuitState.CLOSED,
            ),
        )

    def usage_snapshot(self):
        return None

    def reset(self) -> None:
        return None

    def clear_cache(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


def _discovery(
    rag: _Rag,
    reranker: _FakeReranker | None,
    *,
    reranker_candidate_limit: int = 2,
):
    shops = _Shops([_candidate(1), _candidate(2)])
    return GlobalHybridCandidateDiscovery(
        shops,
        rag,
        _Global(),
        fusion_pool_limit=2,
        hydration_limit=2,
        reranker=reranker,
        reranker_candidate_limit=reranker_candidate_limit,
    )


async def test_m4_cross_encoder_reorders_shared_pool_without_legacy_ranker():
    rag = _Rag()
    reranker = _FakeReranker()
    constraints = UserConstraints(query="quiet restaurant", result_limit=2)

    result = await _discovery(rag, reranker).discover(constraints, limit=2)

    assert [candidate.shop_id for candidate in result.candidates] == [2, 1]
    assert rag.calls == 0
    assert len(reranker.calls) == 1
    metadata = result.retrieval_metadata
    assert metadata["preRerankCandidateExternalIds"] == ["osm:1", "osm:2"]
    assert len(metadata["preRerankPoolFingerprint"]) == 64
    assert len(metadata["rerankerInputFingerprint"]) == 64
    assert metadata["rerankerProvider"] == "qwen"
    assert metadata["rerankerFallback"] is False
    assert metadata["rerankerInputDocumentIds"] == {
        "1": ["document-1"],
        "2": ["document-2"],
    }


async def test_m4_provider_failure_restores_exact_m3_heuristic_order():
    rag = _Rag()
    reranker = _FakeReranker(unavailable=True)
    constraints = UserConstraints(query="quiet restaurant", result_limit=2)

    result = await _discovery(rag, reranker).discover(constraints, limit=2)

    assert [candidate.shop_id for candidate in result.candidates] == [1, 2]
    assert rag.calls == 1
    assert result.retrieval_metadata["rerankerFallback"] is True
    assert result.retrieval_metadata["rerankerFallbackReason"] == "timeout"
    assert result.retrieval_metadata["rerankerFailureCount"] == 1


async def test_m4_authorization_failure_is_fail_closed():
    rag = _Rag()
    reranker = _FakeReranker(authorization_error=True)

    try:
        await _discovery(rag, reranker).discover(
            UserConstraints(query="quiet restaurant", result_limit=2),
            limit=2,
        )
    except CandidateDiscoveryError as exc:
        assert "authorization" in str(exc)
    else:
        raise AssertionError("Authorization failures must not fall back silently.")
    assert rag.calls == 0


async def test_m4_disabled_control_exposes_same_input_fingerprint():
    constraints = UserConstraints(query="quiet restaurant", result_limit=2)
    control = await _discovery(_Rag(), None).discover(constraints, limit=2)
    treatment = await _discovery(_Rag(), _FakeReranker()).discover(constraints, limit=2)

    assert (
        control.retrieval_metadata["rerankerInputFingerprint"]
        == treatment.retrieval_metadata["rerankerInputFingerprint"]
    )
    assert control.retrieval_metadata["rerankerEnabled"] is False
    assert control.retrieval_metadata["rerankerProvider"] == "heuristic"


@pytest.mark.parametrize(
    ("contract_violation", "reranker_candidate_limit", "final_limit"),
    [
        ("partial", 2, 1),
        ("substitute", 1, 1),
        ("fingerprint", 2, 2),
        ("input-sha", 2, 2),
    ],
)
async def test_m4_invalid_applied_result_contract_falls_back_to_m3(
    contract_violation: str,
    reranker_candidate_limit: int,
    final_limit: int,
):
    rag = _Rag()
    reranker = _FakeReranker(contract_violation=contract_violation)

    result = await _discovery(
        rag,
        reranker,
        reranker_candidate_limit=reranker_candidate_limit,
    ).discover(
        UserConstraints(query="quiet restaurant", result_limit=final_limit),
        limit=final_limit,
    )

    assert rag.calls == 1
    assert result.retrieval_metadata["rerankerFallback"] is True
    assert result.retrieval_metadata["rerankerFallbackReason"] == "reranker-error"
