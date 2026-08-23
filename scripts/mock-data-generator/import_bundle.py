"""Build deterministic MySQL and Redis import artifacts from generated NYC data."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

FIXED_TIME = "2026-08-17 12:00:00"
SQL_MARKER = "NYC_IMPORT_BUNDLE_V1"
LEGACY_ARCHIVE_KEY = "initial-hangzhou"
LEGACY_TABLES = (
    "tb_shop_type",
    "tb_shop",
    "tb_user",
    "tb_user_info",
    "tb_blog",
    "tb_blog_comments",
    "tb_follow",
    "tb_voucher",
    "tb_seckill_voucher",
    "tb_voucher_order",
    "tb_sign",
    "tb_shop_review",
)
CATEGORY_ICONS = {
    1: "/types/nyc-dining.svg",
    2: "/types/nyc-cafe.svg",
    3: "/types/nyc-nightlife.svg",
    4: "/types/nyc-entertainment.svg",
    5: "/types/nyc-wellness.svg",
    6: "/types/nyc-beauty.svg",
}
LEGACY_COLUMN_MAP = {
    # Keep the archive import compatible with a legacy_hangzhou_tb_shop table
    # created before later NYC/provenance columns were added to tb_shop.
    "tb_shop": (
        "id", "name", "type_id", "images", "area", "address", "x", "y",
        "avg_price", "sold", "comments", "score", "open_hours", "create_time", "update_time",
    ),
}


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


def _mysql_datetime(value: str | None) -> str | None:
    if value is None:
        return None
    return value[:19].replace("T", " ")


def _insert_statements(
    table: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    *,
    chunk_size: int = 500,
) -> list[str]:
    materialized = list(rows)
    if not materialized:
        return []
    quoted_columns = ", ".join(f"`{column}`" for column in columns)
    statements: list[str] = []
    for offset in range(0, len(materialized), chunk_size):
        chunk = materialized[offset : offset + chunk_size]
        values = ",\n".join(
            "(" + ", ".join(_sql_literal(value) for value in row) + ")"
            for row in chunk
        )
        statements.append(f"INSERT INTO `{table}` ({quoted_columns}) VALUES\n{values};")
    return statements


def _first_open_hours(shop_id: int, hours: list[dict[str, Any]]) -> str | None:
    for item in hours:
        if item["shopId"] == shop_id and not item["closed"]:
            suffix = "+1" if item.get("closesNextDay") else ""
            return f"{item['openTime']}-{item['closeTime']}{suffix}"
    return None


def build_mysql_sql(
    datasets: dict[str, list[dict[str, Any]]],
    profile: str,
    seed: int,
    dataset_sha256: str,
) -> str:
    shop_types = datasets["shop_types.json"]
    subcategories = datasets["shop_subcategories.json"]
    shops = datasets["shops.json"]
    hours = datasets["shop_business_hours.json"]
    users = datasets["users.json"]
    reviews = datasets["shop_reviews.json"]
    blogs = datasets["blogs.json"]
    comments = datasets["blog_comments.json"]
    follows = datasets["follows.json"]
    vouchers = datasets["vouchers.json"]
    seckill = datasets["seckill_vouchers.json"]

    lines = [
        f"-- {SQL_MARKER}",
        "-- HMDP content is synthetic; some establishment identity fields may come from NYC Open Data.",
        "-- Run only after p3_nyc_compatibility.sql, p4_nyc_domain.sql, and p8_p6_data_provenance.sql.",
        "-- Stop the application before importing. The initial active dataset is archived exactly once.",
        "SET NAMES utf8mb4;",
        "SET @HMDP_OLD_TIME_ZONE = @@SESSION.time_zone;",
        "SET SESSION time_zone = '+00:00';",
        "",
        "CREATE TABLE IF NOT EXISTS `tb_legacy_archive_state` (",
        "  `archive_key` VARCHAR(64) NOT NULL,",
        "  `archived_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,",
        "  `source_note` VARCHAR(255) NOT NULL,",
        "  PRIMARY KEY (`archive_key`)",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;",
        "",
    ]
    for table in LEGACY_TABLES:
        lines.append(f"CREATE TABLE IF NOT EXISTS `legacy_hangzhou_{table}` LIKE `{table}`;")
    lines.extend(["", "START TRANSACTION;"])
    for table in LEGACY_TABLES:
        columns = LEGACY_COLUMN_MAP.get(table)
        if columns:
            quoted = ", ".join(f"`{column}`" for column in columns)
            lines.append(
                f"INSERT INTO `legacy_hangzhou_{table}` ({quoted}) SELECT {quoted} FROM `{table}` "
                f"WHERE NOT EXISTS (SELECT 1 FROM `tb_legacy_archive_state` WHERE `archive_key` = '{LEGACY_ARCHIVE_KEY}');"
            )
        else:
            lines.append(
                f"INSERT INTO `legacy_hangzhou_{table}` SELECT * FROM `{table}` "
                f"WHERE NOT EXISTS (SELECT 1 FROM `tb_legacy_archive_state` WHERE `archive_key` = '{LEGACY_ARCHIVE_KEY}');"
            )
    lines.extend(
        [
            "INSERT IGNORE INTO `tb_legacy_archive_state` (`archive_key`, `source_note`) ",
            f"VALUES ('{LEGACY_ARCHIVE_KEY}', 'Snapshot before the first NYC mock import');",
            "COMMIT;",
            "",
            "SET @OLD_FOREIGN_KEY_CHECKS = @@FOREIGN_KEY_CHECKS;",
            "SET FOREIGN_KEY_CHECKS = 0;",
            "START TRANSACTION;",
        ]
    )
    for table in (
        "tb_voucher_order",
        "tb_seckill_voucher",
        "tb_voucher",
        "tb_blog_comments",
        "tb_shop_review",
        "tb_blog",
        "tb_follow",
        "tb_sign",
        "tb_user_info",
        "tb_user",
        "tb_shop_business_hours",
        "tb_shop_tag",
        "tb_shop",
        "tb_shop_subcategory",
        "tb_shop_type",
    ):
        lines.append(f"DELETE FROM `{table}`;")
    lines.extend(["UPDATE `tb_data_import` SET `active` = 0;", ""])

    statements: list[str] = []
    statements += _insert_statements(
        "tb_shop_type",
        ("id", "name", "slug", "icon", "sort", "create_time", "update_time"),
        (
            (
                item["id"],
                item["name"],
                item["slug"],
                CATEGORY_ICONS[item["id"]],
                item["sort"],
                FIXED_TIME,
                FIXED_TIME,
            )
            for item in shop_types
        ),
    )
    statements += _insert_statements(
        "tb_shop_subcategory",
        ("id", "type_id", "name", "slug", "create_time", "update_time"),
        ((item["id"], item["typeId"], item["name"], item["slug"], FIXED_TIME, FIXED_TIME) for item in subcategories),
    )
    statements += _insert_statements(
        "tb_shop",
        (
            "id", "name", "type_id", "subcategory_id", "images", "area", "borough", "address",
            "description", "x", "y", "avg_price", "price_level", "sold", "comments", "score",
            "open_hours", "timezone", "source_type", "external_id", "source_name", "source_url",
            "source_fetched_at", "synthetic_fields", "data_version", "create_time", "update_time",
        ),
        (
            (
                item["id"], item["name"], item["typeId"], item["subcategoryId"], item["images"],
                item["area"], item["borough"], item["address"], item["description"], item["x"], item["y"],
                item["avgPriceCents"] // 100, item["priceLevel"], item["sold"], item["comments"], item["score"],
                _first_open_hours(item["id"], hours), item["timezone"], item["sourceType"],
                item.get("externalId"), item.get("sourceName"), item.get("sourceUrl"),
                _mysql_datetime(item.get("sourceFetchedAt")),
                json.dumps(item.get("syntheticFields") or [], separators=(",", ":")), item["dataVersion"],
                FIXED_TIME, FIXED_TIME,
            )
            for item in shops
        ),
    )
    statements += _insert_statements(
        "tb_shop_tag",
        ("shop_id", "tag", "create_time"),
        ((shop["id"], tag, FIXED_TIME) for shop in shops for tag in shop["tags"]),
    )
    statements += _insert_statements(
        "tb_shop_business_hours",
        ("shop_id", "day_of_week", "closed", "open_time", "close_time", "closes_next_day", "create_time", "update_time"),
        (
            (
                item["shopId"], item["dayOfWeek"], item["closed"], item.get("openTime"), item.get("closeTime"),
                item.get("closesNextDay", False), FIXED_TIME, FIXED_TIME,
            )
            for item in hours
        ),
    )
    statements += _insert_statements(
        "tb_user",
        ("id", "phone", "password", "nick_name", "icon", "create_time", "update_time"),
        ((item["id"], item["phone"], "", item["nickName"], item["icon"], FIXED_TIME, FIXED_TIME) for item in users),
    )
    statements += _insert_statements(
        "tb_user_info",
        ("user_id", "city", "introduce", "fans", "followee", "gender", "birthday", "credits", "level", "create_time", "update_time"),
        ((item["id"], item["city"], item["introduce"], 0, 0, 0, None, 0, 0, FIXED_TIME, FIXED_TIME) for item in users),
    )
    statements += _insert_statements(
        "tb_shop_review",
        ("id", "shop_id", "user_id", "rating", "content", "images", "liked", "create_time", "update_time"),
        (
            (
                item["id"], item["shopId"], item["userId"], item["rating"], item["content"], item["images"],
                item["liked"], _mysql_datetime(item["createTime"]), _mysql_datetime(item["createTime"]),
            )
            for item in reviews
        ),
    )
    statements += _insert_statements(
        "tb_blog",
        ("id", "shop_id", "user_id", "title", "images", "content", "liked", "comments", "create_time", "update_time"),
        (
            (
                item["id"], item["shopId"], item["userId"], item["title"], item["images"], item["content"],
                item["liked"], item["comments"], _mysql_datetime(item["createTime"]), _mysql_datetime(item["createTime"]),
            )
            for item in blogs
        ),
    )
    statements += _insert_statements(
        "tb_blog_comments",
        ("id", "user_id", "blog_id", "parent_id", "answer_id", "content", "liked", "status", "create_time", "update_time"),
        (
            (
                item["id"], item["userId"], item["blogId"], item["parentId"], item["answerId"], item["content"],
                item["liked"], 0, _mysql_datetime(item["createTime"]), _mysql_datetime(item["createTime"]),
            )
            for item in comments
        ),
    )
    statements += _insert_statements(
        "tb_follow",
        ("id", "user_id", "follow_user_id", "create_time"),
        ((item["id"], item["userId"], item["followUserId"], FIXED_TIME) for item in follows),
    )
    statements += _insert_statements(
        "tb_voucher",
        ("id", "shop_id", "title", "sub_title", "rules", "pay_value", "actual_value", "type", "status", "create_time", "update_time"),
        (
            (
                item["id"], item["shopId"], item["title"], item["subTitle"], item["rules"],
                item["payValueCents"], item["actualValueCents"], item["type"], item["status"], FIXED_TIME, FIXED_TIME,
            )
            for item in vouchers
        ),
    )
    statements += _insert_statements(
        "tb_seckill_voucher",
        ("voucher_id", "stock", "create_time", "begin_time", "end_time", "update_time"),
        (
            (
                item["voucherId"], item["stock"], FIXED_TIME, _mysql_datetime(item["beginTime"]),
                _mysql_datetime(item["endTime"]), FIXED_TIME,
            )
            for item in seckill
        ),
    )
    data_version = shops[0]["dataVersion"] if shops else "nyc-mock-v2"
    statements.append(
        "INSERT INTO `tb_data_import` "
        "(`import_id`, `data_version`, `profile`, `seed`, `dataset_sha256`, `shop_count`, `active`) VALUES "
        f"({_sql_literal(dataset_sha256)}, {_sql_literal(data_version)}, {_sql_literal(profile)}, {seed}, "
        f"{_sql_literal(dataset_sha256)}, {len(shops)}, 1) "
        "ON DUPLICATE KEY UPDATE `data_version` = VALUES(`data_version`), `profile` = VALUES(`profile`), "
        "`seed` = VALUES(`seed`), `shop_count` = VALUES(`shop_count`), `active` = 1, "
        "`imported_at` = CURRENT_TIMESTAMP;"
    )
    lines.extend(statements)
    lines.extend(
        [
            "COMMIT;",
            "SET FOREIGN_KEY_CHECKS = @OLD_FOREIGN_KEY_CHECKS;",
            "SET SESSION time_zone = @HMDP_OLD_TIME_ZONE;",
            "",
            f"-- Dataset SHA-256: {dataset_sha256}",
            "",
        ]
    )
    return "\n".join(lines)


def _resp_command(*arguments: Any) -> bytes:
    encoded = [str(argument).encode("utf-8") for argument in arguments]
    parts = [f"*{len(encoded)}\r\n".encode("ascii")]
    for item in encoded:
        parts.append(f"${len(item)}\r\n".encode("ascii"))
        parts.append(item + b"\r\n")
    return b"".join(parts)


def build_redis_resp(datasets: dict[str, list[dict[str, Any]]]) -> bytes:
    shops = datasets["shops.json"]
    seckill = datasets["seckill_vouchers.json"]
    cleanup_script = """local total=0 for _,pattern in ipairs(ARGV) do local removed=0 repeat removed=0 local cursor='0' repeat local result=redis.call('SCAN',cursor,'MATCH',pattern,'COUNT',1000) cursor=result[1] local keys=result[2] if #keys>0 then redis.call('DEL',unpack(keys)) removed=removed+#keys total=total+#keys end until cursor=='0' until removed==0 end return total"""
    commands = [
        _resp_command(
            "EVAL",
            cleanup_script,
            0,
            "shop:geo:*",
            "cache:shop:*",
            "cache:shop-review:*",
            "seckill:stock:*",
            "seckill:order:*",
            "seckill:pending:*",
            "blog:liked:*",
            "follows:*",
            "feed:*",
            "sign:*",
        ),
        # Remove P2/P3 legacy Stream keys during a clean import; P4 never recreates them.
        _resp_command("DEL", "cache:shopType:list", "stream:orders", "stream:orders:dead-letter"),
    ]
    by_type: dict[int, list[dict[str, Any]]] = {}
    for shop in shops:
        by_type.setdefault(shop["typeId"], []).append(shop)
    for type_id in sorted(by_type):
        typed_shops = by_type[type_id]
        for offset in range(0, len(typed_shops), 200):
            arguments: list[Any] = ["GEOADD", f"shop:geo:{type_id}"]
            for shop in typed_shops[offset : offset + 200]:
                arguments.extend((shop["x"], shop["y"], shop["id"]))
            commands.append(_resp_command(*arguments))
    for item in sorted(seckill, key=lambda entry: entry["voucherId"]):
        commands.append(_resp_command("SET", f"seckill:stock:{item['voucherId']}", item["stock"]))
        commands.append(_resp_command("DEL", f"seckill:order:{item['voucherId']}"))
    return b"".join(commands)


def _shop_ids_sha256(shop_ids: list[int]) -> str:
    encoded = json.dumps(shop_ids, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_import_bundle(
    output: Path,
    datasets: dict[str, list[dict[str, Any]]],
    profile: str,
    seed: int,
    dataset_sha256: str,
) -> dict[str, Any]:
    sql_path = output / "mysql_import.sql"
    redis_path = output / "redis_seed.resp"
    import_manifest_path = output / "import_manifest.json"
    _write_text_atomic(sql_path, build_mysql_sql(datasets, profile, seed, dataset_sha256))
    _write_bytes_atomic(redis_path, build_redis_resp(datasets))

    shop_ids = sorted(shop["id"] for shop in datasets["shops.json"])
    source_counts: dict[str, int] = {}
    for shop in datasets["shops.json"]:
        source_type = str(shop.get("sourceType") or "UNKNOWN")
        source_counts[source_type] = source_counts.get(source_type, 0) + 1
    dataset_files = {
        filename: {"sha256": _sha256(output / filename)}
        for filename in sorted(datasets)
    }
    computed_dataset_sha256 = hashlib.sha256(
        json.dumps(dataset_files, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    if computed_dataset_sha256 != dataset_sha256:
        raise ValueError("Dataset files changed while the import bundle was being generated.")
    manifest = {
        "dataVersion": datasets["shops.json"][0]["dataVersion"] if datasets["shops.json"] else "nyc-mock-v2",
        "datasetSha256": dataset_sha256,
        "datasetFiles": dataset_files,
        "profile": profile,
        "seed": seed,
        "shopIds": shop_ids,
        "shopIdsSha256": _shop_ids_sha256(shop_ids),
        "provenance": {
            "sourceCounts": dict(sorted(source_counts.items())),
            "syntheticContent": True,
        },
        "mysql": {
            "file": sql_path.name,
            "sha256": _sha256(sql_path),
            "archivesLegacyKey": LEGACY_ARCHIVE_KEY,
        },
        "redis": {
            "file": redis_path.name,
            "sha256": _sha256(redis_path),
            "geoKeys": [f"shop:geo:{type_id}" for type_id in sorted({shop["typeId"] for shop in datasets["shops.json"]})],
            "seckillStockKeys": [f"seckill:stock:{item['voucherId']}" for item in datasets["seckill_vouchers.json"]],
        },
    }
    _write_text_atomic(
        import_manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return manifest
