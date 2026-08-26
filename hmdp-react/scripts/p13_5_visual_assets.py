#!/usr/bin/env python3
"""Build the frontend-only P13.5 merchant visual asset pack.

The script reads the accepted P13 bundle, fetches reusable contextual photos
from Wikimedia Commons, stores fixed thumbnails under ``public`` and writes a
compact TypeScript assignment manifest. It never changes the P13 data bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


API_URL = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "hm-dianping-p13.5/1.0 (https://github.com/hollis-yang/hmdp; educational portfolio)"
ALLOWED_LICENSE_PREFIXES = ("CC0", "CC BY", "CC-BY", "Public domain", "PDM")
REJECT_TITLE_WORDS = {
    "logo", "icon", "pictogram", "diagram", "floor plan", "map of", "coat of arms",
    "menu board", "advertisement", "poster", "screenshot", "qr code", "trademark",
    "toilet", "restroom", "bathroom", "lavatory", "anbieter", "chronologisch", "list of",
}

SEARCHES: dict[int, list[str]] = {
    1: [
        "restaurant interior", "restaurant dining room", "diner interior", "New York restaurant",
        "casual restaurant interior", "restaurant tables interior", "restaurant seating",
    ],
    2: ["Italian restaurant interior", "trattoria interior", "pizzeria dining room"],
    3: ["Chinese restaurant interior", "Chinese dining room", "dim sum restaurant interior"],
    4: ["Japanese restaurant interior", "sushi restaurant interior", "ramen restaurant interior"],
    5: ["Mexican restaurant interior", "taqueria interior", "Mexican dining room"],
    6: ["vegetarian restaurant interior", "vegan restaurant interior", "plant based cafe interior"],
    7: ["coffee shop interior", "New York cafe interior", "coffee bar interior"],
    8: ["bakery interior", "bread bakery shop interior", "pastry shop interior"],
    9: ["dessert shop interior", "ice cream shop interior", "cake shop interior"],
    10: ["bubble tea shop interior", "tea shop interior", "boba tea cafe"],
    11: ["cocktail bar interior", "cocktail lounge interior", "New York cocktail bar"],
    12: ["pub interior", "tavern interior", "beer pub interior"],
    13: ["rooftop bar", "rooftop terrace restaurant", "New York rooftop terrace"],
    14: ["live music venue interior", "music club stage", "jazz club interior"],
    15: ["karaoke room interior", "karaoke bar interior", "karaoke lounge"],
    16: ["museum gallery interior", "New York museum interior", "art museum gallery"],
    17: ["theatre auditorium interior", "New York theater auditorium", "theater stage interior"],
    18: ["cinema auditorium interior", "movie theater interior", "cinema lobby"],
    19: ["video arcade interior", "arcade games room", "amusement arcade interior"],
    20: ["escape room interior", "escape game room", "puzzle room interior"],
    21: ["fitness gym interior", "gym equipment interior", "New York fitness studio"],
    22: ["yoga studio interior", "yoga class studio", "yoga room interior"],
    23: ["pilates studio interior", "pilates reformer studio", "fitness studio interior"],
    24: ["spa treatment room interior", "day spa interior", "wellness spa interior"],
    25: ["massage therapy room", "massage spa interior", "therapy treatment room"],
    26: [
        "hair salon", "beauty salon", "hairdresser", "hairdressing salon",
        "hair salon interior", "hairdressing salon interior", "New York hair salon",
    ],
    27: ["barbershop interior", "barber shop chairs", "New York barbershop"],
    28: [
        "nail salon interior", "manicure salon interior", "nail spa interior", "manicure table",
        "nail care salon", "nail art", "manicure", "nail polish salon",
    ],
    29: [
        "skincare clinic interior", "facial treatment room", "beauty clinic interior",
        "facial treatment", "skin care clinic", "beauty treatment room", "esthetician room",
    ],
}

TITLE_KEYWORDS: dict[int, tuple[str, ...]] = {
    1: ("restaurant", "diner", "dining", "bistro", "eatery", "grill", "steakhouse", "tavern", "café", "cafe"),
    2: ("italian", "trattoria", "pizzeria", "pizza", "restaurant", "dining"),
    3: ("chinese", "dim sum", "noodle", "restaurant", "dining"),
    4: ("japanese", "sushi", "ramen", "izakaya", "restaurant", "dining"),
    5: ("mexican", "taqueria", "taco", "restaurant", "dining"),
    6: ("vegetarian", "vegan", "plant based", "restaurant", "cafe"),
    7: ("coffee", "café", "cafe", "espresso", "roastery"),
    8: ("bakery", "bread", "pastry", "boulangerie"),
    9: ("dessert", "ice cream", "cake", "patisserie", "sweet shop"),
    10: ("bubble tea", "boba", "tea shop", "tearoom", "tea room"),
    11: ("cocktail", "bar", "lounge"),
    12: ("pub", "tavern", "beer", "bar"),
    13: ("rooftop", "roof terrace", "terrace bar", "sky bar"),
    14: ("music", "jazz", "concert", "stage", "club", "venue"),
    15: ("karaoke", "singing room", "music room"),
    16: ("museum", "gallery", "exhibition"),
    17: ("theatre", "theater", "auditorium", "stage"),
    18: ("cinema", "movie theater", "movie theatre", "film theater", "auditorium"),
    19: ("arcade", "amusement", "video game"),
    20: ("escape room", "escape game", "puzzle room"),
    21: ("gym", "fitness", "weight room", "exercise"),
    22: ("yoga",),
    23: ("pilates", "reformer", "fitness studio"),
    24: ("spa", "wellness", "treatment room"),
    25: ("massage", "therapy room", "treatment room"),
    26: ("hair salon", "hairdresser", "hairdressing", "beauty salon"),
    27: ("barber", "barbershop", "barber shop"),
    28: ("nail", "manicure", "beauty salon"),
    29: ("skin", "facial", "beauty", "esthetician"),
}


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def write_json_atomic(path: Path, payload: Any) -> None:
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def metadata_value(metadata: dict[str, Any], key: str) -> str:
    item = metadata.get(key) or {}
    return str(item.get("value") or "").strip() if isinstance(item, dict) else ""


def plain_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(without_tags).split())


def allowed_license(name: str, url: str) -> bool:
    lowered = f"{name} {url}".lower()
    if not name.startswith(ALLOWED_LICENSE_PREFIXES):
        return False
    return "/nc" not in lowered and "-nc" not in lowered and "/nd" not in lowered and "-nd" not in lowered


def commons_search(query: str, *, offset: int | None = None, limit: int = 50) -> tuple[list[dict[str, Any]], int | None]:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}",
        "gsrnamespace": "6",
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|mime|size|sha1|extmetadata",
        "iiurlwidth": "720",
        "format": "json",
        "formatversion": "2",
        "origin": "*",
    }
    if offset is not None:
        params["gsroffset"] = str(offset)
    request = urllib.request.Request(
        f"{API_URL}?{urllib.parse.urlencode(params)}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    pages = (payload.get("query") or {}).get("pages") or []
    next_offset = (payload.get("continue") or {}).get("gsroffset")
    return pages, int(next_offset) if next_offset is not None else None


def normalize_page(page: dict[str, Any], *, subcategory_id: int, fetched_at: str) -> dict[str, Any] | None:
    info = (page.get("imageinfo") or [None])[0]
    if not isinstance(info, dict):
        return None
    mime = str(info.get("mime") or "")
    if mime not in {"image/jpeg", "image/png", "image/webp"}:
        return None
    width = int(info.get("width") or 0)
    height = int(info.get("height") or 0)
    if width < 640 or height < 400:
        return None
    title = str(page.get("title") or "")
    lowered_title = title.lower()
    if any(word in lowered_title for word in REJECT_TITLE_WORDS):
        return None
    if not any(keyword in lowered_title for keyword in TITLE_KEYWORDS[subcategory_id]):
        return None
    metadata = info.get("extmetadata") or {}
    license_name = metadata_value(metadata, "LicenseShortName")
    license_url = metadata_value(metadata, "LicenseUrl")
    attribution = plain_text(metadata_value(metadata, "Artist"))
    if not license_name or not license_url or not attribution or not allowed_license(license_name, license_url):
        return None
    image_url = str(info.get("thumburl") or info.get("url") or "")
    source_url = str(info.get("descriptionurl") or "")
    if not image_url or not source_url:
        return None
    return {
        "subcategoryId": subcategory_id,
        "title": title,
        "downloadUrl": image_url,
        "sourceUrl": source_url,
        "sourceName": "Wikimedia Commons",
        "licenseName": license_name,
        "licenseUrl": license_url,
        "attribution": attribution[:500],
        "sourceSha1": str(info.get("sha1") or ""),
        "mime": mime,
        "width": width,
        "height": height,
        "fetchedAt": fetched_at,
    }


def fetch_candidates(subcategory_id: int, target: int, fetched_at: str) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in SEARCHES[subcategory_id]:
        offset: int | None = None
        for _ in range(10):
            pages, offset = commons_search(query, offset=offset)
            for page in pages:
                item = normalize_page(page, subcategory_id=subcategory_id, fetched_at=fetched_at)
                if item is None or item["sourceUrl"] in seen:
                    continue
                seen.add(item["sourceUrl"])
                accepted.append(item)
                if len(accepted) >= target:
                    return accepted
            if offset is None:
                break
            time.sleep(0.15)
        if len(accepted) >= target:
            break
    return accepted


def download_asset(item: dict[str, Any], output_dir: Path, ordinal: int) -> dict[str, Any]:
    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[item["mime"]]
    source_key = item["sourceSha1"] or hashlib.sha256(item["sourceUrl"].encode()).hexdigest()
    filename = f"s{item['subcategoryId']:02d}-{ordinal:03d}-{source_key[:12]}.{extension}"
    destination = output_dir / filename
    request = urllib.request.Request(item["downloadUrl"], headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
    with urllib.request.urlopen(request, timeout=90) as response:
        content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0]
        content = response.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024:
        raise ValueError(f"Image exceeds 8 MiB: {item['sourceUrl']}")
    if content_type not in {"image/jpeg", "image/png", "image/webp", "application/octet-stream"}:
        raise ValueError(f"Unexpected image content type {content_type}: {item['sourceUrl']}")
    if len(content) < 12_000:
        raise ValueError(f"Image is unexpectedly small: {item['sourceUrl']}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=destination.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, destination)
    return {
        **{key: value for key, value in item.items() if key not in {"downloadUrl", "mime"}},
        "file": filename,
        "publicUrl": f"/merchant-visuals/context/{filename}",
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
    }


def pin_remote_asset(item: dict[str, Any], ordinal: int) -> dict[str, Any]:
    """Pin a Commons thumbnail without bulk-downloading the source file."""
    source_key = item["sourceSha1"] or hashlib.sha256(item["sourceUrl"].encode()).hexdigest()
    return {
        **{key: value for key, value in item.items() if key != "mime"},
        "file": None,
        "publicUrl": item["downloadUrl"],
        "sha256": None,
        "bytes": None,
        "assetId": f"s{item['subcategoryId']:02d}-{ordinal:03d}-{source_key[:12]}",
    }


def typescript_manifest(
    *,
    data_version: str,
    exact_shop_ids: list[int],
    assets: list[dict[str, Any]],
    assignments: dict[int, tuple[int, int]],
    exact_primary_urls: dict[int, str],
) -> str:
    asset_urls = [item["publicUrl"] for item in assets]
    compact_assignments = {str(key): list(value) for key, value in sorted(assignments.items())}
    return (
        "// Generated by hmdp-react/scripts/p13_5_visual_assets.py. Do not edit by hand.\n"
        f"export const P13_VISUAL_DATA_VERSION = {json.dumps(data_version)};\n"
        f"export const P13_MERCHANT_SPECIFIC_SHOP_IDS = {json.dumps(exact_shop_ids, separators=(',', ':'))} as const;\n"
        "export const P13_MERCHANT_PRIMARY_URLS: Readonly<Record<number, string>> = "
        f"{json.dumps({str(key): value for key, value in sorted(exact_primary_urls.items())}, separators=(',', ':'))};\n"
        f"export const P13_CONTEXTUAL_ASSET_URLS = {json.dumps(asset_urls, separators=(',', ':'))} as const;\n"
        "export const P13_SHOP_VISUAL_ASSIGNMENTS: Readonly<Record<number, readonly [number, number]>> = "
        f"{json.dumps(compact_assignments, separators=(',', ':'))};\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("../data/generated/nyc-real-p13-full"))
    parser.add_argument("--max-reuse", type=int, default=15)
    parser.add_argument("--minimum-per-subcategory", type=int, default=1)
    parser.add_argument(
        "--download-assets",
        action="store_true",
        help="Cache thumbnails locally. The default pins URLs to respect Wikimedia bulk-download limits.",
    )
    parser.add_argument("--public-directory", type=Path, default=Path("public/merchant-visuals"))
    parser.add_argument("--manifest", type=Path, default=Path("src/generated/merchantVisualManifest.ts"))
    parser.add_argument("--report", type=Path, default=Path("reports/p13-5-visual-coverage.json"))
    args = parser.parse_args()

    dataset = args.dataset.resolve()
    public_directory = args.public_directory.resolve()
    context_directory = public_directory / "context"
    shops: list[dict[str, Any]] = read_json(dataset / "shops.json")
    shop_images: list[dict[str, Any]] = read_json(dataset / "shop_images.json")
    blogs: list[dict[str, Any]] = read_json(dataset / "blogs.json")
    manifest = read_json(dataset / "manifest.json")
    data_version = str(manifest["dataVersion"])

    exact_shop_ids = sorted({
        int(image["shopId"])
        for image in shop_images
        if image.get("imageType") == "MERCHANT_SPECIFIC" and image.get("availabilityStatus") == "AVAILABLE"
    })
    exact_set = set(exact_shop_ids)
    exact_primary_urls: dict[int, str] = {}
    for image in sorted(
        shop_images,
        key=lambda item: (int(item["shopId"]), 0 if item.get("isPrimary") else 1, int(item.get("displayOrder") or 0)),
    ):
        shop_id = int(image["shopId"])
        if shop_id in exact_set and shop_id not in exact_primary_urls and image.get("url"):
            exact_primary_urls[shop_id] = str(image["cachedUrl"] or image["url"])
    missing_by_subcategory: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for shop in shops:
        if int(shop["id"]) not in exact_set:
            missing_by_subcategory[int(shop["subcategoryId"])].append(shop)

    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    downloaded: list[dict[str, Any]] = []
    rejected_downloads: list[dict[str, str]] = []
    for subcategory_id in sorted(missing_by_subcategory):
        missing_count = len(missing_by_subcategory[subcategory_id])
        target = max(args.minimum_per_subcategory, math.ceil(missing_count / args.max_reuse))
        candidates = fetch_candidates(subcategory_id, target + 4, fetched_at)
        accepted_for_subcategory = 0
        for candidate in candidates:
            if args.download_assets:
                try:
                    asset = download_asset(candidate, context_directory, accepted_for_subcategory + 1)
                except (OSError, ValueError) as error:
                    rejected_downloads.append({"sourceUrl": candidate["sourceUrl"], "error": str(error)})
                    continue
            else:
                asset = pin_remote_asset(candidate, accepted_for_subcategory + 1)
            downloaded.append(asset)
            accepted_for_subcategory += 1
            if accepted_for_subcategory >= target:
                break
        if accepted_for_subcategory < target:
            sample_errors = [
                rejected["error"]
                for rejected in rejected_downloads[-min(5, len(rejected_downloads)):]
            ]
            raise RuntimeError(
                f"Only {accepted_for_subcategory}/{target} contextual assets available for subcategory "
                f"{subcategory_id}; candidates={len(candidates)}; errors={sample_errors}"
            )

    asset_indexes_by_subcategory: dict[int, list[int]] = defaultdict(list)
    for index, asset in enumerate(downloaded):
        asset_indexes_by_subcategory[int(asset["subcategoryId"])].append(index)
    type_by_subcategory = {
        int(shop["subcategoryId"]): int(shop["typeId"])
        for shop in shops
    }

    assignments: dict[int, tuple[int, int]] = {}
    reuse_counts: Counter[int] = Counter()
    shops_by_id = {int(shop["id"]): shop for shop in shops}
    for subcategory_id, subcategory_shops in sorted(missing_by_subcategory.items()):
        indexes = asset_indexes_by_subcategory[subcategory_id]
        stable_shops = sorted(
            subcategory_shops,
            key=lambda shop: hashlib.sha256(f"{shop['id']}:{shop.get('externalId', '')}".encode()).hexdigest(),
        )
        for position, shop in enumerate(stable_shops):
            asset_index = indexes[position % len(indexes)]
            shop_id = int(shop["id"])
            assignments[shop_id] = (asset_index, int(shop["typeId"]))
            reuse_counts[asset_index] += 1

    # Exact photos still receive a contextual fallback in case the remote
    # official-site image becomes unavailable.
    for shop_id in exact_shop_ids:
        shop = shops_by_id[shop_id]
        subcategory_id = int(shop["subcategoryId"])
        indexes = asset_indexes_by_subcategory.get(subcategory_id)
        if not indexes:
            type_id = int(shop["typeId"])
            indexes = [
                index
                for index, item in enumerate(downloaded)
                if type_by_subcategory[int(item["subcategoryId"])] == type_id
            ]
        digest = int(hashlib.sha256(f"fallback:{shop_id}".encode()).hexdigest()[:12], 16)
        assignments[shop_id] = (indexes[digest % len(indexes)], int(shop["typeId"]))

    max_contextual_reuse = max(reuse_counts.values(), default=0)
    if max_contextual_reuse > args.max_reuse:
        raise RuntimeError(f"Contextual asset reuse {max_contextual_reuse} exceeds {args.max_reuse}")

    credits = {
        "metadata": {
            "datasetId": "hmdp-p13.5-frontend-contextual-visuals",
            "dataVersion": data_version,
            "fetchedAt": fetched_at,
            "sourceName": "Wikimedia Commons",
            "sourceUrl": "https://commons.wikimedia.org/",
            "notes": "Contextual category imagery; not a claim that an image depicts the assigned merchant.",
        },
        "assets": downloaded,
    }
    write_json_atomic(public_directory / "credits.json", credits)
    write_text_atomic(
        args.manifest.resolve(),
        typescript_manifest(
            data_version=data_version,
            exact_shop_ids=exact_shop_ids,
            assets=downloaded,
            assignments=assignments,
            exact_primary_urls=exact_primary_urls,
        ),
    )

    generated_blog_count = sum(1 for blog in blogs if blog.get("sourceType") == "SYNTHETIC")
    report = {
        "status": "ok",
        "dataVersion": data_version,
        "shops": len(shops),
        "merchantSpecificShops": len(exact_shop_ids),
        "merchantSpecificCoverage": round(len(exact_shop_ids) / len(shops), 6),
        "contextualPhotoShops": len(shops) - len(exact_shop_ids),
        "photoBackedFrontendShops": len(shops),
        "photoBackedFrontendCoverage": 1.0,
        "nonDefaultVisualShops": len(shops),
        "nonDefaultVisualCoverage": 1.0,
        "generatedNotes": generated_blog_count,
        "notesWithVisualFallback": generated_blog_count,
        "contextualAssets": len(downloaded),
        "locallyCachedContextualAssets": sum(1 for asset in downloaded if asset["file"]),
        "maximumContextualReuseForMissingShops": max_contextual_reuse,
        "allowedLicenses": sorted({asset["licenseName"] for asset in downloaded}),
        "rejectedDownloads": rejected_downloads,
        "runtimeSearchApiRequests": 0,
        "backendChangesRequired": False,
    }
    write_json_atomic(args.report.resolve(), report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
