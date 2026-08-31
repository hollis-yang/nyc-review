-- Remove the generator-only visit timestamp from existing note comments.
-- The fixed prefix format keeps this migration away from user-submitted text.
-- The WHERE clause also makes the update idempotent.
SET NAMES utf8mb4;

UPDATE `tb_blog_comments`
SET `content` = CONCAT(
  UPPER(LEFT(REGEXP_REPLACE(
    `content`,
    '^From my [[:alpha:]]+ [0-9]{1,2}, [0-9]{4} around [0-9]{1,2}:[0-9]{2} (AM|PM) visit:[[:space:]]*',
    ''
  ), 1)),
  SUBSTRING(REGEXP_REPLACE(
    `content`,
    '^From my [[:alpha:]]+ [0-9]{1,2}, [0-9]{4} around [0-9]{1,2}:[0-9]{2} (AM|PM) visit:[[:space:]]*',
    ''
  ), 2)
)
WHERE `source_type` = 'SYNTHETIC'
  AND `content` REGEXP '^From my [[:alpha:]]+ [0-9]{1,2}, [0-9]{4} around [0-9]{1,2}:[0-9]{2} (AM|PM) visit:';
