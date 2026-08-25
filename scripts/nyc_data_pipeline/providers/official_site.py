from __future__ import annotations

import ipaddress
import json
from collections import defaultdict
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from ..matching import EntityMatcher
from ..matching.normalize import normalize_text
from ..schemas import FieldObservation, SourceMatch
from .base import ProviderResult

PROVIDER = "OFFICIAL_SITE"
TYPE_NAMES = {
    "LocalBusiness", "FoodEstablishment", "Restaurant", "CafeOrCoffeeShop", "Bakery",
    "IceCreamShop", "BarOrPub", "NightClub", "EntertainmentBusiness", "TouristAttraction",
    "SportsActivityLocation", "ExerciseGym", "HealthClub", "HealthAndBeautyBusiness",
    "BeautySalon", "DaySpa", "HairSalon", "NailSalon",
}


def is_safe_public_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal")):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast)


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.active = False
        self.buffer: list[str] = []
        self.documents: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value for key, value in attrs}
        if tag.lower() == "script" and (attributes.get("type") or "").lower() == "application/ld+json":
            self.active = True
            self.buffer = []

    def handle_data(self, data: str) -> None:
        if self.active:
            self.buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or not self.active:
            return
        self.active = False
        try:
            self.documents.append(json.loads("".join(self.buffer)))
        except json.JSONDecodeError:
            pass


def extract_local_business_jsonld(html: str) -> list[dict[str, Any]]:
    parser = _JsonLdParser()
    parser.feed(html[:2_000_000])
    result: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            if "@graph" in value:
                visit(value["@graph"])
            kinds = value.get("@type")
            values = kinds if isinstance(kinds, list) else [kinds]
            normalized = {str(item).rstrip("/").rsplit("/", 1)[-1] for item in values}
            if normalized.intersection(TYPE_NAMES):
                result.append(value)

    for document in parser.documents:
        visit(document)
    return result


def _first_scalar(value: Any) -> Any:
    if isinstance(value, list):
        for item in value:
            result = _first_scalar(item)
            if result not in (None, "", []):
                return result
        return None
    if isinstance(value, dict):
        for key in ("url", "@id", "urlTemplate", "value"):
            result = _first_scalar(value.get(key))
            if result not in (None, "", []):
                return result
        return None
    return value


def _contact_phone(values: dict[str, Any]) -> Any:
    direct = _first_scalar(values.get("telephone"))
    if direct:
        return direct
    points = values.get("contactPoint")
    points = points if isinstance(points, list) else [points]
    for point in points:
        if isinstance(point, dict):
            phone = _first_scalar(point.get("telephone"))
            if phone:
                return phone
    return None


def _reservation(values: dict[str, Any]) -> tuple[Any, Any]:
    accepts = values.get("acceptsReservations")
    if isinstance(accepts, str) and accepts.lower().startswith(("http://", "https://")):
        return accepts, "yes"
    policy = "yes" if accepts is True else "no" if accepts is False else None
    actions = values.get("potentialAction")
    actions = actions if isinstance(actions, list) else [actions]
    for action in actions:
        if not isinstance(action, dict):
            continue
        action_type = str(action.get("@type") or "").lower()
        if not any(token in action_type for token in ("reserve", "order", "book")):
            continue
        target = action.get("target")
        url = _first_scalar(target) or _first_scalar(action.get("url"))
        if url:
            return url, "yes"
    return None, policy


def _price_range(values: dict[str, Any]) -> Any:
    direct = values.get("priceRange")
    if direct not in (None, "", []):
        return _first_scalar(direct)
    offers = values.get("offers")
    offers = offers if isinstance(offers, list) else [offers]
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        currency = str(offer.get("priceCurrency") or "USD").upper()
        prefix = "$" if currency == "USD" else f"{currency} "
        low = _first_scalar(offer.get("lowPrice"))
        high = _first_scalar(offer.get("highPrice"))
        price = _first_scalar(offer.get("price"))
        if low not in (None, "") and high not in (None, ""):
            return f"{prefix}{low}-{prefix}{high}"
        if price not in (None, ""):
            return f"{prefix}{price}"
    return None


def _rating(values: dict[str, Any]) -> tuple[float | None, Any]:
    aggregate = values.get("aggregateRating") if isinstance(values.get("aggregateRating"), dict) else {}
    try:
        raw = float(aggregate.get("ratingValue"))
        best = float(aggregate.get("bestRating") or 5)
        worst = float(aggregate.get("worstRating") or 0)
        normalized = (raw - worst) * 5 / (best - worst) if best > worst else raw
        normalized = max(0.0, min(5.0, normalized))
    except (TypeError, ValueError):
        normalized = None
    return normalized, aggregate.get("ratingCount") or aggregate.get("reviewCount")


class OfficialSiteProvider:
    priority = 100

    def __init__(self, matcher: EntityMatcher | None = None) -> None:
        self.matcher = matcher or EntityMatcher()

    def collect(self, shops: list[dict[str, Any]], snapshot: dict[str, Any]) -> ProviderResult:
        metadata = snapshot.get("metadata") or {}
        observed_at = str(metadata.get("fetchedAt") or "2026-08-24T00:00:00Z")
        version = str(metadata.get("datasetVersion") or "unknown")
        by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in snapshot.get("records") or []:
            if isinstance(record, dict) and is_safe_public_url(str(record.get("sourceUrl") or "")):
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
            external_id = str(record.get("externalId") or record.get("sourceUrl"))
            matches.append(SourceMatch(
                int(shop["id"]), PROVIDER, external_id, record.get("sourceUrl"),
                result.matched_fields, result.score, result.method, observed_at, version,
            ))
            values = record.get("jsonLd") if isinstance(record.get("jsonLd"), dict) else record
            reservation_url, reservation_policy = _reservation(values)
            rating, rating_count = _rating(values)
            field_values = {
                "phone": _contact_phone(values),
                "website": _first_scalar(values.get("url")) or record.get("sourceUrl"),
                "reservationUrl": reservation_url,
                "reservationPolicy": reservation_policy,
                "openingHours": values.get("openingHours") or values.get("openingHoursSpecification"),
                "priceRangeText": _price_range(values),
                "rating": rating,
                "ratingCount": rating_count,
                "image": values.get("image"),
            }
            for field, value in field_values.items():
                if value in (None, "", []):
                    continue
                observations.append(FieldObservation(
                    int(shop["id"]), field, value, PROVIDER, external_id, observed_at,
                    None, result.score, self.priority, version,
                ))
        return ProviderResult(tuple(matches), tuple(observations))
