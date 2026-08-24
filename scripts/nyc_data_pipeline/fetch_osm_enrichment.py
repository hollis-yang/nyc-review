#!/usr/bin/env python3
"""Fetch current OSM tags for the exact shop identities in an existing bundle."""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .snapshots import write_json_atomic

DEFAULT_URL = "https://overpass-api.de/api/interpreter"
ALLOWED_TAGS = {
    "opening_hours", "phone", "contact:phone", "website", "contact:website",
    "reservation", "contact:reservation", "wikidata", "wikimedia_commons", "image",
    "wheelchair", "outdoor_seating", "diet:vegan", "diet:halal", "dog",
}


def fetch(shops: list[dict[str, Any]], *, endpoint: str, batch_size: int = 400, retries: int = 4) -> dict[str, Any]:
    identities: dict[str, list[int]] = defaultdict(list)
    for shop in shops:
        parts = str(shop.get("externalId") or "").split(":")
        if len(parts) != 3 or parts[0] != "openstreetmap" or parts[1] not in {"node", "way", "relation"}:
            continue
        try:
            identities[parts[1]].append(int(parts[2]))
        except ValueError:
            continue
    elements: list[dict[str, Any]] = []
    flattened = [(kind, identifier) for kind in sorted(identities) for identifier in sorted(set(identities[kind]))]
    for offset in range(0, len(flattened), batch_size):
        batch = flattened[offset: offset + batch_size]
        grouped: dict[str, list[int]] = defaultdict(list)
        for kind, identifier in batch:
            grouped[kind].append(identifier)
        statements = "".join(f"{kind}(id:{','.join(map(str, ids))});" for kind, ids in sorted(grouped.items()))
        query = f"[out:json][timeout:180];({statements});out tags center;"
        payload = _request(endpoint, query, retries)
        elements.extend(item for item in payload.get("elements") or [] if isinstance(item, dict))
        if offset + batch_size < len(flattened):
            time.sleep(0.5)
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    records = []
    for item in elements:
        kind = str(item.get("type") or "")
        identifier = item.get("id")
        tags = item.get("tags") or {}
        if kind not in {"node", "way", "relation"} or not isinstance(identifier, int) or not isinstance(tags, dict):
            continue
        records.append({
            "externalId": f"openstreetmap:{kind}:{identifier}",
            "sourceUrl": f"https://www.openstreetmap.org/{kind}/{identifier}",
            "sourceTags": {key: " ".join(str(tags[key]).split()) for key in sorted(ALLOWED_TAGS) if tags.get(key)},
        })
    records.sort(key=lambda item: item["externalId"])
    return {
        "metadata": {
            "datasetId": "openstreetmap-shop-enrichment",
            "datasetVersion": fetched_at[:10],
            "fetchedAt": fetched_at,
            "sourceName": "OpenStreetMap contributors",
            "sourceUrl": "https://www.openstreetmap.org/copyright",
            "licenseName": "ODbL-1.0",
            "recordCount": len(records),
        },
        "records": records,
    }


def _request(endpoint: str, query: str, retries: int) -> dict[str, Any]:
    encoded = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(retries):
        request = urllib.request.Request(
            endpoint, data=encoded,
            headers={"User-Agent": "hm-dianping-p2-p3-enrichment/1.0", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=210) as response:
                return json.load(response)
        except Exception:
            if attempt + 1 == retries:
                raise
            time.sleep(min(30, 2 ** attempt * 3))
    raise RuntimeError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shops", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--endpoint", default=DEFAULT_URL)
    parser.add_argument("--batch-size", type=int, default=400)
    args = parser.parse_args()
    with args.shops.open(encoding="utf-8") as handle:
        shops = json.load(handle)
    snapshot = fetch(shops, endpoint=args.endpoint, batch_size=args.batch_size)
    write_json_atomic(args.output, snapshot)
    print(json.dumps(snapshot["metadata"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
