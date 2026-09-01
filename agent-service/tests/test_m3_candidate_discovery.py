from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import CandidateSet, ShopCandidate, UserConstraints
from app.rag.candidate_discovery import GlobalHybridCandidateDiscovery
from app.rag.global_retrieval import (
    ChannelRetrievalResult,
    GlobalDocumentHit,
    GlobalQueryVariant,
    GlobalRetrievalResult,
    GlobalRetrievalScope,
    MultiQueryGlobalRetrievalResult,
    MultiQueryRetrievalTrace,
    RetrievalChannel,
    VariantGlobalRetrievalResult,
    VariantHitProvenance,
)
from app.rag.query_rewriter import (
    DisabledQueryRewriter,
    HardConstraintEcho,
    QueryRewritePlan,
    QueryRewriteTrace,
    QueryVariant,
)

DATA_VERSION = "nyc-real-m3-test"
DATASET_SHA = "a" * 64


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


def _hit(shop_id: int, channel: RetrievalChannel, rank: int, *, suffix: str) -> GlobalDocumentHit:
    return GlobalDocumentHit(
        point_id=f"{suffix}-{channel.value}-{shop_id}",
        shop_id=shop_id,
        shop_external_id=f"osm:{shop_id}",
        channel=channel,
        rank=rank,
        score=1.0 / rank,
        document_id=f"document-{suffix}-{shop_id}",
        source_id=f"source-{suffix}-{channel.value}-{shop_id}",
        content_type="shop_attribute_fact",
        document_kind="fact",
        text=f"Evidence for {shop_id}",
    )


def _variant_result(variant: GlobalQueryVariant, shop_id: int) -> VariantGlobalRetrievalResult:
    dense = ChannelRetrievalResult(
        channel=RetrievalChannel.DENSE,
        hits=(_hit(shop_id, RetrievalChannel.DENSE, 1, suffix=variant.variant_id),),
        returned_points=1,
    )
    sparse = ChannelRetrievalResult(
        channel=RetrievalChannel.SPARSE,
        hits=(_hit(shop_id, RetrievalChannel.SPARSE, 1, suffix=variant.variant_id),),
        returned_points=1,
    )
    return VariantGlobalRetrievalResult(
        variant=variant,
        dense=dense,
        sparse=sparse,
    )


class _Shops:
    def __init__(self, candidates: list[ShopCandidate]) -> None:
        self._candidates = candidates
        self.search_constraints: list[UserConstraints] = []

    async def search(self, constraints: UserConstraints) -> CandidateSet:
        self.search_constraints.append(constraints)
        return CandidateSet(candidates=list(self._candidates))

    async def details(self, shop_ids: list[int]) -> list[ShopCandidate]:
        by_id = {candidate.shop_id: candidate for candidate in self._candidates}
        return [by_id[shop_id] for shop_id in shop_ids if shop_id in by_id]


class _Rag:
    def __init__(self) -> None:
        self.ranking_constraints: list[UserConstraints] = []
        self.ranking_pools: list[CandidateSet] = []

    async def rank_candidates(
        self,
        constraints: UserConstraints,
        candidates: CandidateSet,
        *,
        limit: int,
    ) -> CandidateSet:
        self.ranking_constraints.append(constraints)
        self.ranking_pools.append(candidates)
        return candidates.model_copy(update={"candidates": candidates.candidates[:limit]})


class _Global:
    def __init__(self, shop_by_variant: dict[str, int]) -> None:
        self.scope = GlobalRetrievalScope(
            collection_name="m3-test",
            data_version=DATA_VERSION,
            dataset_sha256=DATASET_SHA,
            retrieval_version="m3-rewrite-v1",
            embedding_identity="b" * 64,
        )
        self.shop_by_variant = shop_by_variant
        self.variant_calls: list[list[GlobalQueryVariant]] = []
        self.document_queries: list[str] = []

    async def search_query_variants(
        self,
        variants: list[GlobalQueryVariant],
        **_kwargs,
    ) -> MultiQueryGlobalRetrievalResult:
        self.variant_calls.append(list(variants))
        results = tuple(
            _variant_result(variant, self.shop_by_variant[variant.variant_id]) for variant in variants
        )
        provenance = tuple(
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
        return MultiQueryGlobalRetrievalResult(
            dense=results[0].dense,
            sparse=results[0].sparse,
            variants=results,
            provenance=provenance,
            trace=MultiQueryRetrievalTrace(
                requested_variant_ids=tuple(item.variant.variant_id for item in results),
                completed_variant_ids=tuple(item.variant.variant_id for item in results),
            ),
        )

    async def search_documents(self, query: str, **_kwargs) -> GlobalRetrievalResult:
        self.document_queries.append(query)
        dense = ChannelRetrievalResult(
            channel=RetrievalChannel.DENSE,
            hits=(_hit(1, RetrievalChannel.DENSE, 1, suffix="fallback"),),
        )
        sparse = ChannelRetrievalResult(
            channel=RetrievalChannel.SPARSE,
            hits=(_hit(1, RetrievalChannel.SPARSE, 1, suffix="fallback"),),
        )
        return GlobalRetrievalResult(dense=dense, sparse=sparse)


@dataclass
class _Rewriter:
    plan: QueryRewritePlan | None = None
    error: Exception | None = None

    async def rewrite(self, _constraints: UserConstraints, *, rule_query: str | None = None):
        if self.error is not None:
            raise self.error
        assert rule_query is not None
        return self.plan


def _rewrite_plan(constraints: UserConstraints) -> QueryRewritePlan:
    original = QueryVariant(source="original", text=constraints.query)
    rule_text = f"{constraints.query} Food & Dining Chelsea-Hudson Yards"
    rule = QueryVariant(source="rule", text=rule_text)
    rewrite = QueryVariant(source="llm", text="quiet Chelsea restaurant", semantic_tags=["quiet"])
    return QueryRewritePlan(
        language="en",
        original=original,
        rule=rule,
        rewrites=[rewrite],
        retrieval_queries=[original.text, rule.text, rewrite.text],
        semantic_tags=["quiet"],
        hard_constraints=HardConstraintEcho.from_constraints(constraints),
        trace=QueryRewriteTrace(
            requested_provider="openai",
            requested_model="gpt-4o-mini-2024-07-18",
            provider="openai",
            model="gpt-4o-mini-2024-07-18",
            rewrite_count=1,
            network_requests=1,
            input_tokens=120,
            output_tokens=30,
            latency_ms=12.5,
        ),
    )


async def test_m3_uses_explicit_variants_and_soft_tags_only_for_final_ranking():
    constraints = UserConstraints(
        query="somewhere conversation is easy",
        category="Food & Dining",
        neighborhood="Chelsea-Hudson Yards",
        result_limit=2,
    )
    shops = _Shops([_candidate(1), _candidate(2)])
    rag = _Rag()
    global_retriever = _Global({"original": 1, "rules": 1, "llm-1": 2})
    discovery = GlobalHybridCandidateDiscovery(
        shops,
        rag,
        global_retriever,
        fusion_pool_limit=2,
        hydration_limit=2,
        query_rewriter=_Rewriter(plan=_rewrite_plan(constraints)),
    )

    result = await discovery.discover(constraints, limit=2)

    assert [item.variant_id for item in global_retriever.variant_calls[0]] == [
        "original",
        "rules",
        "llm-1",
    ]
    assert shops.search_constraints == [constraints]
    assert rag.ranking_constraints[0].desired_tags == ["quiet"]
    assert {candidate.shop_id for candidate in rag.ranking_pools[0].candidates} == {1, 2}
    assert result.retrieval_metadata["queryRewriteCount"] == 1
    assert result.retrieval_metadata["globalQueryVariantCount"] == 3
    assert result.retrieval_metadata["merchantQueryVariantProvenance"]["2"] == [
        {"variantId": "llm-1", "source": "llm", "channels": ["dense", "sparse"]}
    ]


async def test_m3_explicit_exclusion_is_enforced_before_fusion_and_ranking():
    constraints = UserConstraints(
        query="dinner without patio",
        category="Food & Dining",
        neighborhood="Chelsea-Hudson Yards",
        result_limit=2,
    )
    base = await DisabledQueryRewriter().rewrite(constraints)
    fallback_plan = base.model_copy(
        update={
            "trace": base.trace.model_copy(
                update={
                    "requested_provider": "openai",
                    "requested_model": "gpt-4o-mini-2024-07-18",
                    "fallback_used": True,
                    "fallback_reason": "rate-limited",
                }
            )
        }
    )
    shops = _Shops([_candidate(1, tags=["outdoor_seating"]), _candidate(2)])
    rag = _Rag()
    global_retriever = _Global({"original": 1, "rules": 2})
    discovery = GlobalHybridCandidateDiscovery(
        shops,
        rag,
        global_retriever,
        fusion_pool_limit=2,
        hydration_limit=2,
        query_rewriter=_Rewriter(plan=fallback_plan),
    )

    result = await discovery.discover(constraints, limit=2)

    assert [candidate.shop_id for candidate in rag.ranking_pools[0].candidates] == [2]
    assert result.retrieval_metadata["hardConstraintFilteredByReason"]["excludedTags"] == 1
    assert result.retrieval_metadata["queryRewriteFallback"] is True
    assert result.retrieval_metadata["queryRewriteFallbackReason"] == "rate-limited"


async def test_unexpected_rewriter_error_falls_back_to_single_m2_rule_query():
    constraints = UserConstraints(query="dinner", result_limit=1)
    shops = _Shops([_candidate(1)])
    rag = _Rag()
    global_retriever = _Global({})
    discovery = GlobalHybridCandidateDiscovery(
        shops,
        rag,
        global_retriever,
        fusion_pool_limit=1,
        hydration_limit=1,
        query_rewriter=_Rewriter(error=RuntimeError("provider bug")),
    )

    result = await discovery.discover(constraints, limit=1)

    assert global_retriever.variant_calls == []
    assert global_retriever.document_queries == ["dinner"]
    assert result.retrieval_metadata["queryRewriteFallback"] is True
    assert result.retrieval_metadata["queryRewriteFallbackReason"] == "rewriter-error"
