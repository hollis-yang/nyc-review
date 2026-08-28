#!/usr/bin/env python3
"""Fetch bounded official pages and pin LocalBusiness JSON-LD observations."""

from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .providers.official_site import extract_local_business_jsonld, is_safe_public_url
from .snapshots import write_json_atomic

MAX_RESPONSE_BYTES = 2_000_000


def _resolves_publicly(url: str) -> bool:
    if not is_safe_public_url(url):
        return False
    host = urlparse(url).hostname
    if not host:
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except OSError:
        return False
    if not addresses:
        return False
    return all(not (
        address.is_private or address.is_loopback or address.is_link_local
        or address.is_reserved or address.is_multicast
    ) for address in (ipaddress.ip_address(value) for value in addresses))


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):  # type: ignore[no-untyped-def]
        if not _resolves_publicly(new_url):
            raise ValueError("Official-site redirect resolved to a non-public URL")
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def _quality(document: dict[str, Any]) -> tuple[int, int]:
    useful = (
        "aggregateRating", "openingHours", "openingHoursSpecification", "priceRange",
        "offers", "telephone", "contactPoint", "acceptsReservations", "potentialAction",
        "image", "url",
    )
    return sum(1 for key in useful if document.get(key) not in (None, "", [])), len(document)


def merge_local_business_documents(documents: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Merge complementary LocalBusiness nodes without inventing field values."""
    if not documents:
        return None
    ordered = sorted(documents, key=_quality, reverse=True)
    merged = dict(ordered[0])
    for document in ordered[1:]:
        for key, value in document.items():
            if merged.get(key) in (None, "", [], {}) and value not in (None, "", [], {}):
                merged[key] = value
    return merged


def _fetch_shop(shop: dict[str, Any]) -> dict[str, Any] | None:
    url = str(shop.get("website") or "")
    if not _resolves_publicly(url):
        return None
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "nyc-review-official-enrichment/2.0", "Accept": "text/html,application/xhtml+xml"},
    )
    try:
        with urllib.request.build_opener(SafeRedirectHandler()).open(request, timeout=8) as response:
            final_url = str(response.geturl())
            if not _resolves_publicly(final_url):
                return None
            if str(response.headers.get_content_type()) not in {"text/html", "application/xhtml+xml"}:
                return None
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                return None
            html = raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return None
    json_ld = merge_local_business_documents(extract_local_business_jsonld(html))
    if not json_ld:
        return None
    return {
        "externalId": f"official-site:{shop['id']}",
        "name": shop["name"],
        "address": shop.get("address"),
        "borough": shop.get("borough"),
        "latitude": shop.get("y"),
        "longitude": shop.get("x"),
        "sourceUrl": final_url,
        "jsonLd": json_ld,
    }


def fetch(shops: list[dict[str, Any]], limit: int, workers: int = 16) -> dict[str, Any]:
    selected = [shop for shop in shops if is_safe_public_url(str(shop.get("website") or ""))][:limit]
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 32))) as executor:
        results = list(executor.map(_fetch_shop, selected))
    records = sorted(
        (record for record in results if record is not None),
        key=lambda item: int(str(item["externalId"]).rsplit(":", 1)[-1]),
    )
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "metadata": {
            "datasetId": "official-site-jsonld",
            "datasetVersion": fetched_at[:10],
            "fetchedAt": fetched_at,
            "attemptedSites": len(selected),
            "recordCount": len(records),
        },
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shops", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=5_000)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    with args.shops.open(encoding="utf-8") as handle:
        shops = json.load(handle)
    snapshot = fetch(shops, max(1, min(args.limit, 5_000)), args.workers)
    write_json_atomic(args.output, snapshot)
    print(json.dumps(snapshot["metadata"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
