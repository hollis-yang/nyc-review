"""P13 deterministic content-quality metrics and fail-closed gates."""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from typing import Any

TOKEN_PATTERN = re.compile(r"[a-z0-9']+")
SPACE_PATTERN = re.compile(r"\s+")


def _normalized(text: str) -> str:
    return SPACE_PATTERN.sub(" ", re.sub(r"[^a-z0-9']+", " ", text.casefold())).strip()


def _tokens(text: str) -> set[str]:
    return set(TOKEN_PATTERN.findall(text.casefold()))


def _duplicate_count(items: list[str]) -> int:
    values = [_normalized(item) for item in items]
    return len(values) - len(set(values))


def _near_duplicate_roots(roots: list[dict[str, Any]]) -> int:
    """Count roots with a highly similar sibling for the same merchant.

    Comparing twenty roots within each shop is bounded (~950k comparisons for
    the full profile) and catches the product-visible template problem without
    an O(n²) global comparison over 100k documents.
    """

    by_shop: dict[int, list[set[str]]] = defaultdict(list)
    for root in roots:
        if root.get("securityTest"):
            continue
        by_shop[int(root["shopId"])].append(_tokens(str(root.get("content") or "")))
    near = 0
    for token_sets in by_shop.values():
        marked: set[int] = set()
        for left_index, left in enumerate(token_sets):
            for right_index in range(left_index + 1, len(token_sets)):
                right = token_sets[right_index]
                union = left | right
                similarity = len(left & right) / len(union) if union else 1.0
                if similarity >= .82:
                    marked.update((left_index, right_index))
        near += len(marked)
    return near


def build_content_quality_report(
    shops: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    note_comments: list[dict[str, Any]],
) -> dict[str, Any]:
    roots = [item for item in reviews if int(item.get("depth") or 0) == 0]
    non_security_roots = [item for item in roots if not item.get("securityTest")]
    non_security_comments = [item for item in note_comments if not item.get("securityTest")]
    rating_counts = Counter(int(item["rating"]) for item in roots)
    sentiment_mismatches = sum(
        1 for item in roots
        if str(item.get("sentiment")) != (
            "POSITIVE" if int(item["rating"]) >= 4
            else "MIXED" if int(item["rating"]) == 3
            else "NEGATIVE"
        )
    )
    roots_by_shop: dict[int, list[int]] = defaultdict(list)
    for item in roots:
        roots_by_shop[int(item["shopId"])].append(int(item["rating"]))
    aggregate_scores = [sum(values) / len(values) for values in roots_by_shop.values() if values]
    rating_diversity = [len(set(values)) for values in roots_by_shop.values() if values]
    count_mismatches = sum(
        1 for shop in shops
        if int(shop.get("localReviewCount", shop.get("comments") or 0))
        != len(roots_by_shop.get(int(shop["id"]), []))
        or int(shop.get("comments") or 0) != len(roots_by_shop.get(int(shop["id"]), []))
    )
    word_lengths = [len(TOKEN_PATTERN.findall(str(item.get("content") or ""))) for item in non_security_roots]
    near_count = _near_duplicate_roots(roots)
    denominator = max(1, len(non_security_roots))
    report = {
        "generatorVersion": "p13-content-v2",
        "reviewRoots": len(roots),
        "ratingDistribution": {str(star): rating_counts.get(star, 0) for star in range(1, 6)},
        "ratingShares": {
            str(star): round(rating_counts.get(star, 0) / max(1, len(roots)), 5)
            for star in range(1, 6)
        },
        "shopAggregateScore": {
            "min": round(min(aggregate_scores), 3) if aggregate_scores else None,
            "max": round(max(aggregate_scores), 3) if aggregate_scores else None,
            "mean": round(statistics.fmean(aggregate_scores), 3) if aggregate_scores else None,
            "standardDeviation": round(statistics.pstdev(aggregate_scores), 3) if len(aggregate_scores) > 1 else 0,
        },
        "shopRatingDiversity": {
            "minDistinctRatings": min(rating_diversity) if rating_diversity else 0,
            "maxDistinctRatings": max(rating_diversity) if rating_diversity else 0,
            "singleRatingShops": sum(value == 1 for value in rating_diversity),
        },
        "reviewLength": {
            "minWords": min(word_lengths) if word_lengths else 0,
            "maxWords": max(word_lengths) if word_lengths else 0,
            "meanWords": round(statistics.fmean(word_lengths), 2) if word_lengths else 0,
            "shortShare": round(sum(value < 45 for value in word_lengths) / max(1, len(word_lengths)), 5),
            "longShare": round(sum(value >= 55 for value in word_lengths) / max(1, len(word_lengths)), 5),
        },
        "exactDuplicateReviewRoots": _duplicate_count([str(item["content"]) for item in non_security_roots]),
        "nearDuplicateReviewRoots": near_count,
        "nearDuplicateReviewRootRate": round(near_count / denominator, 5),
        "exactDuplicateNotes": _duplicate_count([str(item["content"]) for item in notes]),
        "exactDuplicateNoteComments": _duplicate_count([str(item["content"]) for item in non_security_comments]),
        "sentimentRatingMismatches": sentiment_mismatches,
        "localReviewCountMismatches": count_mismatches,
    }
    return report


def enforce_content_quality(report: dict[str, Any], shop_count: int) -> None:
    failed: list[str] = []
    if report["exactDuplicateReviewRoots"]:
        failed.append("exact duplicate review roots")
    if report["exactDuplicateNotes"]:
        failed.append("exact duplicate notes")
    if report["exactDuplicateNoteComments"]:
        failed.append("exact duplicate note comments")
    if float(report["nearDuplicateReviewRootRate"]) >= .02:
        failed.append("near-duplicate review root rate")
    if report["sentimentRatingMismatches"]:
        failed.append("rating/sentiment mismatch")
    if report["localReviewCountMismatches"]:
        failed.append("local review count mismatch")
    rating_shares = report["ratingShares"]
    rating_counts = report["ratingDistribution"]
    rating_tail_missing = (
        any(int(rating_counts[str(star)]) == 0 for star in range(1, 6))
        if int(report["reviewRoots"]) < 500
        else any(float(rating_shares[str(star)]) < .02 for star in range(1, 6))
    )
    if rating_tail_missing:
        failed.append("missing rating tail")
    if max(float(value) for value in rating_shares.values()) > .60:
        failed.append("rating bucket concentration")
    diversity = report["shopRatingDiversity"]
    if int(report["reviewRoots"]) >= shop_count * 10 and (
        int(diversity["singleRatingShops"]) > 0
        or int(diversity["minDistinctRatings"]) < 2
    ):
        failed.append("per-shop rating diversity")
    aggregate = report["shopAggregateScore"]
    if shop_count >= 100 and (
        float(aggregate["standardDeviation"] or 0) < .25
        or float(aggregate["min"] or 5) > 3.2
        or float(aggregate["max"] or 0) < 4.6
    ):
        failed.append("shop aggregate rating spread")
    lengths = report["reviewLength"]
    length_gate_failed = (
        float(lengths["shortShare"]) < .15 or float(lengths["longShare"]) < .10
        if int(report["reviewRoots"]) >= 500
        else int(lengths["maxWords"]) - int(lengths["minWords"]) < 15
    )
    if length_gate_failed:
        failed.append("review length diversity")
    if failed:
        raise ValueError("P13 content quality gates failed: " + ", ".join(failed))
