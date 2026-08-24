-- P2/P3 merchant field enrichment and merchant-specific image metadata.
-- Additive and safe to rerun after p10_p8_real_content.sql.

SET NAMES utf8mb4 COLLATE utf8mb4_general_ci;

-- The legacy table started with ROW_FORMAT=COMPACT and later accumulated
-- several large utf8mb4 VARCHAR columns. Move unindexed long text off-page
-- before adding more enrichment fields, otherwise MySQL can reject the next
-- ALTER with ERROR 1118 (row size too large). This is safe to rerun after a
-- partially completed P11 migration.
ALTER TABLE `tb_shop`
    ROW_FORMAT=DYNAMIC,
    MODIFY COLUMN `images` TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL
        COMMENT 'Compatibility projection of ordered resolved image URLs',
    MODIFY COLUMN `description` TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL
        COMMENT 'Resolved merchant description',
    MODIFY COLUMN `source_url` TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL
        COMMENT 'Public source page for the merchant identity';

ALTER TABLE `tb_shop_image`
    ROW_FORMAT=DYNAMIC,
    MODIFY COLUMN `display_url` TEXT NOT NULL
        COMMENT 'Resolved attributed merchant-specific or fallback image URL',
    MODIFY COLUMN `source_page_url` TEXT NULL
        COMMENT 'Attribution or source page rather than only the image bytes',
    MODIFY COLUMN `license_url` TEXT NULL;

CREATE TABLE IF NOT EXISTS `tb_shop_source_match` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `shop_id` BIGINT UNSIGNED NOT NULL,
    `provider` VARCHAR(32) NOT NULL,
    `external_id` VARCHAR(255) NOT NULL,
    `source_url` VARCHAR(1024) NULL,
    `matched_fields` JSON NOT NULL,
    `match_score` DECIMAL(6,5) NOT NULL,
    `match_method` VARCHAR(32) NOT NULL,
    `observed_at` DATETIME NOT NULL,
    `snapshot_version` VARCHAR(64) NOT NULL,
    `active` TINYINT(1) NOT NULL DEFAULT 1,
    `create_time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `update_time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_shop_source_match` (`shop_id`, `provider`, `external_id`, `snapshot_version`),
    KEY `idx_source_match_provider_external` (`provider`, `external_id`),
    KEY `idx_source_match_shop_active` (`shop_id`, `active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `tb_shop_field_observation` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `shop_id` BIGINT UNSIGNED NOT NULL,
    `field_name` VARCHAR(64) NOT NULL,
    `value_json` JSON NOT NULL,
    `provider` VARCHAR(32) NOT NULL,
    `external_id` VARCHAR(255) NULL,
    `observed_at` DATETIME NOT NULL,
    `expires_at` DATETIME NULL,
    `match_score` DECIMAL(6,5) NOT NULL,
    `source_priority` SMALLINT UNSIGNED NOT NULL,
    `content_sha256` CHAR(64) NOT NULL,
    `snapshot_version` VARCHAR(64) NOT NULL,
    `create_time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_shop_field_observation` (`shop_id`, `field_name`, `provider`, `content_sha256`),
    KEY `idx_field_observation_resolve` (`shop_id`, `field_name`, `source_priority`, `observed_at`),
    KEY `idx_field_observation_snapshot` (`snapshot_version`, `provider`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- MySQL 8 has no portable ADD COLUMN IF NOT EXISTS across supported minor
-- versions, so each additive column is guarded through information_schema.
SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop' AND COLUMN_NAME='phone'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop` ADD COLUMN `phone` VARCHAR(64) NULL AFTER `open_hours`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop' AND COLUMN_NAME='website'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop` ADD COLUMN `website` TEXT NULL AFTER `phone`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop' AND COLUMN_NAME='reservation_url'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop` ADD COLUMN `reservation_url` TEXT NULL AFTER `website`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop' AND COLUMN_NAME='business_status'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop` ADD COLUMN `business_status` VARCHAR(32) NOT NULL DEFAULT ''OPERATIONAL'' AFTER `reservation_url`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop' AND COLUMN_NAME='rating_count'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop` ADD COLUMN `rating_count` INT UNSIGNED NULL AFTER `business_status`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop' AND COLUMN_NAME='price_range_text'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop` ADD COLUMN `price_range_text` VARCHAR(32) NULL AFTER `rating_count`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop' AND COLUMN_NAME='health_grade'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop` ADD COLUMN `health_grade` VARCHAR(8) NULL AFTER `price_range_text`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop' AND COLUMN_NAME='last_enriched_at'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop` ADD COLUMN `last_enriched_at` DATETIME NULL AFTER `health_grade`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_image' AND COLUMN_NAME='match_type'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop_image` ADD COLUMN `match_type` VARCHAR(32) NOT NULL DEFAULT ''CATEGORY_FALLBACK'' AFTER `image_type`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_image' AND COLUMN_NAME='is_primary'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop_image` ADD COLUMN `is_primary` TINYINT(1) NOT NULL DEFAULT 0 AFTER `match_type`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_image' AND COLUMN_NAME='display_order'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop_image` ADD COLUMN `display_order` SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER `is_primary`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_image' AND COLUMN_NAME='width'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop_image` ADD COLUMN `width` INT UNSIGNED NULL AFTER `display_order`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_image' AND COLUMN_NAME='height'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop_image` ADD COLUMN `height` INT UNSIGNED NULL AFTER `width`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_image' AND COLUMN_NAME='content_sha256'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop_image` ADD COLUMN `content_sha256` CHAR(64) NULL AFTER `height`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_image' AND COLUMN_NAME='last_checked_at'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop_image` ADD COLUMN `last_checked_at` DATETIME NULL AFTER `content_sha256`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_image' AND COLUMN_NAME='availability_status'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop_image` ADD COLUMN `availability_status` VARCHAR(24) NOT NULL DEFAULT ''AVAILABLE'' AFTER `last_checked_at`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop_image' AND COLUMN_NAME='cached_url'),
    'SET @HMDP_P11_NOOP = 0',
    'ALTER TABLE `tb_shop_image` ADD COLUMN `cached_url` TEXT NULL AFTER `availability_status`'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;

SET @HMDP_P11_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop' AND INDEX_NAME='idx_shop_status_type'),
    'SET @HMDP_P11_NOOP = 0',
    'CREATE INDEX `idx_shop_status_type` ON `tb_shop` (`business_status`, `type_id`)'
);
PREPARE HMDP_P11_STMT FROM @HMDP_P11_SQL; EXECUTE HMDP_P11_STMT; DEALLOCATE PREPARE HMDP_P11_STMT;
