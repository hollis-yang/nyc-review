#!/usr/bin/env python3
"""Build a pinned, attributed illustrative-image catalog from Wikimedia Commons."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API_URL = "https://commons.wikimedia.org/w/api.php"
DATASET_ID = "wikimedia-commons-illustrative-images"
SOURCE_NAME = "Wikimedia Commons"
SEARCHES = {
    1: "restaurant interior",
    2: "coffee shop interior",
    3: "bar interior",
    4: "museum interior",
    5: "fitness gym interior",
    6: "hair salon interior",
}
ALLOWED_LICENSE_PREFIXES = ("CC0", "CC BY", "CC-BY", "Public domain", "PDM")


def fetch_catalog(images_per_type: int = 5) -> dict[str, Any]:
    if images_per_type < 3 or images_per_type > 5:
        raise ValueError("images_per_type must be between 3 and 5")
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    images: list[dict[str, Any]] = []
    for type_id, search in SEARCHES.items():
        pages = _search(search, limit=30)
        accepted = []
        for page in pages:
            normalized = normalize_page(page, type_id=type_id, fetched_at=fetched_at)
            if normalized is not None:
                accepted.append(normalized)
            if len(accepted) >= images_per_type:
                break
        if len(accepted) < images_per_type:
            raise ValueError(
                f"Wikimedia Commons returned only {len(accepted)} reusable images for type {type_id}"
            )
        images.extend(accepted)
    return {
        "metadata": {
            "datasetId": DATASET_ID,
            "datasetVersion": fetched_at[:10],
            "sourceName": SOURCE_NAME,
            "sourceUrl": "https://commons.wikimedia.org/",
            "fetchedAt": fetched_at,
            "imagesPerType": images_per_type,
            "notes": (
                "Category-level illustrative images only. They are not photographs of the linked merchants. "
                "Each entry retains the Commons file page, author and machine-readable license metadata."
            ),
        },
        "images": images,
    }


def normalize_page(page: dict[str, Any], *, type_id: int, fetched_at: str) -> dict[str, Any] | None:
    image_info = (page.get("imageinfo") or [None])[0]
    if not isinstance(image_info, dict):
        return None
    mime = str(image_info.get("mime") or "")
    if mime not in {"image/jpeg", "image/png", "image/webp"}:
        return None
    metadata = image_info.get("extmetadata") or {}
    license_name = _metadata_value(metadata, "LicenseShortName")
    license_url = _metadata_value(metadata, "LicenseUrl")
    artist = _plain_text(_metadata_value(metadata, "Artist"))
    if not license_name or not license_url or not artist:
        return None
    if not license_name.startswith(ALLOWED_LICENSE_PREFIXES):
        return None
    url = image_info.get("thumburl") or image_info.get("url")
    source_url = image_info.get("descriptionurl")
    if not url or not source_url:
        return None
    # Do not silently truncate attribution or URLs. Assets that cannot fit the
    # P10 provenance schema are unsuitable for the import catalog.
    if (
        len(str(url)) > 1024
        or len(str(source_url)) > 1024
        or len(license_name) > 80
        or len(license_url) > 1024
        or len(artist) > 160
    ):
        return None
    return {
        "typeId": type_id,
        "title": page.get("title"),
        "url": url,
        "sourceName": SOURCE_NAME,
        "sourceUrl": source_url,
        "licenseName": license_name,
        "licenseUrl": license_url,
        "attribution": artist,
        # Commons exposes SHA-1 for the original. P10 accepts SHA-256 only, so
        # do not mislabel it; retain it separately in the source snapshot.
        "sourceSha1": image_info.get("sha1"),
        "sha256": None,
        "fetchedAt": fetched_at,
    }


def load_catalog(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        catalog = json.load(handle)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("images"), list):
        raise TypeError(f"Invalid illustrative image catalog: {path}")
    if (catalog.get("metadata") or {}).get("datasetId") != DATASET_ID:
        raise ValueError(f"Image catalog datasetId must be {DATASET_ID}")
    return catalog


def _search(search: str, *, limit: int) -> list[dict[str, Any]]:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {search}",
        "gsrnamespace": "6",
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|mime|sha1|extmetadata",
        "iiurlwidth": "900",
        "format": "json",
        "formatversion": "2",
        "origin": "*",
    }
    request = urllib.request.Request(
        f"{API_URL}?{urllib.parse.urlencode(params)}",
        headers={
            "Accept": "application/json",
            "User-Agent": "nyc-review-p8-image-catalog/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    pages = (payload.get("query") or {}).get("pages") or []
    return sorted(pages, key=lambda page: (int(page.get("index") or 10_000), str(page.get("title"))))


def _metadata_value(metadata: dict[str, Any], key: str) -> str:
    item = metadata.get(key) or {}
    return str(item.get("value") or "").strip() if isinstance(item, dict) else ""


def _plain_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(without_tags).split())


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(serialized)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images-per-type", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = fetch_catalog(args.images_per_type)
    output = args.output.resolve()
    write_json_atomic(output, catalog)
    print(json.dumps(catalog["metadata"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
