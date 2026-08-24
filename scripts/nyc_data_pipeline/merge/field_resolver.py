from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .hours_resolver import normalize_hours
from .price_resolver import price_level, price_text
from .rating_resolver import count, rating_tenths


@dataclass(frozen=True)
class ResolvedShop:
    shop: dict[str, Any]
    hours: list[dict[str, Any]] | None
    resolved_providers: dict[str, str]


class FieldResolver:
    def __init__(self, observations: list[dict[str, Any]]) -> None:
        grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
        for observation in observations:
            grouped[(int(observation["shopId"]), str(observation["fieldName"]))].append(observation)
        self._best = {
            key: sorted(values, key=lambda item: (
                int(item.get("sourcePriority") or 0), float(item.get("matchScore") or 0),
                str(item.get("observedAt") or ""), str(item.get("provider") or ""),
            ), reverse=True)[0]
            for key, values in grouped.items()
        }

    def resolve(self, shop: dict[str, Any]) -> ResolvedShop:
        resolved = dict(shop)
        shop_id = int(shop["id"])
        providers: dict[str, str] = {}

        def value(field: str) -> Any:
            observation = self._best.get((shop_id, field))
            if observation:
                providers[field] = str(observation["provider"])
                return observation.get("value")
            return None

        phone = _phone(value("phone"))
        website = _url(value("website"))
        reservation_url = _url(value("reservationUrl"))
        reservation_policy = str(value("reservationPolicy") or "").strip().lower()
        if reservation_url is None and website and reservation_policy in {"yes", "recommended", "required"}:
            reservation_url = website
        status = str(value("businessStatus") or "OPERATIONAL").upper()
        if status not in {"OPERATIONAL", "TEMPORARILY_CLOSED", "PERMANENTLY_CLOSED"}:
            status = "OPERATIONAL"
        rating = rating_tenths(value("rating"))
        rating_count = count(value("ratingCount"))
        resolved_level = price_level(value("priceLevel")) or price_level(value("priceRangeText"))
        range_text = price_text(value("priceRangeText"), resolved_level or resolved.get("priceLevel"))
        health_grade = str(value("healthGrade") or "").strip().upper() or None

        resolved.update({
            "phone": phone,
            "website": website,
            "reservationUrl": reservation_url,
            "businessStatus": status,
            "ratingCount": rating_count if rating_count is not None else int(resolved.get("comments") or 0),
            "priceRangeText": range_text or ("$" * int(resolved.get("priceLevel") or 0) or None),
            "healthGrade": health_grade,
            "lastEnrichedAt": max(
                (str(item.get("observedAt") or "") for (sid, _), item in self._best.items() if sid == shop_id),
                default="2026-08-24T00:00:00Z",
            ),
        })
        if rating is not None:
            resolved["score"] = rating
        if resolved_level is not None:
            resolved["priceLevel"] = resolved_level
        hours_value = value("businessHours")
        if hours_value is None:
            hours_value = value("openingHours")
        hours = normalize_hours(hours_value, shop_id) if hours_value is not None else None
        return ResolvedShop(resolved, hours, providers)


def _url(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = urlparse(text if "://" in text else f"https://{text}")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return parsed.geturl()


def _phone(value: Any) -> str | None:
    text = " ".join(str(value or "").split()).strip()
    return text[:64] if len([character for character in text if character.isdigit()]) >= 7 else None
