#!/usr/bin/env python3
"""Restore visible note likers and enrich the two documented demo accounts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEMO_LIKER_IDS = (17, 83, 241, 509, 887)
DEMO_PHONES = ("+8618817638328", "+13322157333")


def resp_command(*arguments: Any) -> bytes:
    encoded = [str(argument).encode("utf-8") for argument in arguments]
    parts = [f"*{len(encoded)}\r\n".encode("ascii")]
    for item in encoded:
        parts.extend((f"${len(item)}\r\n".encode("ascii"), item, b"\r\n"))
    return b"".join(parts)


def build_sql(data_version: str, blog_count: int) -> str:
    liker_ids = ", ".join(str(value) for value in DEMO_LIKER_IDS)
    return f"""-- NYC_REVIEW_DEMO_ASSETS_OVERLAY_V2
SET NAMES utf8mb4;
SET time_zone = '+00:00';
SET @NYC_REVIEW_CN_USER = (SELECT `id` FROM `tb_user` WHERE `phone` = '{DEMO_PHONES[0]}' LIMIT 1);
SET @NYC_REVIEW_US_USER = (SELECT `id` FROM `tb_user` WHERE `phone` = '{DEMO_PHONES[1]}' LIMIT 1);
SET @NYC_REVIEW_LIKER_COUNT = (SELECT COUNT(*) FROM `tb_user` WHERE `id` IN ({liker_ids}));
SET @NYC_REVIEW_NOTE_COUNT = (SELECT COUNT(*) FROM `tb_blog` WHERE `data_version` = '{data_version}');
SET @NYC_REVIEW_DEMO_ASSET_GUARD = IF(
  @NYC_REVIEW_CN_USER IS NOT NULL AND @NYC_REVIEW_US_USER IS NOT NULL
  AND @NYC_REVIEW_LIKER_COUNT = {len(DEMO_LIKER_IDS)} AND @NYC_REVIEW_NOTE_COUNT = {blog_count},
  'DO 0',
  'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''Demo accounts or note dataset missing; demo assets overlay aborted'''
);
PREPARE NYC_REVIEW_DEMO_ASSET_GUARD FROM @NYC_REVIEW_DEMO_ASSET_GUARD;
EXECUTE NYC_REVIEW_DEMO_ASSET_GUARD;
DEALLOCATE PREPARE NYC_REVIEW_DEMO_ASSET_GUARD;

START TRANSACTION;
INSERT IGNORE INTO `tb_follow` (`user_id`, `follow_user_id`, `create_time`)
SELECT @NYC_REVIEW_CN_USER, `id`, CURRENT_TIMESTAMP FROM `tb_user` WHERE `id` IN ({liker_ids});
INSERT IGNORE INTO `tb_follow` (`user_id`, `follow_user_id`, `create_time`)
SELECT @NYC_REVIEW_US_USER, `id`, CURRENT_TIMESTAMP FROM `tb_user` WHERE `id` IN ({liker_ids});

DROP TEMPORARY TABLE IF EXISTS `tmp_nyc_review_demo_coupon_v2`;
CREATE TEMPORARY TABLE `tmp_nyc_review_demo_coupon_v2` (
  `user_id` BIGINT UNSIGNED NOT NULL,
  `seq` INT NOT NULL,
  `voucher_id` BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (`user_id`, `seq`),
  UNIQUE KEY (`user_id`, `voucher_id`)
) ENGINE=InnoDB;
INSERT INTO `tmp_nyc_review_demo_coupon_v2`
SELECT @NYC_REVIEW_CN_USER, ranked.rn, ranked.id FROM (
  SELECT `id`, ROW_NUMBER() OVER (ORDER BY CRC32(CONCAT('cn-voucher:', `id`))) rn
  FROM `tb_voucher` WHERE `type` = 0 AND `status` = 1
) ranked WHERE ranked.rn <= 10;
INSERT INTO `tmp_nyc_review_demo_coupon_v2`
SELECT @NYC_REVIEW_US_USER, ranked.rn, ranked.id FROM (
  SELECT `id`, ROW_NUMBER() OVER (ORDER BY CRC32(CONCAT('us-voucher:', `id`))) rn
  FROM `tb_voucher` WHERE `type` = 0 AND `status` = 1
) ranked WHERE ranked.rn <= 10;

INSERT INTO `tb_voucher_order`
  (`id`, `user_id`, `voucher_id`, `pay_type`, `status`, `create_time`, `pay_time`, `expires_at`, `update_time`)
SELECT 890000000000000000 + dc.`user_id` * 100 + dc.`seq`, dc.`user_id`, dc.`voucher_id`, 1, 2,
  CURRENT_TIMESTAMP - INTERVAL dc.`seq` DAY,
  CURRENT_TIMESTAMP - INTERVAL dc.`seq` DAY,
  CASE dc.`seq`
    WHEN 1 THEN CURRENT_TIMESTAMP - INTERVAL 28 DAY
    WHEN 2 THEN CURRENT_TIMESTAMP - INTERVAL 14 DAY
    WHEN 3 THEN CURRENT_TIMESTAMP - INTERVAL 3 DAY
    WHEN 4 THEN CURRENT_TIMESTAMP + INTERVAL 7 DAY
    WHEN 5 THEN CURRENT_TIMESTAMP + INTERVAL 21 DAY
    WHEN 6 THEN CURRENT_TIMESTAMP + INTERVAL 45 DAY
    WHEN 7 THEN CURRENT_TIMESTAMP + INTERVAL 60 DAY
    WHEN 8 THEN CURRENT_TIMESTAMP + INTERVAL 90 DAY
    WHEN 9 THEN CURRENT_TIMESTAMP + INTERVAL 120 DAY
    ELSE CURRENT_TIMESTAMP + INTERVAL 183 DAY
  END,
  CURRENT_TIMESTAMP
FROM `tmp_nyc_review_demo_coupon_v2` dc
ON DUPLICATE KEY UPDATE
  `status` = VALUES(`status`), `pay_time` = VALUES(`pay_time`),
  `expires_at` = VALUES(`expires_at`), `update_time` = CURRENT_TIMESTAMP;

UPDATE `tb_blog` SET `liked` = GREATEST(COALESCE(`liked`, 0), 4)
WHERE `data_version` = '{data_version}';
UPDATE `tb_user_info` i
SET i.`fans` = (SELECT COUNT(*) FROM `tb_follow` f WHERE f.`follow_user_id` = i.`user_id`),
    i.`followee` = (SELECT COUNT(*) FROM `tb_follow` f WHERE f.`user_id` = i.`user_id`)
WHERE i.`user_id` IN (@NYC_REVIEW_CN_USER, @NYC_REVIEW_US_USER, {liker_ids});
DROP TEMPORARY TABLE `tmp_nyc_review_demo_coupon_v2`;
COMMIT;
"""


def build_resp(blogs: list[dict[str, Any]]) -> bytes:
    commands: list[bytes] = []
    for blog in blogs:
        author_id = int(blog["userId"])
        likers = [value for value in DEMO_LIKER_IDS if value != author_id][:3]
        arguments: list[Any] = ["ZADD", f"blog:liked:{blog['id']}"]
        for offset, user_id in enumerate(likers):
            arguments.extend((1_790_100_000_000 + int(blog["id"]) * 10 + offset, user_id))
        commands.append(resp_command(*arguments))
    return b"".join(commands)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    args = parser.parse_args()

    dataset = args.dataset.resolve()
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    blogs = json.loads((dataset / "blogs.json").read_text(encoding="utf-8"))
    users = json.loads((dataset / "users.json").read_text(encoding="utf-8"))
    data_version = str(manifest["dataVersion"])
    user_ids = {int(item["id"]) for item in users}
    missing = set(DEMO_LIKER_IDS) - user_ids
    if missing:
        raise ValueError(f"demo liker IDs are absent from the dataset: {sorted(missing)}")
    if not any(int(blog["id"]) == 3078 for blog in blogs):
        raise ValueError("required demo note 3078 is absent from the dataset")

    sql_path = dataset / "demo_assets_v2_overlay.sql"
    resp_path = dataset / "demo_assets_v2_overlay.resp"
    sql_path.write_text(build_sql(data_version, len(blogs)), encoding="utf-8")

    resp_path.write_bytes(build_resp(blogs))

    print(json.dumps({
        "status": "ok",
        "dataVersion": data_version,
        "blogs": len(blogs),
        "demoAccounts": DEMO_PHONES,
        "couponsPerAccount": 10,
        "expiredCouponsPerAccount": 3,
        "sql": str(sql_path),
        "redis": str(resp_path),
    }, indent=2))


if __name__ == "__main__":
    main()
