#!/usr/bin/env python3
"""Fail fast on P6 dataset scale, provenance and referential-quality regressions."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

REQUIRED_BOROUGHS = {"Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"}
PUBLIC_SOURCE = "NYC_OPEN_DATA"
REAL_SOURCES = {"NYC_OPEN_DATA", "OPENSTREETMAP"}
REQUIRED_TYPE_IDS = {1, 2, 3, 4, 5, 6}
REAL_SHOP_FIELD_LIMITS = {
    "name": 128,
    "images": 4096,
    "area": 128,
    "borough": 64,
    "address": 255,
    "description": 1024,
    "sourceType": 16,
    "externalId": 160,
    "sourceName": 160,
    "sourceUrl": 768,
    "dataVersion": 32,
}
SHOP_IMAGE_FIELD_LIMITS = {
    "url": 1024,
    "sourceUrl": 1024,
    "sourceName": 160,
    "attribution": 160,
    "licenseName": 80,
    "licenseUrl": 1024,
    "imageType": 32,
    "sha256": 64,
    "dataVersion": 32,
}
REVIEW_FIELD_LIMITS = {
    "authorRole": 16,
    "sourceType": 32,
    "language": 16,
    "sentiment": 16,
    "content": 2000,
    "images": 1024,
}
CONTENT_SOURCE_FIELD_LIMITS = {
    "sourceType": 32,
    "dataVersion": 32,
}


def validate_dataset(directory: Path) -> dict[str, Any]:
    manifest = _read_object(directory / "manifest.json")
    import_manifest = _read_object(directory / "import_manifest.json")
    shops = _read_list(directory / "shops.json")
    reviews = _read_list(directory / "shop_reviews.json")
    blogs = _read_list(directory / "blogs.json")
    blog_comments = _read_list(directory / "blog_comments.json")
    vouchers = _read_list(directory / "vouchers.json")
    business_hours = _read_list(directory / "shop_business_hours.json")
    image_path = directory / "shop_images.json"
    images = _read_list(image_path) if image_path.is_file() else []
    observation_path = directory / "shop_field_observations.json"
    observations = _read_list(observation_path) if observation_path.is_file() else []
    shop_ids = [int(shop["id"]) for shop in shops]
    if len(shop_ids) != len(set(shop_ids)):
        raise ValueError("shops.json contains duplicate shop IDs")
    shop_id_set = set(shop_ids)
    if not REQUIRED_BOROUGHS.issubset({shop.get("borough") for shop in shops}):
        raise ValueError("shops.json does not cover all five NYC boroughs")
    if any(review.get("shopId") not in shop_id_set for review in reviews):
        raise ValueError("shop_reviews.json contains an unknown shopId")
    _validate_field_observations(observations, shop_id_set)

    source_counts = Counter(str(shop.get("sourceType") or "UNKNOWN") for shop in shops)
    public_shops = [shop for shop in shops if shop.get("sourceType") == PUBLIC_SOURCE]
    source_backed_shops = [shop for shop in shops if shop.get("sourceType") in REAL_SOURCES]
    external_ids = [(shop.get("sourceType"), shop.get("externalId")) for shop in source_backed_shops]
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
    expected_public_count = len(source_backed_shops) if str(manifest.get("dataVersion") or "").startswith("nyc-real-") else len(public_shops)
    if manifest_provenance.get("publicSourceBackedShops") != expected_public_count:
        if not str(manifest.get("dataVersion") or "").startswith("nyc-real-"):
            raise ValueError("manifest provenance count does not match shops.json")

    identity_mode = manifest.get("merchantIdentityMode") or manifest_provenance.get("merchantIdentityMode")
    if str(manifest.get("dataVersion") or "").startswith("nyc-real-v1-") or identity_mode == "REAL_ONLY":
        _validate_real_only(
            manifest,
            import_manifest,
            shops,
            reviews,
            images,
            blogs,
            blog_comments,
            vouchers,
            business_hours,
            source_counts,
            shop_id_set,
        )
    return {
        "dataVersion": manifest.get("dataVersion"),
        "datasetSha256": manifest.get("datasetSha256"),
        "merchantIdentityMode": identity_mode,
        "shops": len(shops),
        "reviews": len(reviews),
        "illustrativeImages": len(images),
        "boroughs": sorted({shop.get("borough") for shop in shops}),
        "sourceCounts": dict(sorted(source_counts.items())),
        "publicSourceRatio": round(len(source_backed_shops) / len(shops), 4) if shops else 0,
        "status": "ok",
    }


def _validate_real_only(
    manifest: dict[str, Any],
    import_manifest: dict[str, Any],
    shops: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    images: list[dict[str, Any]],
    blogs: list[dict[str, Any]],
    blog_comments: list[dict[str, Any]],
    vouchers: list[dict[str, Any]],
    business_hours: list[dict[str, Any]],
    source_counts: Counter[str],
    shop_id_set: set[int],
) -> None:
    provenance = manifest.get("provenance") or {}
    data_version = str(manifest.get("dataVersion") or "")
    snapshot_sha256 = str(provenance.get("sourceSnapshotSha256") or "")
    seed = manifest.get("seed")
    if not isinstance(seed, int) or len(snapshot_sha256) != 64:
        raise ValueError("REAL_ONLY manifest must retain its source snapshot SHA-256 and seed")
    profile_name = str(manifest.get("profile") or "")
    if data_version.startswith("nyc-real-v2-"):
        enrichment_sha256 = str(provenance.get("enrichmentVersionSha256") or "")
        expected_version = f"nyc-real-v2-{enrichment_sha256[:8]}-m20260824"
        if len(enrichment_sha256) != 64 or data_version != expected_version:
            raise ValueError("P2/P3 dataVersion must be bound to its enrichment snapshot set")
    else:
        expected_version = _real_data_version(snapshot_sha256, seed, profile_name)
        if data_version != expected_version:
            raise ValueError(
                "REAL_ONLY dataVersion must be bound to sourceSnapshotSha256 and seed"
            )
    if len(data_version) > 32:
        raise ValueError("REAL_ONLY dataVersion exceeds the database column limit")
    if manifest.get("merchantIdentityMode") != "REAL_ONLY":
        raise ValueError("nyc-real-v1-* manifest must declare merchantIdentityMode=REAL_ONLY")
    if import_manifest.get("dataVersion") != data_version:
        raise ValueError("import_manifest.json dataVersion does not match manifest.json")
    if (manifest.get("importBundle") or {}).get("dataVersion") != data_version:
        raise ValueError("embedded importBundle dataVersion does not match manifest.json")
    if set(source_counts).difference(REAL_SOURCES):
        raise ValueError("REAL_ONLY dataset contains a mock, legacy or unknown merchant identity")
    if source_counts.get("MOCK", 0) or provenance.get("mockShops") != 0:
        raise ValueError("REAL_ONLY provenance must declare mockShops=0")
    if provenance.get("realShops") != len(shops):
        raise ValueError("REAL_ONLY provenance realShops does not match shops.json")
    if provenance.get("sourceCounts") != dict(sorted(source_counts.items())):
        raise ValueError("REAL_ONLY provenance sourceCounts does not match shops.json")
    if {int(shop.get("typeId") or 0) for shop in shops} != REQUIRED_TYPE_IDS:
        raise ValueError("REAL_ONLY shops must cover all six top-level categories")
    for shop in shops:
        missing = [
            field
            for field in (
                "name", "address", "borough", "neighborhood", "neighborhoodCode", "externalId",
                "sourceName", "sourceUrl", "sourceFetchedAt",
            )
            if not shop.get(field)
        ]
        if missing:
            raise ValueError(f"real shop {shop.get('id')} is missing: {', '.join(missing)}")
        if not isinstance(shop.get("avgPriceCents"), int) or shop["avgPriceCents"] <= 0:
            raise ValueError(f"real shop {shop['id']} is missing its price estimate")
        if shop.get("priceLevel") not in {1, 2, 3, 4}:
            raise ValueError(f"real shop {shop['id']} has an invalid price level")
        if not isinstance(shop.get("score"), int) or not 0 <= shop["score"] <= 50:
            raise ValueError(f"real shop {shop['id']} is missing its review-derived score")
        if not shop.get("tags"):
            raise ValueError(f"real shop {shop['id']} is missing discovery tags")
        if shop.get("sourceType") not in REAL_SOURCES:
            raise ValueError(f"real shop {shop['id']} has a non-real sourceType")
        if shop.get("dataVersion") != data_version:
            raise ValueError(f"real shop {shop['id']} has a mismatched dataVersion")
        _validate_field_lengths(
            f"real shop {shop.get('externalId') or shop.get('id')}",
            shop,
            REAL_SHOP_FIELD_LIMITS,
        )

    hours_by_shop: Counter[int] = Counter(
        int(item.get("shopId") or 0) for item in business_hours
    )
    if set(hours_by_shop) != shop_id_set or any(count != 7 for count in hours_by_shop.values()):
        raise ValueError("every real shop must have seven daily business-hour rows")

    _validate_images(images, shop_id_set, provenance, shops, data_version)
    depth_counts, root_count = _validate_review_threads(reviews, shop_id_set, shops)
    _validate_synthetic_content(
        blogs,
        blog_comments,
        vouchers,
        shop_id_set,
        data_version,
        provenance,
        import_manifest.get("provenance") or {},
    )
    if provenance.get("syntheticReviews") != len(reviews):
        raise ValueError("manifest syntheticReviews does not match shop_reviews.json")
    if provenance.get("syntheticReviewRoots") != root_count:
        raise ValueError("manifest syntheticReviewRoots does not match review roots")
    if provenance.get("reviewDepthCounts") != dict(sorted(depth_counts.items())):
        raise ValueError("manifest reviewDepthCounts does not match shop_reviews.json")


def _validate_synthetic_content(
    blogs: list[dict[str, Any]],
    blog_comments: list[dict[str, Any]],
    vouchers: list[dict[str, Any]],
    shop_id_set: set[int],
    data_version: str,
    provenance: dict[str, Any],
    import_provenance: dict[str, Any],
) -> None:
    blog_ids: set[int] = set()
    for blog in blogs:
        blog_id = blog.get("id")
        if not isinstance(blog_id, int) or blog_id in blog_ids:
            raise ValueError("blogs.json contains an invalid or duplicate id")
        blog_ids.add(blog_id)
        if blog.get("shopId") not in shop_id_set:
            raise ValueError(f"synthetic blog {blog_id} references an unknown shopId")
        _validate_synthetic_source("blog", blog, data_version)

    comment_ids: set[int] = set()
    for comment in blog_comments:
        comment_id = comment.get("id")
        if not isinstance(comment_id, int) or comment_id in comment_ids:
            raise ValueError("blog_comments.json contains an invalid or duplicate id")
        comment_ids.add(comment_id)
        if comment.get("blogId") not in blog_ids:
            raise ValueError(f"synthetic blog comment {comment_id} references an unknown blogId")
        _validate_synthetic_source("blog comment", comment, data_version)

    voucher_ids: set[int] = set()
    for voucher in vouchers:
        voucher_id = voucher.get("id")
        if not isinstance(voucher_id, int) or voucher_id in voucher_ids:
            raise ValueError("vouchers.json contains an invalid or duplicate id")
        voucher_ids.add(voucher_id)
        if voucher.get("shopId") not in shop_id_set:
            raise ValueError(f"synthetic voucher {voucher_id} references an unknown shopId")
        _validate_synthetic_source("voucher", voucher, data_version)

    expected_counts = {
        "syntheticBlogs": len(blogs),
        "syntheticBlogComments": len(blog_comments),
        "syntheticVouchers": len(vouchers),
    }
    for field, expected in expected_counts.items():
        if provenance.get(field) != expected:
            raise ValueError(f"manifest {field} does not match generated content")
        if import_provenance.get(field) != expected:
            raise ValueError(f"import_manifest {field} does not match generated content")


def _validate_synthetic_source(kind: str, item: dict[str, Any], data_version: str) -> None:
    item_id = item.get("id")
    if item.get("sourceType") != "SYNTHETIC":
        raise ValueError(f"{kind} {item_id} is not marked SYNTHETIC")
    if item.get("dataVersion") != data_version:
        raise ValueError(f"synthetic {kind} {item_id} has a mismatched dataVersion")
    _validate_field_lengths(
        f"synthetic {kind} {item_id}",
        item,
        CONTENT_SOURCE_FIELD_LIMITS,
    )


def _validate_field_observations(
    observations: list[dict[str, Any]],
    shop_id_set: set[int],
) -> None:
    keys: set[tuple[int, str, str, str]] = set()
    for observation in observations:
        shop_id = int(observation.get("shopId") or 0)
        if shop_id not in shop_id_set:
            raise ValueError("shop_field_observations.json contains an unknown shopId")
        key = (
            shop_id,
            str(observation.get("fieldName") or ""),
            str(observation.get("provider") or ""),
            str(observation.get("contentSha256") or ""),
        )
        if not all(key) or key in keys:
            raise ValueError(
                "shop_field_observations.json violates uk_shop_field_observation"
            )
        keys.add(key)


def _validate_images(
    images: list[dict[str, Any]],
    shop_id_set: set[int],
    provenance: dict[str, Any],
    shops: list[dict[str, Any]],
    data_version: str,
) -> None:
    if not images:
        raise ValueError("REAL_ONLY dataset is missing shop_images.json")
    image_ids = [image.get("id") for image in images]
    if len(image_ids) != len(set(image_ids)):
        raise ValueError("shop_images.json contains duplicate IDs")
    counts: Counter[int] = Counter()
    urls_by_shop: dict[int, list[str]] = {}
    for image in images:
        shop_id = image.get("shopId")
        if shop_id not in shop_id_set:
            raise ValueError("shop_images.json contains an unknown shopId")
        if image.get("imageType") not in {"ILLUSTRATIVE", "MERCHANT_SPECIFIC"}:
            raise ValueError("shop images must be labeled ILLUSTRATIVE or MERCHANT_SPECIFIC")
        required_fields = ["url", "sourceUrl", "sourceName", "attribution", "dataVersion"]
        if image.get("matchType") != "OFFICIAL_SITE_IMAGE":
            required_fields.extend(["licenseName", "licenseUrl"])
        for field in required_fields:
            if not image.get(field):
                raise ValueError(f"illustrative image {image.get('id')} is missing {field}")
        if image.get("dataVersion") != data_version:
            raise ValueError(f"illustrative image {image.get('id')} has a mismatched dataVersion")
        _validate_field_lengths(
            f"illustrative image {image.get('sourceUrl') or image.get('id')}",
            image,
            SHOP_IMAGE_FIELD_LIMITS,
        )
        if image.get("sourceName") == "Wikimedia Commons" and not str(image["sourceUrl"]).startswith("https://commons.wikimedia.org/wiki/File:"):
            raise ValueError("illustrative sourceUrl must be a Wikimedia Commons file page")
        counts[int(shop_id)] += 1
        urls_by_shop.setdefault(int(shop_id), []).append(str(image["url"]))
    if set(counts) != shop_id_set or any(count < 1 or count > 5 for count in counts.values()):
        raise ValueError("every real shop must have between one and five attributed illustrative images")
    for shop in shops:
        if str(shop.get("images") or "").split(",") != urls_by_shop[shop["id"]]:
            raise ValueError(f"shop {shop['id']} image list does not match shop_images.json")
    illustrative_count = sum(1 for image in images if image.get("imageType") == "ILLUSTRATIVE")
    merchant_count = sum(1 for image in images if image.get("imageType") == "MERCHANT_SPECIFIC")
    if provenance.get("illustrativeImages") != illustrative_count:
        raise ValueError("manifest illustrativeImages does not match fallback images")
    if provenance.get("merchantSpecificImages", 0) != merchant_count:
        raise ValueError("manifest merchantSpecificImages does not match shop_images.json")


def _real_data_version(snapshot_sha256: str, seed: int, profile_name: str) -> str:
    profile_codes = {
        "real-small": "s",
        "real-medium": "m",
        "real-large": "l",
        "real-load": "x",
    }
    if profile_name not in profile_codes:
        raise ValueError("REAL_ONLY manifest has an unsupported profile")
    profile_code = profile_codes[profile_name]
    seed_token = str(seed)
    version = f"nyc-real-v1-{snapshot_sha256[:8]}-{profile_code}{seed_token}"
    if len(version) > 32:
        seed_token = hashlib.sha256(seed_token.encode("utf-8")).hexdigest()[:8]
        version = f"nyc-real-v1-{snapshot_sha256[:8]}-{profile_code}h{seed_token}"
    return version


def _validate_review_threads(
    reviews: list[dict[str, Any]],
    shop_id_set: set[int],
    shops: list[dict[str, Any]],
) -> tuple[dict[str, int], int]:
    by_id: dict[int, dict[str, Any]] = {}
    closed_roots: set[int] = set()
    current_root: int | None = None
    depth_counts: Counter[str] = Counter()
    root_counts: Counter[int] = Counter()
    root_ratings: set[int] = set()
    for review in reviews:
        review_id = review.get("id")
        if not isinstance(review_id, int) or review_id in by_id:
            raise ValueError("shop_reviews.json contains an invalid or duplicate id")
        if review.get("shopId") not in shop_id_set:
            raise ValueError("shop_reviews.json contains an unknown shopId")
        depth = review.get("depth")
        if depth not in (0, 1, 2):
            raise ValueError(f"review {review_id} has an invalid depth")
        root_id = review.get("rootId")
        if not isinstance(root_id, int):
            raise ValueError(f"review {review_id} is missing rootId")
        if root_id != current_root:
            if current_root is not None:
                closed_roots.add(current_root)
            if root_id in closed_roots:
                raise ValueError("review threads are not contiguous by rootId")
            current_root = root_id
        if review.get("sourceType") != "SYNTHETIC":
            raise ValueError(f"review {review_id} is not marked SYNTHETIC")
        _validate_field_lengths(f"review {review_id}", review, REVIEW_FIELD_LIMITS)
        if not review.get("language") or not review.get("sentiment") or not isinstance(review.get("topicTags"), list):
            raise ValueError(f"review {review_id} is missing synthetic review metadata")
        parent_id = review.get("parentId")
        if depth == 0:
            if root_id != review_id or parent_id not in (None, 0):
                raise ValueError(f"review root {review_id} has invalid root/parent identity")
            rating = review.get("rating")
            if not isinstance(rating, int) or not 1 <= rating <= 5:
                raise ValueError(f"review root {review_id} must carry rating 1..5")
            if review.get("replyToUserId") is not None:
                raise ValueError(f"review root {review_id} cannot reply to a user")
            root_counts[int(review["shopId"])] += 1
            root_ratings.add(rating)
        else:
            parent = by_id.get(parent_id)
            if parent is None:
                raise ValueError(f"review {review_id} references a missing or later parent")
            if parent.get("shopId") != review.get("shopId") or parent.get("rootId") != root_id:
                raise ValueError(f"review {review_id} crosses shop or thread boundaries")
            if parent.get("depth") != depth - 1:
                raise ValueError(f"review {review_id} parent depth is invalid")
            if review.get("rating") is not None:
                raise ValueError(f"review reply {review_id} must not carry a rating")
            if review.get("replyToUserId") != parent.get("userId"):
                raise ValueError(f"review {review_id} replyToUserId does not match its parent")
        by_id[review_id] = review
        depth_counts[str(depth)] += 1
    if root_ratings != {1, 2, 3, 4, 5}:
        raise ValueError("synthetic review roots must cover all rating levels 1..5")
    for shop in shops:
        if int(shop.get("comments") or 0) != root_counts[shop["id"]]:
            raise ValueError(f"shop {shop['id']} comments must count depth-0 reviews only")
    return dict(depth_counts), sum(root_counts.values())


def _read_list(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, list):
        raise TypeError(f"Expected JSON list: {path}")
    return value


def _validate_field_lengths(
    identity: str,
    record: dict[str, Any],
    field_limits: dict[str, int],
) -> None:
    for field, maximum in field_limits.items():
        value = record.get(field)
        if value is not None and len(str(value)) > maximum:
            raise ValueError(
                f"{identity} {field} has {len(str(value))} characters; database limit is {maximum}"
            )


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
