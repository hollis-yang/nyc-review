from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..matching import EntityMatcher
from ..matching.normalize import normalize_text
from ..schemas import FieldObservation, SourceMatch
from .base import ProviderResult

PROVIDER = "NYC_DOHMH"


class NycDohmhProvider:
    priority = 72

    def __init__(self, matcher: EntityMatcher | None = None) -> None:
        self.matcher = matcher or EntityMatcher()

    def collect(self, shops: list[dict[str, Any]], snapshot: dict[str, Any]) -> ProviderResult:
        metadata = snapshot.get("metadata") or {}
        observed_at = str(metadata.get("fetchedAt") or "2026-08-24T00:00:00Z")
        version = str(metadata.get("datasetVersion") or observed_at[:10])
        by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in snapshot.get("records") or []:
            if isinstance(record, dict):
                by_name[normalize_text(record.get("name"))].append(record)
        matches: list[SourceMatch] = []
        observations: list[FieldObservation] = []
        for shop in shops:
            candidates = by_name.get(normalize_text(shop.get("name")), [])
            best: tuple[float, dict[str, Any], Any] | None = None
            for record in candidates:
                result = self.matcher.match(shop, record)
                if result and (best is None or result.score > best[0]):
                    best = (result.score, record, result)
            if best is None:
                continue
            _, record, result = best
            external_id = str(record.get("externalId"))
            source_url = f"https://data.cityofnewyork.us/resource/43nn-pn8j.json?camis={external_id}"
            matches.append(SourceMatch(
                int(shop["id"]), PROVIDER, external_id, source_url, result.matched_fields,
                result.score, result.method, observed_at, version,
            ))
            if record.get("latestGrade"):
                observations.append(FieldObservation(
                    int(shop["id"]), "healthGrade", record["latestGrade"], PROVIDER,
                    external_id, observed_at, None, result.score, self.priority, version,
                ))
        return ProviderResult(tuple(matches), tuple(observations))
