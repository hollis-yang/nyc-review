#!/usr/bin/env python3
"""Fetch and normalize a reproducible NYC Open Data restaurant snapshot."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATASET_ID = "43nn-pn8j"
DATASET_NAME = "DOHMH New York City Restaurant Inspection Results"
DATASET_PAGE_URL = (
    "https://data.cityofnewyork.us/Health/"
    "DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j"
)
API_URL = f"https://data.cityofnewyork.us/resource/{DATASET_ID}.json"
BOROUGHS = ("Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island")
SELECT_FIELDS = (
    "camis,dba,boro,building,street,zipcode,cuisine_description,"
    "latitude,longitude,grade,inspection_date,record_date"
)


def fetch_snapshot(count_per_borough: int, app_token: str = "") -> dict[str, Any]:
    if count_per_borough < 1 or count_per_borough > 1_000:
        raise ValueError("count_per_borough must be between 1 and 1000")
    records: list[dict[str, Any]] = []
    for borough in BOROUGHS:
        # Inspection rows repeat per violation. Fetch a larger latest-first window,
        # then keep the first valid row for each CAMIS establishment identifier.
        params = {
            "$select": SELECT_FIELDS,
            "$where": (
                f"boro='{borough}' AND dba IS NOT NULL AND "
                "latitude IS NOT NULL AND longitude IS NOT NULL"
            ),
            "$order": "inspection_date DESC, camis ASC",
            "$limit": str(min(50_000, max(200, count_per_borough * 30))),
        }
        request = urllib.request.Request(
            f"{API_URL}?{urllib.parse.urlencode(params)}",
            headers={
                "Accept": "application/json",
                "User-Agent": "hm-dianping-p6-data-pipeline/1.0",
                **({"X-App-Token": app_token} if app_token else {}),
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
        normalized = normalize_records(payload, borough=borough)
        if len(normalized) < count_per_borough:
            raise ValueError(
                f"NYC Open Data returned only {len(normalized)} valid unique records for {borough}."
            )
        records.extend(normalized[:count_per_borough])

    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "metadata": {
            "datasetId": DATASET_ID,
            "datasetName": DATASET_NAME,
            "sourceUrl": DATASET_PAGE_URL,
            "apiUrl": API_URL,
            "publisher": "NYC Department of Health and Mental Hygiene",
            "fetchedAt": fetched_at,
            "recordCount": len(records),
            "countPerBorough": count_per_borough,
            "boroughs": list(BOROUGHS),
            "notes": (
                "Public establishment identity and location fields only. "
                "HMDP reviews, prices, tags, hours, images and promotions are synthetic."
            ),
        },
        "records": records,
    }


def normalize_records(payload: Any, borough: str | None = None) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise TypeError("NYC Open Data response must be a JSON list")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        camis = _clean(item.get("camis"))
        name = _clean(item.get("dba"))
        normalized_borough = _normalize_borough(item.get("boro"))
        if not camis or not name or not normalized_borough:
            continue
        if borough and normalized_borough != borough:
            continue
        try:
            latitude = float(item.get("latitude"))
            longitude = float(item.get("longitude"))
        except (TypeError, ValueError):
            continue
        if not (40.45 <= latitude <= 40.95 and -74.30 <= longitude <= -73.65):
            continue
        if camis in seen:
            continue
        seen.add(camis)
        building = _clean(item.get("building"))
        street = _clean(item.get("street"))
        zipcode = _clean(item.get("zipcode"))
        street_address = " ".join(part for part in (building, street) if part)
        city_address = ", ".join(part for part in (street_address, normalized_borough, "NY") if part)
        address = f"{city_address} {zipcode}".strip()
        result.append(
            {
                "externalId": camis,
                "name": name,
                "borough": normalized_borough,
                "address": address,
                "zipcode": zipcode,
                "cuisine": _clean(item.get("cuisine_description")) or "Other",
                "latitude": round(latitude, 6),
                "longitude": round(longitude, 6),
                "latestGrade": _clean(item.get("grade")) or None,
                "latestInspectionDate": _date_only(item.get("inspection_date")),
                "sourceRecordDate": _date_only(item.get("record_date")),
            }
        )
    return result


def load_snapshot(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        snapshot = json.load(handle)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("records"), list):
        raise TypeError(f"Invalid NYC Open Data snapshot: {path}")
    metadata = snapshot.get("metadata") or {}
    if metadata.get("datasetId") != DATASET_ID:
        raise ValueError(f"Snapshot datasetId must be {DATASET_ID}")
    records = normalize_records(
        [
            {
                "camis": item.get("externalId"),
                "dba": item.get("name"),
                "boro": item.get("borough"),
                "building": "",
                "street": item.get("address"),
                "zipcode": "",
                "cuisine_description": item.get("cuisine"),
                "latitude": item.get("latitude"),
                "longitude": item.get("longitude"),
                "grade": item.get("latestGrade"),
                "inspection_date": item.get("latestInspectionDate"),
                "record_date": item.get("sourceRecordDate"),
            }
            for item in snapshot["records"]
        ]
    )
    # Keep the already-normalized address rather than reconstructing it.
    addresses = {
        str(item.get("externalId")): item.get("address")
        for item in snapshot["records"]
        if isinstance(item, dict)
    }
    for item in records:
        item["address"] = addresses.get(item["externalId"]) or item["address"]
    return {"metadata": metadata, "records": records}


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(serialized)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def _normalize_borough(value: Any) -> str | None:
    normalized = _clean(value).lower()
    aliases = {
        "manhattan": "Manhattan",
        "brooklyn": "Brooklyn",
        "queens": "Queens",
        "bronx": "Bronx",
        "staten island": "Staten Island",
    }
    return aliases.get(normalized)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _date_only(value: Any) -> str | None:
    cleaned = _clean(value)
    return cleaned[:10] if cleaned else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count-per-borough", type=int, default=12)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot = fetch_snapshot(
        count_per_borough=args.count_per_borough,
        app_token=os.getenv("NYC_OPEN_DATA_APP_TOKEN", ""),
    )
    output = args.output.resolve()
    write_json_atomic(output, snapshot)
    print(json.dumps(snapshot["metadata"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
