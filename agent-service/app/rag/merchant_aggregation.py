from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from app.rag.global_retrieval import (
    ChannelRetrievalResult,
    GlobalDocumentHit,
    GlobalRetrievalResult,
    RetrievalChannel,
)


class RetainedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    point_id: str = Field(min_length=1)
    shop_external_id: str | None = Field(default=None, min_length=1)
    document_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    root_id: int | None = Field(default=None, gt=0)
    content_type: str = Field(min_length=1)
    document_kind: str = Field(min_length=1)
    document_rank: int = Field(ge=1)
    score: float


class MerchantChannelSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    shop_id: int = Field(gt=0)
    channel: RetrievalChannel
    merchant_rank: int = Field(ge=1)
    best_document_rank: int = Field(ge=1)
    best_score: float
    top_k_mean: float
    retained_documents: tuple[RetainedDocument, ...]
    content_types: tuple[str, ...]
    shop_external_ids: tuple[str, ...] = ()


class MerchantChannelRanking(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    channel: RetrievalChannel
    merchants: tuple[MerchantChannelSignal, ...] = ()
    available: bool = True
    fallback_reason: str | None = None
    input_documents: int = Field(default=0, ge=0)
    rejected_documents: int = Field(default=0, ge=0)


class DocumentSuppressionStats(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    duplicate_points: int = Field(default=0, ge=0)
    duplicate_sources: int = Field(default=0, ge=0)
    duplicate_roots: int = Field(default=0, ge=0)
    duplicate_excerpts: int = Field(default=0, ge=0)
    document_cap: int = Field(default=0, ge=0)

    @property
    def duplicate_documents(self) -> int:
        return self.duplicate_points + self.duplicate_sources + self.duplicate_roots + self.duplicate_excerpts


class MerchantAggregationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    channels: tuple[MerchantChannelRanking, ...]
    suppression: DocumentSuppressionStats
    unique_merchants: int = Field(ge=0)
    identity_conflict_shop_ids: tuple[int, ...] = ()
    identity_conflicts: int = Field(default=0, ge=0)

    def ranking(self, channel: RetrievalChannel) -> MerchantChannelRanking:
        for ranking in self.channels:
            if ranking.channel is channel:
                return ranking
        raise KeyError(f"No merchant ranking exists for channel {channel.value!r}.")

    def expected_external_id(self, shop_id: int) -> str | None:
        """Return the one trusted external ID, rejecting ambiguous identities."""

        if shop_id in self.identity_conflict_shop_ids:
            raise ValueError(f"Shop {shop_id} has conflicting external identities.")
        external_ids = {
            external_id
            for channel in self.channels
            for merchant in channel.merchants
            if merchant.shop_id == shop_id
            for external_id in merchant.shop_external_ids
        }
        if len(external_ids) > 1:
            raise ValueError(f"Shop {shop_id} has conflicting external identities.")
        return next(iter(external_ids), None)


@dataclass
class _MutableSuppression:
    duplicate_points: int = 0
    duplicate_sources: int = 0
    duplicate_roots: int = 0
    duplicate_excerpts: int = 0
    document_cap: int = 0

    def freeze(self) -> DocumentSuppressionStats:
        return DocumentSuppressionStats(
            duplicate_points=self.duplicate_points,
            duplicate_sources=self.duplicate_sources,
            duplicate_roots=self.duplicate_roots,
            duplicate_excerpts=self.duplicate_excerpts,
            document_cap=self.document_cap,
        )


@dataclass(frozen=True)
class _MerchantSummary:
    shop_id: int
    best_document_rank: int
    best_score: float
    top_k_mean: float
    retained_documents: tuple[RetainedDocument, ...]
    content_types: tuple[str, ...]
    shop_external_ids: tuple[str, ...]


def aggregate_merchants(
    result: GlobalRetrievalResult,
    *,
    documents_per_merchant: int = 3,
) -> MerchantAggregationResult:
    """Aggregate document ranks independently within each retrieval channel."""

    if documents_per_merchant < 1:
        raise ValueError("Documents per merchant must be positive.")
    external_ids_by_shop: dict[int, set[str]] = defaultdict(set)
    for channel_result in (result.dense, result.sparse):
        for hit in channel_result.hits:
            external_id = _normalized_external_id(hit.shop_external_id)
            if external_id is not None:
                external_ids_by_shop[hit.shop_id].add(external_id)
    identity_conflict_shop_ids = tuple(
        sorted(shop_id for shop_id, external_ids in external_ids_by_shop.items() if len(external_ids) > 1)
    )
    conflict_shop_ids = set(identity_conflict_shop_ids)
    suppression = _MutableSuppression()
    channels = tuple(
        _aggregate_channel(
            channel_result,
            documents_per_merchant=documents_per_merchant,
            suppression=suppression,
            excluded_shop_ids=conflict_shop_ids,
        )
        for channel_result in (result.dense, result.sparse)
    )
    merchant_ids = {merchant.shop_id for channel in channels for merchant in channel.merchants}
    return MerchantAggregationResult(
        channels=channels,
        suppression=suppression.freeze(),
        unique_merchants=len(merchant_ids),
        identity_conflict_shop_ids=identity_conflict_shop_ids,
        identity_conflicts=len(identity_conflict_shop_ids),
    )


def _aggregate_channel(
    result: ChannelRetrievalResult,
    *,
    documents_per_merchant: int,
    suppression: _MutableSuppression,
    excluded_shop_ids: set[int],
) -> MerchantChannelRanking:
    by_shop: dict[int, list[GlobalDocumentHit]] = defaultdict(list)
    identity_rejected_documents = 0
    for hit in sorted(
        result.hits,
        key=lambda item: (item.rank, -item.score, item.point_id),
    ):
        if hit.shop_id in excluded_shop_ids:
            identity_rejected_documents += 1
            continue
        by_shop[hit.shop_id].append(hit)

    summaries: list[_MerchantSummary] = []
    for shop_id, hits in sorted(by_shop.items()):
        summary = _summarize_merchant(
            shop_id,
            hits,
            documents_per_merchant=documents_per_merchant,
            suppression=suppression,
        )
        if summary is not None:
            summaries.append(summary)
    summaries.sort(
        key=lambda item: (
            item.best_document_rank,
            -item.top_k_mean,
            -item.best_score,
            item.shop_id,
        )
    )
    merchants = tuple(
        MerchantChannelSignal(
            shop_id=summary.shop_id,
            channel=result.channel,
            merchant_rank=rank,
            best_document_rank=summary.best_document_rank,
            best_score=summary.best_score,
            top_k_mean=summary.top_k_mean,
            retained_documents=summary.retained_documents,
            content_types=summary.content_types,
            shop_external_ids=summary.shop_external_ids,
        )
        for rank, summary in enumerate(summaries, start=1)
    )
    return MerchantChannelRanking(
        channel=result.channel,
        merchants=merchants,
        available=result.available,
        fallback_reason=result.fallback_reason,
        input_documents=len(result.hits),
        rejected_documents=result.rejected_points + identity_rejected_documents,
    )


def _summarize_merchant(
    shop_id: int,
    hits: list[GlobalDocumentHit],
    *,
    documents_per_merchant: int,
    suppression: _MutableSuppression,
) -> _MerchantSummary | None:
    unique: list[GlobalDocumentHit] = []
    seen_points: set[str] = set()
    seen_sources: set[str] = set()
    seen_roots: set[int] = set()
    seen_excerpts: set[str] = set()

    for hit in hits:
        excerpt_key = _normalized_excerpt(hit.text)
        if hit.point_id in seen_points:
            suppression.duplicate_points += 1
            continue
        if hit.source_id in seen_sources:
            suppression.duplicate_sources += 1
            continue
        if hit.root_id is not None and hit.root_id in seen_roots:
            suppression.duplicate_roots += 1
            continue
        if excerpt_key in seen_excerpts:
            suppression.duplicate_excerpts += 1
            continue
        seen_points.add(hit.point_id)
        seen_sources.add(hit.source_id)
        if hit.root_id is not None:
            seen_roots.add(hit.root_id)
        seen_excerpts.add(excerpt_key)
        unique.append(hit)

    if not unique:
        return None
    best_document_rank = min(hit.rank for hit in unique)
    best_score = max(hit.score for hit in unique)
    scoring_documents = sorted(
        unique,
        key=lambda hit: (hit.rank, -hit.score, hit.point_id),
    )[:documents_per_merchant]
    prioritized = sorted(
        unique,
        key=lambda hit: (
            _document_priority(hit),
            hit.rank,
            -hit.score,
            hit.point_id,
        ),
    )
    if len(prioritized) > documents_per_merchant:
        suppression.document_cap += len(prioritized) - documents_per_merchant
        prioritized = prioritized[:documents_per_merchant]

    documents = tuple(
        RetainedDocument(
            point_id=hit.point_id,
            shop_external_id=_normalized_external_id(hit.shop_external_id),
            document_id=hit.document_id,
            source_id=hit.source_id,
            root_id=hit.root_id,
            content_type=hit.content_type,
            document_kind=hit.document_kind,
            document_rank=hit.rank,
            score=hit.score,
        )
        for hit in prioritized
    )
    scores = [hit.score for hit in scoring_documents]
    return _MerchantSummary(
        shop_id=shop_id,
        best_document_rank=best_document_rank,
        best_score=best_score,
        top_k_mean=sum(scores) / len(scores),
        retained_documents=documents,
        content_types=tuple(sorted({hit.content_type for hit in prioritized})),
        shop_external_ids=tuple(
            sorted(
                {
                    external_id
                    for hit in unique
                    if (external_id := _normalized_external_id(hit.shop_external_id)) is not None
                }
            )
        ),
    )


def _normalized_excerpt(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _normalized_external_id(external_id: str | None) -> str | None:
    if external_id is None:
        return None
    normalized = external_id.strip()
    return normalized or None


def _document_priority(hit: GlobalDocumentHit) -> int:
    if hit.document_kind == "fact" or hit.content_type in {
        "shop_identity_fact",
        "shop_attribute_fact",
    }:
        return 0
    if hit.content_type == "shop_review_thread":
        return 1
    if hit.content_type in {"shop_review", "blog_comment", "nested_comment"}:
        return 2
    return 3
