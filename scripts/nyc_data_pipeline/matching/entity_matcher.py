from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .normalize import haversine_meters, normalize_domain, normalize_phone, normalize_text, postcode
from .match_rules import ENTITY_MATCH_THRESHOLD, IMAGE_MATCH_THRESHOLD, MAX_ENTITY_DISTANCE_METERS


@dataclass(frozen=True)
class MatchResult:
    score: float
    method: str
    matched_fields: tuple[str, ...]


class EntityMatcher:
    """Conservative merchant matcher; media matching uses a stricter threshold."""

    def match(self, shop: dict[str, Any], record: dict[str, Any], *, for_image: bool = False) -> MatchResult | None:
        if shop.get("externalId") and record.get("externalId") == shop.get("externalId"):
            return MatchResult(1.0, "EXTERNAL_ID", ("externalId",))

        if self._hard_conflict(shop, record):
            return None
        name_score = SequenceMatcher(None, normalize_text(shop.get("name")), normalize_text(record.get("name"))).ratio()
        address_score = SequenceMatcher(
            None,
            normalize_text(shop.get("address")),
            normalize_text(record.get("address")),
        ).ratio()
        distance = self._distance(shop, record)
        coordinate_score = 1.0 if distance is not None and distance <= 30 else 0.8 if distance is not None and distance <= 100 else 0.0
        phone_equal = bool(normalize_phone(shop.get("phone"))) and normalize_phone(shop.get("phone")) == normalize_phone(record.get("phone"))
        domain_equal = bool(normalize_domain(shop.get("website"))) and normalize_domain(shop.get("website")) == normalize_domain(record.get("website"))
        score = name_score * 0.46 + address_score * 0.28 + coordinate_score * 0.16 + (0.06 if phone_equal else 0) + (0.04 if domain_equal else 0)
        threshold = IMAGE_MATCH_THRESHOLD if for_image else ENTITY_MATCH_THRESHOLD
        if score < threshold or name_score < (0.9 if for_image else 0.72):
            return None
        fields = ["name"]
        if address_score >= 0.72:
            fields.append("address")
        if coordinate_score:
            fields.append("coordinates")
        if phone_equal:
            fields.append("phone")
        if domain_equal:
            fields.append("website")
        return MatchResult(score, "COMPOSITE", tuple(fields))

    @staticmethod
    def _distance(shop: dict[str, Any], record: dict[str, Any]) -> float | None:
        try:
            return haversine_meters(
                float(shop.get("y", shop.get("latitude"))),
                float(shop.get("x", shop.get("longitude"))),
                float(record.get("latitude", record.get("y"))),
                float(record.get("longitude", record.get("x"))),
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _hard_conflict(shop: dict[str, Any], record: dict[str, Any]) -> bool:
        shop_postcode = postcode(shop.get("address"))
        record_postcode = postcode(record.get("address") or record.get("zipcode"))
        if shop_postcode and record_postcode and shop_postcode != record_postcode:
            return True
        shop_borough = normalize_text(shop.get("borough"))
        record_borough = normalize_text(record.get("borough"))
        if shop_borough and record_borough and shop_borough != record_borough:
            return True
        distance = EntityMatcher._distance(shop, record)
        return distance is not None and distance > MAX_ENTITY_DISTANCE_METERS
