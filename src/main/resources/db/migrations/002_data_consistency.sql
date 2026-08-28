-- P1-C data repair. This script is safe to run more than once.
-- Back up tb_user_info and tb_follow before applying it to an existing database.

START TRANSACTION;

-- Keep the oldest row for every duplicate follow relationship.
DELETE duplicate_follow
FROM tb_follow duplicate_follow
JOIN tb_follow original_follow
  ON duplicate_follow.user_id = original_follow.user_id
 AND duplicate_follow.follow_user_id = original_follow.follow_user_id
 AND duplicate_follow.id > original_follow.id;

-- Every user needs a detail row so partial profile updates and counters can succeed.
INSERT INTO tb_user_info (user_id, fans, followee, credits, level)
SELECT user.id, 0, 0, 0, 0
FROM tb_user user
LEFT JOIN tb_user_info info ON info.user_id = user.id
WHERE info.user_id IS NULL;

-- Rebuild counters from the relationship table, which is the source of truth.
UPDATE tb_user_info info
LEFT JOIN (
    SELECT follow_user_id AS user_id, COUNT(*) AS fans
    FROM tb_follow
    GROUP BY follow_user_id
) fan_count ON fan_count.user_id = info.user_id
LEFT JOIN (
    SELECT user_id, COUNT(*) AS followee
    FROM tb_follow
    GROUP BY user_id
) followee_count ON followee_count.user_id = info.user_id
SET info.fans = COALESCE(fan_count.fans, 0),
    info.followee = COALESCE(followee_count.followee, 0);

COMMIT;

-- MySQL versions used by this project do not consistently support
-- ALTER TABLE ... ADD INDEX IF NOT EXISTS, so use information_schema.
SET @follow_pair_index_exists = (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'tb_follow'
      AND index_name = 'uk_follow_user_pair'
);
SET @follow_pair_ddl = IF(
    @follow_pair_index_exists = 0,
    'ALTER TABLE tb_follow ADD UNIQUE INDEX uk_follow_user_pair (user_id, follow_user_id)',
    'SELECT 1'
);
PREPARE follow_pair_statement FROM @follow_pair_ddl;
EXECUTE follow_pair_statement;
DEALLOCATE PREPARE follow_pair_statement;

SET @follow_target_index_exists = (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'tb_follow'
      AND index_name = 'idx_follow_target'
);
SET @follow_target_ddl = IF(
    @follow_target_index_exists = 0,
    'ALTER TABLE tb_follow ADD INDEX idx_follow_target (follow_user_id)',
    'SELECT 1'
);
PREPARE follow_target_statement FROM @follow_target_ddl;
EXECUTE follow_target_statement;
DEALLOCATE PREPARE follow_target_statement;
