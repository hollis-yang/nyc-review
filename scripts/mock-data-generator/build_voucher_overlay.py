#!/usr/bin/env python3
"""Build a non-destructive voucher coverage overlay for an existing dataset.

The full dataset import intentionally replaces user-scoped development data. This
overlay only changes generated vouchers for the dataset's current dataVersion, so
it is suitable when shops, reviews, users, favorites, and orders must be preserved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any, Iterable, Sequence

from generate import generate_vouchers
from import_bundle import (
    _mysql_datetime,
    _resp_command,
    _sql_literal,
    _write_bytes_atomic,
    _write_text_atomic,
)

DEFAULT_STANDARD_PERCENT = 60.0
DEFAULT_SECKILL_PERCENT = 30.0
FIXED_TIME = "2026-08-30 12:00:00"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _percentage_count(total: int, percent: float) -> int:
    return int(total * percent / 100.0 + 0.5)


def _default_voucher_id_base(data_version: str) -> int:
    # A stable, high range keeps overlay IDs away from generated IDs while
    # remaining below JavaScript's exact-integer boundary.
    bucket = int(hashlib.sha256(data_version.encode("utf-8")).hexdigest()[:8], 16) % 100_000
    return 70_000_000_000 + bucket * 100_000


def _upsert_statements(
    table: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    update_columns: Sequence[str],
    *,
    chunk_size: int = 500,
) -> list[str]:
    materialized = list(rows)
    quoted_columns = ", ".join(f"`{column}`" for column in columns)
    updates = ", ".join(
        f"`{column}` = VALUES(`{column}`)" for column in update_columns
    )
    statements: list[str] = []
    for offset in range(0, len(materialized), chunk_size):
        chunk = materialized[offset : offset + chunk_size]
        values = ",\n".join(
            "(" + ", ".join(_sql_literal(value) for value in row) + ")"
            for row in chunk
        )
        statements.append(
            f"INSERT INTO `{table}` ({quoted_columns}) VALUES\n{values}\n"
            f"ON DUPLICATE KEY UPDATE {updates};"
        )
    return statements


def _remap_voucher_ids(
    vouchers: list[dict[str, Any]],
    seckill: list[dict[str, Any]],
    voucher_id_base: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    id_map: dict[int, int] = {}
    remapped_vouchers: list[dict[str, Any]] = []
    for offset, voucher in enumerate(vouchers, start=1):
        new_id = voucher_id_base + offset
        id_map[voucher["id"]] = new_id
        remapped_vouchers.append({**voucher, "id": new_id})
    return remapped_vouchers, [
        {**item, "voucherId": id_map[item["voucherId"]]}
        for item in seckill
    ]


def build_overlay(
    dataset: Path,
    output: Path,
    standard_percent: float = DEFAULT_STANDARD_PERCENT,
    seckill_percent: float = DEFAULT_SECKILL_PERCENT,
    voucher_id_base: int | None = None,
) -> dict[str, Any]:
    if (
        standard_percent < 0
        or seckill_percent < 0
        or standard_percent + seckill_percent > 100
    ):
        raise ValueError("voucher percentages must be non-negative and total no more than 100")

    shops = _read_json(dataset / "shops.json")
    manifest = _read_json(dataset / "manifest.json")
    previous_vouchers = _read_json(dataset / "vouchers.json")
    if not shops:
        raise ValueError("shops.json must contain at least one shop")
    data_versions = {shop.get("dataVersion") for shop in shops}
    if len(data_versions) != 1 or None in data_versions:
        raise ValueError("shops.json must contain exactly one non-null dataVersion")
    data_version = next(iter(data_versions))
    if manifest.get("dataVersion") != data_version:
        raise ValueError("manifest dataVersion does not match shops.json")

    standard_count = _percentage_count(len(shops), standard_percent)
    seckill_count = _percentage_count(len(shops), seckill_percent)
    if standard_count + seckill_count > len(shops):
        raise ValueError("rounded voucher counts exceed the shop count")

    seed = manifest.get("seed", 20260817)
    rng = random.Random(f"voucher-overlay-v2:{seed}:{data_version}")
    vouchers, seckill = generate_vouchers(rng, standard_count, seckill_count, shops)
    resolved_id_base = voucher_id_base or _default_voucher_id_base(data_version)
    if resolved_id_base < 1_000_000:
        raise ValueError("voucher-id-base must be at least 1000000")
    vouchers, seckill = _remap_voucher_ids(vouchers, seckill, resolved_id_base)

    standard_shop_ids = {item["shopId"] for item in vouchers if item["type"] == 0}
    voucher_by_id = {item["id"]: item for item in vouchers}
    seckill_shop_ids = {voucher_by_id[item["voucherId"]]["shopId"] for item in seckill}
    if standard_shop_ids & seckill_shop_ids:
        raise AssertionError("standard and seckill shop assignments overlap")

    sql_lines = [
        "-- NYC_REVIEW_VOUCHER_COVERAGE_OVERLAY_V1",
        "-- Non-destructive: preserves shops, reviews, users, orders, favorites, and itineraries.",
        "-- Pause new seckill traffic while applying this SQL and the matching Redis RESP file.",
        "SET NAMES utf8mb4;",
        "SET @NYC_REVIEW_OLD_TIME_ZONE = @@SESSION.time_zone;",
        "SET SESSION time_zone = '+00:00';",
        "START TRANSACTION;",
        "CREATE TEMPORARY TABLE `tmp_voucher_overlay_guard` (",
        f"  `shop_count` INT NOT NULL CHECK (`shop_count` = {len(shops)})",
        ");",
        "INSERT INTO `tmp_voucher_overlay_guard` (`shop_count`)",
        f"SELECT COUNT(*) FROM `tb_shop` WHERE `data_version` = {_sql_literal(data_version)};",
        "DROP TEMPORARY TABLE `tmp_voucher_overlay_guard`;",
        "UPDATE `tb_voucher` SET `status` = 2, `update_time` = CURRENT_TIMESTAMP",
        f"WHERE `source_type` = 'SYNTHETIC' AND `data_version` = {_sql_literal(data_version)};",
    ]
    voucher_columns = (
        "id", "shop_id", "title", "sub_title", "rules", "pay_value", "actual_value",
        "type", "status", "valid_days", "source_type", "data_version", "create_time", "update_time",
    )
    sql_lines.extend(
        _upsert_statements(
            "tb_voucher",
            voucher_columns,
            (
                (
                    item["id"], item["shopId"], item["title"], item["subTitle"], item["rules"],
                    item["payValueCents"], item["actualValueCents"], item["type"], 1, item["validDays"],
                    "SYNTHETIC", data_version, FIXED_TIME, FIXED_TIME,
                )
                for item in vouchers
            ),
            (
                "shop_id", "title", "sub_title", "rules", "pay_value", "actual_value",
                "type", "status", "valid_days", "source_type", "data_version", "update_time",
            ),
        )
    )
    sql_lines.extend(
        _upsert_statements(
            "tb_seckill_voucher",
            ("voucher_id", "stock", "create_time", "begin_time", "end_time", "update_time"),
            (
                (
                    item["voucherId"], item["stock"], FIXED_TIME,
                    _mysql_datetime(item["beginTime"]), _mysql_datetime(item["endTime"]), FIXED_TIME,
                )
                for item in seckill
            ),
            # Preserve remaining stock when the same overlay is applied again.
            ("begin_time", "end_time", "update_time"),
        )
    )
    sql_lines.extend(["COMMIT;", "SET SESSION time_zone = @NYC_REVIEW_OLD_TIME_ZONE;", ""])
    sql_path = output / "voucher_coverage_overlay.sql"
    _write_text_atomic(sql_path, "\n".join(sql_lines))

    old_seckill_ids = sorted(
        item["id"] for item in previous_vouchers if item.get("type") == 1
    )
    redis_commands = [
        *(_resp_command("DEL", f"seckill:stock:{voucher_id}") for voucher_id in old_seckill_ids),
        *(
            _resp_command("SETNX", f"seckill:stock:{item['voucherId']}", item["stock"])
            for item in seckill
        ),
    ]
    redis_path = output / "voucher_coverage_redis.resp"
    _write_bytes_atomic(redis_path, b"".join(redis_commands))

    selected_ids = sorted(standard_shop_ids | seckill_shop_ids)
    report = {
        "status": "ok",
        "dataVersion": data_version,
        "datasetSha256": manifest.get("datasetSha256"),
        "shops": len(shops),
        "standardVoucherShops": len(standard_shop_ids),
        "seckillVoucherShops": len(seckill_shop_ids),
        "voucherCoveredShops": len(selected_ids),
        "uncoveredShops": len(shops) - len(selected_ids),
        "standardCoveragePercent": round(len(standard_shop_ids) * 100 / len(shops), 2),
        "seckillCoveragePercent": round(len(seckill_shop_ids) * 100 / len(shops), 2),
        "totalCoveragePercent": round(len(selected_ids) * 100 / len(shops), 2),
        "assignmentOverlap": len(standard_shop_ids & seckill_shop_ids),
        "voucherIdBase": resolved_id_base,
        "coveredShopIdsSha256": hashlib.sha256(
            json.dumps(selected_ids, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "sql": str(sql_path.resolve()),
        "redis": str(redis_path.resolve()),
    }
    _write_text_atomic(
        output / "voucher_coverage_report.json",
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--standard-percent", type=float, default=DEFAULT_STANDARD_PERCENT)
    parser.add_argument("--seckill-percent", type=float, default=DEFAULT_SECKILL_PERCENT)
    parser.add_argument("--voucher-id-base", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = args.dataset.resolve()
    output = (args.output or dataset).resolve()
    report = build_overlay(
        dataset,
        output,
        args.standard_percent,
        args.seckill_percent,
        args.voucher_id_base,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
