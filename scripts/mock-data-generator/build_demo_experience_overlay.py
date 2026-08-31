#!/usr/bin/env python3
"""Build P13 demo-account and engagement overlays for an imported dataset.

The generated SQL is idempotent. It replaces generated note comments for the
active dataset, recalculates long-tail engagement counts, and adds a curated
set of assets and social connections to the two documented demo accounts.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

from content_v2 import generate_realistic_note_comments
from generate import DEFAULT_SEED
from import_bundle import _insert_statements, _mysql_datetime, _sql_literal


COMMENT_ID_BASE = 800_000_000
DEMO_DATA_VERSION = "demo-users-v1"


def load_json(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_engagement_sql(
    notes: list[dict[str, Any]],
    users: list[dict[str, Any]],
    data_version: str,
    seed: int,
) -> tuple[str, dict[str, Any]]:
    user_ids = [int(item["id"]) for item in users]
    current_notes = [dict(item) for item in notes]
    for offset, note in enumerate(current_notes):
        # This matches build_user_social_overlay.py and the currently imported
        # note authors, so a generated commenter is never the note author.
        note["userId"] = user_ids[(offset * 37 + 1) % len(user_ids)]

    comments = generate_realistic_note_comments(
        random.Random(seed + 313), len(current_notes) * 10, current_notes, users
    )
    rows: list[tuple[Any, ...]] = []
    for item in comments:
        physical_id = COMMENT_ID_BASE + int(item["id"])
        parent_id = int(item["parentId"] or 0)
        physical_parent = COMMENT_ID_BASE + parent_id if parent_id else 0
        rows.append((
            physical_id,
            item["userId"],
            item["blogId"],
            physical_parent,
            physical_parent,
            item["content"],
            item["liked"],
            0,
            item["sourceType"],
            item["dataVersion"],
            _mysql_datetime(item["createTime"]),
            _mysql_datetime(item["createTime"]),
        ))

    lines = [
        "-- NYC_REVIEW_ENGAGEMENT_OVERLAY_V2",
        "SET NAMES utf8mb4;",
        "SET time_zone = '+00:00';",
        "SET @NYC_REVIEW_EXPECTED_NOTES = " + str(len(current_notes)) + ";",
        "SET @NYC_REVIEW_MATCHED_NOTES = (SELECT COUNT(*) FROM `tb_blog` "
        f"WHERE `data_version` = {_sql_literal(data_version)});",
        "SET @NYC_REVIEW_CONTENT_GUARD = IF(",
        "  @NYC_REVIEW_MATCHED_NOTES = @NYC_REVIEW_EXPECTED_NOTES, 'DO 0',",
        "  'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''Dataset note mismatch; engagement overlay aborted''');",
        "PREPARE NYC_REVIEW_CONTENT_GUARD FROM @NYC_REVIEW_CONTENT_GUARD;",
        "EXECUTE NYC_REVIEW_CONTENT_GUARD;",
        "DEALLOCATE PREPARE NYC_REVIEW_CONTENT_GUARD;",
        "SET @NYC_REVIEW_COMMENT_INDEX_SQL = IF(",
        "  EXISTS(SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() "
        "AND TABLE_NAME='tb_blog_comments' AND INDEX_NAME='idx_blog_comments_blog_time'),",
        "  'DO 0',",
        "  'ALTER TABLE `tb_blog_comments` ADD INDEX `idx_blog_comments_blog_time` (`blog_id`, `create_time`)');",
        "PREPARE NYC_REVIEW_COMMENT_INDEX FROM @NYC_REVIEW_COMMENT_INDEX_SQL;",
        "EXECUTE NYC_REVIEW_COMMENT_INDEX;",
        "DEALLOCATE PREPARE NYC_REVIEW_COMMENT_INDEX;",
        "START TRANSACTION;",
        "DELETE FROM `tb_blog_comments` WHERE `source_type` = 'SYNTHETIC' "
        f"AND `data_version` = {_sql_literal(data_version)};",
    ]
    lines.extend(_insert_statements(
        "tb_blog_comments",
        (
            "id", "user_id", "blog_id", "parent_id", "answer_id", "content",
            "liked", "status", "source_type", "data_version", "create_time", "update_time",
        ),
        rows,
        chunk_size=400,
    ))
    lines.extend([
        "UPDATE `tb_blog` b LEFT JOIN (",
        "  SELECT `blog_id`, COUNT(*) AS n FROM `tb_blog_comments` GROUP BY `blog_id`",
        ") c ON c.`blog_id` = b.`id`",
        "SET b.`comments` = COALESCE(c.n, 0),",
        "    b.`liked` = FLOOR(POW(CRC32(CONCAT('note-like-v3:', b.`id`)) / 4294967295.0, 4.5) * 4000),",
        "    b.`update_time` = CURRENT_TIMESTAMP",
        f"WHERE b.`data_version` = {_sql_literal(data_version)};",
        "UPDATE `tb_shop_review` SET `liked` = CASE",
        "  WHEN `depth` = 0 THEN FLOOR(POW(CRC32(CONCAT('review-like-v3:', `id`)) / 4294967295.0, 3.8) * 600)",
        "  WHEN `depth` = 1 THEN FLOOR(POW(CRC32(CONCAT('reply-like-v3:', `id`)) / 4294967295.0, 4.2) * 140)",
        "  ELSE FLOOR(POW(CRC32(CONCAT('nested-like-v3:', `id`)) / 4294967295.0, 4.5) * 70)",
        "END, `update_time` = CURRENT_TIMESTAMP WHERE `source_type` = 'SYNTHETIC';",
        "COMMIT;",
        "",
    ])

    volumes = Counter(int(item["blogId"]) for item in comments)
    author_sets: dict[int, set[int]] = {}
    for item in comments:
        author_sets.setdefault(int(item["blogId"]), set()).add(int(item["userId"]))
    report = {
        "notes": len(current_notes),
        "comments": len(comments),
        "averageComments": round(len(comments) / len(current_notes), 2),
        "minComments": min(volumes.get(int(note["id"]), 0) for note in current_notes),
        "maxComments": max(volumes.get(int(note["id"]), 0) for note in current_notes),
        "distinctCommentVolumes": len(set(volumes.values()) | ({0} if len(volumes) < len(current_notes) else set())),
        "multiCommentNotesWithMultipleAuthors": sum(
            len(author_sets.get(int(note["id"]), set())) >= 2
            for note in current_notes if volumes.get(int(note["id"]), 0) >= 2
        ),
    }
    return "\n".join(lines), report


def build_demo_sql() -> str:
    numbers = ",\n".join(f"({number})" for number in range(1, 21))
    lines = [
        "-- NYC_REVIEW_DEMO_ACCOUNTS_OVERLAY_V1",
        "-- Demo accounts: +86 18817638328 and +1 3322157333.",
        "SET NAMES utf8mb4;",
        "SET time_zone = '+00:00';",
        "SET @NYC_REVIEW_CN_USER = (SELECT `id` FROM `tb_user` WHERE `phone` IN ('+8618817638328', '18817638328') LIMIT 1);",
        "SET @NYC_REVIEW_US_USER = (SELECT `id` FROM `tb_user` WHERE `phone` = '+13322157333' LIMIT 1);",
        "SET @NYC_REVIEW_DEMO_GUARD = IF(@NYC_REVIEW_CN_USER IS NOT NULL AND @NYC_REVIEW_US_USER IS NOT NULL "
        "AND @NYC_REVIEW_CN_USER <> @NYC_REVIEW_US_USER, 'DO 0', "
        "'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''Both demo accounts must be registered before importing the overlay''');",
        "PREPARE NYC_REVIEW_DEMO_GUARD FROM @NYC_REVIEW_DEMO_GUARD;",
        "EXECUTE NYC_REVIEW_DEMO_GUARD;",
        "DEALLOCATE PREPARE NYC_REVIEW_DEMO_GUARD;",
        "START TRANSACTION;",
        "UPDATE `tb_user` SET `phone` = '+8618817638328', `nick_name` = 'ManhattanFoodExplorer',",
        "  `icon` = '/imgs/avatars/avatar-04.svg', `update_time` = CURRENT_TIMESTAMP WHERE `id` = @NYC_REVIEW_CN_USER;",
        "UPDATE `tb_user` SET `nick_name` = 'HollisExploresNYC', `icon` = '/imgs/avatars/avatar-09.svg',",
        "  `update_time` = CURRENT_TIMESTAMP WHERE `id` = @NYC_REVIEW_US_USER;",
        "INSERT INTO `tb_user_info` (`user_id`, `city`, `introduce`, `fans`, `followee`, `gender`, `birthday`, `credits`, `level`)",
        "VALUES",
        "  (@NYC_REVIEW_CN_USER, 'Flushing', 'Finding excellent food, cafés, and accessible weekend stops across NYC.', 0, 0, 0, '1996-06-18', 0, 0),",
        "  (@NYC_REVIEW_US_USER, 'Upper West Side', 'Neighborhood walks, independent restaurants, and practical AI-planned itineraries.', 0, 0, 0, '1994-03-22', 0, 0)",
        "ON DUPLICATE KEY UPDATE `city`=VALUES(`city`), `introduce`=VALUES(`introduce`), `gender`=VALUES(`gender`),",
        "  `birthday`=VALUES(`birthday`), `update_time`=CURRENT_TIMESTAMP;",
        "DROP TEMPORARY TABLE IF EXISTS `tmp_nyc_review_demo_peer`;",
        "CREATE TEMPORARY TABLE `tmp_nyc_review_demo_peer` (`user_id` BIGINT UNSIGNED PRIMARY KEY) ENGINE=InnoDB;",
        "INSERT INTO `tmp_nyc_review_demo_peer` SELECT `id` FROM `tb_user` WHERE `id` BETWEEN 1 AND 1000;",
        "INSERT IGNORE INTO `tb_follow` (`user_id`, `follow_user_id`, `create_time`)",
        "SELECT @NYC_REVIEW_CN_USER, `user_id`, CURRENT_TIMESTAMP FROM `tmp_nyc_review_demo_peer`",
        "ORDER BY CRC32(CONCAT('cn-out:', `user_id`)) LIMIT 90;",
        "INSERT IGNORE INTO `tb_follow` (`user_id`, `follow_user_id`, `create_time`)",
        "SELECT `user_id`, @NYC_REVIEW_CN_USER, CURRENT_TIMESTAMP FROM `tmp_nyc_review_demo_peer`",
        "ORDER BY CRC32(CONCAT('cn-in:', `user_id`)) LIMIT 140;",
        "INSERT IGNORE INTO `tb_follow` (`user_id`, `follow_user_id`, `create_time`)",
        "SELECT @NYC_REVIEW_US_USER, `user_id`, CURRENT_TIMESTAMP FROM `tmp_nyc_review_demo_peer`",
        "ORDER BY CRC32(CONCAT('us-out:', `user_id`)) LIMIT 110;",
        "INSERT IGNORE INTO `tb_follow` (`user_id`, `follow_user_id`, `create_time`)",
        "SELECT `user_id`, @NYC_REVIEW_US_USER, CURRENT_TIMESTAMP FROM `tmp_nyc_review_demo_peer`",
        "ORDER BY CRC32(CONCAT('us-in:', `user_id`)) LIMIT 165;",
        "INSERT IGNORE INTO `tb_follow` (`user_id`, `follow_user_id`, `create_time`) VALUES",
        "  (@NYC_REVIEW_CN_USER, @NYC_REVIEW_US_USER, CURRENT_TIMESTAMP),",
        "  (@NYC_REVIEW_US_USER, @NYC_REVIEW_CN_USER, CURRENT_TIMESTAMP);",
        "DROP TEMPORARY TABLE IF EXISTS `tmp_nyc_review_demo_shop`;",
        "CREATE TEMPORARY TABLE `tmp_nyc_review_demo_shop` (",
        "  `user_id` BIGINT UNSIGNED NOT NULL, `seq` INT NOT NULL, `shop_id` BIGINT UNSIGNED NOT NULL,",
        "  PRIMARY KEY (`user_id`, `seq`), UNIQUE KEY (`user_id`, `shop_id`)",
        ") ENGINE=InnoDB;",
        "INSERT INTO `tmp_nyc_review_demo_shop` (`user_id`, `seq`, `shop_id`)",
        "SELECT @NYC_REVIEW_CN_USER, ranked.rn, ranked.id FROM (",
        "  SELECT `id`, ROW_NUMBER() OVER (ORDER BY CRC32(CONCAT('cn-shop:', `id`))) rn FROM `tb_shop`",
        ") ranked WHERE ranked.rn <= 6;",
        "INSERT INTO `tmp_nyc_review_demo_shop` (`user_id`, `seq`, `shop_id`)",
        "SELECT @NYC_REVIEW_US_USER, ranked.rn, ranked.id FROM (",
        "  SELECT `id`, ROW_NUMBER() OVER (ORDER BY CRC32(CONCAT('us-shop:', `id`))) rn FROM `tb_shop`",
        ") ranked WHERE ranked.rn <= 6;",
        "DELETE c FROM `tb_blog_comments` c JOIN `tb_blog` b ON b.`id` = c.`blog_id`",
        f"WHERE b.`data_version` = {_sql_literal(DEMO_DATA_VERSION)};",
        f"DELETE FROM `tb_blog` WHERE `data_version` = {_sql_literal(DEMO_DATA_VERSION)};",
        "INSERT INTO `tb_blog` (`shop_id`, `user_id`, `title`, `images`, `content`, `liked`, `comments`, `source_type`, `data_version`, `create_time`, `update_time`)",
        "SELECT ds.`shop_id`, ds.`user_id`,",
        "  CASE ds.`seq` WHEN 1 THEN CONCAT('A relaxed first visit to ', s.`name`) WHEN 2 THEN CONCAT('What stood out at ', s.`name`)",
        "    WHEN 3 THEN CONCAT('Planning a return to ', s.`name`) WHEN 4 THEN CONCAT(s.`name`, ' on a neighborhood afternoon')",
        "    WHEN 5 THEN CONCAT('A practical stop at ', s.`name`) ELSE CONCAT('Small details I noticed at ', s.`name`) END,",
        "  COALESCE(NULLIF(s.`images`, ''), '/imgs/icons/default-icon.png'),",
        "  CASE ds.`seq` WHEN 1 THEN CONCAT('The visit felt easy to fit into the neighborhood, and I would happily return to ', s.`name`, '.')",
        "    WHEN 2 THEN CONCAT('The service, pacing, and location made ', s.`name`, ' useful for a flexible day out.')",
        "    WHEN 3 THEN CONCAT('Next time at ', s.`name`, ', I would leave a little more time and explore another nearby stop.')",
        "    WHEN 4 THEN CONCAT(s.`name`, ' worked well as the middle stop in a relaxed afternoon itinerary.')",
        "    WHEN 5 THEN CONCAT('A straightforward visit with enough character to keep ', s.`name`, ' on my shortlist.')",
        "    ELSE CONCAT('I noticed thoughtful details at ', s.`name`, ' that made the visit memorable.') END,",
        "  CASE ds.`seq` WHEN 1 THEN 38 WHEN 2 THEN 121 WHEN 3 THEN 267 WHEN 4 THEN 74 WHEN 5 THEN 493 ELSE 186 END,",
        f"  0, 'USER_SUBMITTED', {_sql_literal(DEMO_DATA_VERSION)}, CURRENT_TIMESTAMP - INTERVAL ds.`seq` DAY, CURRENT_TIMESTAMP",
        "FROM `tmp_nyc_review_demo_shop` ds JOIN `tb_shop` s ON s.`id` = ds.`shop_id`;",
        "DROP TEMPORARY TABLE IF EXISTS `tmp_nyc_review_demo_number`;",
        "CREATE TEMPORARY TABLE `tmp_nyc_review_demo_number` (`n` INT PRIMARY KEY) ENGINE=InnoDB;",
        "INSERT INTO `tmp_nyc_review_demo_number` (`n`) VALUES\n" + numbers + ";",
        "INSERT INTO `tb_blog_comments` (`user_id`, `blog_id`, `parent_id`, `answer_id`, `content`, `liked`, `status`, `source_type`, `data_version`, `create_time`, `update_time`)",
        "SELECT 1 + MOD(b.`id` * 43 + n.`n` * 71, 1000), b.`id`, 0, 0,",
        "  CASE MOD(n.`n`, 5) WHEN 0 THEN CONCAT('This is useful context for planning a visit to ', s.`name`, '.')",
        "    WHEN 1 THEN CONCAT('I had a similar experience at ', s.`name`, ' and would also return.')",
        "    WHEN 2 THEN CONCAT('The timing tip for ', s.`name`, ' is especially helpful.')",
        "    WHEN 3 THEN CONCAT('Adding ', s.`name`, ' to my neighborhood list now.')",
        "    ELSE CONCAT('Did the atmosphere at ', s.`name`, ' stay consistent later in the day?') END,",
        "  FLOOR(POW(CRC32(CONCAT('demo-comment:', b.`id`, ':', n.`n`)) / 4294967295.0, 4) * 90),",
        f"  0, 'SYNTHETIC', {_sql_literal(DEMO_DATA_VERSION)}, CURRENT_TIMESTAMP - INTERVAL n.`n` HOUR, CURRENT_TIMESTAMP",
        "FROM `tb_blog` b JOIN `tb_shop` s ON s.`id` = b.`shop_id` JOIN `tmp_nyc_review_demo_number` n",
        "  ON n.`n` <= MOD(CRC32(CONCAT('demo-volume:', b.`id`)), 21)",
        f"WHERE b.`data_version` = {_sql_literal(DEMO_DATA_VERSION)};",
        "UPDATE `tb_blog` b LEFT JOIN (SELECT `blog_id`, COUNT(*) n FROM `tb_blog_comments` GROUP BY `blog_id`) c",
        "  ON c.`blog_id` = b.`id` SET b.`comments` = COALESCE(c.n, 0), b.`update_time` = CURRENT_TIMESTAMP",
        f"WHERE b.`data_version` = {_sql_literal(DEMO_DATA_VERSION)};",
        "INSERT IGNORE INTO `tb_shop_favorite` (`user_id`, `shop_id`, `create_time`)",
        "SELECT `user_id`, `shop_id`, CURRENT_TIMESTAMP - INTERVAL `seq` DAY FROM `tmp_nyc_review_demo_shop` WHERE `seq` <= 5;",
        "INSERT INTO `tb_agent_user_memory` (`user_id`, `memory_key`, `memory_value`, `source`, `confidence`, `create_time`, `update_time`) VALUES",
        "  (@NYC_REVIEW_CN_USER, 'preferred_category', 'Food & Dining, Cafes & Bakeries', 'explicit', 1.000, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),",
        "  (@NYC_REVIEW_CN_USER, 'preferred_neighborhood', 'Flushing, Astoria, Midtown', 'explicit', 1.000, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),",
        "  (@NYC_REVIEW_CN_USER, 'preferred_tags', 'quiet, outdoor_seating, budget_friendly', 'explicit', 1.000, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),",
        "  (@NYC_REVIEW_US_USER, 'preferred_category', 'Food & Dining, Bars & Nightlife', 'explicit', 1.000, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),",
        "  (@NYC_REVIEW_US_USER, 'preferred_neighborhood', 'Upper West Side, Chelsea, East Village', 'explicit', 1.000, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),",
        "  (@NYC_REVIEW_US_USER, 'preferred_tags', 'date_night, good_for_groups, late_night', 'explicit', 1.000, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        "ON DUPLICATE KEY UPDATE `memory_value`=VALUES(`memory_value`), `source`=VALUES(`source`),",
        "  `confidence`=VALUES(`confidence`), `update_time`=CURRENT_TIMESTAMP;",
        "INSERT INTO `tb_saved_itinerary` (`user_id`, `run_id`, `title`, `content_json`, `create_time`, `update_time`)",
        "SELECT ds.`user_id`, CONCAT('demo-', ds.`user_id`), 'A flexible NYC neighborhood day',",
        "  JSON_OBJECT('shopIds', JSON_ARRAYAGG(ds.`shop_id`), 'itinerary', JSON_OBJECT('total_estimated_cost_cents', 8600, 'summary', 'A relaxed five-stop demo itinerary')),",
        "  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM `tmp_nyc_review_demo_shop` ds WHERE ds.`seq` <= 5 GROUP BY ds.`user_id`",
        "ON DUPLICATE KEY UPDATE `title`=VALUES(`title`), `content_json`=VALUES(`content_json`), `update_time`=CURRENT_TIMESTAMP;",
        "DROP TEMPORARY TABLE IF EXISTS `tmp_nyc_review_demo_voucher`;",
        "CREATE TEMPORARY TABLE `tmp_nyc_review_demo_voucher` (`user_id` BIGINT UNSIGNED, `seq` INT, `voucher_id` BIGINT UNSIGNED, PRIMARY KEY (`user_id`, `seq`)) ENGINE=InnoDB;",
        "INSERT INTO `tmp_nyc_review_demo_voucher` SELECT @NYC_REVIEW_CN_USER, ranked.rn, ranked.id FROM (",
        "  SELECT `id`, ROW_NUMBER() OVER (ORDER BY CRC32(CONCAT('cn-voucher:', `id`))) rn FROM `tb_voucher` WHERE `type` = 0 AND `status` = 1",
        ") ranked WHERE ranked.rn <= 4;",
        "INSERT INTO `tmp_nyc_review_demo_voucher` SELECT @NYC_REVIEW_US_USER, ranked.rn, ranked.id FROM (",
        "  SELECT `id`, ROW_NUMBER() OVER (ORDER BY CRC32(CONCAT('us-voucher:', `id`))) rn FROM `tb_voucher` WHERE `type` = 0 AND `status` = 1",
        ") ranked WHERE ranked.rn <= 4;",
        "INSERT INTO `tb_voucher_order` (`id`, `user_id`, `voucher_id`, `pay_type`, `status`, `create_time`, `pay_time`, `update_time`)",
        "SELECT 880000000000000000 + dv.`user_id` * 100 + dv.`seq`, dv.`user_id`, dv.`voucher_id`, 1,",
        "  CASE WHEN MOD(dv.`seq`, 3) = 0 THEN 3 ELSE 2 END, CURRENT_TIMESTAMP - INTERVAL dv.`seq` DAY,",
        "  CURRENT_TIMESTAMP - INTERVAL dv.`seq` DAY, CURRENT_TIMESTAMP FROM `tmp_nyc_review_demo_voucher` dv",
        "ON DUPLICATE KEY UPDATE `status`=VALUES(`status`), `pay_time`=VALUES(`pay_time`), `update_time`=CURRENT_TIMESTAMP;",
        "UPDATE `tb_user_info` i LEFT JOIN (SELECT `user_id`, COUNT(*) n FROM `tb_follow` GROUP BY `user_id`) outgoing ON outgoing.`user_id`=i.`user_id`",
        "LEFT JOIN (SELECT `follow_user_id`, COUNT(*) n FROM `tb_follow` GROUP BY `follow_user_id`) incoming ON incoming.`follow_user_id`=i.`user_id`",
        "SET i.`followee`=COALESCE(outgoing.n,0), i.`fans`=COALESCE(incoming.n,0), i.`update_time`=CURRENT_TIMESTAMP",
        "WHERE i.`user_id` IN (@NYC_REVIEW_CN_USER, @NYC_REVIEW_US_USER);",
        "DROP TEMPORARY TABLE `tmp_nyc_review_demo_voucher`;",
        "DROP TEMPORARY TABLE `tmp_nyc_review_demo_number`;",
        "DROP TEMPORARY TABLE `tmp_nyc_review_demo_shop`;",
        "DROP TEMPORARY TABLE `tmp_nyc_review_demo_peer`;",
        "COMMIT;",
        "",
    ]
    return "\n".join(lines)


def build_overlay(dataset: Path, output: Path, seed: int) -> dict[str, Any]:
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    notes = load_json(dataset / "blogs.json")
    users = load_json(dataset / "users.json")
    if not notes or not users:
        raise ValueError("dataset must contain notes and users")
    data_version = str(manifest["dataVersion"])
    engagement_sql, engagement_report = build_engagement_sql(
        notes, users, data_version, seed
    )
    output.mkdir(parents=True, exist_ok=True)
    engagement_path = output / "engagement_overlay.sql"
    demo_path = output / "demo_accounts_overlay.sql"
    report_path = output / "demo_experience_report.json"
    engagement_path.write_text(engagement_sql, encoding="utf-8")
    demo_path.write_text(build_demo_sql(), encoding="utf-8")
    report = {
        "status": "ok",
        "dataVersion": data_version,
        "engagement": engagement_report,
        "demoAccounts": ["+8618817638328", "+13322157333"],
        "engagementSql": engagement_path.name,
        "demoAccountsSql": demo_path.name,
    }
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    output = args.output or args.dataset
    print(json.dumps(build_overlay(args.dataset.resolve(), output.resolve(), args.seed), indent=2))


if __name__ == "__main__":
    main()
