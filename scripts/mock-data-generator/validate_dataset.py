#!/usr/bin/env python3
"""Fail fast on P6 dataset scale, provenance and referential-quality regressions."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

REQUIRED_BOROUGHS = {"Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"}
PUBLIC_SOURCE = "NYC_OPEN_DATA"


def validate_dataset(directory: Path) -> dict[str, Any]:
    manifest = _read_object(directory / "manifest.json")
    shops = _read_list(directory / "shops.json")
    reviews = _read_list(directory / "shop_reviews.json")
    shop_ids = [int(shop["id"]) for shop in shops]
    if len(shop_ids) != len(set(shop_ids)):
        raise ValueError("shops.json contains duplicate shop IDs")
    shop_id_set = set(shop_ids)
    if not REQUIRED_BOROUGHS.issubset({shop.get("borough") for shop in shops}):
        raise ValueError("shops.json does not cover all five NYC boroughs")
    if any(review.get("shopId") not in shop_id_set for review in reviews):
        raise ValueError("shop_reviews.json contains an unknown shopId")

    source_counts = Counter(str(shop.get("sourceType") or "UNKNOWN") for shop in shops)
    public_shops = [shop for shop in shops if shop.get("sourceType") == PUBLIC_SOURCE]
    external_ids = [shop.get("externalId") for shop in public_shops]
    if len(external_ids) != len(set(external_ids)):
        raise ValueError("public-source-backed shops contain duplicate external IDs")
    for shop in shops:
        if not shop.get("externalId") or not shop.get("sourceName"):
            raise ValueError(f"shop {shop.get('id')} is missing provenance identity")
        if not shop.get("syntheticFields"):
            raise ValueError(f"shop {shop.get('id')} does not disclose synthetic fields")
    for shop in public_shops:
        if not shop.get("sourceUrl") or not shop.get("sourceFetchedAt"):
            raise ValueError(f"public-source-backed shop {shop['id']} is missing source metadata")

    manifest_provenance = manifest.get("provenance") or {}
    if manifest_provenance.get("publicSourceBackedShops") != len(public_shops):
        raise ValueError("manifest provenance count does not match shops.json")
    return {
        "dataVersion": manifest.get("dataVersion"),
        "datasetSha256": manifest.get("datasetSha256"),
        "shops": len(shops),
        "reviews": len(reviews),
        "boroughs": sorted({shop.get("borough") for shop in shops}),
        "sourceCounts": dict(sorted(source_counts.items())),
        "publicSourceRatio": round(len(public_shops) / len(shops), 4) if shops else 0,
        "status": "ok",
    }


def _read_list(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, list):
        raise TypeError(f"Expected JSON list: {path}")
    return value


def _read_object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    report = validate_dataset(args.directory.resolve())
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
