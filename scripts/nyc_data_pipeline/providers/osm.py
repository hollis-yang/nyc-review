from __future__ import annotations

from typing import Any

from ..schemas import FieldObservation, SourceMatch
from .base import ProviderResult

PROVIDER = "OPENSTREETMAP"
FIELD_MAP = {
    "opening_hours": "openingHours",
    "phone": "phone",
    "contact:phone": "phone",
    "website": "website",
    "contact:website": "website",
    "reservation": "reservationPolicy",
    "contact:reservation": "reservationUrl",
    "wikidata": "wikidata",
    "wikimedia_commons": "wikimediaCommons",
    "image": "image",
}


class OsmProvider:
    priority = 80

    def collect(self, shops: list[dict[str, Any]], snapshot: dict[str, Any]) -> ProviderResult:
        metadata = snapshot.get("metadata") or {}
        observed_at = str(metadata.get("fetchedAt") or "2026-08-24T00:00:00Z")
        version = str(metadata.get("datasetVersion") or "unknown")
        records = {
            str(record.get("externalId")): record
            for record in snapshot.get("records") or []
            if isinstance(record, dict) and record.get("externalId")
        }
        matches: list[SourceMatch] = []
        observations: list[FieldObservation] = []
        for shop in shops:
            record = records.get(str(shop.get("externalId")))
            if record is None:
                continue
            external_id = str(record["externalId"])
            matches.append(SourceMatch(
                int(shop["id"]), PROVIDER, external_id, record.get("sourceUrl"),
                ("externalId",), 1.0, "EXTERNAL_ID", observed_at, version,
            ))
            tags = record.get("sourceTags") or {}
            for source_field, target_field in FIELD_MAP.items():
                value = tags.get(source_field)
                if value in (None, ""):
                    continue
                observations.append(FieldObservation(
                    int(shop["id"]), target_field, value, PROVIDER, external_id,
                    observed_at, None, 1.0, self.priority, version,
                ))
            observations.append(FieldObservation(
                int(shop["id"]), "businessStatus", "OPERATIONAL", PROVIDER, external_id,
                observed_at, None, 1.0, self.priority, version,
            ))
        return ProviderResult(tuple(matches), tuple(observations))
