from __future__ import annotations

from collections import Counter
from typing import Any


def build_image_manifest(images: list[dict[str, Any]]) -> dict[str, Any]:
    shops = {int(image["shopId"]) for image in images}
    match_counts = Counter(str(image.get("matchType") or "UNKNOWN") for image in images)
    return {
        "images": len(images),
        "shopsWithImages": len(shops),
        "matchTypeCounts": dict(sorted(match_counts.items())),
        "licensedImages": sum(1 for image in images if image.get("licenseName") and image.get("licenseUrl")),
    }
