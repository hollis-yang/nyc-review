-- P8 real-shop content schema.
-- Shop identity is public-source backed. Images are illustrative assets and
-- generated review rows are explicitly synthetic. This migration is additive,
-- idempotent, and keeps the legacy comma-delimited tb_shop.images projection.

SET NAMES utf8mb4 COLLATE utf8mb4_general_ci;

-- Five illustrative URLs can exceed the original 1024-byte legacy column.
ALTER TABLE `tb_shop`
    MODIFY COLUMN `images` VARCHAR(4096) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL
        COMMENT 'Compatibility projection of ordered illustrative image URLs',
    MODIFY COLUMN `score` INT UNSIGNED NULL
        COMMENT 'Rating multiplied by 10; NULL when the public source provides no rating';

CREATE TABLE IF NOT EXISTS `tb_shop_image` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `shop_id` BIGINT UNSIGNED NOT NULL,
    `display_url` VARCHAR(1024) NOT NULL COMMENT 'URL rendered by NYC Review; not a claimed shop photograph',
    `source_page_url` VARCHAR(1024) NULL COMMENT 'Attribution or source page rather than only the image bytes',
    `source_name` VARCHAR(160) NOT NULL,
    `author_name` VARCHAR(160) NULL,
    `license_name` VARCHAR(80) NULL,
    `license_url` VARCHAR(1024) NULL,
    `image_type` VARCHAR(32) NOT NULL DEFAULT 'ILLUSTRATIVE',
    `sha256` CHAR(64) NULL,
    `sort_order` TINYINT UNSIGNED NOT NULL DEFAULT 0,
    `fetched_at` DATETIME NULL,
    `data_version` VARCHAR(32) NOT NULL,
    `create_time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `update_time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_shop_image_order` (`shop_id`, `data_version`, `sort_order`),
    KEY `idx_shop_image_shop` (`shop_id`, `sort_order`),
    KEY `idx_shop_image_version_type` (`data_version`, `image_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Content provenance is stored on every seeded content family. Existing
-- rows remain explicitly LEGACY; generated P8 rows carry SYNTHETIC plus the
-- exact dataset version. User-created rows are overwritten by Spring as
-- USER_SUBMITTED and intentionally have no generated data version.
SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_blog' AND COLUMN_NAME='source_type'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_blog` ADD COLUMN `source_type` VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT ''LEGACY'' AFTER `comments`'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_blog' AND COLUMN_NAME='data_version'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_blog` ADD COLUMN `data_version` VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL AFTER `source_type`'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_blog_comments' AND COLUMN_NAME='source_type'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_blog_comments` ADD COLUMN `source_type` VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT ''LEGACY'' AFTER `status`'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_blog_comments' AND COLUMN_NAME='data_version'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_blog_comments` ADD COLUMN `data_version` VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL AFTER `source_type`'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_voucher' AND COLUMN_NAME='source_type'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_voucher` ADD COLUMN `source_type` VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT ''LEGACY'' AFTER `status`'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_voucher' AND COLUMN_NAME='data_version'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_voucher` ADD COLUMN `data_version` VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL AFTER `source_type`'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

-- Add review-thread columns one at a time so rerunning P10 is safe after a
-- partially completed migration.
SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_review' AND COLUMN_NAME='root_id'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_shop_review` ADD COLUMN `root_id` BIGINT UNSIGNED NULL AFTER `shop_id`'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_review' AND COLUMN_NAME='parent_id'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_shop_review` ADD COLUMN `parent_id` BIGINT UNSIGNED NULL AFTER `root_id`'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_review' AND COLUMN_NAME='reply_to_user_id'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_shop_review` ADD COLUMN `reply_to_user_id` BIGINT UNSIGNED NULL AFTER `user_id`'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_review' AND COLUMN_NAME='depth'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_shop_review` ADD COLUMN `depth` TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER `parent_id`'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_review' AND COLUMN_NAME='author_role'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_shop_review` ADD COLUMN `author_role` VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT ''USER'' AFTER `depth`'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_review' AND COLUMN_NAME='source_type'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_shop_review` ADD COLUMN `source_type` VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT ''LEGACY'' AFTER `author_role`'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_review' AND COLUMN_NAME='language'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_shop_review` ADD COLUMN `language` VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL AFTER `source_type`'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_review' AND COLUMN_NAME='sentiment'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_shop_review` ADD COLUMN `sentiment` VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL AFTER `language`'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_review' AND COLUMN_NAME='topic_tags'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_shop_review` ADD COLUMN `topic_tags` JSON NULL AFTER `sentiment`'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_review' AND COLUMN_NAME='security_test'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_shop_review` ADD COLUMN `security_test` TINYINT(1) NOT NULL DEFAULT 0 AFTER `topic_tags`'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

-- Replies do not carry a rating; longer generated discussions need more than
-- the legacy 512-character content field.
ALTER TABLE `tb_shop_review`
    MODIFY COLUMN `rating` TINYINT UNSIGNED NULL COMMENT '1-5 for depth-0 reviews; NULL for replies',
    MODIFY COLUMN `content` VARCHAR(2000) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL;

UPDATE `tb_shop_review`
SET `root_id` = `id`, `depth` = 0
WHERE `root_id` IS NULL AND (`parent_id` IS NULL OR `parent_id` = 0);

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_review' AND INDEX_NAME='idx_shop_review_roots'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_shop_review` ADD INDEX `idx_shop_review_roots` (`shop_id`, `parent_id`, `create_time`)'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_review' AND INDEX_NAME='idx_shop_review_thread'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_shop_review` ADD INDEX `idx_shop_review_thread` (`root_id`, `depth`, `create_time`)'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;

SET @NYC_REVIEW_P8_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
           WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_review'
             AND CONSTRAINT_NAME='chk_shop_review_depth'),
    'SET @NYC_REVIEW_P8_NOOP = 0',
    'ALTER TABLE `tb_shop_review` ADD CONSTRAINT `chk_shop_review_depth` CHECK (`depth` BETWEEN 0 AND 2)'
);
PREPARE NYC_REVIEW_P8_STMT FROM @NYC_REVIEW_P8_SQL;
EXECUTE NYC_REVIEW_P8_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P8_STMT;
