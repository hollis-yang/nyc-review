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
            aggregate = values.get("aggregateRating") if isinstance(values.get("aggregateRating"), dict) else {}
            field_values = {
                "phone": values.get("telephone"),
                "website": values.get("url") or record.get("sourceUrl"),
                "reservationUrl": values.get("acceptsReservations") if isinstance(values.get("acceptsReservations"), str) else None,
                "openingHours": values.get("openingHours") or values.get("openingHoursSpecification"),
                "priceRangeText": values.get("priceRange"),
                "rating": aggregate.get("ratingValue"),
                "ratingCount": aggregate.get("ratingCount") or aggregate.get("reviewCount"),
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
