from __future__ import annotations

import pytest

from app.domain.models import ShopCandidate
from app.rag.candidate_fusion import fuse_candidates
from app.rag.global_retrieval import (
    ChannelRetrievalResult,
    GlobalDocumentHit,
    GlobalQueryVariant,
    MultiQueryGlobalRetrievalResult,
    MultiQueryRetrievalTrace,
    QueryVariantSource,
    RetrievalChannel,
    VariantGlobalRetrievalResult,
    VariantRetrievalStatus,
)
from app.rag.merchant_aggregation import (
    aggregate_merchants,
    aggregate_query_variant_merchants,
)


def _hit(
    *,
    point_id: str,
    shop_id: int,
    channel: RetrievalChannel,
    rank: int,
    score: float,
    shop_external_id: str | None = None,
) -> GlobalDocumentHit:
    return GlobalDocumentHit(
        point_id=point_id,
        shop_id=shop_id,
        shop_external_id=shop_external_id or f"node:{shop_id}",
        channel=channel,
        rank=rank,
        score=score,
        document_id=f"document:{point_id}",
        source_id=f"source:{point_id}",
        root_id=shop_id * 10_000 + rank,
        content_type="shop_review_thread",
        document_kind="evidence",
        text=f"Evidence from {point_id}",
    )


def _channel(
    channel: RetrievalChannel,
    hits: tuple[GlobalDocumentHit, ...] = (),
    *,
    available: bool = True,
    fallback_reason: str | None = None,
) -> ChannelRetrievalResult:
    return ChannelRetrievalResult(
        channel=channel,
        hits=hits,
        available=available,
        fallback_reason=fallback_reason,
        returned_points=len(hits),
    )


def _variant(
    variant_id: str,
    source: QueryVariantSource,
    *,
    dense_hits: tuple[GlobalDocumentHit, ...] = (),
    sparse_hits: tuple[GlobalDocumentHit, ...] = (),
    dense_available: bool = True,
    sparse_available: bool = True,
    status: VariantRetrievalStatus | None = None,
) -> VariantGlobalRetrievalResult:
    if status is None:
        if dense_available and sparse_available:
            status = VariantRetrievalStatus.COMPLETE
        elif dense_available or sparse_available:
            status = VariantRetrievalStatus.PARTIAL
        else:
            status = VariantRetrievalStatus.UNAVAILABLE
    return VariantGlobalRetrievalResult(
        variant=GlobalQueryVariant(
            variant_id=variant_id,
            source=source,
            query=f"query for {variant_id}",
        ),
        status=status,
        fallback_reason=None if status is VariantRetrievalStatus.COMPLETE else "fixture-fallback",
        dense=_channel(
            RetrievalChannel.DENSE,
            dense_hits,
            available=dense_available,
            fallback_reason=None if dense_available else "fixture-unavailable",
        ),
        sparse=_channel(
            RetrievalChannel.SPARSE,
            sparse_hits,
            available=sparse_available,
            fallback_reason=None if sparse_available else "fixture-unavailable",
        ),
    )


def _multi(
    variants: tuple[VariantGlobalRetrievalResult, ...],
) -> MultiQueryGlobalRetrievalResult:
    dense_results = tuple(item.dense for item in variants)
    sparse_results = tuple(item.sparse for item in variants)
    dense_hits = tuple(hit for result in dense_results for hit in result.hits)
    sparse_hits = tuple(hit for result in sparse_results for hit in result.hits)
    return MultiQueryGlobalRetrievalResult(
        dense=_channel(
            RetrievalChannel.DENSE,
            dense_hits,
            available=any(item.available for item in dense_results),
        ),
        sparse=_channel(
            RetrievalChannel.SPARSE,
            sparse_hits,
            available=any(item.available for item in sparse_results),
        ),
        variants=variants,
        trace=MultiQueryRetrievalTrace(
            requested_variant_ids=tuple(item.variant.variant_id for item in variants),
            completed_variant_ids=tuple(
                item.variant.variant_id
                for item in variants
                if item.status is not VariantRetrievalStatus.TIMEOUT
            ),
            partial_failure_variant_ids=tuple(
                item.variant.variant_id
                for item in variants
                if item.status is not VariantRetrievalStatus.COMPLETE
            ),
            timed_out_variant_ids=tuple(
                item.variant.variant_id for item in variants if item.status is VariantRetrievalStatus.TIMEOUT
            ),
        ),
    )


def _candidate(shop_id: int) -> ShopCandidate:
    return ShopCandidate(
        shop_id=shop_id,
        name=f"Merchant {shop_id}",
        category="Food & Dining",
        neighborhood="Midtown",
        latitude=40.75,
        longitude=-73.98,
        score=4.5,
        external_id=f"node:{shop_id}",
    )


def test_query_variant_rrf_rewards_repeated_merchant_recall_over_raw_document_score():
    original = _variant(
        "original",
        QueryVariantSource.ORIGINAL,
        dense_hits=(
            _hit(
                point_id="original-a",
                shop_id=1,
                channel=RetrievalChannel.DENSE,
                rank=1,
                score=0.99,
            ),
            _hit(
                point_id="original-b",
                shop_id=2,
                channel=RetrievalChannel.DENSE,
                rank=2,
                score=0.30,
            ),
        ),
    )
    rules = _variant(
        "rules",
        QueryVariantSource.RULES,
        dense_hits=(
            _hit(
                point_id="rules-b",
                shop_id=2,
                channel=RetrievalChannel.DENSE,
                rank=1,
                score=0.30,
            ),
        ),
    )
    llm = _variant(
        "llm-1",
        QueryVariantSource.LLM,
        dense_hits=(
            _hit(
                point_id="llm-b",
                shop_id=2,
                channel=RetrievalChannel.DENSE,
                rank=1,
                score=0.30,
            ),
        ),
    )
    retrieval = _multi((original, rules, llm))

    raw_document_order = aggregate_merchants(retrieval)
    aggregated = aggregate_query_variant_merchants(retrieval, rrf_k=60)

    assert [
        merchant.shop_id for merchant in raw_document_order.ranking(RetrievalChannel.DENSE).merchants
    ] == [1, 2]
    assert [merchant.shop_id for merchant in aggregated.ranking(RetrievalChannel.DENSE).merchants] == [2, 1]
    assert [merchant.merchant_rank for merchant in aggregated.ranking(RetrievalChannel.DENSE).merchants] == [
        1,
        2,
    ]
    assert aggregated.unique_merchants == 2


def test_query_variant_rrf_is_stable_across_variant_and_hit_input_order():
    variants = (
        _variant(
            "original",
            QueryVariantSource.ORIGINAL,
            dense_hits=(
                _hit(
                    point_id="a",
                    shop_id=1,
                    channel=RetrievalChannel.DENSE,
                    rank=1,
                    score=0.8,
                ),
                _hit(
                    point_id="b",
                    shop_id=2,
                    channel=RetrievalChannel.DENSE,
                    rank=2,
                    score=0.7,
                ),
            ),
        ),
        _variant(
            "rules",
            QueryVariantSource.RULES,
            dense_hits=(
                _hit(
                    point_id="c",
                    shop_id=2,
                    channel=RetrievalChannel.DENSE,
                    rank=1,
                    score=0.6,
                ),
                _hit(
                    point_id="d",
                    shop_id=1,
                    channel=RetrievalChannel.DENSE,
                    rank=2,
                    score=0.5,
                ),
            ),
        ),
    )
    reordered = tuple(
        item.model_copy(
            update={"dense": item.dense.model_copy(update={"hits": tuple(reversed(item.dense.hits))})}
        )
        for item in reversed(variants)
    )

    first = aggregate_query_variant_merchants(_multi(variants))
    second = aggregate_query_variant_merchants(_multi(reordered))

    assert first == second
    assert [merchant.shop_id for merchant in first.ranking(RetrievalChannel.DENSE).merchants] == [1, 2]


def test_query_variant_aggregation_rejects_cross_variant_identity_conflicts_and_deduplicates():
    first_shared = _hit(
        point_id="shared",
        shop_id=2,
        channel=RetrievalChannel.DENSE,
        rank=2,
        score=0.7,
    )
    original = _variant(
        "original",
        QueryVariantSource.ORIGINAL,
        dense_hits=(
            _hit(
                point_id="conflict-original",
                shop_id=1,
                channel=RetrievalChannel.DENSE,
                rank=1,
                score=0.9,
                shop_external_id="node:one",
            ),
            first_shared,
        ),
    )
    rules = _variant(
        "rules",
        QueryVariantSource.RULES,
        dense_hits=(
            _hit(
                point_id="conflict-rules",
                shop_id=1,
                channel=RetrievalChannel.DENSE,
                rank=1,
                score=0.8,
                shop_external_id="node:other",
            ),
            first_shared.model_copy(update={"rank": 2, "score": 0.6}),
        ),
    )

    aggregated = aggregate_query_variant_merchants(_multi((original, rules)))

    assert aggregated.identity_conflict_shop_ids == (1,)
    assert aggregated.identity_conflicts == 1
    assert aggregated.unique_merchants == 1
    dense = aggregated.ranking(RetrievalChannel.DENSE)
    assert [merchant.shop_id for merchant in dense.merchants] == [2]
    assert dense.rejected_documents == 2
    assert [item.point_id for item in dense.merchants[0].retained_documents] == ["shared"]
    assert aggregated.suppression.duplicate_points == 1
    assert aggregated.expected_external_id(2) == "node:2"
    with pytest.raises(ValueError, match="conflicting external identities"):
        aggregated.expected_external_id(1)


def test_partial_query_variants_contribute_only_healthy_channels_and_remain_fusion_compatible():
    original = _variant(
        "original",
        QueryVariantSource.ORIGINAL,
        dense_hits=(
            _hit(
                point_id="dense-1",
                shop_id=1,
                channel=RetrievalChannel.DENSE,
                rank=1,
                score=0.9,
            ),
        ),
        sparse_available=False,
    )
    rules = _variant(
        "rules",
        QueryVariantSource.RULES,
        dense_hits=(
            _hit(
                point_id="ignored-unavailable",
                shop_id=99,
                channel=RetrievalChannel.DENSE,
                rank=1,
                score=1.0,
            ),
        ),
        sparse_hits=(
            _hit(
                point_id="sparse-2",
                shop_id=2,
                channel=RetrievalChannel.SPARSE,
                rank=1,
                score=2.0,
            ),
        ),
        dense_available=False,
    )
    timed_out = _variant(
        "llm-1",
        QueryVariantSource.LLM,
        dense_available=False,
        sparse_available=False,
        status=VariantRetrievalStatus.TIMEOUT,
    )

    aggregated = aggregate_query_variant_merchants(_multi((original, rules, timed_out)))

    dense = aggregated.ranking(RetrievalChannel.DENSE)
    sparse = aggregated.ranking(RetrievalChannel.SPARSE)
    assert dense.available is True
    assert dense.fallback_reason == "partial-variant-fallback"
    assert [merchant.shop_id for merchant in dense.merchants] == [1]
    assert sparse.available is True
    assert sparse.fallback_reason == "partial-variant-fallback"
    assert [merchant.shop_id for merchant in sparse.merchants] == [2]
    assert aggregated.unique_merchants == 2

    fusion = fuse_candidates(
        [],
        aggregated,
        {1: _candidate(1), 2: _candidate(2), 99: _candidate(99)},
        limit=3,
    )
    assert [candidate.shop_id for candidate in fusion.candidates] == [1, 2]
    assert fusion.stats.global_merchants == 2

    with pytest.raises(ValueError, match="RRF k"):
        aggregate_query_variant_merchants(_multi((original,)), rrf_k=0)
