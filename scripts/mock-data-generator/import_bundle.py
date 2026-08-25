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
    # P10 adds threading/provenance columns to the live review table. The
    # one-time Hangzhou archive was created from the original nine-column
    # schema, so SELECT * would fail at statement validation even after the
    # archive guard has already been written.
    "tb_shop_review": (
        "id", "shop_id", "user_id", "rating", "content", "images", "liked",
        "create_time", "update_time",
    ),
    # P10 also adds provenance fields to generated posts, comments and
    # vouchers. Select only the original columns so an archive created by an
    # earlier P6 import remains usable after the additive migration.
    "tb_blog": (
        "id", "shop_id", "user_id", "title", "images", "content", "liked",
        "comments", "create_time", "update_time",
    ),
    "tb_blog_comments": (
        "id", "user_id", "blog_id", "parent_id", "answer_id", "content", "liked",
        "status", "create_time", "update_time",
    ),
    "tb_voucher": (
        "id", "shop_id", "title", "sub_title", "rules", "pay_value", "actual_value",
        "type", "status", "create_time", "update_time",
    ),
}
P7_DERIVED_TABLES = (
    "tb_neighborhood_shop_count",
    "tb_borough_shop_count",
    "tb_shop_map_location",
)
# These optional P5/P6 tables contain user-, shop-, voucher-, or run-scoped
# state. IDs are intentionally reused by each generated bundle, so retaining
# them would attach the previous dataset's assets and memories to unrelated
# identities. Clear children before replacing their parent entities below.
DATASET_SCOPED_OPTIONAL_TABLES = (
    "tb_agent_action_audit",
    "tb_seckill_reminder",
    "tb_saved_itinerary",
    "tb_shop_favorite",
    "tb_agent_user_memory",
)


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


def _delete_optional_table(table: str) -> list[str]:
    """Clear a derived P7 table when its additive migration has been applied."""
    statement_name = "HMDP_OPTIONAL_DELETE"
    sql_variable = "@HMDP_OPTIONAL_DELETE_SQL"
    return [
        f"SET {sql_variable} = IF(",
        "  EXISTS(SELECT 1 FROM information_schema.TABLES "
        f"WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='{table}'),",
        f"  'DELETE FROM `{table}`',",
        "  'SET @HMDP_OPTIONAL_DELETE_NOOP = 0'",
        ");",
        f"PREPARE {statement_name} FROM {sql_variable};",
        f"EXECUTE {statement_name};",
        f"DEALLOCATE PREPARE {statement_name};",
    ]


def build_mysql_sql(
    datasets: dict[str, list[dict[str, Any]]],
    profile: str,
    seed: int,
    dataset_sha256: str,
) -> str:
    shop_types = datasets["shop_types.json"]
    subcategories = datasets["shop_subcategories.json"]
    shops = datasets["shops.json"]
    shop_images = datasets.get("shop_images.json", [])
    shop_source_matches = datasets.get("shop_source_matches.json", [])
    shop_field_observations = datasets.get("shop_field_observations.json", [])
    hours = datasets["shop_business_hours.json"]
    users = datasets["users.json"]
    reviews = datasets["shop_reviews.json"]
    blogs = datasets["blogs.json"]
    comments = datasets["blog_comments.json"]
    follows = datasets["follows.json"]
    vouchers = datasets["vouchers.json"]
    seckill = datasets["seckill_vouchers.json"]
    data_version = shops[0]["dataVersion"] if shops else "nyc-mock-v2"
    real_only = data_version.startswith("nyc-real-")

    lines = [
        f"-- {SQL_MARKER}",
        (
            "-- Merchant identities are source-backed OpenStreetMap records; reviews, platform activity "
            "and illustrative media are synthetic and explicitly attributed."
            if real_only
            else "-- HMDP content is synthetic; some establishment identity fields may come from NYC Open Data."
        ),
        (
            "-- Run only after p3, p4, p8 provenance, p10_p8_real_content.sql, "
            "p11_p2_p3_shop_enrichment.sql, and p12_p13_data_quality.sql. Run p9 plus the "
            "matching neighborhood import afterward to rebuild map projections."
            if data_version.startswith("nyc-real-v5-")
            else
            "-- Run only after p3, p4, p8 provenance, p10_p8_real_content.sql, and "
            "p11_p2_p3_shop_enrichment.sql. Run p9 plus the matching neighborhood import "
            "afterward to rebuild map projections."
            if real_only
            else "-- Run only after p3_nyc_compatibility.sql, p4_nyc_domain.sql, and p8_p6_data_provenance.sql."
        ),
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
    for table in P7_DERIVED_TABLES:
        lines.extend(_delete_optional_table(table))
    lines.extend(_delete_optional_table("tb_shop_field_observation"))
    lines.extend(_delete_optional_table("tb_shop_source_match"))
    lines.extend(_delete_optional_table("tb_shop_image"))
    for table in DATASET_SCOPED_OPTIONAL_TABLES:
        lines.extend(_delete_optional_table(table))
    lines.extend(
        [
            "SET @HMDP_OPTIONAL_DELETE_SQL = IF(",
            "  EXISTS(SELECT 1 FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_map_data_import'),",
            "  'UPDATE `tb_map_data_import` SET `active`=0',",
            "  'SET @HMDP_OPTIONAL_DELETE_NOOP = 0'",
            ");",
            "PREPARE HMDP_OPTIONAL_DELETE FROM @HMDP_OPTIONAL_DELETE_SQL;",
            "EXECUTE HMDP_OPTIONAL_DELETE;",
            "DEALLOCATE PREPARE HMDP_OPTIONAL_DELETE;",
            "",
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
            "local_review_count", "local_score", "open_hours", "phone", "website", "reservation_url",
            "business_status", "rating_count", "external_score", "external_rating_count",
            "price_range_text", "health_grade", "last_enriched_at", "timezone", "source_type",
            "external_id", "source_name", "source_url", "source_fetched_at", "synthetic_fields",
            "data_version", "create_time", "update_time",
        ),
        (
            (
                item["id"], item["name"], item["typeId"], item["subcategoryId"], item["images"],
                item["area"], item["borough"], item["address"], item["description"], item["x"], item["y"],
                item["avgPriceCents"] // 100 if item.get("avgPriceCents") is not None else None,
                item.get("priceLevel"), item["sold"], item["comments"], item["score"],
                item.get("localReviewCount", item["comments"]), item.get("localScore", item["score"]),
                _first_open_hours(item["id"], hours), item.get("phone"), item.get("website"),
                item.get("reservationUrl"), item.get("businessStatus", "OPERATIONAL"),
                item.get("ratingCount"), item.get("externalScore"),
                item.get("externalRatingCount", item.get("ratingCount")),
                item.get("priceRangeText"), item.get("healthGrade"),
                _mysql_datetime(item.get("lastEnrichedAt")), item["timezone"], item["sourceType"],
                item.get("externalId"), item.get("sourceName"), item.get("sourceUrl"),
                _mysql_datetime(item.get("sourceFetchedAt")),
                json.dumps(item.get("syntheticFields") or [], separators=(",", ":")), item["dataVersion"],
                FIXED_TIME, FIXED_TIME,
            )
            for item in shops
        ),
    )
    if shop_images:
        statements += _insert_statements(
            "tb_shop_image",
            (
                "id", "shop_id", "display_url", "source_page_url", "source_name", "author_name",
                "license_name", "license_url", "image_type", "match_type", "is_primary",
                "display_order", "width", "height", "sha256", "content_sha256", "sort_order",
                "fetched_at", "last_checked_at", "availability_status", "cached_url", "data_version",
            ),
            (
                (
                    item["id"], item["shopId"], item["url"], item["sourceUrl"], item["sourceName"],
                    item["attribution"], item["licenseName"], item.get("licenseUrl"), item["imageType"],
                    item.get("matchType", "CATEGORY_FALLBACK"), item.get("isPrimary", False),
                    item.get("displayOrder", item["sortOrder"]), item.get("width"), item.get("height"),
                    item.get("sha256"), item.get("contentSha256"), item["sortOrder"],
                    _mysql_datetime(item.get("fetchedAt")), _mysql_datetime(item.get("lastCheckedAt")),
                    item.get("availabilityStatus", "AVAILABLE"), item.get("cachedUrl"), item["dataVersion"],
                )
                for item in shop_images
            ),
        )
    if shop_source_matches:
        statements += _insert_statements(
            "tb_shop_source_match",
            (
                "shop_id", "provider", "external_id", "source_url", "matched_fields", "match_score",
                "match_method", "observed_at", "snapshot_version", "active",
            ),
            (
                (
                    item["shopId"], item["provider"], item["externalId"], item.get("sourceUrl"),
                    json.dumps(item.get("matchedFields") or [], separators=(",", ":")),
                    item["matchScore"], item["matchMethod"], _mysql_datetime(item["observedAt"]),
                    item["snapshotVersion"], item.get("active", True),
                )
                for item in shop_source_matches
            ),
        )
    if shop_field_observations:
        statements += _insert_statements(
            "tb_shop_field_observation",
            (
                "shop_id", "field_name", "value_json", "provider", "external_id", "observed_at",
                "expires_at", "match_score", "source_priority", "content_sha256", "snapshot_version",
            ),
            (
                (
                    item["shopId"], item["fieldName"],
                    json.dumps(item.get("value"), ensure_ascii=False, separators=(",", ":")),
                    item["provider"], item.get("externalId"), _mysql_datetime(item["observedAt"]),
                    _mysql_datetime(item.get("expiresAt")), item["matchScore"], item["sourcePriority"],
                    item["contentSha256"], item["snapshotVersion"],
                )
                for item in shop_field_observations
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
    if any("rootId" in item for item in reviews):
        statements += _insert_statements(
            "tb_shop_review",
            (
                "id", "shop_id", "user_id", "root_id", "parent_id", "reply_to_user_id", "depth",
                "author_role", "source_type", "language", "sentiment", "topic_tags", "security_test",
                "rating", "content", "images", "liked", "create_time", "update_time",
            ),
            (
                (
                    item["id"], item["shopId"], item["userId"], item["rootId"], item.get("parentId"),
                    item.get("replyToUserId"), item["depth"], item.get("authorRole", "USER"),
                    item["sourceType"], item["language"], item["sentiment"],
                    json.dumps(item.get("topicTags") or [], separators=(",", ":")),
                    item.get("securityTest", False), item.get("rating"), item["content"], item["images"],
                    item["liked"], _mysql_datetime(item["createTime"]), _mysql_datetime(item["createTime"]),
                )
                for item in reviews
            ),
        )
    else:
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
    if real_only:
        statements += _insert_statements(
            "tb_blog",
            (
                "id", "shop_id", "user_id", "title", "images", "content", "liked", "comments",
                "source_type", "data_version", "create_time", "update_time",
            ),
            (
                (
                    item["id"], item["shopId"], item["userId"], item["title"], item["images"],
                    item["content"], item["liked"], item["comments"], item["sourceType"],
                    item["dataVersion"], _mysql_datetime(item["createTime"]),
                    _mysql_datetime(item["createTime"]),
                )
                for item in blogs
            ),
        )
        statements += _insert_statements(
            "tb_blog_comments",
            (
                "id", "user_id", "blog_id", "parent_id", "answer_id", "content", "liked", "status",
                "source_type", "data_version", "create_time", "update_time",
            ),
            (
                (
                    item["id"], item["userId"], item["blogId"], item["parentId"], item["answerId"],
                    item["content"], item["liked"], 0, item["sourceType"], item["dataVersion"],
                    _mysql_datetime(item["createTime"]), _mysql_datetime(item["createTime"]),
                )
                for item in comments
            ),
        )
    else:
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
    voucher_columns = (
        (
            "id", "shop_id", "title", "sub_title", "rules", "pay_value", "actual_value", "type", "status",
            "source_type", "data_version", "create_time", "update_time",
        )
        if real_only
        else (
            "id", "shop_id", "title", "sub_title", "rules", "pay_value", "actual_value", "type", "status",
            "create_time", "update_time",
        )
    )
    statements += _insert_statements(
        "tb_voucher",
        voucher_columns,
        (
            (
                item["id"], item["shopId"], item["title"], item["subTitle"], item["rules"],
                item["payValueCents"], item["actualValueCents"], item["type"], item["status"],
                *((item["sourceType"], item["dataVersion"]) if real_only else ()),
                FIXED_TIME, FIXED_TIME,
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
            # Entity IDs are reused when a dataset is replaced. Keep the
            # SHA-256-based translate:text:* cache, but remove translations
            # whose identity is only entity type + numeric ID.
            "translate:shop:*",
            "translate:review:*",
            "translate:blog:*",
            "translate:comment:*",
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

    shops = datasets["shops.json"]
    shop_ids = sorted(shop["id"] for shop in shops)
    source_counts: dict[str, int] = {}
    for shop in datasets["shops.json"]:
        source_type = str(shop.get("sourceType") or "UNKNOWN")
        source_counts[source_type] = source_counts.get(source_type, 0) + 1
    data_version = shops[0]["dataVersion"] if shops else "nyc-mock-v2"
    merchant_identity_mode = (
        "REAL_ONLY"
        if data_version.startswith("nyc-real-")
        else "HYBRID"
        if data_version.startswith("nyc-hybrid-")
        else "SYNTHETIC"
    )
    reviews = datasets.get("shop_reviews.json", [])
    images = datasets.get("shop_images.json", [])
    review_depth_counts: dict[str, int] = {}
    for review in reviews:
        depth = str(review.get("depth", 0))
        review_depth_counts[depth] = review_depth_counts.get(depth, 0) + 1
    mock_shops = source_counts.get("MOCK", 0)
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
        "dataVersion": data_version,
        "merchantIdentityMode": merchant_identity_mode,
        "datasetSha256": dataset_sha256,
        "datasetFiles": dataset_files,
        "profile": profile,
        "seed": seed,
        "shopIds": shop_ids,
        "shopIdsSha256": _shop_ids_sha256(shop_ids),
        "provenance": {
            "merchantIdentityMode": merchant_identity_mode,
            "sourceCounts": dict(sorted(source_counts.items())),
            "mockShops": mock_shops,
            "realShops": len(shops) - mock_shops,
            "syntheticReviews": len(reviews),
            "syntheticReviewRoots": review_depth_counts.get("0", 0),
            "syntheticBlogs": len(datasets.get("blogs.json", [])),
            "syntheticBlogComments": len(datasets.get("blog_comments.json", [])),
            "syntheticVouchers": len(datasets.get("vouchers.json", [])),
            "reviewDepthCounts": dict(sorted(review_depth_counts.items())),
            "illustrativeImages": len(images),
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
