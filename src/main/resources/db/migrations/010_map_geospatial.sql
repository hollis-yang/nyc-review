-- P7 official NYC Neighborhood Tabulation Area (NTA) map schema.
-- This migration is additive and idempotent. It does not assign or delete shop data.
-- Run build_neighborhood_import.py after applying this schema and importing the matching dataset.
-- The legacy shop schema uses utf8mb4_general_ci. Keep every P7 text column on the same
-- collation so data_version and neighborhood joins also work when MySQL 8.4 defaults to
-- utf8mb4_0900_ai_ci.

SET NAMES utf8mb4 COLLATE utf8mb4_general_ci;

SET @NYC_REVIEW_P7_SQL = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tb_shop' AND COLUMN_NAME = 'legacy_area'
    ),
    'SET @NYC_REVIEW_P7_NOOP = 0',
    'ALTER TABLE `tb_shop` ADD COLUMN `legacy_area` VARCHAR(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL AFTER `area`'
);
PREPARE NYC_REVIEW_P7_STMT FROM @NYC_REVIEW_P7_SQL;
EXECUTE NYC_REVIEW_P7_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P7_STMT;

SET @NYC_REVIEW_P7_SQL = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tb_shop' AND COLUMN_NAME = 'neighborhood_code'
    ),
    'SET @NYC_REVIEW_P7_NOOP = 0',
    'ALTER TABLE `tb_shop` ADD COLUMN `neighborhood_code` VARCHAR(8) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL AFTER `legacy_area`'
);
PREPARE NYC_REVIEW_P7_STMT FROM @NYC_REVIEW_P7_SQL;
EXECUTE NYC_REVIEW_P7_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P7_STMT;

SET @NYC_REVIEW_P7_SQL = IF(
    EXISTS(
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tb_shop' AND INDEX_NAME = 'idx_shop_map_filter'
    ),
    'SET @NYC_REVIEW_P7_NOOP = 0',
    'ALTER TABLE `tb_shop` ADD INDEX `idx_shop_map_filter` (`data_version`, `type_id`, `neighborhood_code`, `x`, `y`)'
);
PREPARE NYC_REVIEW_P7_STMT FROM @NYC_REVIEW_P7_SQL;
EXECUTE NYC_REVIEW_P7_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P7_STMT;

CREATE TABLE IF NOT EXISTS `tb_neighborhood` (
    `code` VARCHAR(8) NOT NULL COMMENT 'Official 2020 NTA code',
    `name` VARCHAR(160) NOT NULL,
    `borough` VARCHAR(64) NOT NULL,
    `nta_type` VARCHAR(8) NOT NULL COMMENT '0=residential; 9=special/non-residential in the source dataset',
    `cdta_code` VARCHAR(8) NOT NULL,
    `centroid_x` DOUBLE NOT NULL COMMENT 'Longitude used for the low-zoom count marker',
    `centroid_y` DOUBLE NOT NULL COMMENT 'Latitude used for the low-zoom count marker',
    `min_x` DOUBLE NOT NULL,
    `min_y` DOUBLE NOT NULL,
    `max_x` DOUBLE NOT NULL,
    `max_y` DOUBLE NOT NULL,
    `boundary` MULTIPOLYGON NOT NULL SRID 4326,
    `source_dataset_id` VARCHAR(32) NOT NULL,
    `source_version` VARCHAR(32) NOT NULL,
    `source_url` VARCHAR(768) NOT NULL,
    `source_revision_date` DATE NOT NULL,
    `source_fetched_at` DATETIME NOT NULL,
    `source_sha256` CHAR(64) NOT NULL,
    `active` TINYINT(1) NOT NULL DEFAULT 1,
    `create_time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `update_time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`code`),
    KEY `idx_neighborhood_borough_name` (`borough`, `name`),
    KEY `idx_neighborhood_source` (`source_dataset_id`, `source_version`),
    SPATIAL KEY `idx_neighborhood_boundary` (`boundary`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `tb_neighborhood_alias` (
    `borough` VARCHAR(64) NOT NULL,
    `alias` VARCHAR(160) NOT NULL,
    `neighborhood_code` VARCHAR(8) NOT NULL,
    `alias_type` VARCHAR(32) NOT NULL COMMENT 'OFFICIAL or LEGACY_AREA',
    `create_time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`borough`, `alias`, `neighborhood_code`),
    KEY `idx_neighborhood_alias_code` (`neighborhood_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `tb_shop_map_location` (
    `shop_id` BIGINT UNSIGNED NOT NULL,
    `data_version` VARCHAR(32) NOT NULL,
    `location` POINT NOT NULL SRID 4326,
    `neighborhood_code` VARCHAR(8) NULL,
    `assignment_method` VARCHAR(32) NOT NULL COMMENT 'POINT_IN_POLYGON or UNASSIGNED',
    `source_area` VARCHAR(128) NULL COMMENT 'Original friendly area; Agent semantics continue to use tb_shop.area',
    `assigned_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`data_version`, `shop_id`),
    KEY `idx_shop_map_neighborhood` (`data_version`, `neighborhood_code`, `shop_id`),
    SPATIAL KEY `idx_shop_map_location` (`location`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `tb_neighborhood_shop_count` (
    `data_version` VARCHAR(32) NOT NULL,
    `neighborhood_code` VARCHAR(8) NOT NULL,
    `type_id` BIGINT UNSIGNED NOT NULL,
    `shop_count` INT UNSIGNED NOT NULL,
    `centroid_x` DOUBLE NOT NULL,
    `centroid_y` DOUBLE NOT NULL,
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`data_version`, `neighborhood_code`, `type_id`),
    KEY `idx_neighborhood_count_filter` (`data_version`, `type_id`, `neighborhood_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `tb_borough_shop_count` (
    `data_version` VARCHAR(32) NOT NULL,
    `borough` VARCHAR(64) NOT NULL,
    `type_id` BIGINT UNSIGNED NOT NULL,
    `shop_count` INT UNSIGNED NOT NULL,
    `assigned_count` INT UNSIGNED NOT NULL,
    `unassigned_count` INT UNSIGNED NOT NULL,
    `centroid_x` DOUBLE NOT NULL,
    `centroid_y` DOUBLE NOT NULL,
    `min_x` DOUBLE NOT NULL,
    `min_y` DOUBLE NOT NULL,
    `max_x` DOUBLE NOT NULL,
    `max_y` DOUBLE NOT NULL,
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`data_version`, `borough`, `type_id`),
    KEY `idx_borough_count_filter` (`data_version`, `type_id`, `borough`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `tb_map_data_import` (
    `dataset_sha256` CHAR(64) NOT NULL,
    `data_version` VARCHAR(32) NOT NULL,
    `shop_ids_sha256` CHAR(64) NOT NULL,
    `nta_source_sha256` CHAR(64) NOT NULL,
    `nta_source_version` VARCHAR(32) NOT NULL,
    `shop_count` INT UNSIGNED NOT NULL,
    `assigned_count` INT UNSIGNED NOT NULL,
    `unassigned_count` INT UNSIGNED NOT NULL,
    `assignment_methods` JSON NOT NULL,
    `active` TINYINT(1) NOT NULL DEFAULT 1,
    `imported_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`dataset_sha256`, `nta_source_sha256`),
    KEY `idx_map_import_active` (`active`, `data_version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- CREATE TABLE IF NOT EXISTS cannot repair tables created by the previous migration.
-- Convert existing textual columns only when needed; this keeps reruns idempotent and
-- also fixes runtime map joins, not just the generated import statement.
SET @NYC_REVIEW_P7_SQL = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tb_neighborhood'
          AND COLLATION_NAME IS NOT NULL AND COLLATION_NAME <> 'utf8mb4_general_ci'
    ),
    'ALTER TABLE `tb_neighborhood` CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci',
    'SET @NYC_REVIEW_P7_NOOP = 0'
);
PREPARE NYC_REVIEW_P7_STMT FROM @NYC_REVIEW_P7_SQL;
EXECUTE NYC_REVIEW_P7_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P7_STMT;

SET @NYC_REVIEW_P7_SQL = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tb_neighborhood_alias'
          AND COLLATION_NAME IS NOT NULL AND COLLATION_NAME <> 'utf8mb4_general_ci'
    ),
    'ALTER TABLE `tb_neighborhood_alias` CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci',
    'SET @NYC_REVIEW_P7_NOOP = 0'
);
PREPARE NYC_REVIEW_P7_STMT FROM @NYC_REVIEW_P7_SQL;
EXECUTE NYC_REVIEW_P7_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P7_STMT;

SET @NYC_REVIEW_P7_SQL = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tb_shop_map_location'
          AND COLLATION_NAME IS NOT NULL AND COLLATION_NAME <> 'utf8mb4_general_ci'
    ),
    'ALTER TABLE `tb_shop_map_location` CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci',
    'SET @NYC_REVIEW_P7_NOOP = 0'
);
PREPARE NYC_REVIEW_P7_STMT FROM @NYC_REVIEW_P7_SQL;
EXECUTE NYC_REVIEW_P7_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P7_STMT;

SET @NYC_REVIEW_P7_SQL = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tb_neighborhood_shop_count'
          AND COLLATION_NAME IS NOT NULL AND COLLATION_NAME <> 'utf8mb4_general_ci'
    ),
    'ALTER TABLE `tb_neighborhood_shop_count` CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci',
    'SET @NYC_REVIEW_P7_NOOP = 0'
);
PREPARE NYC_REVIEW_P7_STMT FROM @NYC_REVIEW_P7_SQL;
EXECUTE NYC_REVIEW_P7_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P7_STMT;

SET @NYC_REVIEW_P7_SQL = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tb_borough_shop_count'
          AND COLLATION_NAME IS NOT NULL AND COLLATION_NAME <> 'utf8mb4_general_ci'
    ),
    'ALTER TABLE `tb_borough_shop_count` CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci',
    'SET @NYC_REVIEW_P7_NOOP = 0'
);
PREPARE NYC_REVIEW_P7_STMT FROM @NYC_REVIEW_P7_SQL;
EXECUTE NYC_REVIEW_P7_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P7_STMT;

SET @NYC_REVIEW_P7_SQL = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tb_map_data_import'
          AND COLLATION_NAME IS NOT NULL AND COLLATION_NAME <> 'utf8mb4_general_ci'
    ),
    'ALTER TABLE `tb_map_data_import` CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci',
    'SET @NYC_REVIEW_P7_NOOP = 0'
);
PREPARE NYC_REVIEW_P7_STMT FROM @NYC_REVIEW_P7_SQL;
EXECUTE NYC_REVIEW_P7_STMT;
DEALLOCATE PREPARE NYC_REVIEW_P7_STMT;
