from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .images import ImageMatcher, build_image_manifest
from .merge import FieldResolver
from .providers import FsqOsProvider, NycDohmhProvider, OfficialSiteProvider, OsmProvider
from .schemas import FieldObservation
from .snapshots import dataset_sha256, load_json, sha256_file, write_json_atomic

GENERATED_PROVIDER = "HMDP_GENERATED"
REAL_PROVIDERS = {"OPENSTREETMAP", "OFFICIAL_SITE", "FSQ_OS_PLACES", "NYC_DOHMH"}
PHASE_CONFIG = {
    "p10-p11": {
        "pipelineVersion": "p10-p11-v2",
        "dataGeneration": "v3",
        "profile": "p10-p11",
    },
    "p11-5": {
        "pipelineVersion": "p11-5-v1",
        "dataGeneration": "v4",
        "profile": "p11-5",
    },
}
BASE_DATASET_FILES = (
    "shop_types.json", "shop_subcategories.json", "shops.json", "shop_images.json",
    "shop_business_hours.json", "users.json", "shop_reviews.json", "blogs.json",
    "blog_comments.json", "follows.json", "vouchers.json", "seckill_vouchers.json",
)


def enrich_bundle(
    bundle: Path,
    output: Path,
    osm_snapshot_path: Path,
    *,
    dohmh_snapshot_path: Path | None = None,
    fsq_snapshot_path: Path | None = None,
    official_site_snapshot_path: Path | None = None,
    merchant_image_snapshot_path: Path | None = None,
    official_site_image_snapshot_path: Path | None = None,
    pilot_per_type: int | None = None,
    phase: str = "p10-p11",
) -> dict[str, Any]:
    if phase not in PHASE_CONFIG:
        raise ValueError(f"Unsupported enrichment phase: {phase}")
    phase_config = PHASE_CONFIG[phase]
    pipeline_version = str(phase_config["pipelineVersion"])
    datasets = {filename: load_json(bundle / filename, default=[]) for filename in BASE_DATASET_FILES}
    if pilot_per_type:
        datasets = _pilot_subset(datasets, pilot_per_type)
    shops = datasets["shops.json"]
    osm_snapshot = load_json(osm_snapshot_path, default={})
    dohmh_snapshot = load_json(dohmh_snapshot_path, default={"records": []})
    fsq_snapshot = load_json(fsq_snapshot_path, default={"records": []})
    official_snapshot = load_json(official_site_snapshot_path, default={"records": []})
    merchant_images = load_json(merchant_image_snapshot_path, default={"records": []})
    official_site_images = load_json(official_site_image_snapshot_path, default={"records": []})
    combined_merchant_images = {
        "records": [
            *(merchant_images.get("records") or []),
            *(official_site_images.get("records") or []),
        ],
    }

    provider_results = [
        OsmProvider().collect(shops, osm_snapshot),
        NycDohmhProvider().collect(shops, dohmh_snapshot),
        FsqOsProvider().collect(shops, fsq_snapshot),
        OfficialSiteProvider().collect(shops, official_snapshot),
    ]
    matches = [match.as_dict() for result in provider_results for match in result.matches]
    observations = [item.as_dict() for result in provider_results for item in result.observations]
    observations.extend(_generated_observations(shops))
    observations = _deduplicate_observations(observations)

    source_hashes = [sha256_file(osm_snapshot_path)]
    for optional_path in (
        dohmh_snapshot_path, fsq_snapshot_path, official_site_snapshot_path,
        merchant_image_snapshot_path, official_site_image_snapshot_path,
    ):
        if optional_path is not None:
            source_hashes.append(sha256_file(optional_path))
    base_manifest = load_json(bundle / "manifest.json", default={})
    enrichment_version_sha256 = hashlib.sha256(
        (pipeline_version + str(base_manifest.get("datasetSha256")) + "".join(source_hashes)).encode()
    ).hexdigest()
    data_version = (
        f"nyc-real-{phase_config['dataGeneration']}-"
        f"{enrichment_version_sha256[:8]}-m20260824"
    )

    resolver = FieldResolver(observations)
    old_hours_by_shop: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in datasets["shop_business_hours.json"]:
        old_hours_by_shop[int(row["shopId"])].append(row)
    resolved_shops: list[dict[str, Any]] = []
    resolved_hours: list[dict[str, Any]] = []
    resolved_provider_maps: dict[int, dict[str, str]] = {}
    for shop in shops:
        result = resolver.resolve(shop)
        resolved = result.shop
        resolved["dataVersion"] = data_version
        resolved_shops.append(resolved)
        resolved_hours.extend(result.hours or old_hours_by_shop[int(shop["id"])])
        resolved_provider_maps[int(shop["id"])] = result.resolved_providers
        if result.resolved_providers.get("avgPriceCents") in REAL_PROVIDERS:
            resolved["syntheticFields"] = [
                field for field in resolved.get("syntheticFields") or []
                if field != "avgPriceCents"
            ]

    assigned_images, image_credits = ImageMatcher().assign(
        resolved_shops, datasets["shop_images.json"], combined_merchant_images, data_version,
    )
    images_by_shop: dict[int, list[str]] = defaultdict(list)
    for image in assigned_images:
        images_by_shop[int(image["shopId"])].append(str(image["url"]))
    merchant_image_shops = {
        int(image["shopId"]) for image in assigned_images if image["matchType"] != "CATEGORY_FALLBACK"
    }
    for shop in resolved_shops:
        shop["images"] = ",".join(images_by_shop.get(int(shop["id"]), []))
        if int(shop["id"]) in merchant_image_shops:
            shop["syntheticFields"] = [field for field in shop.get("syntheticFields") or [] if field != "images"]

    datasets["shops.json"] = resolved_shops
    datasets["shop_business_hours.json"] = resolved_hours
    datasets["shop_images.json"] = assigned_images
    datasets["shop_source_matches.json"] = sorted(matches, key=lambda item: (item["shopId"], item["provider"], item["externalId"]))
    datasets["shop_field_observations.json"] = sorted(observations, key=lambda item: (item["shopId"], item["fieldName"], -item["sourcePriority"], item["provider"]))
    datasets["image_credits.json"] = image_credits
    _replace_data_version(datasets, data_version)

    output.mkdir(parents=True, exist_ok=True)
    for filename, payload in datasets.items():
        write_json_atomic(output / filename, payload)
    dataset_hash, dataset_files = dataset_sha256(output, list(datasets))

    profile_prefix = str(phase_config["profile"])
    profile = f"{profile_prefix}-pilot" if pilot_per_type else f"{profile_prefix}-full"
    import_bundle = _build_import_bundle(output, datasets, base_manifest, dataset_hash, profile)
    report = _report(
        resolved_shops, resolved_provider_maps, assigned_images, observations,
        data_version, dataset_hash, phase,
    )
    write_json_atomic(output / "enrichment_report.json", report)
    source_counts = Counter(str(shop.get("sourceType") or "UNKNOWN") for shop in resolved_shops)
    depth_counts = Counter(str(review.get("depth", 0)) for review in datasets["shop_reviews.json"])
    manifest = {
        "dataVersion": data_version,
        "merchantIdentityMode": "REAL_ONLY",
        "profile": profile,
        "seed": int(base_manifest.get("seed") or 20260817),
        "generatedAt": "deterministic-output",
        "timezone": "America/New_York",
        "currency": "USD",
        "datasetSha256": dataset_hash,
        "counts": {filename.removesuffix(".json"): len(payload) for filename, payload in datasets.items()},
        "provenance": {
            **(base_manifest.get("provenance") or {}),
            "merchantIdentityMode": "REAL_ONLY",
            "mockShops": 0,
            "realShops": len(resolved_shops),
            "publicSourceBackedShops": len(resolved_shops),
            "sourceCounts": dict(sorted(source_counts.items())),
            "syntheticReviews": len(datasets["shop_reviews.json"]),
            "syntheticReviewRoots": depth_counts.get("0", 0),
            "syntheticBlogs": len(datasets["blogs.json"]),
            "syntheticBlogComments": len(datasets["blog_comments.json"]),
            "syntheticVouchers": len(datasets["vouchers.json"]),
            "reviewDepthCounts": dict(sorted(depth_counts.items())),
            "illustrativeImages": sum(1 for image in assigned_images if image["matchType"] == "CATEGORY_FALLBACK"),
            "enrichmentProviders": sorted({item["provider"] for item in matches}),
            "enrichmentPipelineVersion": pipeline_version,
            "enrichmentVersionSha256": enrichment_version_sha256,
            "sourceMatches": len(matches),
            "fieldObservations": len(observations),
            "merchantSpecificImages": sum(1 for image in assigned_images if image["matchType"] != "CATEGORY_FALLBACK"),
            "sourceSnapshots": _source_manifests(
                osm_snapshot_path, dohmh_snapshot_path, fsq_snapshot_path,
                official_site_snapshot_path, merchant_image_snapshot_path,
                official_site_image_snapshot_path,
            ),
        },
        "files": {
            **dataset_files,
            "enrichment_report.json": {"sha256": sha256_file(output / "enrichment_report.json")},
            "mysql_import.sql": {"sha256": sha256_file(output / "mysql_import.sql")},
            "redis_seed.resp": {"sha256": sha256_file(output / "redis_seed.resp")},
            "import_manifest.json": {"sha256": sha256_file(output / "import_manifest.json")},
        },
        "importBundle": import_bundle,
    }
    write_json_atomic(output / "manifest.json", manifest)
    return manifest


def _generated_observations(shops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for shop in shops:
        values = {
            "rating": (shop.get("score") / 10) if shop.get("score") is not None else None,
            "ratingCount": shop.get("comments"),
            "priceLevel": shop.get("priceLevel"),
            "priceRangeText": "$" * int(shop.get("priceLevel") or 0) or None,
        }
        for field, value in values.items():
            if value is None:
                continue
            result.append(FieldObservation(
                int(shop["id"]), field, value, GENERATED_PROVIDER, None,
                "2026-08-24T00:00:00Z", None, 1.0, 10, "p8-generated-v1",
            ).as_dict())
    return result


def _deduplicate_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Match the database observation uniqueness contract before SQL generation.

    OSM commonly publishes the same URL in both ``website`` and
    ``contact:website``. Both normalize to the same field and content hash, so
    retaining both would violate ``uk_shop_field_observation``. Keep the
    strongest and newest deterministic candidate for each database key.
    """
    selected: dict[tuple[int, str, str, str], dict[str, Any]] = {}
    for observation in observations:
        key = (
            int(observation["shopId"]),
            str(observation["fieldName"]),
            str(observation["provider"]),
            str(observation["contentSha256"]),
        )
        rank = (
            int(observation.get("sourcePriority") or 0),
            float(observation.get("matchScore") or 0),
            str(observation.get("observedAt") or ""),
            str(observation.get("snapshotVersion") or ""),
            str(observation.get("externalId") or ""),
        )
        incumbent = selected.get(key)
        if incumbent is None:
            selected[key] = observation
            continue
        incumbent_rank = (
            int(incumbent.get("sourcePriority") or 0),
            float(incumbent.get("matchScore") or 0),
            str(incumbent.get("observedAt") or ""),
            str(incumbent.get("snapshotVersion") or ""),
            str(incumbent.get("externalId") or ""),
        )
        if rank > incumbent_rank:
            selected[key] = observation
    return list(selected.values())


def _pilot_subset(datasets: dict[str, list[dict[str, Any]]], per_type: int) -> dict[str, list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    for type_id in range(1, 7):
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for shop in datasets["shops.json"]:
            if int(shop["typeId"]) == type_id:
                buckets[str(shop.get("borough"))].append(shop)
        for values in buckets.values():
            values.sort(key=lambda item: int(item["id"]))
        boroughs = sorted(buckets)
        while len([item for item in selected if int(item["typeId"]) == type_id]) < per_type:
            progressed = False
            for borough in boroughs:
                if buckets[borough]:
                    selected.append(buckets[borough].pop(0))
                    progressed = True
                    if len([item for item in selected if int(item["typeId"]) == type_id]) >= per_type:
                        break
            if not progressed:
                raise ValueError(f"Type {type_id} has fewer than {per_type} shops")
    shop_ids = {int(item["id"]) for item in selected}
    result = dict(datasets)
    result["shops.json"] = selected
    for filename in ("shop_images.json", "shop_business_hours.json", "shop_reviews.json", "blogs.json", "vouchers.json"):
        result[filename] = [item for item in datasets[filename] if int(item["shopId"]) in shop_ids]
    blog_ids = {int(item["id"]) for item in result["blogs.json"]}
    result["blog_comments.json"] = [item for item in datasets["blog_comments.json"] if int(item["blogId"]) in blog_ids]
    voucher_ids = {int(item["id"]) for item in result["vouchers.json"]}
    result["seckill_vouchers.json"] = [item for item in datasets["seckill_vouchers.json"] if int(item["voucherId"]) in voucher_ids]
    return result


def _replace_data_version(datasets: dict[str, list[dict[str, Any]]], data_version: str) -> None:
    for rows in datasets.values():
        for row in rows:
            if "dataVersion" in row:
                row["dataVersion"] = data_version


def _build_import_bundle(
    output: Path,
    datasets: dict[str, list[dict[str, Any]]],
    base_manifest: dict[str, Any],
    dataset_hash: str,
    profile: str,
) -> dict[str, Any]:
    module_path = Path(__file__).resolve().parents[1] / "mock-data-generator"
    sys.path.insert(0, str(module_path))
    try:
        from import_bundle import build_import_bundle
        return build_import_bundle(
            output, datasets, profile, int(base_manifest.get("seed") or 20260817), dataset_hash,
        )
    finally:
        sys.path.remove(str(module_path))


def _report(
    shops: list[dict[str, Any]],
    providers: dict[int, dict[str, str]],
    images: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    data_version: str,
    dataset_hash: str,
    phase: str,
) -> dict[str, Any]:
    total = len(shops)
    real_fields = defaultdict(set)
    for observation in observations:
        if observation["provider"] in REAL_PROVIDERS:
            real_fields[observation["fieldName"]].add(int(observation["shopId"]))
    merchant_images = {int(image["shopId"]) for image in images if image["matchType"] != "CATEGORY_FALLBACK"}
    fields = {
        "businessHours": real_fields["businessHours"] | real_fields["openingHours"],
        "phone": real_fields["phone"],
        "website": real_fields["website"],
        "phoneOrWebsite": real_fields["phone"] | real_fields["website"],
        "reservationUrl": real_fields["reservationUrl"],
        "operatingStatus": real_fields["businessStatus"],
        "rating": real_fields["rating"],
        "price": real_fields["priceLevel"] | real_fields["priceRangeText"],
        "avgPrice": real_fields["avgPriceCents"],
        "merchantSpecificImage": merchant_images,
    }
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    by_borough: dict[str, Counter[str]] = defaultdict(Counter)
    for shop in shops:
        shop_id = int(shop["id"])
        for field, ids in fields.items():
            if shop_id in ids:
                by_category[str(shop["typeId"])][field] += 1
                by_borough[str(shop["borough"])][field] += 1
        by_category[str(shop["typeId"])]["shops"] += 1
        by_borough[str(shop["borough"])]["shops"] += 1
    coverage = {
        field: {"count": len(ids), "percentage": round(len(ids) * 100 / total, 2) if total else 0}
        for field, ids in fields.items()
    }
    display_count = len({int(image["shopId"]) for image in images})
    quality_gates = {
        "displayImageCoverage100Pct": display_count == total,
        "merchantSpecificImageCoverageAtLeast30Pct": coverage["merchantSpecificImage"]["percentage"] >= 30,
        "externalRatingCoverageNonZero": coverage["rating"]["count"] > 0,
        "externalPriceCoverageNonZero": coverage["price"]["count"] > 0,
        "phoneCoverageAboveP9Baseline": coverage["phone"]["count"] > 3238,
        "hoursCoverageAboveP9Baseline": coverage["businessHours"]["count"] > 2759,
        "reservationUrlCoverageNonZero": coverage["reservationUrl"]["count"] > 0,
    }
    if phase == "p11-5":
        quality_gates.update({
            "merchantSpecificImageCoverageAboveP11Baseline": (
                coverage["merchantSpecificImage"]["count"] > 1772
            ),
            "externalPriceCoverageAboveP11Baseline": coverage["price"]["count"] > 152,
            "officialMenuDerivedAvgPriceNonZero": coverage["avgPrice"]["count"] > 0,
        })
    return {
        "dataVersion": data_version,
        "datasetSha256": dataset_hash,
        "shops": total,
        "coverage": coverage,
        "displayFallbackCoverage": {"count": display_count, "percentage": round(display_count * 100 / total, 2) if total else 0},
        "qualityGates": quality_gates,
        "qualityGateStatus": "passed" if all(quality_gates.values()) else "failed",
        "imageManifest": build_image_manifest(images),
        "byCategory": {key: dict(value) for key, value in sorted(by_category.items())},
        "byBorough": {key: dict(value) for key, value in sorted(by_borough.items())},
        "providerResolutionCounts": dict(sorted(Counter(provider for mapping in providers.values() for provider in mapping.values()).items())),
        "notes": [
            "Coverage counts only externally observed fields; deterministic platform ratings and price estimates are excluded.",
            "Low match scores remain internal and are never rendered as confidence or source labels in the product UI.",
        ],
    }


def _source_manifests(*paths: Path | None) -> list[dict[str, Any]]:
    result = []
    for path in paths:
        if path is None:
            continue
        payload = load_json(path, default={})
        metadata = payload.get("metadata") or {}
        result.append({
            "datasetId": metadata.get("datasetId") or path.stem,
            "version": metadata.get("datasetVersion"),
            "fetchedAt": metadata.get("fetchedAt"),
            "sha256": sha256_file(path),
        })
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a versioned real-only enrichment bundle")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--osm", type=Path, required=True)
    parser.add_argument("--dohmh", type=Path)
    parser.add_argument("--fsq-os", type=Path)
    parser.add_argument("--official-sites", type=Path)
    parser.add_argument("--merchant-images", type=Path)
    parser.add_argument("--official-site-images", type=Path)
    parser.add_argument("--pilot-per-type", type=int)
    parser.add_argument("--phase", choices=sorted(PHASE_CONFIG), default="p10-p11")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = enrich_bundle(
        args.bundle.resolve(), args.output.resolve(), args.osm.resolve(),
        dohmh_snapshot_path=args.dohmh.resolve() if args.dohmh else None,
        fsq_snapshot_path=args.fsq_os.resolve() if args.fsq_os else None,
        official_site_snapshot_path=args.official_sites.resolve() if args.official_sites else None,
        merchant_image_snapshot_path=args.merchant_images.resolve() if args.merchant_images else None,
        official_site_image_snapshot_path=args.official_site_images.resolve() if args.official_site_images else None,
        pilot_per_type=args.pilot_per_type,
        phase=args.phase,
    )
    print(json.dumps({
        "status": "ok", "dataVersion": manifest["dataVersion"],
        "datasetSha256": manifest["datasetSha256"], "counts": manifest["counts"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
