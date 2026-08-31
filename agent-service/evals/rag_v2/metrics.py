from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

from app.rag.lexical import normalized_merchant_name
from app.tools.services import neighborhood_matches

QUALITY_METRICS = (
    "recallAt5",
    "recallAt10",
    "precisionAt5",
    "ndcgAt5",
    "ndcgAt10",
    "mrrAt10",
)

RATE_METRICS = (
    "hardConstraintSatisfaction",
    "evidenceCoverage",
    "duplicateMerchantRate",
    "duplicateBrandRate",
    "excessiveBrandRate",
    "hardNegativeReturnRate",
    "unjudgedReturnedRate",
)


def ranking_metrics(
    ordered_external_ids: Sequence[str | None],
    judgments: Sequence[dict[str, Any]],
    *,
    relevance_threshold: int,
) -> dict[str, float | int]:
    grades = {
        str(item["externalId"]): int(item["relevance"])
        for item in judgments
    }
    relevant = {external_id for external_id, grade in grades.items() if grade >= relevance_threshold}
    if not relevant:
        raise ValueError("Every case must contain at least one binary-relevant judgment.")

    seen: set[str] = set()
    ranked_grades: list[int] = []
    unjudged = 0
    for raw_external_id in ordered_external_ids:
        external_id = str(raw_external_id or "")
        if external_id not in grades:
            unjudged += 1
        if not external_id or external_id in seen:
            ranked_grades.append(0)
            continue
        seen.add(external_id)
        ranked_grades.append(grades.get(external_id, 0))

    return {
        "recallAt5": _recall_at_k(
            ranked_grades, relevant_count=len(relevant), threshold=relevance_threshold, k=5
        ),
        "recallAt10": _recall_at_k(
            ranked_grades, relevant_count=len(relevant), threshold=relevance_threshold, k=10
        ),
        "precisionAt5": _precision_at_k(ranked_grades, threshold=relevance_threshold, k=5),
        "ndcgAt5": _ndcg_at_k(ranked_grades, grades.values(), k=5),
        "ndcgAt10": _ndcg_at_k(ranked_grades, grades.values(), k=10),
        "mrrAt10": _mrr_at_k(ranked_grades, threshold=relevance_threshold, k=10),
        "unjudgedReturnedCount": unjudged,
        "unjudgedReturnedRate": unjudged / max(1, len(ordered_external_ids)),
    }


def hard_constraint_violations(candidate: Any, hard: dict[str, Any]) -> tuple[list[str], list[str]]:
    violations: list[str] = []
    unknown: list[str] = []
    category = _value(candidate, "category")
    if hard.get("category") and category != hard["category"]:
        violations.append("category")
    neighborhood = _value(candidate, "neighborhood")
    if hard.get("neighborhood") and (
        not neighborhood or not neighborhood_matches(str(neighborhood), str(hard["neighborhood"]))
    ):
        violations.append("neighborhood")
    borough = _value(candidate, "borough")
    if hard.get("borough"):
        if not borough:
            violations.append("borough_unknown")
            unknown.append("borough")
        elif borough != hard["borough"]:
            violations.append("borough")
    status = _value(candidate, "business_status", "businessStatus") or "OPERATIONAL"
    if hard.get("businessStatus") and status != hard["businessStatus"]:
        violations.append("business_status")

    max_price = hard.get("maxPricePerPersonCents")
    price = _value(candidate, "avg_price_cents", "avgPriceCents")
    if max_price is not None:
        if price is None:
            violations.append("budget_unknown")
            unknown.append("budget")
        elif int(price) > int(max_price):
            violations.append("budget")

    tags = set(_value(candidate, "tags") or [])
    for tag in sorted(set(hard.get("requiredTags") or []) - tags):
        violations.append(f"required_tag:{tag}")
    for tag in sorted(set(hard.get("excludedTags") or []) & tags):
        violations.append(f"excluded_tag:{tag}")

    open_at = hard.get("openAt")
    if open_at is not None:
        business_hours = _value(candidate, "business_hours", "businessHours") or []
        if not business_hours:
            violations.append("business_hours_unknown")
            unknown.append("business_hours")
        elif not is_open_at(business_hours, open_at):
            violations.append("closed_at_visit")
    return sorted(set(violations)), sorted(set(unknown))


def is_open_at(hours: Iterable[Any], visit: dict[str, Any]) -> bool:
    target_day = int(visit["dayOfWeek"])
    row = next(
        (
            item
            for item in hours
            if int(_value(item, "day_of_week", "dayOfWeek") or 0) == target_day
        ),
        None,
    )
    if row is None or bool(_value(row, "closed")):
        return False
    opening_raw = _value(row, "open_time", "openTime")
    closing_raw = _value(row, "close_time", "closeTime")
    if not opening_raw or not closing_raw:
        return False
    target = _minutes(str(visit["time"]))
    opening = _minutes(str(opening_raw))
    closing = _minutes(str(closing_raw))
    closes_next_day = bool(_value(row, "closes_next_day", "closesNextDay"))
    if closes_next_day or closing <= opening:
        return target >= opening or target < closing
    return opening <= target < closing


def integrity_metrics(
    *,
    candidates: Sequence[Any],
    evidence: Any,
    hard_constraints: dict[str, Any],
    suite: dict[str, Any],
    forbidden_document_ids: set[str],
    hard_negatives: Sequence[dict[str, Any]] = (),
) -> tuple[dict[str, float | int | bool], list[dict[str, Any]]]:
    violations_by_candidate: list[dict[str, Any]] = []
    satisfied = 0
    unknown_count = 0
    for candidate in candidates:
        violations, unknown = hard_constraint_violations(candidate, hard_constraints)
        satisfied += not violations
        unknown_count += len(unknown)
        if violations or unknown:
            violations_by_candidate.append(
                {
                    "shopId": int(_value(candidate, "shop_id", "shopId") or 0),
                    "externalId": _value(candidate, "external_id", "externalId"),
                    "violations": violations,
                    "unknowns": unknown,
                }
            )

    external_ids = [str(_value(item, "external_id", "externalId") or "") for item in candidates]
    duplicate_count = len(external_ids) - len(set(external_ids))
    brands = [normalized_merchant_name(str(_value(item, "name") or "")) for item in candidates]
    brand_counts = Counter(brand for brand in brands if brand)
    duplicate_brands = sum(max(0, count - 1) for count in brand_counts.values())
    excessive_brands = sum(max(0, count - 2) for count in brand_counts.values())
    hard_negative_ids = {
        str(_value(item, "external_id", "externalId") or "")
        for item in hard_negatives
    }
    hard_negative_ids.discard("")
    hard_negative_returns = len(hard_negative_ids & {item for item in external_ids if item})

    evidence_rows = list(_value(evidence, "evidence") or [])
    citations = [
        citation
        for item in evidence_rows
        for citation in (_value(item, "citations") or [])
    ]
    cited_shop_ids = {
        int(_value(item, "shop_id", "shopId") or 0)
        for item in evidence_rows
        if _value(item, "citations")
    }
    candidate_shop_ids = {int(_value(item, "shop_id", "shopId") or 0) for item in candidates}
    citation_ownership_mismatches = 0
    citation_external_id_mismatches = 0
    source_mismatches = 0
    version_mismatches = 0
    security_leakage = 0
    allowed_source_types = set(suite.get("allowedCitationSourceTypes") or [])
    candidate_external_by_id = {
        int(_value(item, "shop_id", "shopId") or 0): str(
            _value(item, "external_id", "externalId") or ""
        )
        for item in candidates
    }
    for evidence_item in evidence_rows:
        owner_shop_id = int(_value(evidence_item, "shop_id", "shopId") or 0)
        for citation in _value(evidence_item, "citations") or []:
            citation_shop_id = int(_value(citation, "shop_id", "shopId") or 0)
            citation_ownership_mismatches += citation_shop_id != owner_shop_id
            citation_external_id = _value(citation, "shop_external_id", "shopExternalId")
            citation_external_id_mismatches += (
                not citation_external_id
                or str(citation_external_id) != candidate_external_by_id.get(owner_shop_id, "")
            )
            source_type = str(_value(citation, "source_type", "sourceType") or "")
            source_mismatches += bool(allowed_source_types and source_type not in allowed_source_types)
            version_mismatches += (
                _value(citation, "data_version", "dataVersion") != suite["dataVersion"]
                or _value(citation, "dataset_sha256", "datasetSha256") != suite["datasetSha256"]
            )
            citation_id = str(_value(citation, "citation_id", "citationId") or "")
            security_leakage += bool(_value(citation, "security_test", "securityTest")) or (
                citation_id in forbidden_document_ids
            )

    returned_count = len(candidates)
    citation_count = len(citations)
    metrics = {
        "hardConstraintSatisfaction": satisfied / returned_count if returned_count else 0.0,
        "hardConstraintViolationCount": returned_count - satisfied,
        "hardConstraintUnknownCount": unknown_count,
        "evidenceCoverage": (
            len(candidate_shop_ids & cited_shop_ids) / returned_count if returned_count else 0.0
        ),
        "duplicateMerchantCount": duplicate_count,
        "duplicateMerchantRate": duplicate_count / returned_count if returned_count else 0.0,
        "duplicateBrandCount": duplicate_brands,
        "duplicateBrandRate": duplicate_brands / returned_count if returned_count else 0.0,
        "excessiveBrandCount": excessive_brands,
        "excessiveBrandRate": excessive_brands / returned_count if returned_count else 0.0,
        "hardNegativeReturnCount": hard_negative_returns,
        "hardNegativeReturnRate": (
            hard_negative_returns / len(hard_negative_ids) if hard_negative_ids else 0.0
        ),
        "citationCount": citation_count,
        "citationOwnershipMismatchCount": citation_ownership_mismatches,
        "citationExternalIdMismatchCount": citation_external_id_mismatches,
        "citationSourceMismatchCount": source_mismatches,
        "citationSourceMismatchRate": source_mismatches / citation_count if citation_count else 0.0,
        "securityLeakageCount": security_leakage,
        "versionMismatchCount": version_mismatches,
        "versionMismatchRate": version_mismatches / citation_count if citation_count else 0.0,
        "emptyResult": not candidates,
    }
    return metrics, violations_by_candidate


def summarize_results(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    overall = _summarize_group(results)
    by_language = {
        language: _summarize_group([item for item in results if item["language"] == language])
        for language in ("en", "zh", "mixed")
    }
    scenarios = sorted({item["scenario"] for item in results})
    by_scenario = {
        scenario: _summarize_group([item for item in results if item["scenario"] == scenario])
        for scenario in scenarios
    }
    integrity = {
        "securityLeakageCount": sum(item["integrity"]["securityLeakageCount"] for item in results),
        "versionMismatchCount": sum(item["integrity"]["versionMismatchCount"] for item in results),
        "citationOwnershipMismatchCount": sum(
            item["integrity"]["citationOwnershipMismatchCount"] for item in results
        ),
        "citationExternalIdMismatchCount": sum(
            item["integrity"]["citationExternalIdMismatchCount"] for item in results
        ),
        "citationSourceMismatchCount": sum(
            item["integrity"]["citationSourceMismatchCount"] for item in results
        ),
        "hardConstraintViolationCount": sum(
            item["integrity"]["hardConstraintViolationCount"] for item in results
        ),
        "hardConstraintUnknownCount": sum(
            item["integrity"]["hardConstraintUnknownCount"] for item in results
        ),
        "duplicateMerchantCount": sum(item["integrity"]["duplicateMerchantCount"] for item in results),
        "duplicateBrandCount": sum(item["integrity"]["duplicateBrandCount"] for item in results),
        "excessiveBrandCount": sum(item["integrity"]["excessiveBrandCount"] for item in results),
        "hardNegativeReturnCount": sum(
            item["integrity"]["hardNegativeReturnCount"] for item in results
        ),
        "emptyResultCount": sum(bool(item["integrity"]["emptyResult"]) for item in results),
    }
    return {
        "overall": overall,
        "byLanguage": by_language,
        "byScenario": by_scenario,
        "integrity": integrity,
        "latencyMs": {
            stage: latency_percentiles([item["latencyMs"][stage] for item in results])
            for stage in ("structuredSearch", "candidateRanking", "evidenceRetrieval", "embedding", "total")
        },
        "requestCounts": {
            "embeddingRequests": sum(item["requests"]["embeddingRequests"] for item in results),
            "embeddedTexts": sum(item["requests"]["embeddedTexts"] for item in results),
            "rewriteRequests": sum(item["requests"]["rewriteRequests"] for item in results),
            "rerankerRequests": sum(item["requests"]["rerankerRequests"] for item in results),
        },
    }


def latency_percentiles(values: Sequence[float]) -> dict[str, float]:
    return {
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
    }


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between zero and one")
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def rounded(value: Any, digits: int = 6) -> Any:
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, dict):
        return {key: rounded(item, digits) for key, item in value.items()}
    if isinstance(value, list):
        return [rounded(item, digits) for item in value]
    return value


def _summarize_group(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {"cases": 0}
    summary: dict[str, Any] = {"cases": len(results)}
    for metric in QUALITY_METRICS:
        summary[metric] = statistics.fmean(float(item["metrics"][metric]) for item in results)
    for metric in RATE_METRICS:
        source = "metrics" if metric == "unjudgedReturnedRate" else "integrity"
        summary[metric] = statistics.fmean(float(item[source][metric]) for item in results)
    return summary


def _recall_at_k(grades: Sequence[int], *, relevant_count: int, threshold: int, k: int) -> float:
    return sum(grade >= threshold for grade in grades[:k]) / relevant_count


def _precision_at_k(grades: Sequence[int], *, threshold: int, k: int) -> float:
    return sum(grade >= threshold for grade in grades[:k]) / k


def _ndcg_at_k(grades: Sequence[int], all_grades: Iterable[int], *, k: int) -> float:
    dcg = _dcg(grades[:k])
    ideal = _dcg(sorted((int(value) for value in all_grades), reverse=True)[:k])
    return dcg / ideal if ideal else 0.0


def _dcg(grades: Sequence[int]) -> float:
    return sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, start=1))


def _mrr_at_k(grades: Sequence[int], *, threshold: int, k: int) -> float:
    for rank, grade in enumerate(grades[:k], start=1):
        if grade >= threshold:
            return 1.0 / rank
    return 0.0


def _minutes(value: str) -> int:
    hour, minute, *_ = value.split(":")
    return int(hour) * 60 + int(minute)


def _value(item: Any, *names: str) -> Any:
    if isinstance(item, dict):
        for name in names:
            if name in item:
                return item[name]
        return None
    for name in names:
        if hasattr(item, name):
            return getattr(item, name)
    return None
