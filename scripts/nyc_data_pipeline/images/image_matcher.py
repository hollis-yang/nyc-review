from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..matching import EntityMatcher
from ..matching.normalize import normalize_text
from .image_validator import valid_image


class ImageMatcher:
    def __init__(self, matcher: EntityMatcher | None = None) -> None:
        self.matcher = matcher or EntityMatcher()

    def assign(
        self,
        shops: list[dict[str, Any]],
        fallback_images: list[dict[str, Any]],
        merchant_snapshot: dict[str, Any] | None,
        data_version: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        merchant_records = (merchant_snapshot or {}).get("records") or []
        by_external: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in merchant_records:
            if not isinstance(item, dict):
                continue
            if item.get("externalId"):
                by_external[str(item.get("externalId"))].append(item)
            if item.get("name"):
                by_name[normalize_text(item.get("name"))].append(item)
        fallback_by_shop: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for image in fallback_images:
            fallback_by_shop[int(image["shopId"])].append(image)
        output: list[dict[str, Any]] = []
        credits: list[dict[str, Any]] = []
        next_id = 1
        for shop in shops:
            records = list(by_external.get(str(shop.get("externalId")), []))
            if not records:
                for candidate in by_name.get(normalize_text(shop.get("name")), []):
                    if self.matcher.match(shop, candidate, for_image=True):
                        records.append(candidate)
            candidates: list[tuple[dict[str, Any], str]] = []
            records.sort(key=lambda item: (
                1 if item.get("matchType") == "OFFICIAL_SITE_IMAGE" else 0,
                int(item.get("displayRank") or 1),
                str(item.get("url") or ""),
            ))
            for record in records:
                if valid_image(record, merchant_specific=True):
                    candidates.append((record, str(record.get("matchType") or "MERCHANT_EXACT")))
            # A category fallback is a last resort, not a fourth image in an
            # otherwise merchant-specific gallery. P10 therefore publishes
            # one to three merchant images, or exactly one fallback.
            if not candidates:
                for fallback in sorted(fallback_by_shop.get(int(shop["id"]), []), key=lambda item: int(item.get("sortOrder") or 0)):
                    if valid_image(fallback, merchant_specific=False):
                        candidates.append((fallback, "CATEGORY_FALLBACK"))
                        break
            seen_urls: set[str] = set()
            display_order = 0
            for image, match_type in candidates:
                url = str(image.get("url") or image.get("displayUrl"))
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                display_order += 1
                entry = {
                    "id": next_id,
                    "shopId": int(shop["id"]),
                    "sortOrder": display_order,
                    "displayOrder": display_order,
                    "isPrimary": display_order == 1,
                    "url": url,
                    "cachedUrl": image.get("cachedUrl"),
                    "imageType": "MERCHANT_SPECIFIC" if match_type != "CATEGORY_FALLBACK" else "ILLUSTRATIVE",
                    "matchType": match_type,
                    "sourceName": image.get("sourceName") or "Wikimedia Commons",
                    "sourceUrl": image.get("sourceUrl") or image.get("sourcePageUrl"),
                    "licenseName": image.get("licenseName"),
                    "licenseUrl": image.get("licenseUrl"),
                    "attribution": image.get("attribution") or image.get("authorName"),
                    "width": image.get("width"),
                    "height": image.get("height"),
                    "sha256": image.get("sha256"),
                    "contentSha256": image.get("contentSha256") or image.get("sha256"),
                    "contentSampleSha256": image.get("contentSampleSha256"),
                    "fetchedAt": image.get("fetchedAt"),
                    "lastCheckedAt": image.get("lastCheckedAt") or image.get("fetchedAt"),
                    "availabilityStatus": "AVAILABLE",
                    "dataVersion": data_version,
                }
                output.append(entry)
                credits.append({
                    "shopId": int(shop["id"]), "shopName": shop.get("name"), "url": url,
                    "sourceUrl": entry["sourceUrl"], "sourceName": entry["sourceName"],
                    "attribution": entry["attribution"], "licenseName": entry["licenseName"],
                    "licenseUrl": entry["licenseUrl"], "matchType": match_type,
                })
                next_id += 1
                if display_order >= 3:
                    break
        return output, credits
