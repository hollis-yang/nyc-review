#!/usr/bin/env python3
"""Build an idempotent P7 NTA assignment SQL bundle for a generated NYC dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence

from nyc_nta import (
    DEFAULT_MANIFEST,
    assign_point,
    load_snapshot,
    normalized_neighborhoods,
)

SQL_MARKER = "NYC_REVIEW_P7_NEIGHBORHOOD_IMPORT_V1"


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def _read_json(path: Path, expected_type: type) -> Any:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, expected_type):
        raise TypeError(f"Unexpected JSON value in {path}")
    return value


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


def _chunked(values: Sequence[Any], size: int = 250) -> Iterable[Sequence[Any]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _shop_ids_sha256(shop_ids: list[int]) -> str:
    payload = json.dumps(shop_ids, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_dataset_identity(
    shops: list[dict[str, Any]],
    import_manifest: dict[str, Any],
) -> tuple[str, str, str]:
    shop_ids = sorted(int(shop["id"]) for shop in shops)
    if len(shop_ids) != len(set(shop_ids)):
        raise ValueError("shops.json contains duplicate IDs")
    actual_ids_sha256 = _shop_ids_sha256(shop_ids)
    if import_manifest.get("shopIds") != shop_ids:
        raise ValueError("import_manifest.json shopIds do not match shops.json")
    if import_manifest.get("shopIdsSha256") != actual_ids_sha256:
        raise ValueError("import_manifest.json shopIdsSha256 does not match shops.json")
    versions = {str(shop.get("dataVersion")) for shop in shops if shop.get("dataVersion")}
    if len(versions) != 1:
        raise ValueError("shops.json must contain exactly one dataVersion")
    data_version = next(iter(versions))
    if import_manifest.get("dataVersion") != data_version:
        raise ValueError("import_manifest.json dataVersion does not match shops.json")
    dataset_sha256 = str(import_manifest.get("datasetSha256") or "")
    if len(dataset_sha256) != 64:
        raise ValueError("import_manifest.json is missing datasetSha256")
    return data_version, dataset_sha256, actual_ids_sha256


def assign_shops(
    shops: list[dict[str, Any]],
    neighborhoods: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    assignments: list[dict[str, Any]] = []
    for shop in sorted(shops, key=lambda item: int(item["id"])):
        longitude = float(shop["x"])
        latitude = float(shop["y"])
        assignment = assign_point(
            neighborhoods,
            longitude,
            latitude,
            str(shop.get("borough") or "") or None,
        )
        assignments.append(
            {
                "shopId": int(shop["id"]),
                "dataVersion": str(shop["dataVersion"]),
                "longitude": longitude,
                "latitude": latitude,
                "sourceArea": str(shop.get("area") or ""),
                "sourceType": str(shop.get("sourceType") or "UNKNOWN"),
                "borough": str(shop.get("borough") or ""),
                "neighborhoodCode": assignment.code,
                "neighborhoodName": assignment.name,
                "assignmentMethod": assignment.method,
            }
        )
    return assignments


def build_sql(
    shops: list[dict[str, Any]],
    neighborhoods: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    *,
    data_version: str,
    dataset_sha256: str,
    shop_ids_sha256: str,
    nta_manifest: dict[str, Any],
) -> str:
    lines = [
        f"-- {SQL_MARKER}",
        "-- Derived map data only. Apply after p9_p7_map_geospatial.sql and the matching NYC dataset import.",
        "-- Point-in-polygon assignments use the pinned official NYC 2020 NTA snapshot.",
        "-- Unmatched coordinates remain UNASSIGNED; the importer never fabricates a nearest NTA.",
        "-- tb_shop.area is intentionally preserved because Agent constraints use the legacy friendly area names.",
        "SET NAMES utf8mb4 COLLATE utf8mb4_general_ci;",
        "SET @NYC_REVIEW_OLD_TIME_ZONE = @@SESSION.time_zone;",
        "SET SESSION time_zone = '+00:00';",
        "",
        "-- Fail closed before persistent writes if this is not the exact source shop dataset.",
        "DROP TEMPORARY TABLE IF EXISTS `nyc_review_p7_expected_shop`;",
        "CREATE TEMPORARY TABLE `nyc_review_p7_expected_shop` (",
        "  `shop_id` BIGINT UNSIGNED NOT NULL PRIMARY KEY,",
        "  `type_id` BIGINT UNSIGNED NOT NULL,",
        "  `longitude` DOUBLE NOT NULL,",
        "  `latitude` DOUBLE NOT NULL,",
        "  `borough` VARCHAR(64) NOT NULL,",
        "  `area` VARCHAR(128) NOT NULL,",
        "  `source_type` VARCHAR(32) NOT NULL",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;",
    ]
    for chunk in _chunked(sorted(shops, key=lambda item: int(item["id"])), 500):
        rows = ",\n".join(
            "(" + ", ".join(
                [
                    str(int(shop["id"])),
                    str(int(shop["typeId"])),
                    str(float(shop["x"])),
                    str(float(shop["y"])),
                    _sql_literal(str(shop.get("borough") or "")),
                    _sql_literal(str(shop.get("area") or "")),
                    _sql_literal(str(shop.get("sourceType") or "UNKNOWN")),
                ]
            ) + ")"
            for shop in chunk
        )
        lines.extend(
            [
                "INSERT INTO `nyc_review_p7_expected_shop` "
                "(`shop_id`, `type_id`, `longitude`, `latitude`, `borough`, `area`, `source_type`) VALUES",
                rows + ";",
            ]
        )
    lines.extend(
        [
            "DROP TEMPORARY TABLE IF EXISTS `nyc_review_p7_dataset_guard`;",
            "CREATE TEMPORARY TABLE `nyc_review_p7_dataset_guard` (",
            "  `ok` TINYINT NOT NULL CHECK (`ok` = 1)",
            ") ENGINE=InnoDB;",
            "-- A missing or map-relevant mismatched shop inserts 0 and trips the CHECK.",
            "INSERT INTO `nyc_review_p7_dataset_guard` (`ok`)",
            "SELECT 0",
            "FROM `nyc_review_p7_expected_shop` AS expected",
            "LEFT JOIN `tb_shop` AS actual",
            "  ON actual.`id`=expected.`shop_id`",
            f" AND actual.`data_version`={_sql_literal(data_version)}",
            "WHERE actual.`id` IS NULL",
            "   OR actual.`type_id` <> expected.`type_id`",
            "   OR ABS(actual.`x` - expected.`longitude`) > 0.000000001",
            "   OR ABS(actual.`y` - expected.`latitude`) > 0.000000001",
            "   OR NOT (CAST(actual.`borough` AS BINARY) <=> CAST(expected.`borough` AS BINARY))",
            "   OR NOT (CAST(actual.`area` AS BINARY) <=> CAST(expected.`area` AS BINARY))",
            "   OR NOT (CAST(actual.`source_type` AS BINARY) <=> CAST(expected.`source_type` AS BINARY))",
            "LIMIT 1;",
            "-- An unexpected shop in the same dataVersion also trips the guard.",
            "INSERT INTO `nyc_review_p7_dataset_guard` (`ok`)",
            "SELECT 0",
            "FROM `tb_shop` AS actual",
            "LEFT JOIN `nyc_review_p7_expected_shop` AS expected ON expected.`shop_id`=actual.`id`",
            f"WHERE actual.`data_version`={_sql_literal(data_version)}",
            "  AND expected.`shop_id` IS NULL",
            "LIMIT 1;",
            "-- The P6 import audit must identify the same reproducible dataset hash.",
            "INSERT INTO `nyc_review_p7_dataset_guard` (`ok`)",
            "SELECT IF(EXISTS(",
            "  SELECT 1 FROM `tb_data_import`",
            f"  WHERE `data_version`={_sql_literal(data_version)}",
            f"    AND `dataset_sha256`={_sql_literal(dataset_sha256)}",
            f"    AND `shop_count`={len(shops)}",
            "    AND `active`=1",
            "), 1, 0);",
            "START TRANSACTION;",
            "",
        ]
    )
    fetched_at = str(nta_manifest["verifiedAt"])[:19].replace("T", " ")
    for chunk in _chunked(neighborhoods, 40):
        rows = []
        for item in chunk:
            geometry_json = json.dumps(item["geometry"], separators=(",", ":"))
            rows.append(
                "(" + ", ".join(
                    [
                        _sql_literal(item["code"]),
                        _sql_literal(item["name"]),
                        _sql_literal(item["borough"]),
                        _sql_literal(item["ntaType"]),
                        _sql_literal(item["cdtaCode"]),
                        str(item["centroidX"]),
                        str(item["centroidY"]),
                        str(item["minX"]),
                        str(item["minY"]),
                        str(item["maxX"]),
                        str(item["maxY"]),
                        f"ST_GeomFromGeoJSON({_sql_literal(geometry_json)}, 1, 4326)",
                        _sql_literal(nta_manifest["datasetId"]),
                        _sql_literal(nta_manifest["datasetVersion"]),
                        _sql_literal(nta_manifest["sourcePageUrl"]),
                        _sql_literal(nta_manifest["revisionDate"]),
                        _sql_literal(fetched_at),
                        _sql_literal(nta_manifest["sha256"]),
                        "1",
                    ]
                ) + ")"
            )
        lines.extend(
            [
                "INSERT INTO `tb_neighborhood` ",
                "(`code`, `name`, `borough`, `nta_type`, `cdta_code`, `centroid_x`, `centroid_y`, "
                "`min_x`, `min_y`, `max_x`, `max_y`, `boundary`, `source_dataset_id`, "
                "`source_version`, `source_url`, `source_revision_date`, `source_fetched_at`, "
                "`source_sha256`, `active`) VALUES",
                ",\n".join(rows),
                "ON DUPLICATE KEY UPDATE `name`=VALUES(`name`), `borough`=VALUES(`borough`), "
                "`nta_type`=VALUES(`nta_type`), `cdta_code`=VALUES(`cdta_code`), "
                "`centroid_x`=VALUES(`centroid_x`), `centroid_y`=VALUES(`centroid_y`), "
                "`min_x`=VALUES(`min_x`), `min_y`=VALUES(`min_y`), `max_x`=VALUES(`max_x`), "
                "`max_y`=VALUES(`max_y`), `boundary`=VALUES(`boundary`), "
                "`source_version`=VALUES(`source_version`), `source_url`=VALUES(`source_url`), "
                "`source_revision_date`=VALUES(`source_revision_date`), "
                "`source_fetched_at`=VALUES(`source_fetched_at`), `source_sha256`=VALUES(`source_sha256`), "
                "`active`=1;",
                "",
            ]
        )

    alias_rows = {
        (item["borough"], item["name"], item["code"], "OFFICIAL")
        for item in neighborhoods
    }
    alias_rows.update(
        (
            assignment["borough"],
            assignment["sourceArea"],
            assignment["neighborhoodCode"],
            "LEGACY_AREA",
        )
        for assignment in assignments
        if assignment["sourceArea"] and assignment["neighborhoodCode"]
    )
    sorted_aliases = sorted(alias_rows)
    for chunk in _chunked(sorted_aliases, 250):
        rows = ",\n".join(
            "(" + ", ".join(_sql_literal(value) for value in row) + ")"
            for row in chunk
        )
        lines.extend(
            [
                "INSERT INTO `tb_neighborhood_alias` "
                "(`borough`, `alias`, `neighborhood_code`, `alias_type`) VALUES",
                rows,
                "ON DUPLICATE KEY UPDATE `alias_type`=VALUES(`alias_type`);",
                "",
            ]
        )

    lines.extend(
        [
            f"DELETE FROM `tb_shop_map_location` WHERE `data_version`={_sql_literal(data_version)};",
            f"UPDATE `tb_shop` SET `legacy_area`=COALESCE(`legacy_area`, `area`), `neighborhood_code`=NULL "
            f"WHERE `data_version`={_sql_literal(data_version)};",
            "",
        ]
    )
    for chunk in _chunked(assignments, 500):
        rows = []
        for item in chunk:
            rows.append(
                "(" + ", ".join(
                    [
                        str(item["shopId"]),
                        _sql_literal(data_version),
                        "ST_GeomFromText("
                        + _sql_literal(f"POINT({item['longitude']} {item['latitude']})")
                        + ", 4326, 'axis-order=long-lat')",
                        _sql_literal(item["neighborhoodCode"]),
                        _sql_literal(item["assignmentMethod"]),
                        _sql_literal(item["sourceArea"]),
                    ]
                ) + ")"
            )
        lines.extend(
            [
                "INSERT INTO `tb_shop_map_location` "
                "(`shop_id`, `data_version`, `location`, `neighborhood_code`, `assignment_method`, `source_area`) VALUES",
                ",\n".join(rows),
                "ON DUPLICATE KEY UPDATE `location`=VALUES(`location`), "
                "`neighborhood_code`=VALUES(`neighborhood_code`), "
                "`assignment_method`=VALUES(`assignment_method`), `source_area`=VALUES(`source_area`), "
                "`assigned_at`=CURRENT_TIMESTAMP;",
                "",
            ]
        )
    lines.extend(
        [
            "UPDATE `tb_shop` AS s",
            "JOIN `tb_shop_map_location` AS ml ON ml.`shop_id`=s.`id` AND ml.`data_version`=s.`data_version`",
            "SET s.`neighborhood_code`=ml.`neighborhood_code`",
            f"WHERE s.`data_version`={_sql_literal(data_version)};",
            "",
            f"DELETE FROM `tb_neighborhood_shop_count` WHERE `data_version`={_sql_literal(data_version)};",
            "INSERT INTO `tb_neighborhood_shop_count` "
            "(`data_version`, `neighborhood_code`, `type_id`, `shop_count`, `centroid_x`, `centroid_y`) ",
            "SELECT s.`data_version`, ml.`neighborhood_code`, s.`type_id`, COUNT(*), AVG(s.`x`), AVG(s.`y`) ",
            "FROM `tb_shop` AS s JOIN `tb_shop_map_location` AS ml "
            "ON ml.`shop_id`=s.`id` AND ml.`data_version`=s.`data_version` ",
            f"WHERE s.`data_version`={_sql_literal(data_version)} AND ml.`neighborhood_code` IS NOT NULL ",
            "GROUP BY s.`data_version`, ml.`neighborhood_code`, s.`type_id`;",
            "",
            f"DELETE FROM `tb_borough_shop_count` WHERE `data_version`={_sql_literal(data_version)};",
            "INSERT INTO `tb_borough_shop_count` "
            "(`data_version`, `borough`, `type_id`, `shop_count`, `assigned_count`, "
            "`unassigned_count`, `centroid_x`, `centroid_y`, `min_x`, `min_y`, `max_x`, `max_y`) ",
            "SELECT s.`data_version`, s.`borough`, s.`type_id`, COUNT(*), "
            "SUM(ml.`neighborhood_code` IS NOT NULL), SUM(ml.`neighborhood_code` IS NULL), "
            "AVG(s.`x`), AVG(s.`y`), MIN(s.`x`), MIN(s.`y`), MAX(s.`x`), MAX(s.`y`) "
            "FROM `tb_shop` AS s "
            "JOIN `tb_shop_map_location` AS ml "
            "ON ml.`shop_id`=s.`id` AND ml.`data_version`=s.`data_version` ",
            f"WHERE s.`data_version`={_sql_literal(data_version)} ",
            "GROUP BY s.`data_version`, s.`borough`, s.`type_id`;",
            "",
            "UPDATE `tb_map_data_import` SET `active`=0;",
        ]
    )
    method_counts = Counter(item["assignmentMethod"] for item in assignments)
    assigned_count = len(assignments) - method_counts.get("UNASSIGNED", 0)
    lines.extend(
        [
            "INSERT INTO `tb_map_data_import` "
            "(`dataset_sha256`, `data_version`, `shop_ids_sha256`, `nta_source_sha256`, "
            "`nta_source_version`, `shop_count`, `assigned_count`, `unassigned_count`, "
            "`assignment_methods`, `active`) VALUES ("
            + ", ".join(
                [
                    _sql_literal(dataset_sha256),
                    _sql_literal(data_version),
                    _sql_literal(shop_ids_sha256),
                    _sql_literal(nta_manifest["sha256"]),
                    _sql_literal(nta_manifest["datasetVersion"]),
                    str(len(shops)),
                    str(assigned_count),
                    str(method_counts.get("UNASSIGNED", 0)),
                    _sql_literal(json.dumps(dict(sorted(method_counts.items())), separators=(",", ":"))),
                    "1",
                ]
            )
            + ") ON DUPLICATE KEY UPDATE `data_version`=VALUES(`data_version`), "
            "`shop_ids_sha256`=VALUES(`shop_ids_sha256`), `nta_source_sha256`=VALUES(`nta_source_sha256`), "
            "`nta_source_version`=VALUES(`nta_source_version`), `shop_count`=VALUES(`shop_count`), "
            "`assigned_count`=VALUES(`assigned_count`), `unassigned_count`=VALUES(`unassigned_count`), "
            "`assignment_methods`=VALUES(`assignment_methods`), `active`=1, "
            "`imported_at`=CURRENT_TIMESTAMP;",
            "COMMIT;",
            "DROP TEMPORARY TABLE IF EXISTS `nyc_review_p7_dataset_guard`;",
            "DROP TEMPORARY TABLE IF EXISTS `nyc_review_p7_expected_shop`;",
            "SET SESSION time_zone = @NYC_REVIEW_OLD_TIME_ZONE;",
            "",
            f"-- Dataset SHA-256: {dataset_sha256}",
            f"-- Shop IDs SHA-256: {shop_ids_sha256}",
            f"-- NTA source SHA-256: {nta_manifest['sha256']}",
            "",
        ]
    )
    return "\n".join(lines)


def build_import(
    dataset_directory: Path,
    nta_snapshot: Path,
    output: Path,
    *,
    nta_manifest_path: Path = DEFAULT_MANIFEST,
    allow_real_unassigned: bool = False,
) -> dict[str, Any]:
    shops = _read_json(dataset_directory / "shops.json", list)
    import_manifest = _read_json(dataset_directory / "import_manifest.json", dict)
    data_version, dataset_sha256, shop_ids_sha256 = validate_dataset_identity(
        shops, import_manifest
    )
    document, nta_manifest = load_snapshot(nta_snapshot, nta_manifest_path)
    neighborhoods = normalized_neighborhoods(document, nta_manifest)
    assignments = assign_shops(shops, neighborhoods)
    method_counts = Counter(item["assignmentMethod"] for item in assignments)
    unassigned = [item["shopId"] for item in assignments if item["neighborhoodCode"] is None]
    real_unassigned = [
        item["shopId"]
        for item in assignments
        if item["neighborhoodCode"] is None and item["sourceType"] != "MOCK"
    ]
    if real_unassigned and not allow_real_unassigned:
        preview = ", ".join(str(shop_id) for shop_id in real_unassigned[:20])
        raise ValueError(
            f"{len(real_unassigned)} non-mock shops could not be assigned to an NTA "
            f"(first IDs: {preview}). Review their source coordinates; do not fabricate a nearest NTA."
        )
    sql = build_sql(
        shops,
        neighborhoods,
        assignments,
        data_version=data_version,
        dataset_sha256=dataset_sha256,
        shop_ids_sha256=shop_ids_sha256,
        nta_manifest=nta_manifest,
    )
    _write_text_atomic(output, sql)
    by_source: dict[str, dict[str, int]] = {}
    for item in assignments:
        counts = by_source.setdefault(item["sourceType"], {"assigned": 0, "unassigned": 0})
        key = "assigned" if item["neighborhoodCode"] else "unassigned"
        counts[key] += 1
    report = {
        "assignmentMethods": dict(sorted(method_counts.items())),
        "coverageBySource": dict(sorted(by_source.items())),
        "dataVersion": data_version,
        "datasetSha256": dataset_sha256,
        "neighborhoods": len(neighborhoods),
        "ntaSourceSha256": nta_manifest["sha256"],
        "ntaSourceVersion": nta_manifest["datasetVersion"],
        "output": str(output),
        "shopIdsSha256": shop_ids_sha256,
        "shops": len(shops),
        "status": "ok",
        "unassignedShopIds": unassigned,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--nta-snapshot", type=Path, required=True)
    parser.add_argument("--nta-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-real-unassigned",
        action="store_true",
        help="Allow non-mock shops without an official polygon match. Default is fail closed.",
    )
    args = parser.parse_args()
    report = build_import(
        args.dataset.resolve(),
        args.nta_snapshot.resolve(),
        args.output.resolve(),
        nta_manifest_path=args.nta_manifest.resolve(),
        allow_real_unassigned=args.allow_real_unassigned,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
