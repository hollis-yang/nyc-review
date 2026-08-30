#!/usr/bin/env python3
"""Build an idempotent social-persona overlay for an existing generated dataset.

The overlay changes only users listed in the dataset, generated-to-generated
follow edges, and generated note authors. Registered users and relationships
that involve registered users are intentionally preserved.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from generate import (
    DEFAULT_SEED,
    generate_blog_likes,
    generate_follows,
    generate_users,
    update_user_social_counts,
)
from import_bundle import FIXED_TIME, _insert_statements, _sql_literal


def load_json(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def resp_command(*arguments: Any) -> bytes:
    encoded = [str(argument).encode("utf-8") for argument in arguments]
    parts = [f"*{len(encoded)}\r\n".encode("ascii")]
    for item in encoded:
        parts.append(f"${len(item)}\r\n".encode("ascii"))
        parts.append(item + b"\r\n")
    return b"".join(parts)


def build_redis_overlay(blog_likes: Iterable[dict[str, Any]]) -> bytes:
    by_blog: dict[int, list[dict[str, Any]]] = {}
    for item in blog_likes:
        by_blog.setdefault(item["blogId"], []).append(item)
    commands: list[bytes] = []
    for blog_id in sorted(by_blog):
        likes = sorted(by_blog[blog_id], key=lambda item: item["userId"])
        for offset in range(0, len(likes), 100):
            arguments: list[Any] = ["ZADD", f"blog:liked:{blog_id}"]
            for item in likes[offset : offset + 100]:
                arguments.extend((item["score"], item["userId"]))
            commands.append(resp_command(*arguments))
    return b"".join(commands)


def build_sql_overlay(
    original_users: list[dict[str, Any]],
    personas: list[dict[str, Any]],
    follows: list[dict[str, Any]],
    blogs: list[dict[str, Any]],
    data_version: str,
) -> str:
    if [item["id"] for item in original_users] != [item["id"] for item in personas]:
        raise ValueError("persona IDs do not match the source dataset")

    lines = [
        "-- NYC_REVIEW_USER_SOCIAL_OVERLAY_V1",
        "-- Updates generated personas only; registered-user rows and relationships are preserved.",
        "SET NAMES utf8mb4;",
        "START TRANSACTION;",
        "DROP TEMPORARY TABLE IF EXISTS `tmp_nyc_review_persona`;",
        "CREATE TEMPORARY TABLE `tmp_nyc_review_persona` (",
        "  `user_id` BIGINT PRIMARY KEY,",
        "  `expected_phone` VARCHAR(32) NOT NULL,",
        "  `icon` VARCHAR(255) NOT NULL,",
        "  `city` VARCHAR(128) NOT NULL,",
        "  `introduce` VARCHAR(255) NOT NULL,",
        "  `gender` TINYINT NOT NULL,",
        "  `birthday` DATE NOT NULL",
        ") ENGINE=InnoDB;",
    ]
    lines.extend(_insert_statements(
        "tmp_nyc_review_persona",
        ("user_id", "expected_phone", "icon", "city", "introduce", "gender", "birthday"),
        (
            (
                persona["id"], original["phone"], persona["icon"], persona["city"],
                persona["introduce"], persona["gender"], persona["birthday"],
            )
            for original, persona in zip(original_users, personas)
        ),
    ))
    lines.extend([
        f"SET @NYC_REVIEW_EXPECTED_PERSONAS = {len(personas)};",
        "SET @NYC_REVIEW_MATCHED_PERSONAS = (",
        "  SELECT COUNT(*) FROM `tmp_nyc_review_persona` p",
        "  JOIN `tb_user` u ON u.`id` = p.`user_id` AND u.`phone` = p.`expected_phone`",
        ");",
        "SET @NYC_REVIEW_PERSONA_GUARD = IF(",
        "  @NYC_REVIEW_MATCHED_PERSONAS = @NYC_REVIEW_EXPECTED_PERSONAS,",
        "  'DO 0',",
        "  'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''Generated user identity mismatch; overlay aborted'''",
        ");",
        "PREPARE NYC_REVIEW_PERSONA_GUARD FROM @NYC_REVIEW_PERSONA_GUARD;",
        "EXECUTE NYC_REVIEW_PERSONA_GUARD;",
        "DEALLOCATE PREPARE NYC_REVIEW_PERSONA_GUARD;",
        "UPDATE `tb_user` u JOIN `tmp_nyc_review_persona` p ON p.`user_id` = u.`id`",
        "SET u.`icon` = p.`icon`, u.`update_time` = CURRENT_TIMESTAMP;",
        "UPDATE `tb_user_info` i JOIN `tmp_nyc_review_persona` p ON p.`user_id` = i.`user_id`",
        "SET i.`city` = p.`city`, i.`introduce` = p.`introduce`, i.`gender` = p.`gender`,",
        "    i.`birthday` = p.`birthday`, i.`update_time` = CURRENT_TIMESTAMP;",
        # MySQL cannot reference the same temporary table twice in one DELETE.
        # Materialize a second ID-only table for the target side of the edge.
        "DROP TEMPORARY TABLE IF EXISTS `tmp_nyc_review_persona_target`;",
        "CREATE TEMPORARY TABLE `tmp_nyc_review_persona_target` (",
        "  `user_id` BIGINT PRIMARY KEY",
        ") ENGINE=InnoDB;",
        "INSERT INTO `tmp_nyc_review_persona_target` (`user_id`)",
        "SELECT `user_id` FROM `tmp_nyc_review_persona`;",
        "DELETE f FROM `tb_follow` f",
        "JOIN `tmp_nyc_review_persona` source_user ON source_user.`user_id` = f.`user_id`",
        "JOIN `tmp_nyc_review_persona_target` target_user ON target_user.`user_id` = f.`follow_user_id`;",
    ])
    lines.extend(_insert_statements(
        "tb_follow",
        ("id", "user_id", "follow_user_id", "create_time"),
        ((item["id"], item["userId"], item["followUserId"], FIXED_TIME) for item in follows),
    ))
    lines.extend([
        "UPDATE `tb_user_info` i JOIN `tmp_nyc_review_persona` p ON p.`user_id` = i.`user_id`",
        "LEFT JOIN (SELECT `user_id`, COUNT(*) AS n FROM `tb_follow` GROUP BY `user_id`) outgoing",
        "  ON outgoing.`user_id` = i.`user_id`",
        "LEFT JOIN (SELECT `follow_user_id`, COUNT(*) AS n FROM `tb_follow` GROUP BY `follow_user_id`) incoming",
        "  ON incoming.`follow_user_id` = i.`user_id`",
        "SET i.`followee` = COALESCE(outgoing.n, 0), i.`fans` = COALESCE(incoming.n, 0),",
        "    i.`update_time` = CURRENT_TIMESTAMP;",
        "DROP TEMPORARY TABLE IF EXISTS `tmp_nyc_review_blog_author`;",
        "CREATE TEMPORARY TABLE `tmp_nyc_review_blog_author` (",
        "  `blog_id` BIGINT PRIMARY KEY, `user_id` BIGINT NOT NULL",
        ") ENGINE=InnoDB;",
    ])
    lines.extend(_insert_statements(
        "tmp_nyc_review_blog_author",
        ("blog_id", "user_id"),
        ((item["id"], item["userId"]) for item in blogs),
    ))
    lines.extend([
        "UPDATE `tb_blog` b JOIN `tmp_nyc_review_blog_author` a ON a.`blog_id` = b.`id`",
        f"SET b.`user_id` = a.`user_id`, b.`update_time` = CURRENT_TIMESTAMP WHERE b.`data_version` = {_sql_literal(data_version)};",
        "DROP TEMPORARY TABLE `tmp_nyc_review_blog_author`;",
        "DROP TEMPORARY TABLE `tmp_nyc_review_persona_target`;",
        "DROP TEMPORARY TABLE `tmp_nyc_review_persona`;",
        "COMMIT;",
        "",
    ])
    return "\n".join(lines)


def build_overlay(dataset: Path, output: Path, seed: int) -> dict[str, Any]:
    original_users = load_json(dataset / "users.json")
    original_blogs = load_json(dataset / "blogs.json")
    original_follows = load_json(dataset / "follows.json")
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    if not original_users or not original_blogs:
        raise ValueError("dataset must contain users and blogs")

    personas = generate_users(random.Random(seed), len(original_users))
    for original, persona in zip(original_users, personas):
        persona["id"] = original["id"]
    follows = generate_follows(random.Random(seed + 101), len(original_follows), len(personas))
    update_user_social_counts(personas, follows)

    blogs = [dict(item) for item in original_blogs]
    user_ids = [item["id"] for item in personas]
    for offset, blog in enumerate(blogs):
        blog["userId"] = user_ids[(offset * 37 + 1) % len(user_ids)]
    blog_likes = generate_blog_likes(personas, blogs, follows)
    data_version = str(manifest["dataVersion"])

    output.mkdir(parents=True, exist_ok=True)
    sql_path = output / "user_social_overlay.sql"
    redis_path = output / "user_social_overlay.resp"
    report_path = output / "user_social_report.json"
    sql_path.write_text(
        build_sql_overlay(original_users, personas, follows, blogs, data_version),
        encoding="utf-8",
    )
    redis_path.write_bytes(build_redis_overlay(blog_likes))

    follow_pairs = {(item["userId"], item["followUserId"]) for item in follows}
    comment_authors = {
        item["userId"] for item in load_json(dataset / "blog_comments.json")
    }
    report = {
        "status": "ok",
        "dataVersion": data_version,
        "users": len(personas),
        "uniqueAvatars": len({item["icon"] for item in personas}),
        "communities": len({item["city"] for item in personas}),
        "uniqueBios": len({item["introduce"] for item in personas}),
        "followEdges": len(follows),
        "reciprocalDirectedEdges": sum(
            1 for source, target in follow_pairs if (target, source) in follow_pairs
        ),
        "blogAuthorCoverage": len({item["userId"] for item in blogs}),
        "commentAuthorCoverage": len(comment_authors),
        "blogLikeEdges": len(blog_likes),
        "usersWithLikes": len({item["userId"] for item in blog_likes}),
        "likesByBlogMedianFloor": sorted(Counter(
            item["blogId"] for item in blog_likes
        ).values())[len({item["blogId"] for item in blog_likes}) // 2],
        "mysql": sql_path.name,
        "redis": redis_path.name,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
