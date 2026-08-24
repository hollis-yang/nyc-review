from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


def content_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SourceMatch:
    shop_id: int
    provider: str
    external_id: str
    source_url: str | None
    matched_fields: tuple[str, ...]
    match_score: float
    match_method: str
    observed_at: str
    snapshot_version: str
    active: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "shopId": self.shop_id,
            "provider": self.provider,
            "externalId": self.external_id,
            "sourceUrl": self.source_url,
            "matchedFields": list(self.matched_fields),
            "matchScore": round(self.match_score, 5),
            "matchMethod": self.match_method,
            "observedAt": self.observed_at,
            "snapshotVersion": self.snapshot_version,
            "active": self.active,
        }


@dataclass(frozen=True)
class FieldObservation:
    shop_id: int
    field_name: str
    value: Any
    provider: str
    external_id: str | None
    observed_at: str
    expires_at: str | None
    match_score: float
    source_priority: int
    snapshot_version: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "shopId": self.shop_id,
            "fieldName": self.field_name,
            "value": self.value,
            "provider": self.provider,
            "externalId": self.external_id,
            "observedAt": self.observed_at,
            "expiresAt": self.expires_at,
            "matchScore": round(self.match_score, 5),
            "sourcePriority": self.source_priority,
            "contentSha256": content_sha256(self.value),
            "snapshotVersion": self.snapshot_version,
        }
