#!/usr/bin/env python3
"""Find openly licensed merchant photos by strict Commons title matching.

This P13 fallback runs only for merchants that still lack a specific image.
It never copies image bytes: the output contains a Commons thumbnail URL,
file page, author and license. Name search is intentionally strict even though
the product does not display match confidence or provenance labels.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fetch_wikimedia_merchant_images import COMMONS_API, _normalize_image
from .snapshots import write_json_atomic

GENERIC_TOKENS = {
    "and", "at", "bar", "beauty", "cafe", "coffee", "company", "fitness",
    "food", "gym", "house", "inc", "llc", "new", "ny", "nyc", "pizzeria",
    "restaurant", "salon", "shop", "spa", "studio", "the", "york",
}
SKIP_TITLE = re.compile(r"(?:logo|icon|map|menu|poster|portrait|headshot|advert)", re.I)


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.casefold())


def _name_match(merchant_name: str, file_title: str) -> bool:
    title = urllib.parse.unquote(file_title.removeprefix("File:")).rsplit(".", 1)[0]
    if SKIP_TITLE.search(title):
        return False
    merchant = [token for token in _tokens(merchant_name) if token not in GENERIC_TOKENS]
    candidate = set(_tokens(title))
    if not merchant:
        merchant = _tokens(merchant_name)
    significant = set(merchant)
    if not significant:
        return False
    overlap = significant & candidate
    if len(significant) == 1:
        return significant <= candidate and bool({"nyc", "new", "york"} & candidate)
    return significant <= candidate or len(overlap) / len(significant) >= .75


def _query(shop: dict[str, Any]) -> dict[str, Any] | None:
    # Commons search tokenization is more effective without phrase quotes; the
    # strict title matcher below remains the acceptance boundary.
    query = f'{shop["name"]} New York'
    params = {
        "action": "query", "generator": "search", "gsrsearch": query,
        "gsrnamespace": "6", "gsrlimit": "6", "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata|sha1|size", "iiurlwidth": "1200",
        "format": "json", "formatversion": "2",
    }
    request = urllib.request.Request(
        f"{COMMONS_API}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": "nyc-review-p13-commons-search/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except Exception:
        return None
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for page in (payload.get("query") or {}).get("pages") or []:
        title = str(page.get("title") or "")
        image_info = (page.get("imageinfo") or [None])[0]
        if not isinstance(image_info, dict) or not _name_match(str(shop["name"]), title):
            continue
        normalized = _normalize_image(image_info, title.removeprefix("File:"))
        if normalized is None:
            continue
        rank = len(set(_tokens(str(shop["name"]))) & set(_tokens(title)))
        candidates.append((rank, title, normalized))
    if not candidates:
        return None
    _, _, normalized = max(candidates, key=lambda item: (item[0], item[1]))
    return {
        "externalId": shop.get("externalId"), "name": shop.get("name"),
        "address": shop.get("address"), "borough": shop.get("borough"),
        "latitude": shop.get("y"), "longitude": shop.get("x"),
        "matchType": "WIKIMEDIA_NAME_SEARCH", **normalized,
    }


def fetch(
    shops: list[dict[str, Any]],
    existing_images: dict[str, Any],
    *,
    limit: int,
    workers: int,
) -> dict[str, Any]:
    covered = {str(item.get("externalId")) for item in existing_images.get("records") or []}
    selected = [shop for shop in shops if str(shop.get("externalId")) not in covered][:limit]
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as executor:
        resolved = list(executor.map(_query, selected))
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    records = []
    for item in resolved:
        if item is None:
            continue
        records.append({**item, "fetchedAt": fetched_at, "lastCheckedAt": fetched_at})
    records.sort(key=lambda item: str(item.get("externalId")))
    return {
        "metadata": {
            "datasetId": "wikimedia-merchant-name-search", "datasetVersion": fetched_at[:10],
            "fetchedAt": fetched_at, "attemptedShops": len(selected), "recordCount": len(records),
            "matchPolicy": "strict-significant-name-token-overlap-with-new-york-query",
            "sourceName": "Wikimedia Commons", "sourceUrl": "https://commons.wikimedia.org/",
        },
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shops", type=Path, required=True)
    parser.add_argument("--existing-images", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=5_000)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    with args.shops.open(encoding="utf-8") as handle:
        shops = json.load(handle)
    existing = {"records": []}
    for path in args.existing_images:
        with path.open(encoding="utf-8") as handle:
            existing["records"].extend(json.load(handle).get("records") or [])
    snapshot = fetch(shops, existing, limit=max(1, args.limit), workers=args.workers)
    write_json_atomic(args.output, snapshot)
    print(json.dumps(snapshot["metadata"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
