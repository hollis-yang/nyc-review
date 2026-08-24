#!/usr/bin/env python3
"""Pin relaxed merchant-image references found on official shop websites.

The snapshot stores remote references only; it does not download or relicense
the image bytes. JSON-LD and social preview images are preferred, followed by a
reasonable page image. Category fallbacks remain available at render time.
"""

from __future__ import annotations

import argparse
import html as html_module
import ipaddress
import json
import re
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from .fetch_official_sites import MAX_RESPONSE_BYTES
from .providers.official_site import extract_local_business_jsonld, is_safe_public_url
from .snapshots import write_json_atomic

META_KEYS = (
    "og:image:secure_url",
    "og:image",
    "twitter:image",
    "twitter:image:src",
)
SKIP_IMAGE_PATTERN = re.compile(r"(?:pixel|spacer|favicon|sprite|tracking|analytics)", re.IGNORECASE)


class _PageImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, list[str]] = {}
        self.link_images: list[str] = []
        self.page_images: list[tuple[str, int | None, int | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value for key, value in attrs}
        tag = tag.lower()
        if tag == "meta":
            key = str(attributes.get("property") or attributes.get("name") or "").lower()
            content = str(attributes.get("content") or "").strip()
            if key and content:
                self.meta.setdefault(key, []).append(content)
        elif tag == "link":
            rel = str(attributes.get("rel") or "").lower().split()
            href = str(attributes.get("href") or "").strip()
            if href and ("image_src" in rel or "preload" in rel and attributes.get("as") == "image"):
                self.link_images.append(href)
        elif tag == "img":
            src = str(attributes.get("src") or attributes.get("data-src") or "").strip()
            if not src:
                return
            self.page_images.append((src, _positive_int(attributes.get("width")), _positive_int(attributes.get("height"))))


def _positive_int(value: str | None) -> int | None:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _json_ld_images(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for child in value for item in _json_ld_images(child)]
    if isinstance(value, dict):
        result: list[str] = []
        for key in ("url", "contentUrl", "thumbnailUrl"):
            result.extend(_json_ld_images(value.get(key)))
        return result
    return []


def extract_official_image_urls(html: str, page_url: str) -> list[str]:
    parser = _PageImageParser()
    parser.feed(html[:MAX_RESPONSE_BYTES])
    raw_candidates: list[str] = []
    for document in extract_local_business_jsonld(html):
        raw_candidates.extend(_json_ld_images(document.get("image")))
        raw_candidates.extend(_json_ld_images(document.get("photo")))
        raw_candidates.extend(_json_ld_images(document.get("logo")))
    for key in META_KEYS:
        raw_candidates.extend(parser.meta.get(key, []))
    raw_candidates.extend(parser.link_images)
    for src, width, height in parser.page_images:
        if width is not None and height is not None and (width < 180 or height < 120):
            continue
        raw_candidates.append(src)

    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        candidate = urljoin(page_url, html_module.unescape(str(raw).strip()))
        # tb_shop.images is retained as a legacy comma-delimited projection.
        # Encode literal commas so one remote URL cannot split into fake images.
        candidate = candidate.replace(",", "%2C")
        if not is_safe_public_url(candidate) or SKIP_IMAGE_PATTERN.search(urlparse(candidate).path):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
        if len(result) >= 12:
            break
    return result


def _resolves_publicly(url: str) -> bool:
    if not is_safe_public_url(url):
        return False
    host = urlparse(url).hostname
    if not host:
        return False
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        }
    except OSError:
        return False
    if not addresses:
        return False
    for value in addresses:
        address = ipaddress.ip_address(value)
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast:
            return False
    return True


class _ResolvedSafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):  # type: ignore[no-untyped-def]
        if not _resolves_publicly(new_url):
            raise ValueError("Official-site redirect resolved to a non-public URL")
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def _fetch_shop(shop: dict[str, Any], fetched_at: str) -> dict[str, Any] | None:
    website = str(shop.get("website") or "")
    if not _resolves_publicly(website):
        return None
    request = urllib.request.Request(
        website,
        headers={
            "User-Agent": "hm-dianping-official-image-discovery/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urllib.request.build_opener(_ResolvedSafeRedirectHandler()).open(request, timeout=7) as response:
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
    image_url = next((
        url
        for url in extract_official_image_urls(html, final_url)
        if _resolves_publicly(url) and _is_reachable_image(url)
    ), None)
    if not image_url:
        return None
    return {
        "externalId": shop.get("externalId"),
        "name": shop.get("name"),
        "address": shop.get("address"),
        "borough": shop.get("borough"),
        "latitude": shop.get("y"),
        "longitude": shop.get("x"),
        "matchType": "OFFICIAL_SITE_IMAGE",
        "url": image_url,
        "sourceUrl": final_url,
        "sourceName": "Official website",
        "attribution": shop.get("name"),
        "usagePolicy": "REMOTE_REFERENCE",
        "fetchedAt": fetched_at,
        "lastCheckedAt": fetched_at,
    }


def _is_reachable_image(url: str) -> bool:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "hm-dianping-official-image-discovery/1.0",
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif,image/*;q=0.8",
            "Range": "bytes=0-63",
        },
    )
    try:
        with urllib.request.build_opener(_ResolvedSafeRedirectHandler()).open(request, timeout=6) as response:
            if not _resolves_publicly(str(response.geturl())):
                return False
            content_type = str(response.headers.get_content_type()).lower()
            prefix = response.read(16)
    except Exception:
        return False
    if content_type.startswith("image/"):
        return True
    return (
        prefix.startswith(b"\xff\xd8\xff")
        or prefix.startswith(b"\x89PNG\r\n\x1a\n")
        or prefix.startswith((b"GIF87a", b"GIF89a"))
        or prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP"
        or len(prefix) >= 12 and prefix[4:12] in {b"ftypavif", b"ftypavis"}
    )


def fetch(shops: list[dict[str, Any]], limit: int, workers: int = 12) -> dict[str, Any]:
    selected = [shop for shop in shops if is_safe_public_url(str(shop.get("website") or ""))][:limit]
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 24))) as executor:
        results = list(executor.map(lambda shop: _fetch_shop(shop, fetched_at), selected))
    records = sorted((item for item in results if item is not None), key=lambda item: int(str(item["externalId"]).rsplit(":", 1)[-1]))
    return {
        "metadata": {
            "datasetId": "official-site-merchant-images",
            "datasetVersion": fetched_at[:10],
            "fetchedAt": fetched_at,
            "attemptedSites": len(selected),
            "recordCount": len(records),
            "matchPolicy": "official-page-jsonld-og-or-content-image",
            "usagePolicy": "REMOTE_REFERENCE",
        },
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shops", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    with args.shops.open(encoding="utf-8") as handle:
        shops = json.load(handle)
    snapshot = fetch(shops, max(1, min(args.limit, 5_000)), args.workers)
    write_json_atomic(args.output, snapshot)
    print(json.dumps(snapshot["metadata"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
