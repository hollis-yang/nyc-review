#!/usr/bin/env python3
"""Build an idempotent overlay that scatters generated note comment times."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def build_sql(data_version: str, expected_comments: int) -> str:
    return f"""-- NYC_REVIEW_NOTE_COMMENT_TIMES_OVERLAY_V3
SET NAMES utf8mb4;
SET time_zone = '+00:00';
SET @NYC_REVIEW_EXPECTED_COMMENTS = {expected_comments};
SET @NYC_REVIEW_MATCHED_COMMENTS = (
  SELECT COUNT(*) FROM `tb_blog_comments`
  WHERE `source_type` = 'SYNTHETIC' AND `data_version` = '{data_version}'
);
SET @NYC_REVIEW_TIME_GUARD = IF(
  @NYC_REVIEW_MATCHED_COMMENTS = @NYC_REVIEW_EXPECTED_COMMENTS,
  'DO 0',
  'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''Dataset comment mismatch; time overlay aborted'''
);
PREPARE NYC_REVIEW_TIME_GUARD FROM @NYC_REVIEW_TIME_GUARD;
EXECUTE NYC_REVIEW_TIME_GUARD;
DEALLOCATE PREPARE NYC_REVIEW_TIME_GUARD;
START TRANSACTION;
UPDATE `tb_blog_comments` c
JOIN `tb_blog` b ON b.`id` = c.`blog_id`
SET c.`create_time` = TIMESTAMPADD(
      MINUTE,
      1 + MOD(CRC32(CONCAT('root-time-v3:', c.`blog_id`, ':', c.`id`)), 259200),
      b.`create_time`
    ),
    c.`update_time` = c.`create_time`
WHERE c.`source_type` = 'SYNTHETIC'
  AND c.`data_version` = '{data_version}'
  AND (c.`parent_id` IS NULL OR c.`parent_id` = 0);
UPDATE `tb_blog_comments` child
JOIN `tb_blog_comments` parent ON parent.`id` = child.`parent_id`
SET child.`create_time` = TIMESTAMPADD(
      MINUTE,
      1 + MOD(CRC32(CONCAT('reply-time-v3:', child.`blog_id`, ':', child.`id`)), 43200),
      parent.`create_time`
    ),
    child.`update_time` = child.`create_time`
WHERE child.`source_type` = 'SYNTHETIC'
  AND child.`data_version` = '{data_version}'
  AND child.`parent_id` > 0;
COMMIT;
"""


def main() -> None:
    args = parse_args()
    dataset = args.dataset.resolve()
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    data_version = str(manifest["dataVersion"])
    report_path = dataset / "demo_experience_report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        expected_comments = int(report["engagement"]["comments"])
    else:
        counts = manifest["counts"]
        expected_comments = int(counts.get("blog_comments", counts.get("blogComments", 0)))
    output = (args.output or dataset / "note_comment_time_overlay_v3.sql").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_sql(data_version, expected_comments), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "dataVersion": data_version,
        "expectedComments": expected_comments,
        "output": str(output),
    }, indent=2))


if __name__ == "__main__":
    main()
