#!/usr/bin/env python3
"""Fetch and normalize named NYC places from OpenStreetMap via Overpass.

The snapshot retains useful source-backed merchant tags (hours, contacts and
Wikimedia/Wikidata references) for the P2/P3 enrichment stage. Reviews,
platform ratings, promotions and fallback media are generated separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nyc_nta import contains_point

DATASET_ID = "openstreetmap-overpass-nyc-places"
DATASET_NAME = "OpenStreetMap NYC named places"
SOURCE_NAME = "OpenStreetMap contributors"
SOURCE_URL = "https://www.openstreetmap.org/copyright"
LICENSE_NAME = "ODbL-1.0"
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NYC_BBOX = (40.477399, -74.259090, 40.917577, -73.700272)
SHOP_SOURCE_FIELD_LIMITS = {
    "name": 128,
    "address": 255,
    "borough": 64,
    "neighborhood": 128,
    "neighborhoodCode": 8,
    "externalId": 160,
    "sourceName": 160,
    "sourceUrl": 768,
}


# Queries are split by product category so public Overpass instances do not
# need to evaluate one very large union. Duplicate OSM elements are removed
# after all responses have been normalized.
CATEGORY_FILTERS = {
    1: (
        '["amenity"~"^(restaurant|fast_food|food_court)$"]',
    ),
    2: (
        '["amenity"~"^(cafe|ice_cream)$"]',
        '["shop"~"^(bakery|pastry|coffee|tea|confectionery)$"]',
    ),
    3: (
        '["amenity"~"^(bar|pub|nightclub|music_venue)$"]',
    ),
    4: (
        '["amenity"~"^(theatre|cinema|arts_centre)$"]',
        '["tourism"~"^(museum|gallery|attraction)$"]',
        '["leisure"~"^(amusement_arcade|escape_game|bowling_alley)$"]',
    ),
    5: (
        '["leisure"~"^(fitness_centre|sports_centre|dance|yoga|spa)$"]',
        '["sport"~"^(fitness|yoga|pilates)$"]',
        '["amenity"="spa"]',
        '["shop"="massage"]',
    ),
    6: (
        '["shop"~"^(hairdresser|beauty|cosmetics|nail_salon)$"]',
    ),
}


def fetch_snapshot(
    nta_snapshot: Path,
    *,
    overpass_url: str = DEFAULT_OVERPASS_URL,
    user_agent: str = "nyc-review-p8-real-data-pipeline/1.0",
    retries: int = 5,
    request_delay: float = 1.0,
    retry_base_delay: float = 5.0,
    max_retry_delay: float = 60.0,
) -> dict[str, Any]:
    neighborhoods = _load_neighborhoods(nta_snapshot)
    elements: dict[tuple[str, int], dict[str, Any]] = {}
    request_count = 0
    for type_id, filters in CATEGORY_FILTERS.items():
        for osm_filter in filters:
            if request_count and request_delay > 0:
                # Public Overpass instances are shared infrastructure. A
                # short interval keeps this reproducible fetch from issuing a
                # burst of category requests and being rate-limited halfway.
                time.sleep(request_delay)
            query = _overpass_query(osm_filter)
            payload = _post_overpass(
                overpass_url,
                query,
                user_agent=user_agent,
                retries=retries,
                retry_base_delay=retry_base_delay,
                max_retry_delay=max_retry_delay,
            )
            request_count += 1
            for element in payload.get("elements") or []:
                if not isinstance(element, dict):
                    continue
                element_type = str(element.get("type") or "")
                element_id = element.get("id")
                if element_type not in {"node", "way", "relation"} or not isinstance(element_id, int):
                    continue
                # Preserve the first category match. Classification below uses
                # the tags again and therefore remains deterministic.
                elements.setdefault((element_type, element_id), element)

    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    records = normalize_elements(list(elements.values()), neighborhoods, fetched_at=fetched_at)
    category_counts = Counter(str(record["typeId"]) for record in records)
    return {
        "metadata": {
            "datasetId": DATASET_ID,
            "datasetName": DATASET_NAME,
            "datasetVersion": fetched_at[:10],
            "sourceName": SOURCE_NAME,
            "sourceUrl": SOURCE_URL,
            "licenseName": LICENSE_NAME,
            "overpassUrl": overpass_url,
            "overpassRequests": request_count,
            "requestDelaySeconds": request_delay,
            "fetchedAt": fetched_at,
            "recordCount": len(records),
            "categoryCounts": dict(sorted(category_counts.items())),
            "bbox": list(NYC_BBOX),
            "notes": (
                "Only OSM establishment identity, tags and location are source-backed. "
                "NYC Review reviews, ratings, promotions and illustrative images are synthetic demo content."
            ),
        },
        "records": records,
    }


def normalize_elements(
    elements: list[dict[str, Any]],
    neighborhoods: list[dict[str, Any]],
    *,
    fetched_at: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_identity: set[tuple[str, int]] = set()
    seen_places: set[tuple[str, str, int, int]] = set()
    for element in elements:
        element_type = str(element.get("type") or "")
        element_id = element.get("id")
        if element_type not in {"node", "way", "relation"} or not isinstance(element_id, int):
            continue
        identity = (element_type, element_id)
        if identity in seen_identity:
            continue
        tags = element.get("tags") or {}
        if not isinstance(tags, dict):
            continue
        name = _clean(tags.get("name") or tags.get("brand"))
        if not name or _is_closed(tags):
            continue
        latitude, longitude = _coordinates(element)
        if latitude is None or longitude is None or not _inside_bbox(latitude, longitude):
            continue
        category = classify_tags(tags)
        if category is None:
            continue
        address = _address(tags)
        if not address:
            # A coordinate is not a merchant address. Real-only mode excludes
            # incomplete identities instead of inventing a display address.
            continue
        neighborhood = _find_neighborhood(neighborhoods, longitude, latitude)
        if neighborhood is None:
            # NYC identity mode is fail-closed: places outside an official NTA
            # are not silently assigned to the nearest neighborhood.
            continue
        dedupe_key = (
            _normalize_text(name),
            _normalize_text(address),
            round(latitude * 10_000),
            round(longitude * 10_000),
        )
        if dedupe_key in seen_places:
            continue
        seen_identity.add(identity)
        seen_places.add(dedupe_key)
        source_url = f"https://www.openstreetmap.org/{element_type}/{element_id}"
        external_id = f"openstreetmap:{element_type}:{element_id}"
        record = {
            "externalId": external_id,
            "name": name,
            "typeId": category["typeId"],
            "subcategory": category["subcategory"],
            "sourceCategory": category["sourceCategory"],
            "borough": neighborhood["borough"],
            "neighborhood": neighborhood["name"],
            "neighborhoodCode": neighborhood["code"],
            "address": address,
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "sourceName": SOURCE_NAME,
            "sourceUrl": source_url,
            "sourceFetchedAt": fetched_at,
            "sourceLicense": LICENSE_NAME,
            "sourceTags": _source_tags(tags),
            "verifiedTags": _verified_nyc_review_tags(tags),
        }
        _validate_source_field_lengths(record, external_id)
        records.append(record)
    return sorted(records, key=lambda item: (item["typeId"], item["externalId"]))


def classify_tags(tags: dict[str, Any]) -> dict[str, Any] | None:
    amenity = _normalize_text(tags.get("amenity"))
    shop = _normalize_text(tags.get("shop"))
    tourism = _normalize_text(tags.get("tourism"))
    leisure = _normalize_text(tags.get("leisure"))
    sport = _normalize_text(tags.get("sport"))
    cuisine = _normalize_text(tags.get("cuisine"))

    if amenity in {"cafe", "ice_cream"} or shop in {"bakery", "pastry", "coffee", "tea", "confectionery"}:
        subcategory = "Bakery" if shop in {"bakery", "pastry"} else "Dessert" if amenity == "ice_cream" or shop == "confectionery" else "Coffee Shop"
        return _category(2, subcategory, amenity or shop)
    if amenity in {"bar", "pub", "nightclub", "music_venue"}:
        subcategory = {"pub": "Pub", "music_venue": "Live Music", "nightclub": "Live Music"}.get(amenity, "Cocktail Bar")
        return _category(3, subcategory, amenity)
    if amenity in {"theatre", "cinema", "arts_centre"} or tourism in {"museum", "gallery", "attraction"} or leisure in {"amusement_arcade", "escape_game", "bowling_alley"}:
        value = amenity or tourism or leisure
        subcategory = {
            "theatre": "Theater",
            "cinema": "Cinema",
            "amusement_arcade": "Arcade",
            "bowling_alley": "Arcade",
            "escape_game": "Escape Room",
        }.get(value, "Museum")
        return _category(4, subcategory, value)
    if leisure in {"fitness_centre", "sports_centre", "dance", "yoga", "spa"} or sport in {"fitness", "yoga", "pilates"} or amenity == "spa" or shop == "massage":
        value = leisure or sport or amenity or shop
        subcategory = "Yoga" if value == "yoga" else "Pilates" if value in {"dance", "pilates"} else "Spa" if value == "spa" else "Massage" if value == "massage" else "Gym"
        return _category(5, subcategory, value)
    if shop in {"hairdresser", "beauty", "cosmetics", "nail_salon"}:
        beauty = _normalize_text(tags.get("beauty"))
        if shop == "nail_salon" or beauty in {"nails", "nail"}:
            subcategory = "Nail Salon"
        elif shop == "cosmetics" or beauty in {"skin_care", "skincare"}:
            subcategory = "Skincare"
        elif _normalize_text(tags.get("hairdresser")) == "barber" or beauty == "barber":
            subcategory = "Barber"
        else:
            subcategory = "Hair Salon"
        return _category(6, subcategory, shop)
    if amenity in {"restaurant", "fast_food", "food_court"}:
        if "chinese" in cuisine:
            subcategory = "Chinese"
        elif "japanese" in cuisine:
            subcategory = "Japanese"
        elif "italian" in cuisine or "pizza" in cuisine:
            subcategory = "Italian"
        elif "mexican" in cuisine:
            subcategory = "Mexican"
        elif "vegetarian" in cuisine or "vegan" in cuisine:
            subcategory = "Vegetarian"
        else:
            subcategory = "American"
        return _category(1, subcategory, amenity)
    return None


def load_snapshot(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        snapshot = json.load(handle)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("records"), list):
        raise TypeError(f"Invalid OpenStreetMap place snapshot: {path}")
    metadata = snapshot.get("metadata") or {}
    if metadata.get("datasetId") != DATASET_ID:
        raise ValueError(f"Snapshot datasetId must be {DATASET_ID}")
    if metadata.get("licenseName") != LICENSE_NAME:
        raise ValueError(f"Snapshot licenseName must be {LICENSE_NAME}")
    records = snapshot["records"]
    required = {
        "externalId", "name", "typeId", "subcategory", "borough", "neighborhood",
        "neighborhoodCode", "address", "latitude", "longitude", "sourceName",
        "sourceUrl", "sourceFetchedAt",
    }
    identities: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or required.difference(record):
            raise ValueError("OSM snapshot contains an incomplete normalized record")
        external_id = str(record["externalId"])
        if not external_id.startswith("openstreetmap:") or external_id in identities:
            raise ValueError("OSM snapshot contains an invalid or duplicate externalId")
        if record["typeId"] not in CATEGORY_FILTERS:
            raise ValueError("OSM snapshot contains an unsupported typeId")
        if record.get("sourceName") != SOURCE_NAME or not record.get("sourceUrl"):
            raise ValueError("OSM snapshot record is missing source provenance")
        _validate_source_field_lengths(record, external_id)
        identities.add(external_id)
    return {"metadata": metadata, "records": records}


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(serialized)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _overpass_query(osm_filter: str) -> str:
    south, west, north, east = NYC_BBOX
    return (
        "[out:json][timeout:180];"
        f"nwr[\"name\"]{osm_filter}({south},{west},{north},{east});"
        "out center tags;"
    )


def _post_overpass(
    url: str,
    query: str,
    *,
    user_agent: str,
    retries: int,
    retry_base_delay: float,
    max_retry_delay: float,
) -> dict[str, Any]:
    if retries < 1:
        raise ValueError("retries must be at least one")
    encoded = urllib.parse.urlencode({"data": query}).encode("utf-8")
    for attempt in range(retries):
        request = urllib.request.Request(
            url,
            data=encoded,
            headers={"Accept": "application/json", "User-Agent": user_agent},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise TypeError("Overpass response must be a JSON object")
            return payload
        except urllib.error.HTTPError as error:
            if error.code not in {429, 502, 503, 504} or attempt + 1 >= retries:
                raise
            retry_after = _retry_after_seconds(error.headers.get("Retry-After"))
            delay = retry_after if retry_after is not None else retry_base_delay * (2 ** attempt)
            time.sleep(min(max_retry_delay, max(0.0, delay)))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            if attempt + 1 >= retries:
                raise
            time.sleep(min(max_retry_delay, retry_base_delay * (2 ** attempt)))
    raise RuntimeError("unreachable")


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        # Overpass commonly sends delta-seconds. Fail closed to exponential
        # backoff for an HTTP-date or malformed value instead of guessing at
        # local clock skew.
        return None


def _validate_source_field_lengths(record: dict[str, Any], external_id: str) -> None:
    for field, maximum in SHOP_SOURCE_FIELD_LIMITS.items():
        value = str(record.get(field) or "")
        if len(value) > maximum:
            raise ValueError(
                f"OSM place {external_id} {field} has {len(value)} characters; "
                f"tb_shop limit is {maximum}. Extend the schema or exclude the source record explicitly."
            )


def _load_neighborhoods(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    neighborhoods = []
    for feature in document.get("features") or []:
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry")
        code = _clean(properties.get("nta2020"))
        name = _clean(properties.get("ntaname"))
        borough = _clean(properties.get("boroname"))
        if not code or not name or not borough or not isinstance(geometry, dict):
            continue
        coordinates = [point for point in _geometry_points(geometry)]
        if not coordinates:
            continue
        neighborhoods.append(
            {
                "code": code,
                "name": name,
                "borough": borough,
                "geometry": geometry,
                "minX": min(point[0] for point in coordinates),
                "minY": min(point[1] for point in coordinates),
                "maxX": max(point[0] for point in coordinates),
                "maxY": max(point[1] for point in coordinates),
            }
        )
    if not neighborhoods:
        raise ValueError(f"No valid NTA polygons found in {path}")
    return neighborhoods


def _find_neighborhood(neighborhoods: list[dict[str, Any]], longitude: float, latitude: float) -> dict[str, Any] | None:
    for neighborhood in neighborhoods:
        if not (
            neighborhood["minX"] <= longitude <= neighborhood["maxX"]
            and neighborhood["minY"] <= latitude <= neighborhood["maxY"]
        ):
            continue
        if contains_point(neighborhood["geometry"], longitude, latitude):
            return neighborhood
    return None


def _geometry_points(geometry: dict[str, Any]):
    coordinates = geometry.get("coordinates") or []
    if geometry.get("type") == "Polygon":
        polygons = [coordinates]
    elif geometry.get("type") == "MultiPolygon":
        polygons = coordinates
    else:
        return
    for polygon in polygons:
        for ring in polygon:
            for point in ring:
                if isinstance(point, list) and len(point) >= 2:
                    yield float(point[0]), float(point[1])


def _coordinates(element: dict[str, Any]) -> tuple[float | None, float | None]:
    center = element.get("center") or {}
    try:
        latitude = float(element.get("lat", center.get("lat")))
        longitude = float(element.get("lon", center.get("lon")))
    except (TypeError, ValueError):
        return None, None
    return latitude, longitude


def _inside_bbox(latitude: float, longitude: float) -> bool:
    south, west, north, east = NYC_BBOX
    return south <= latitude <= north and west <= longitude <= east


def _address(tags: dict[str, Any]) -> str:
    full = _clean(tags.get("addr:full"))
    if full:
        return full
    street_name = _clean(tags.get("addr:street"))
    if not street_name:
        return ""
    street = " ".join(
        item for item in (_clean(tags.get("addr:housenumber")), street_name) if item
    )
    locality = ", ".join(
        item for item in (_clean(tags.get("addr:city")), _clean(tags.get("addr:state"))) if item
    )
    postcode = _clean(tags.get("addr:postcode"))
    return ", ".join(item for item in (street, locality) if item) + (f" {postcode}" if postcode else "")


def _source_tags(tags: dict[str, Any]) -> dict[str, str]:
    allowed = (
        "amenity", "shop", "tourism", "leisure", "sport", "cuisine", "opening_hours",
        "wheelchair", "outdoor_seating", "diet:vegan", "diet:halal", "reservation", "dog",
        "phone", "contact:phone", "website", "contact:website", "contact:reservation",
        "wikidata", "wikimedia_commons", "image", "brand:wikidata", "facebook", "instagram",
    )
    return {key: _clean(tags.get(key)) for key in allowed if _clean(tags.get(key))}


def _verified_nyc_review_tags(tags: dict[str, Any]) -> list[str]:
    result = []
    if _normalize_text(tags.get("wheelchair")) == "yes":
        result.append("wheelchair_accessible")
    if _normalize_text(tags.get("outdoor_seating")) == "yes":
        result.append("outdoor_seating")
    if _normalize_text(tags.get("diet:vegan")) == "yes":
        result.append("vegan_options")
    if _normalize_text(tags.get("diet:halal")) == "yes":
        result.append("halal")
    if _normalize_text(tags.get("reservation")) == "required":
        result.append("reservation_required")
    if _normalize_text(tags.get("dog")) == "yes":
        result.append("pet_friendly")
    return sorted(result)


def _is_closed(tags: dict[str, Any]) -> bool:
    return _normalize_text(tags.get("disused")) in {"yes", "true"} or any(
        key.startswith(("disused:", "abandoned:")) for key in tags
    )


def _category(type_id: int, subcategory: str, source_category: str) -> dict[str, Any]:
    return {"typeId": type_id, "subcategory": subcategory, "sourceCategory": source_category}


def _normalize_text(value: Any) -> str:
    return _clean(value).casefold().replace("-", "_").replace(" ", "_")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nta-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overpass-url", default=DEFAULT_OVERPASS_URL)
    parser.add_argument("--request-delay", type=float, default=1.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--retry-base-delay", type=float, default=5.0)
    parser.add_argument("--max-retry-delay", type=float, default=60.0)
    args = parser.parse_args()
    snapshot = fetch_snapshot(
        args.nta_snapshot.resolve(),
        overpass_url=args.overpass_url,
        retries=args.retries,
        request_delay=args.request_delay,
        retry_base_delay=args.retry_base_delay,
        max_retry_delay=args.max_retry_delay,
    )
    output = args.output.resolve()
    write_json_atomic(output, snapshot)
    sidecar = output.with_name(output.stem + ".manifest.json")
    sidecar_payload = {
        **snapshot["metadata"],
        "snapshotFile": output.name,
        "snapshotSha256": sha256(output),
        "categoryFilters": {str(key): list(value) for key, value in CATEGORY_FILTERS.items()},
    }
    write_json_atomic(sidecar, sidecar_payload)
    print(json.dumps({**snapshot["metadata"], "manifest": str(sidecar)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
