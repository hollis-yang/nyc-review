#!/usr/bin/env python3
"""Fetch bounded official pages and pin LocalBusiness JSON-LD observations."""

from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .providers.official_site import extract_local_business_jsonld, is_safe_public_url
from .snapshots import write_json_atomic

MAX_RESPONSE_BYTES = 2_000_000


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):  # type: ignore[no-untyped-def]
        if not is_safe_public_url(new_url):
            raise ValueError("Official-site redirect resolved to a non-public URL")
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def fetch(shops: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    opener = urllib.request.build_opener(SafeRedirectHandler())
    records = []
    attempted = 0
    for shop in shops:
        url = str(shop.get("website") or "")
        if not is_safe_public_url(url):
            continue
        if attempted >= limit:
            break
        attempted += 1
        request = urllib.request.Request(url, headers={"User-Agent": "hm-dianping-p2-p3-jsonld/1.0", "Accept": "text/html"})
        try:
            with opener.open(request, timeout=8) as response:
                content_type = str(response.headers.get_content_type())
                if content_type not in {"text/html", "application/xhtml+xml"}:
                    continue
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    continue
                html = raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        json_ld = extract_local_business_jsonld(html)
        if not json_ld:
            continue
        records.append({
            "externalId": f"official-site:{shop['id']}", "name": shop["name"],
            "address": shop.get("address"), "borough": shop.get("borough"),
            "latitude": shop.get("y"), "longitude": shop.get("x"),
            "sourceUrl": url, "jsonLd": json_ld[0],
        })
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "metadata": {
            "datasetId": "official-site-jsonld", "datasetVersion": fetched_at[:10],
            "fetchedAt": fetched_at, "attemptedSites": attempted, "recordCount": len(records),
        },
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shops", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    with args.shops.open(encoding="utf-8") as handle:
        shops = json.load(handle)
    snapshot = fetch(shops, max(1, min(args.limit, 5_000)))
    write_json_atomic(args.output, snapshot)
    print(json.dumps(snapshot["metadata"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
