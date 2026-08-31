#!/usr/bin/env python3
"""Vary followed-user note likes for the documented demo accounts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


DEMO_PHONES = ("+8618817638328", "+13322157333")
DEMO_LIKER_IDS = (17, 29, 53, 83, 127, 173, 241, 353, 509, 673, 887, 997)


def resp_command(*arguments: Any) -> bytes:
    encoded = [str(argument).encode("utf-8") for argument in arguments]
    parts = [f"*{len(encoded)}\r\n".encode("ascii")]
    for item in encoded:
        parts.extend((f"${len(item)}\r\n".encode("ascii"), item, b"\r\n"))
    return b"".join(parts)


def select_likers(blog_id: int, author_id: int) -> tuple[int, ...]:
    """Return a stable, varied group of one to five synthetic followed likers."""
    eligible = [user_id for user_id in DEMO_LIKER_IDS if user_id != author_id]
    count = 1 + int.from_bytes(
        hashlib.sha256(f"note-liker-count:{blog_id}".encode()).digest()[:2], "big"
    ) % min(5, len(eligible))
    ranked = sorted(
        eligible,
        key=lambda user_id: hashlib.sha256(
            f"note-liker:{blog_id}:{user_id}".encode()
        ).digest(),
    )
    return tuple(ranked[:count])


def build_sql(data_version: str, blog_count: int) -> str:
    liker_ids = ", ".join(str(value) for value in DEMO_LIKER_IDS)
    demo_phones = ", ".join(f"'{phone}'" for phone in DEMO_PHONES)
    return f"""-- NYC_REVIEW_DEMO_NOTE_LIKES_OVERLAY_V3
SET NAMES utf8mb4;
SET time_zone = '+00:00';
SET @NYC_REVIEW_DEMO_ACCOUNT_COUNT = (
  SELECT COUNT(*) FROM `tb_user` WHERE `phone` IN ({demo_phones})
);
SET @NYC_REVIEW_DEMO_LIKER_COUNT = (
  SELECT COUNT(*) FROM `tb_user` WHERE `id` IN ({liker_ids})
);
SET @NYC_REVIEW_NOTE_COUNT = (
  SELECT COUNT(*) FROM `tb_blog` WHERE `data_version` = '{data_version}'
);
SET @NYC_REVIEW_DEMO_LIKES_GUARD = IF(
  @NYC_REVIEW_DEMO_ACCOUNT_COUNT = {len(DEMO_PHONES)}
  AND @NYC_REVIEW_DEMO_LIKER_COUNT = {len(DEMO_LIKER_IDS)}
  AND @NYC_REVIEW_NOTE_COUNT = {blog_count},
  'DO 0',
  'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''Demo accounts, liker users, or note dataset missing; note-likes overlay aborted'''
);
PREPARE NYC_REVIEW_DEMO_LIKES_GUARD FROM @NYC_REVIEW_DEMO_LIKES_GUARD;
EXECUTE NYC_REVIEW_DEMO_LIKES_GUARD;
DEALLOCATE PREPARE NYC_REVIEW_DEMO_LIKES_GUARD;

START TRANSACTION;
INSERT IGNORE INTO `tb_follow` (`user_id`, `follow_user_id`, `create_time`)
SELECT demo.`id`, liker.`id`, CURRENT_TIMESTAMP
FROM `tb_user` demo
JOIN `tb_user` liker ON liker.`id` IN ({liker_ids})
WHERE demo.`phone` IN ({demo_phones}) AND demo.`id` <> liker.`id`;

UPDATE `tb_blog`
SET `liked` = GREATEST(COALESCE(`liked`, 0), 5)
WHERE `data_version` = '{data_version}';

UPDATE `tb_user_info` info
JOIN `tb_user` target_user ON target_user.`id` = info.`user_id`
SET info.`fans` = (
      SELECT COUNT(*) FROM `tb_follow` follow_row
      WHERE follow_row.`follow_user_id` = target_user.`id`
    ),
    info.`followee` = (
      SELECT COUNT(*) FROM `tb_follow` follow_row
      WHERE follow_row.`user_id` = target_user.`id`
    )
WHERE target_user.`phone` IN ({demo_phones}) OR target_user.`id` IN ({liker_ids});
COMMIT;
"""


def build_resp(blogs: list[dict[str, Any]]) -> bytes:
    commands: list[bytes] = []
    for blog in blogs:
        blog_id = int(blog["id"])
        author_id = int(blog["userId"])
        key = f"blog:liked:{blog_id}"
        commands.append(resp_command("ZREM", key, *DEMO_LIKER_IDS))
        likers = select_likers(blog_id, author_id)
        arguments: list[Any] = ["ZADD", key]
        for offset, user_id in enumerate(likers):
            arguments.extend((1_777_000_000_000 + blog_id * 10 + offset, user_id))
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

    sql_path = dataset / "demo_likes_v3_overlay.sql"
    resp_path = dataset / "demo_likes_v3_overlay.resp"
    sql_path.write_text(build_sql(data_version, len(blogs)), encoding="utf-8")
    resp_path.write_bytes(build_resp(blogs))

    distribution: dict[int, int] = {}
    for blog in blogs:
        count = len(select_likers(int(blog["id"]), int(blog["userId"])))
        distribution[count] = distribution.get(count, 0) + 1
    print(json.dumps({
        "status": "ok",
        "dataVersion": data_version,
        "blogs": len(blogs),
        "demoAccounts": DEMO_PHONES,
        "candidateFollowedLikers": len(DEMO_LIKER_IDS),
        "visibleLikerCountDistribution": distribution,
        "sql": str(sql_path),
        "redis": str(resp_path),
    }, indent=2))


if __name__ == "__main__":
    main()
