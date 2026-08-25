#!/usr/bin/env python3
"""Deepen official-site image discovery and derive per-person menu prices.

P11.5 reuses the pinned P10/P11 homepage snapshots, then visits a bounded set
of same-site gallery, location, menu, service and pricing pages. Image bytes are
read only for validation and are never persisted. Menu prices come from
JSON-LD, visible HTML price tokens and text-bearing PDF streams; the snapshot
stores the observed distribution and a deterministic per-person estimate.
"""

from __future__ import annotations

import argparse
import html as html_module
import json
import re
import statistics
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from .fetch_official_site_images import (
    MAX_IMAGES_PER_SHOP,
    SKIP_IMAGE_PATTERN,
    _ResolvedSafeRedirectHandler,
    _official_image_candidates,
    _resolves_publicly,
    _validate_remote_image,
)
from .fetch_official_sites import MAX_RESPONSE_BYTES, merge_local_business_documents
from .providers.official_site import (
    extract_jsonld_documents,
    extract_local_business_jsonld,
    is_safe_public_url,
)
from .snapshots import write_json_atomic

TARGET_PATTERN = re.compile(
    r"(?:menu|gallery|galleries|photo|locations?|visit|services?|pricing|price-list|our-work|about|contact|hours|reserv|book|events?|story|team|space|food|drink|classes|treatments?|portfolio|studio|facility)",
    re.IGNORECASE,
)
SKIP_PAGE_PATTERN = re.compile(
    r"(?:login|sign-in|account|cart|checkout|privacy|terms|career|press|blog|news)",
    re.IGNORECASE,
)
CSS_URL_PATTERN = re.compile(r"url\(\s*['\"]?([^)'\"]+)", re.IGNORECASE)
PRICE_PATTERN = re.compile(r"(?<![\w$])\$\s*(\d{1,3}(?:\.\d{1,2})?)")
MAX_DEEP_PAGES = 8
MAX_PDF_BYTES = 6_000_000
DAY_NAMES = {
    "mon": "Monday", "monday": "Monday", "tue": "Tuesday", "tues": "Tuesday", "tuesday": "Tuesday",
    "wed": "Wednesday", "wednesday": "Wednesday", "thu": "Thursday", "thur": "Thursday",
    "thurs": "Thursday", "thursday": "Thursday", "fri": "Friday", "friday": "Friday",
    "sat": "Saturday", "saturday": "Saturday", "sun": "Sunday", "sunday": "Sunday",
}
DAY_PATTERN = re.compile(r"\b(" + "|".join(sorted(DAY_NAMES, key=len, reverse=True)) + r")\b", re.I)
TIME_RANGE_PATTERN = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\s*(?:-|–|—|to)\s*"
    r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\b",
    re.I,
)


class _DeepPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[tuple[str, str]] = []
        self.extra_images: list[str] = []
        self.text: list[str] = []
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value for key, value in attrs}
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg"}:
            self._hidden_depth += 1
        if lowered == "a":
            self._anchor_href = str(attributes.get("href") or "").strip() or None
            self._anchor_text = []
        if lowered in {"img", "source"}:
            srcset = str(attributes.get("srcset") or attributes.get("data-srcset") or "")
            for item in srcset.split(","):
                candidate = item.strip().split(" ", 1)[0]
                if candidate:
                    self.extra_images.append(candidate)
        style = str(attributes.get("style") or "")
        self.extra_images.extend(CSS_URL_PATTERN.findall(style))

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "a" and self._anchor_href:
            self.anchors.append((self._anchor_href, " ".join(self._anchor_text)))
            self._anchor_href = None
            self._anchor_text = []
        if lowered in {"script", "style", "noscript", "svg"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._anchor_href:
            self._anchor_text.append(data.strip())
        if not self._hidden_depth and data.strip():
            self.text.append(data.strip())


def _site_host(url: str) -> str:
    host = str(urlparse(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _same_site(root_url: str, candidate_url: str) -> bool:
    root = _site_host(root_url)
    candidate = _site_host(candidate_url)
    return bool(root and candidate and (
        root == candidate or root.endswith("." + candidate) or candidate.endswith("." + root)
    ))


def _resolves_safely(url: str) -> bool:
    try:
        return _resolves_publicly(url)
    except (UnicodeError, ValueError, OSError):
        return False


def _fetch(url: str, *, accept: str, max_bytes: int, timeout: int = 8) -> tuple[str, str, bytes] | None:
    if not _resolves_safely(url):
        return None
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "hm-dianping-official-enrichment/2.1",
            "Accept": accept,
        },
    )
    try:
        with urllib.request.build_opener(_ResolvedSafeRedirectHandler()).open(request, timeout=timeout) as response:
            final_url = str(response.geturl())
            if not _resolves_safely(final_url):
                return None
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                return None
            return final_url, str(response.headers.get_content_type()).lower(), raw
    except Exception:
        return None


def _decode_html(content_type: str, raw: bytes) -> str | None:
    if content_type not in {"text/html", "application/xhtml+xml"}:
        return None
    return raw.decode("utf-8", errors="replace")


def _target_links(html: str, page_url: str, root_url: str) -> tuple[list[str], list[str]]:
    parser = _DeepPageParser()
    parser.feed(html[:MAX_RESPONSE_BYTES])
    pages: list[tuple[int, str]] = []
    pdfs: list[str] = []
    seen: set[str] = set()
    for href, text in parser.anchors:
        candidate = urljoin(page_url, html_module.unescape(href.strip()))
        parsed = urlparse(candidate)
        candidate = parsed._replace(fragment="").geturl()
        label = f"{parsed.path} {parsed.query} {text}"
        if candidate in seen or not is_safe_public_url(candidate) or not _same_site(root_url, candidate):
            continue
        if SKIP_PAGE_PATTERN.search(label) or not TARGET_PATTERN.search(label):
            continue
        seen.add(candidate)
        if parsed.path.lower().endswith(".pdf"):
            pdfs.append(candidate)
            continue
        priority = 0 if re.search(r"menu|pricing|price-list|services?|contact|hours|reserv|book", label, re.I) else 1
        pages.append((priority, candidate))
    pages.sort(key=lambda item: (item[0], item[1]))
    return [url for _, url in pages], pdfs


def _sitemap_links(root_url: str) -> tuple[list[str], list[str]]:
    root = urlparse(root_url)
    sitemap_url = f"{root.scheme}://{root.netloc}/sitemap.xml"
    fetched = _fetch(sitemap_url, accept="application/xml,text/xml,*/*;q=0.1", max_bytes=MAX_RESPONSE_BYTES)
    if fetched is None:
        return [], []
    _, _, raw = fetched
    locations = [
        html_module.unescape(item.decode("utf-8", errors="replace").strip())
        for item in re.findall(rb"<loc>\s*(.*?)\s*</loc>", raw, re.I | re.S)
    ]
    nested = [url for url in locations if urlparse(url).path.lower().endswith(".xml") and _same_site(root_url, url)][:2]
    for nested_url in nested:
        child = _fetch(nested_url, accept="application/xml,text/xml,*/*;q=0.1", max_bytes=MAX_RESPONSE_BYTES)
        if child:
            locations.extend(
                item.decode("utf-8", errors="replace").strip()
                for item in re.findall(rb"<loc>\s*(.*?)\s*</loc>", child[2], re.I | re.S)
            )
    pages: list[str] = []
    pdfs: list[str] = []
    for raw_url in locations:
        candidate = html_module.unescape(raw_url)
        if not is_safe_public_url(candidate) or not _same_site(root_url, candidate):
            continue
        if not TARGET_PATTERN.search(urlparse(candidate).path) or SKIP_PAGE_PATTERN.search(candidate):
            continue
        if urlparse(candidate).path.lower().endswith(".pdf"):
            pdfs.append(candidate)
        elif not urlparse(candidate).path.lower().endswith(".xml"):
            pages.append(candidate)
    return list(dict.fromkeys(pages)), list(dict.fromkeys(pdfs))


def _extra_image_candidates(html: str, page_url: str) -> list[dict[str, Any]]:
    parser = _DeepPageParser()
    parser.feed(html[:MAX_RESPONSE_BYTES])
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in parser.extra_images:
        candidate = urljoin(page_url, html_module.unescape(raw.strip())).replace(",", "%2C")
        parsed = urlparse(candidate)
        candidate = parsed._replace(fragment="").geturl()
        if candidate in seen or not is_safe_public_url(candidate) or SKIP_IMAGE_PATTERN.search(parsed.path):
            continue
        seen.add(candidate)
        candidates.append({"url": candidate, "sourceRank": 8, "declaredWidth": None, "declaredHeight": None})
    return candidates[:24]


def _number(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("value") or value.get("price")
    try:
        parsed = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if 2 <= parsed <= 500 else None


def _jsonld_prices(documents: list[Any]) -> list[float]:
    prices: list[float] = []

    def visit(value: Any, currency: str = "USD") -> None:
        if isinstance(value, list):
            for item in value:
                visit(item, currency)
            return
        if not isinstance(value, dict):
            return
        local_currency = str(value.get("priceCurrency") or currency).upper()
        if local_currency in {"USD", "$", ""}:
            for key in ("price", "lowPrice", "highPrice", "minPrice", "maxPrice"):
                parsed = _number(value.get(key))
                if parsed is not None:
                    prices.append(parsed)
        for child in value.values():
            if isinstance(child, (dict, list)):
                visit(child, local_currency)

    visit(documents)
    return prices


def _text_prices(text: str) -> list[float]:
    return [float(value) for value in PRICE_PATTERN.findall(text) if 2 <= float(value) <= 500]


def _clock(hour_text: str, minute_text: str | None, meridiem: str | None) -> str | None:
    hour = int(hour_text)
    minute = int(minute_text or 0)
    token = re.sub(r"[^apm]", "", str(meridiem or "").lower())
    if token.startswith("p") and hour < 12:
        hour += 12
    elif token.startswith("a") and hour == 12:
        hour = 0
    if not token and hour == 24:
        hour = 0
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def extract_visible_contact_fields(html: str, page_url: str) -> dict[str, Any]:
    """Extract bounded first-party facts that are often absent from JSON-LD."""

    parser = _DeepPageParser()
    parser.feed(html[:MAX_RESPONSE_BYTES])
    phone = None
    reservation_url = None
    for href, label in parser.anchors:
        raw = html_module.unescape(href.strip())
        if raw.lower().startswith("tel:") and phone is None:
            candidate = " ".join(unquote(raw[4:]).split()).strip()
            if 7 <= len([character for character in candidate if character.isdigit()]) <= 15:
                phone = candidate[:64]
            continue
        candidate_url = urljoin(page_url, raw)
        if (
            reservation_url is None
            and is_safe_public_url(candidate_url)
            and _same_site(page_url, candidate_url)
            and re.search(r"reserv|book|appointment", f"{candidate_url} {label}", re.I)
        ):
            reservation_url = candidate_url

    hours_by_day: dict[str, dict[str, Any]] = {}
    for text in parser.text:
        compact = " ".join(text.split())
        if len(compact) > 180:
            continue
        days = [DAY_NAMES[match.group(1).lower()] for match in DAY_PATTERN.finditer(compact)]
        time_match = TIME_RANGE_PATTERN.search(compact)
        if not days or time_match is None:
            continue
        opens = _clock(time_match.group(1), time_match.group(2), time_match.group(3))
        closes = _clock(time_match.group(4), time_match.group(5), time_match.group(6))
        if opens is None or closes is None:
            continue
        for day in days:
            hours_by_day[day] = {
                "@type": "OpeningHoursSpecification",
                "dayOfWeek": f"https://schema.org/{day}",
                "opens": opens,
                "closes": closes,
            }
    return {
        "telephone": phone,
        "reservationUrl": reservation_url,
        "openingHoursSpecification": list(hours_by_day.values()),
    }


def _pdf_text(raw: bytes) -> str:
    """Extract simple text-bearing PDF streams without a runtime dependency."""
    streams: list[bytes] = [raw]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        content = match.group(1)
        try:
            content = zlib.decompress(content)
        except zlib.error:
            pass
        streams.append(content)
    strings: list[str] = []
    for stream in streams:
        for item in re.findall(rb"\((?:\\.|[^\\)])*\)", stream):
            value = item[1:-1]
            value = re.sub(rb"\\([()\\])", rb"\1", value)
            value = re.sub(
                rb"\\([0-7]{1,3})",
                lambda match: bytes([int(match.group(1), 8) % 256]),
                value,
            )
            strings.append(value.decode("latin-1", errors="ignore"))
    return " ".join(strings)


def _price_stats(prices: list[float], type_id: int, pages: list[str]) -> dict[str, Any] | None:
    values = sorted({round(value, 2) for value in prices if 2 <= value <= 500})
    if not values:
        return None
    median = statistics.median(values)
    lower = values[max(0, round((len(values) - 1) * 0.25))]
    upper = values[min(len(values) - 1, round((len(values) - 1) * 0.75))]
    multiplier = {1: 1.35, 2: 1.2, 3: 2.0, 4: 1.0, 5: 1.0, 6: 1.0}.get(type_id, 1.0)
    estimate = round(median * multiplier)
    minimum, maximum = ({1: (8, 250), 2: (4, 120), 3: (8, 300)}.get(type_id, (8, 500)))
    estimate = max(minimum, min(maximum, estimate))
    return {
        "currency": "USD",
        "observedPriceCount": len(values),
        "minimumPriceCents": round(values[0] * 100),
        "lowerPriceCents": round(lower * 100),
        "medianPriceCents": round(median * 100),
        "upperPriceCents": round(upper * 100),
        "maximumPriceCents": round(values[-1] * 100),
        "estimatedSpendCents": estimate * 100,
        "derivation": "OFFICIAL_MENU_MEDIAN_BY_CATEGORY",
        "sourcePages": list(dict.fromkeys(pages))[:8],
    }


def _record_image(shop: dict[str, Any], image: dict[str, Any], source_url: str, fetched_at: str) -> dict[str, Any]:
    return {
        "externalId": shop.get("externalId"),
        "name": shop.get("name"),
        "address": shop.get("address"),
        "borough": shop.get("borough"),
        "latitude": shop.get("y"),
        "longitude": shop.get("x"),
        "matchType": "OFFICIAL_SITE_IMAGE",
        "url": image["url"],
        "sourceUrl": source_url,
        "sourceName": "Official website",
        "attribution": shop.get("name"),
        "usagePolicy": "REMOTE_REFERENCE",
        "discoveryRank": image.get("sourceRank"),
        "width": image.get("width"),
        "height": image.get("height"),
        "contentType": image.get("contentType"),
        "contentSampleSha256": image["contentSampleSha256"],
        "sampleBytes": image["sampleBytes"],
        "fetchedAt": fetched_at,
        "lastCheckedAt": fetched_at,
    }


def _crawl_shop(
    shop: dict[str, Any],
    base_images: list[dict[str, Any]],
    base_site: dict[str, Any] | None,
    fetched_at: str,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, int, int]:
    website = str(shop.get("website") or "")
    if not _resolves_safely(website):
        return base_images, base_site, 0, 0
    homepage = _fetch(website, accept="text/html,application/xhtml+xml", max_bytes=MAX_RESPONSE_BYTES)
    if homepage is None:
        return base_images, base_site, 0, 0
    final_url, content_type, raw = homepage
    html = _decode_html(content_type, raw)
    if html is None:
        return base_images, base_site, 0, 0

    page_links, pdf_links = _target_links(html, final_url, final_url)
    if len(page_links) < MAX_DEEP_PAGES:
        sitemap_pages, sitemap_pdfs = _sitemap_links(final_url)
        page_links.extend(sitemap_pages)
        pdf_links.extend(sitemap_pdfs)
    if not page_links:
        root = urlparse(final_url)
        base = f"{root.scheme}://{root.netloc}"
        page_links.extend([
            f"{base}/menu", f"{base}/gallery", f"{base}/locations",
            f"{base}/contact", f"{base}/about", f"{base}/hours",
        ])
    page_links = [url for url in dict.fromkeys(page_links) if url != final_url][:MAX_DEEP_PAGES]
    pdf_links = list(dict.fromkeys(pdf_links))[:1]

    image_records = list(base_images)
    seen_urls = {str(item.get("url")) for item in image_records}
    seen_hashes = {str(item.get("contentSampleSha256")) for item in image_records if item.get("contentSampleSha256")}
    prices = _jsonld_prices(extract_jsonld_documents(html))
    price_pages: list[str] = [final_url] if prices else []
    local_business = extract_local_business_jsonld(html)
    visible_fields = extract_visible_contact_fields(html, final_url)
    pages_crawled = 1

    for page_url in page_links:
        fetched = _fetch(page_url, accept="text/html,application/xhtml+xml", max_bytes=MAX_RESPONSE_BYTES)
        if fetched is None or not _same_site(final_url, fetched[0]):
            continue
        page_final_url, page_type, page_raw = fetched
        page_html = _decode_html(page_type, page_raw)
        if page_html is None:
            continue
        pages_crawled += 1
        documents = extract_jsonld_documents(page_html)
        page_prices = _jsonld_prices(documents)
        parser = _DeepPageParser()
        parser.feed(page_html[:MAX_RESPONSE_BYTES])
        if TARGET_PATTERN.search(page_final_url):
            page_prices.extend(_text_prices(" ".join(parser.text)))
        if page_prices:
            prices.extend(page_prices)
            price_pages.append(page_final_url)
        local_business.extend(extract_local_business_jsonld(page_html))
        page_visible = extract_visible_contact_fields(page_html, page_final_url)
        if not visible_fields.get("telephone") and page_visible.get("telephone"):
            visible_fields["telephone"] = page_visible["telephone"]
        if not visible_fields.get("reservationUrl") and page_visible.get("reservationUrl"):
            visible_fields["reservationUrl"] = page_visible["reservationUrl"]
        existing_hours = {
            str(item.get("dayOfWeek")): item
            for item in visible_fields.get("openingHoursSpecification") or []
        }
        for item in page_visible.get("openingHoursSpecification") or []:
            existing_hours[str(item.get("dayOfWeek"))] = item
        visible_fields["openingHoursSpecification"] = list(existing_hours.values())

        if len(image_records) < MAX_IMAGES_PER_SHOP:
            candidates = [*_official_image_candidates(page_html, page_final_url), *_extra_image_candidates(page_html, page_final_url)]
            for candidate in candidates:
                result = _validate_remote_image(candidate)
                if result is None:
                    continue
                fingerprint = str(result["contentSampleSha256"])
                if str(result["url"]) in seen_urls or fingerprint in seen_hashes:
                    continue
                seen_urls.add(str(result["url"]))
                seen_hashes.add(fingerprint)
                image_records.append(_record_image(shop, result, page_final_url, fetched_at))
                if len(image_records) >= MAX_IMAGES_PER_SHOP:
                    break

    pdfs_parsed = 0
    for pdf_url in pdf_links:
        fetched = _fetch(pdf_url, accept="application/pdf,*/*;q=0.1", max_bytes=MAX_PDF_BYTES, timeout=10)
        if fetched is None or fetched[1] != "application/pdf":
            continue
        pdf_prices = _text_prices(_pdf_text(fetched[2]))
        if pdf_prices:
            prices.extend(pdf_prices)
            price_pages.append(fetched[0])
            pdfs_parsed += 1

    menu_stats = _price_stats(prices, int(shop.get("typeId") or 0), price_pages)
    merged = merge_local_business_documents(local_business)
    if base_site and isinstance(base_site.get("jsonLd"), dict):
        merged = {**base_site["jsonLd"], **(merged or {})}
    if menu_stats:
        merged = dict(merged or {"@type": "LocalBusiness", "name": shop.get("name"), "url": final_url})
        merged["menuPriceStats"] = menu_stats
    if any(visible_fields.values()):
        merged = dict(merged or {"@type": "LocalBusiness", "name": shop.get("name"), "url": final_url})
        if not merged.get("telephone") and visible_fields.get("telephone"):
            merged["telephone"] = visible_fields["telephone"]
        if not (merged.get("openingHours") or merged.get("openingHoursSpecification")) and visible_fields.get("openingHoursSpecification"):
            merged["openingHoursSpecification"] = visible_fields["openingHoursSpecification"]
        if visible_fields.get("reservationUrl") and not merged.get("potentialAction"):
            merged["potentialAction"] = {
                "@type": "ReserveAction",
                "target": {"urlTemplate": visible_fields["reservationUrl"]},
            }
    site_record = base_site
    if merged:
        site_record = {
            "externalId": f"official-site:{shop['id']}",
            "name": shop.get("name"),
            "address": shop.get("address"),
            "borough": shop.get("borough"),
            "latitude": shop.get("y"),
            "longitude": shop.get("x"),
            "sourceUrl": final_url,
            "crawlPages": [final_url, *page_links][:MAX_DEEP_PAGES + 1],
            "jsonLd": merged,
        }
    image_records = image_records[:MAX_IMAGES_PER_SHOP]
    for rank, record in enumerate(image_records, start=1):
        record["displayRank"] = rank
    return image_records, site_record, pages_crawled, pdfs_parsed


def fetch(
    shops: list[dict[str, Any]],
    base_image_snapshot: dict[str, Any],
    base_site_snapshot: dict[str, Any],
    limit: int,
    workers: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_images_by_external: dict[str, list[dict[str, Any]]] = {}
    for record in base_image_snapshot.get("records") or []:
        base_images_by_external.setdefault(str(record.get("externalId")), []).append(dict(record))
    base_sites_by_id = {
        str(record.get("externalId")): dict(record)
        for record in base_site_snapshot.get("records") or []
        if isinstance(record, dict)
    }
    selected = [shop for shop in shops if is_safe_public_url(str(shop.get("website") or ""))][:limit]
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def crawl(shop: dict[str, Any]):
        return _crawl_shop(
            shop,
            base_images_by_external.get(str(shop.get("externalId")), []),
            base_sites_by_id.get(f"official-site:{shop['id']}"),
            fetched_at,
        )

    with ThreadPoolExecutor(max_workers=max(1, min(workers, 24))) as executor:
        results = list(executor.map(crawl, selected))
    image_records = [record for images, _, _, _ in results for record in images]
    image_records.sort(key=lambda item: (
        int(str(item["externalId"]).rsplit(":", 1)[-1]), int(item.get("displayRank") or 1),
    ))
    site_records = [site for _, site, _, _ in results if site is not None]
    site_records.sort(key=lambda item: int(str(item["externalId"]).rsplit(":", 1)[-1]))
    pages_crawled = sum(pages for _, _, pages, _ in results)
    pdfs_parsed = sum(pdfs for _, _, _, pdfs in results)
    shops_with_menu_prices = sum(
        1 for record in site_records
        if isinstance(record.get("jsonLd"), dict) and record["jsonLd"].get("menuPriceStats")
    )
    shops_with_images = len({str(item["externalId"]) for item in image_records})
    return (
        {
            "metadata": {
                "datasetId": "official-site-merchant-images-deep",
                "datasetVersion": fetched_at[:10],
                "fetchedAt": fetched_at,
                "attemptedSites": len(selected),
                "pagesCrawled": pages_crawled,
                "shopsWithImages": shops_with_images,
                "recordCount": len(image_records),
                "maxImagesPerShop": MAX_IMAGES_PER_SHOP,
                "matchPolicy": "homepage-plus-same-site-gallery-location-menu-contact-about-hours-reservation-sitemap-srcset-css",
                "usagePolicy": "REMOTE_REFERENCE",
            },
            "records": image_records,
        },
        {
            "metadata": {
                "datasetId": "official-site-jsonld-menu-deep",
                "datasetVersion": fetched_at[:10],
                "fetchedAt": fetched_at,
                "attemptedSites": len(selected),
                "pagesCrawled": pages_crawled,
                "pdfMenusParsed": pdfs_parsed,
                "shopsWithMenuPrices": shops_with_menu_prices,
                "recordCount": len(site_records),
            },
            "records": site_records,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shops", type=Path, required=True)
    parser.add_argument("--base-images", type=Path, required=True)
    parser.add_argument("--base-official-sites", type=Path, required=True)
    parser.add_argument("--output-images", type=Path, required=True)
    parser.add_argument("--output-official-sites", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=5_000)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    with args.shops.open(encoding="utf-8") as handle:
        shops = json.load(handle)
    with args.base_images.open(encoding="utf-8") as handle:
        base_images = json.load(handle)
    with args.base_official_sites.open(encoding="utf-8") as handle:
        base_sites = json.load(handle)
    images, sites = fetch(shops, base_images, base_sites, min(max(1, args.limit), 5_000), args.workers)
    write_json_atomic(args.output_images, images)
    write_json_atomic(args.output_official_sites, sites)
    print(json.dumps({
        "status": "ok",
        "attemptedSites": images["metadata"]["attemptedSites"],
        "pagesCrawled": images["metadata"]["pagesCrawled"],
        "shopsWithImages": images["metadata"]["shopsWithImages"],
        "imageRecords": images["metadata"]["recordCount"],
        "shopsWithMenuPrices": sites["metadata"]["shopsWithMenuPrices"],
        "pdfMenusParsed": sites["metadata"]["pdfMenusParsed"],
        "officialSiteRecords": sites["metadata"]["recordCount"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
