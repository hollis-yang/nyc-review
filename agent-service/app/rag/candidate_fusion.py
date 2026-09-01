from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import ShopCandidate
from app.rag.global_retrieval import RetrievalChannel
from app.rag.lexical import normalized_merchant_name
from app.rag.merchant_aggregation import MerchantAggregationResult


class FusionChannel(StrEnum):
    STRUCTURED = "structured"
    DENSE = "dense"
    SPARSE = "sparse"


class FusionSourceRank(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    channel: FusionChannel
    rank: int = Field(ge=1)


class FusedMerchant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    fusion_rank: int = Field(ge=1)
    shop_id: int = Field(gt=0)
    rrf_score: float = Field(gt=0)
    source_ranks: tuple[FusionSourceRank, ...]
    candidate: ShopCandidate


class CandidateFusionStats(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    structured_candidates: int = Field(ge=0)
    global_merchants: int = Field(ge=0)
    fusion_candidates: int = Field(ge=0)
    structured_only_merchants: int = Field(ge=0)
    qdrant_only_merchants: int = Field(ge=0)
    overlap_merchants: int = Field(ge=0)
    missing_hydrated_candidates: int = Field(ge=0)
    duplicate_shop_ids_suppressed: int = Field(ge=0)
    duplicate_merchants_suppressed: int = Field(ge=0)
    duplicate_brands_suppressed: int = Field(ge=0)
    returned_candidates: int = Field(ge=0)


class CandidateFusionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidates: tuple[ShopCandidate, ...]
    ranked_merchants: tuple[FusedMerchant, ...]
    stats: CandidateFusionStats


@dataclass(frozen=True)
class _ScoredCandidate:
    candidate: ShopCandidate
    rrf_score: float
    source_ranks: tuple[FusionSourceRank, ...]

    @property
    def tie_key(self) -> tuple[float, int, int, int, float, int]:
        ranks = {item.channel: item.rank for item in self.source_ranks}
        best_rank = min(ranks.values())
        structured_rank = ranks.get(FusionChannel.STRUCTURED, 2**31 - 1)
        rating = self.candidate.score if self.candidate.score is not None else -1.0
        return (
            -self.rrf_score,
            -len(self.source_ranks),
            best_rank,
            structured_rank,
            -rating,
            self.candidate.shop_id,
        )


def fuse_candidates(
    structured_candidates: Sequence[ShopCandidate],
    global_merchants: MerchantAggregationResult,
    hydrated_candidates: Mapping[int, ShopCandidate],
    *,
    limit: int,
    rrf_k: int = 60,
    brand_cap: int = 2,
) -> CandidateFusionResult:
    """Fuse merchant ranks without comparing uncalibrated channel scores."""

    if limit < 1:
        raise ValueError("Fusion output limit must be positive.")
    if rrf_k < 1:
        raise ValueError("RRF k must be positive.")
    if brand_cap < 1:
        raise ValueError("Brand cap must be positive.")

    candidates_by_shop: dict[int, ShopCandidate] = {}
    structured_ranks: dict[int, int] = {}
    duplicate_shop_ids = 0
    for rank, candidate in enumerate(structured_candidates, start=1):
        if candidate.shop_id in candidates_by_shop:
            duplicate_shop_ids += 1
            continue
        candidates_by_shop[candidate.shop_id] = candidate
        structured_ranks[candidate.shop_id] = rank

    for shop_id, candidate in hydrated_candidates.items():
        if isinstance(shop_id, bool) or shop_id <= 0 or candidate.shop_id != shop_id:
            raise ValueError("Hydrated candidate keys must match positive candidate shop IDs.")
        candidates_by_shop.setdefault(shop_id, candidate)

    dense_ranks = {
        merchant.shop_id: merchant.merchant_rank
        for merchant in global_merchants.ranking(RetrievalChannel.DENSE).merchants
    }
    sparse_ranks = {
        merchant.shop_id: merchant.merchant_rank
        for merchant in global_merchants.ranking(RetrievalChannel.SPARSE).merchants
    }
    qdrant_ids = set(dense_ranks) | set(sparse_ranks)
    structured_ids = set(structured_ranks)
    signal_ids = structured_ids | qdrant_ids

    missing_hydrated = 0
    scored: list[_ScoredCandidate] = []
    for shop_id in sorted(signal_ids):
        candidate = candidates_by_shop.get(shop_id)
        if candidate is None:
            missing_hydrated += 1
            continue
        ranks: list[FusionSourceRank] = []
        if shop_id in structured_ranks:
            ranks.append(
                FusionSourceRank(
                    channel=FusionChannel.STRUCTURED,
                    rank=structured_ranks[shop_id],
                )
            )
        if shop_id in dense_ranks:
            ranks.append(
                FusionSourceRank(
                    channel=FusionChannel.DENSE,
                    rank=dense_ranks[shop_id],
                )
            )
        if shop_id in sparse_ranks:
            ranks.append(
                FusionSourceRank(
                    channel=FusionChannel.SPARSE,
                    rank=sparse_ranks[shop_id],
                )
            )
        ranks.sort(key=lambda item: _channel_order(item.channel))
        rrf_score = sum(1.0 / (rrf_k + source.rank) for source in ranks)
        scored.append(
            _ScoredCandidate(
                candidate=candidate,
                rrf_score=rrf_score,
                source_ranks=tuple(ranks),
            )
        )
    scored.sort(key=lambda item: item.tie_key)

    ranked_merchants = tuple(
        FusedMerchant(
            fusion_rank=rank,
            shop_id=item.candidate.shop_id,
            rrf_score=item.rrf_score,
            source_ranks=item.source_ranks,
            candidate=item.candidate,
        )
        for rank, item in enumerate(scored, start=1)
    )

    merchant_deduplicated: list[_ScoredCandidate] = []
    external_ids: set[str] = set()
    duplicate_merchants = 0
    for item in scored:
        candidate = item.candidate
        external_key = str(candidate.external_id or "").strip().casefold()
        if external_key and external_key in external_ids:
            duplicate_merchants += 1
            continue
        if external_key:
            external_ids.add(external_key)
        merchant_deduplicated.append(item)

    selected: list[ShopCandidate] = []
    brand_overflow: list[ShopCandidate] = []
    brand_counts: dict[str, int] = {}
    duplicate_brands = 0
    for item in merchant_deduplicated:
        candidate = item.candidate
        brand = normalized_merchant_name(candidate.name) or f"shop:{candidate.shop_id}"
        if brand_counts.get(brand, 0) >= brand_cap:
            duplicate_brands += 1
            brand_overflow.append(candidate)
            continue
        brand_counts[brand] = brand_counts.get(brand, 0) + 1
        selected.append(candidate)
        if len(selected) >= limit:
            break

    # Diversity is a preference, not a hard constraint. If enforcing the brand
    # cap would under-fill the requested result count, restore the strongest
    # suppressed merchants in their original fusion order.
    if len(selected) < limit:
        selected.extend(brand_overflow[: limit - len(selected)])

    return CandidateFusionResult(
        candidates=tuple(selected),
        ranked_merchants=ranked_merchants,
        stats=CandidateFusionStats(
            structured_candidates=len(structured_ids),
            global_merchants=len(qdrant_ids),
            fusion_candidates=len(scored),
            structured_only_merchants=len(structured_ids - qdrant_ids),
            qdrant_only_merchants=len(qdrant_ids - structured_ids),
            overlap_merchants=len(structured_ids & qdrant_ids),
            missing_hydrated_candidates=missing_hydrated,
            duplicate_shop_ids_suppressed=duplicate_shop_ids,
            duplicate_merchants_suppressed=duplicate_merchants,
            duplicate_brands_suppressed=duplicate_brands,
            returned_candidates=len(selected),
        ),
    )


def _channel_order(channel: FusionChannel) -> int:
    return {
        FusionChannel.STRUCTURED: 0,
        FusionChannel.DENSE: 1,
        FusionChannel.SPARSE: 2,
    }[channel]
