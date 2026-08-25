#!/usr/bin/env python3
"""Pin validated merchant-image references found on official shop websites.

The crawler transiently reads a bounded prefix of each image to validate its
format, dimensions and duplicate fingerprint. Only the remote URL and audit
metadata are persisted; image bytes are never cached or redistributed. When
``--official-sites-output`` is supplied, the same page fetch also pins the best
LocalBusiness JSON-LD document for the P11 field resolver.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_module
import ipaddress
import json
import re
import socket
import struct
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from .fetch_official_sites import MAX_RESPONSE_BYTES, merge_local_business_documents
from .providers.official_site import extract_local_business_jsonld, is_safe_public_url
from .snapshots import write_json_atomic

META_KEYS = (
    "og:image:secure_url",
    "og:image",
    "twitter:image",
    "twitter:image:src",
)
SKIP_IMAGE_PATTERN = re.compile(
    r"(?:pixel|spacer|favicon|sprite|tracking|analytics|(?:^|[-_/])logo(?:[-_.?/]|$)|"
    r"(?:^|[-_/])icon(?:[-_.?/]|$)|badge|avatar|payment|captcha)",
    re.IGNORECASE,
)
MAX_IMAGE_SAMPLE_BYTES = 524_288
MAX_IMAGES_PER_SHOP = 3


class _PageImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, list[str]] = {}
        self.link_images: list[str] = []
        self.page_images: list[tuple[str, int | None, int | None, str]] = []

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
            context = " ".join(str(attributes.get(key) or "") for key in ("alt", "class", "id"))
            self.page_images.append((
                src,
                _positive_int(attributes.get("width")),
                _positive_int(attributes.get("height")),
                context,
            ))


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


def _official_image_candidates(html: str, page_url: str) -> list[dict[str, Any]]:
    parser = _PageImageParser()
    parser.feed(html[:MAX_RESPONSE_BYTES])
    raw_candidates: list[tuple[str, int, int | None, int | None]] = []
    for document in extract_local_business_jsonld(html):
        raw_candidates.extend((url, 0, None, None) for url in _json_ld_images(document.get("image")))
        raw_candidates.extend((url, 1, None, None) for url in _json_ld_images(document.get("photo")))
    for rank, key in enumerate(META_KEYS, start=2):
        raw_candidates.extend((url, rank, None, None) for url in parser.meta.get(key, []))
    raw_candidates.extend((url, 6, None, None) for url in parser.link_images)
    for src, width, height, context in parser.page_images:
        if width is not None and height is not None and (width < 320 or height < 180):
            continue
        if SKIP_IMAGE_PATTERN.search(context):
            continue
        raw_candidates.append((src, 7, width, height))

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw, source_rank, declared_width, declared_height in raw_candidates:
        candidate = urljoin(page_url, html_module.unescape(str(raw).strip())).replace(",", "%2C")
        parsed = urlparse(candidate)
        if not is_safe_public_url(candidate) or SKIP_IMAGE_PATTERN.search(parsed.path):
            continue
        canonical = parsed._replace(fragment="").geturl()
        if canonical in seen:
            continue
        seen.add(canonical)
        result.append({
            "url": canonical,
            "sourceRank": source_rank,
            "declaredWidth": declared_width,
            "declaredHeight": declared_height,
        })
        if len(result) >= 24:
            break
    return result


def extract_official_image_urls(html: str, page_url: str) -> list[str]:
    """Compatibility helper used by unit tests and other pipeline scripts."""
    return [str(candidate["url"]) for candidate in _official_image_candidates(html, page_url)]


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


def _image_dimensions(content: bytes) -> tuple[int | None, int | None]:
    if content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) >= 24:
        return struct.unpack(">II", content[16:24])
    if content.startswith((b"GIF87a", b"GIF89a")) and len(content) >= 10:
        return struct.unpack("<HH", content[6:10])
    if content.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(content):
            if content[index] != 0xFF:
                index += 1
                continue
            marker = content[index + 1]
            index += 2
            if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                continue
            if index + 2 > len(content):
                break
            length = int.from_bytes(content[index:index + 2], "big")
            if length < 2 or index + length > len(content):
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                return (
                    int.from_bytes(content[index + 5:index + 7], "big"),
                    int.from_bytes(content[index + 3:index + 5], "big"),
                )
            index += length
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP" and len(content) >= 30:
        kind = content[12:16]
        if kind == b"VP8X":
            return (
                1 + int.from_bytes(content[24:27], "little"),
                1 + int.from_bytes(content[27:30], "little"),
            )
        if kind == b"VP8 " and content[23:26] == b"\x9d\x01\x2a":
            return (
                int.from_bytes(content[26:28], "little") & 0x3FFF,
                int.from_bytes(content[28:30], "little") & 0x3FFF,
            )
    return None, None


def _validate_remote_image(candidate: dict[str, Any]) -> dict[str, Any] | None:
    url = str(candidate["url"])
    if not _resolves_publicly(url):
        return None
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "hm-dianping-official-image-discovery/2.0",
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif,image/*;q=0.8",
            "Range": f"bytes=0-{MAX_IMAGE_SAMPLE_BYTES - 1}",
        },
    )
    try:
        with urllib.request.build_opener(_ResolvedSafeRedirectHandler()).open(request, timeout=7) as response:
            final_url = str(response.geturl())
            if not _resolves_publicly(final_url):
                return None
            content_type = str(response.headers.get_content_type()).lower()
            content = response.read(MAX_IMAGE_SAMPLE_BYTES + 1)
    except Exception:
        return None
    signature_is_image = (
        content.startswith(b"\xff\xd8\xff")
        or content.startswith(b"\x89PNG\r\n\x1a\n")
        or content.startswith((b"GIF87a", b"GIF89a"))
        or content.startswith(b"RIFF") and content[8:12] == b"WEBP"
        or len(content) >= 12 and content[4:12] in {b"ftypavif", b"ftypavis"}
    )
    if not content_type.startswith("image/") and not signature_is_image:
        return None
    width, height = _image_dimensions(content)
    width = width or candidate.get("declaredWidth")
    height = height or candidate.get("declaredHeight")
    if width is not None and height is not None:
        if width < 320 or height < 180 or width / height > 5.0 or height / width > 3.0:
            return None
    return {
        **candidate,
        "url": final_url.replace(",", "%2C"),
        "width": width,
        "height": height,
        "contentType": content_type,
        "sampleBytes": min(len(content), MAX_IMAGE_SAMPLE_BYTES),
        "contentSampleSha256": hashlib.sha256(content[:MAX_IMAGE_SAMPLE_BYTES]).hexdigest(),
    }


def _site_record(shop: dict[str, Any], final_url: str, html: str) -> dict[str, Any] | None:
    merged = merge_local_business_documents(extract_local_business_jsonld(html))
    if not merged:
        return None
    return {
        "externalId": f"official-site:{shop['id']}",
        "name": shop.get("name"),
        "address": shop.get("address"),
        "borough": shop.get("borough"),
        "latitude": shop.get("y"),
        "longitude": shop.get("x"),
        "sourceUrl": final_url,
        "jsonLd": merged,
    }


def _fetch_shop(shop: dict[str, Any], fetched_at: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    website = str(shop.get("website") or "")
    if not _resolves_publicly(website):
        return [], None
    request = urllib.request.Request(
        website,
        headers={
            "User-Agent": "hm-dianping-official-enrichment/2.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urllib.request.build_opener(_ResolvedSafeRedirectHandler()).open(request, timeout=8) as response:
            final_url = str(response.geturl())
            if not _resolves_publicly(final_url):
                return [], None
            if str(response.headers.get_content_type()) not in {"text/html", "application/xhtml+xml"}:
                return [], None
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                return [], None
            html = raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return [], None

    images: list[dict[str, Any]] = []
    seen_fingerprints: set[str] = set()
    validated = []
    for candidate in _official_image_candidates(html, final_url):
        result = _validate_remote_image(candidate)
        if result is None or result["contentSampleSha256"] in seen_fingerprints:
            continue
        seen_fingerprints.add(str(result["contentSampleSha256"]))
        validated.append(result)
        if len(validated) >= MAX_IMAGES_PER_SHOP:
            break
    validated.sort(key=lambda item: (
        int(item["sourceRank"]),
        -int(item.get("width") or 0) * int(item.get("height") or 0),
        str(item["url"]),
    ))
    for display_rank, image in enumerate(validated, start=1):
        images.append({
            "externalId": shop.get("externalId"),
            "name": shop.get("name"),
            "address": shop.get("address"),
            "borough": shop.get("borough"),
            "latitude": shop.get("y"),
            "longitude": shop.get("x"),
            "matchType": "OFFICIAL_SITE_IMAGE",
            "url": image["url"],
            "sourceUrl": final_url,
            "sourceName": "Official website",
            "attribution": shop.get("name"),
            "usagePolicy": "REMOTE_REFERENCE",
            "displayRank": display_rank,
            "discoveryRank": image["sourceRank"],
            "width": image.get("width"),
            "height": image.get("height"),
            "contentType": image.get("contentType"),
            "contentSampleSha256": image["contentSampleSha256"],
            "sampleBytes": image["sampleBytes"],
            "fetchedAt": fetched_at,
            "lastCheckedAt": fetched_at,
        })
    return images, _site_record(shop, final_url, html)


def fetch_with_official_sites(
    shops: list[dict[str, Any]],
    limit: int,
    workers: int = 12,
) -> tuple[dict[str, Any], dict[str, Any]]:
    selected = [shop for shop in shops if is_safe_public_url(str(shop.get("website") or ""))][:limit]
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 32))) as executor:
        results = list(executor.map(lambda shop: _fetch_shop(shop, fetched_at), selected))
    image_records = [image for images, _ in results for image in images]
    image_records.sort(key=lambda item: (
        int(str(item["externalId"]).rsplit(":", 1)[-1]),
        int(item["displayRank"]),
    ))
    site_records = [site for _, site in results if site is not None]
    site_records.sort(key=lambda item: int(str(item["externalId"]).rsplit(":", 1)[-1]))
    shop_count = len({str(item["externalId"]) for item in image_records})
    image_snapshot = {
        "metadata": {
            "datasetId": "official-site-merchant-images",
            "datasetVersion": fetched_at[:10],
            "fetchedAt": fetched_at,
            "attemptedSites": len(selected),
            "shopsWithImages": shop_count,
            "recordCount": len(image_records),
            "maxImagesPerShop": MAX_IMAGES_PER_SHOP,
            "matchPolicy": "ranked-jsonld-social-or-content-image",
            "validationPolicy": "public-redirect-image-signature-size-dimensions-sample-sha256",
            "usagePolicy": "REMOTE_REFERENCE",
        },
        "records": image_records,
    }
    site_snapshot = {
        "metadata": {
            "datasetId": "official-site-jsonld",
            "datasetVersion": fetched_at[:10],
            "fetchedAt": fetched_at,
            "attemptedSites": len(selected),
            "recordCount": len(site_records),
        },
        "records": site_records,
    }
    return image_snapshot, site_snapshot


def fetch(shops: list[dict[str, Any]], limit: int, workers: int = 12) -> dict[str, Any]:
    return fetch_with_official_sites(shops, limit, workers)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shops", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--official-sites-output", type=Path)
    parser.add_argument("--limit", type=int, default=5_000)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    with args.shops.open(encoding="utf-8") as handle:
        shops = json.load(handle)
    image_snapshot, site_snapshot = fetch_with_official_sites(
        shops, max(1, min(args.limit, 5_000)), args.workers,
    )
    write_json_atomic(args.output, image_snapshot)
    if args.official_sites_output:
        write_json_atomic(args.official_sites_output, site_snapshot)
    print(json.dumps({
        **image_snapshot["metadata"],
        "officialSiteRecords": site_snapshot["metadata"]["recordCount"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
