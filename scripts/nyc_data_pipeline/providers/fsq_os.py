from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..matching import EntityMatcher
from ..matching.normalize import normalize_text
from ..schemas import FieldObservation, SourceMatch
from .base import ProviderResult

PROVIDER = "FSQ_OS_PLACES"
SUPPORTED_FIELDS = {
    "telephone": "phone",
    "phone": "phone",
    "website": "website",
    "hours": "businessHours",
    "rating": "rating",
    "ratingCount": "ratingCount",
    "price": "priceLevel",
    "priceRange": "priceRangeText",
    "status": "businessStatus",
}


class FsqOsProvider:
    """Consumes a pinned local FSQ OS or licensed export; it never calls the API."""

    priority = 70

    def __init__(self, matcher: EntityMatcher | None = None) -> None:
        self.matcher = matcher or EntityMatcher()

    def collect(self, shops: list[dict[str, Any]], snapshot: dict[str, Any]) -> ProviderResult:
        metadata = snapshot.get("metadata") or {}
        observed_at = str(metadata.get("fetchedAt") or "2026-08-24T00:00:00Z")
        version = str(metadata.get("datasetVersion") or "unknown")
        by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in snapshot.get("records") or []:
            if isinstance(record, dict):
                by_name[normalize_text(record.get("name"))].append(record)
        matches: list[SourceMatch] = []
        observations: list[FieldObservation] = []
        for shop in shops:
            best = None
            for record in by_name.get(normalize_text(shop.get("name")), []):
                result = self.matcher.match(shop, record)
                if result and (best is None or result.score > best[0].score):
                    best = (result, record)
            if best is None:
                continue
            result, record = best
            external_id = str(record.get("externalId") or record.get("fsqPlaceId") or "")
            if not external_id:
                continue
            matches.append(SourceMatch(
                int(shop["id"]), PROVIDER, external_id, record.get("sourceUrl"),
                result.matched_fields, result.score, result.method, observed_at, version,
            ))
            for source_field, target_field in SUPPORTED_FIELDS.items():
                value = record.get(source_field)
                if value in (None, "", []):
                    continue
                observations.append(FieldObservation(
                    int(shop["id"]), target_field, value, PROVIDER, external_id,
                    observed_at, record.get("expiresAt"), result.score, self.priority, version,
                ))
        return ProviderResult(tuple(matches), tuple(observations))
