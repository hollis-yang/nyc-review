#!/usr/bin/env python3
"""Guarantee visible followed-user likes for the two documented demo accounts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEMO_LIKER_IDS = (17, 83, 241, 509, 887)


def resp_command(*arguments: Any) -> bytes:
    encoded = [str(argument).encode("utf-8") for argument in arguments]
    parts = [f"*{len(encoded)}\r\n".encode("ascii")]
    for item in encoded:
        parts.extend((f"${len(item)}\r\n".encode("ascii"), item, b"\r\n"))
    return b"".join(parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    return parser.parse_args()


def build_sql(data_version: str, blog_count: int) -> str:
    liker_ids = ", ".join(str(value) for value in DEMO_LIKER_IDS)
    return f"""-- NYC_REVIEW_FOLLOWED_NOTE_LIKES_OVERLAY_V1
SET NAMES utf8mb4;
SET @NYC_REVIEW_CN_USER = (SELECT `id` FROM `tb_user` WHERE `phone` = '+8618817638328' LIMIT 1);
SET @NYC_REVIEW_US_USER = (SELECT `id` FROM `tb_user` WHERE `phone` = '+13322157333' LIMIT 1);
SET @NYC_REVIEW_LIKER_COUNT = (SELECT COUNT(*) FROM `tb_user` WHERE `id` IN ({liker_ids}));
SET @NYC_REVIEW_NOTE_COUNT = (SELECT COUNT(*) FROM `tb_blog` WHERE `data_version` = '{data_version}');
SET @NYC_REVIEW_FOLLOWED_LIKE_GUARD = IF(
  @NYC_REVIEW_CN_USER IS NOT NULL AND @NYC_REVIEW_US_USER IS NOT NULL
  AND @NYC_REVIEW_LIKER_COUNT = {len(DEMO_LIKER_IDS)} AND @NYC_REVIEW_NOTE_COUNT = {blog_count},
  'DO 0',
  'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''Demo accounts or note dataset missing; followed likes overlay aborted'''
);
PREPARE NYC_REVIEW_FOLLOWED_LIKE_GUARD FROM @NYC_REVIEW_FOLLOWED_LIKE_GUARD;
EXECUTE NYC_REVIEW_FOLLOWED_LIKE_GUARD;
DEALLOCATE PREPARE NYC_REVIEW_FOLLOWED_LIKE_GUARD;
START TRANSACTION;
INSERT IGNORE INTO `tb_follow` (`user_id`, `follow_user_id`, `create_time`)
SELECT @NYC_REVIEW_CN_USER, `id`, CURRENT_TIMESTAMP FROM `tb_user` WHERE `id` IN ({liker_ids});
INSERT IGNORE INTO `tb_follow` (`user_id`, `follow_user_id`, `create_time`)
SELECT @NYC_REVIEW_US_USER, `id`, CURRENT_TIMESTAMP FROM `tb_user` WHERE `id` IN ({liker_ids});
UPDATE `tb_user_info` i
SET i.`fans` = (SELECT COUNT(*) FROM `tb_follow` f WHERE f.`follow_user_id` = i.`user_id`),
    i.`followee` = (SELECT COUNT(*) FROM `tb_follow` f WHERE f.`user_id` = i.`user_id`)
WHERE i.`user_id` IN (@NYC_REVIEW_CN_USER, @NYC_REVIEW_US_USER, {liker_ids});
UPDATE `tb_blog` SET `liked` = GREATEST(COALESCE(`liked`, 0), 3)
WHERE `data_version` = '{data_version}';
COMMIT;
"""


def main() -> None:
    args = parse_args()
    dataset = args.dataset.resolve()
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    blogs = json.loads((dataset / "blogs.json").read_text(encoding="utf-8"))
    data_version = str(manifest["dataVersion"])
    user_ids = {int(item["id"]) for item in json.loads((dataset / "users.json").read_text(encoding="utf-8"))}
    missing = set(DEMO_LIKER_IDS) - user_ids
    if missing:
        raise ValueError(f"demo liker IDs are absent from the dataset: {sorted(missing)}")

    sql_path = dataset / "followed_note_likes_overlay.sql"
    resp_path = dataset / "followed_note_likes_overlay.resp"
    sql_path.write_text(build_sql(data_version, len(blogs)), encoding="utf-8")
    commands: list[bytes] = []
    for blog in blogs:
        author_id = int(blog["userId"])
        likers = [value for value in DEMO_LIKER_IDS if value != author_id][:3]
        arguments: list[Any] = ["ZADD", f"blog:liked:{blog['id']}"]
        for offset, user_id in enumerate(likers):
            arguments.extend((1_790_000_000_000 + int(blog["id"]) * 10 + offset, user_id))
        commands.append(resp_command(*arguments))
    resp_path.write_bytes(b"".join(commands))
    print(json.dumps({
        "status": "ok",
        "dataVersion": data_version,
        "blogs": len(blogs),
        "demoLikerIds": DEMO_LIKER_IDS,
        "sql": str(sql_path),
        "redis": str(resp_path),
    }, indent=2))


if __name__ == "__main__":
    main()
