-- P13 local/external review aggregate separation.
-- Additive and safe to rerun after p11_p2_p3_shop_enrichment.sql.

SET NAMES utf8mb4 COLLATE utf8mb4_general_ci;

SET @NYC_REVIEW_P13_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop' AND COLUMN_NAME='local_review_count'),
    'SET @NYC_REVIEW_P13_NOOP = 0',
    'ALTER TABLE `tb_shop` ADD COLUMN `local_review_count` INT UNSIGNED NOT NULL DEFAULT 0 AFTER `comments`'
);
PREPARE NYC_REVIEW_P13_STMT FROM @NYC_REVIEW_P13_SQL; EXECUTE NYC_REVIEW_P13_STMT; DEALLOCATE PREPARE NYC_REVIEW_P13_STMT;

SET @NYC_REVIEW_P13_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop' AND COLUMN_NAME='local_score'),
    'SET @NYC_REVIEW_P13_NOOP = 0',
    'ALTER TABLE `tb_shop` ADD COLUMN `local_score` INT UNSIGNED NULL AFTER `score`'
);
PREPARE NYC_REVIEW_P13_STMT FROM @NYC_REVIEW_P13_SQL; EXECUTE NYC_REVIEW_P13_STMT; DEALLOCATE PREPARE NYC_REVIEW_P13_STMT;

SET @NYC_REVIEW_P13_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop' AND COLUMN_NAME='external_score'),
    'SET @NYC_REVIEW_P13_NOOP = 0',
    'ALTER TABLE `tb_shop` ADD COLUMN `external_score` INT UNSIGNED NULL AFTER `rating_count`'
);
PREPARE NYC_REVIEW_P13_STMT FROM @NYC_REVIEW_P13_SQL; EXECUTE NYC_REVIEW_P13_STMT; DEALLOCATE PREPARE NYC_REVIEW_P13_STMT;

SET @NYC_REVIEW_P13_SQL = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_shop' AND COLUMN_NAME='external_rating_count'),
    'SET @NYC_REVIEW_P13_NOOP = 0',
    'ALTER TABLE `tb_shop` ADD COLUMN `external_rating_count` INT UNSIGNED NULL AFTER `external_score`'
);
PREPARE NYC_REVIEW_P13_STMT FROM @NYC_REVIEW_P13_SQL; EXECUTE NYC_REVIEW_P13_STMT; DEALLOCATE PREPARE NYC_REVIEW_P13_STMT;

-- Recompute local aggregates from browsable depth-zero rows instead of trusting
-- a legacy counter. USER_SUBMITTED rows and generated rows are both retained.
UPDATE `tb_shop` shop
LEFT JOIN (
    SELECT
        `shop_id`,
        COUNT(*) AS `root_count`,
        ROUND(AVG(`rating`) * 10) AS `root_score`
    FROM `tb_shop_review`
    WHERE (`parent_id` IS NULL OR `parent_id` = 0)
      AND `rating` BETWEEN 1 AND 5
    GROUP BY `shop_id`
) local_aggregate ON local_aggregate.`shop_id` = shop.`id`
SET shop.`local_review_count` = COALESCE(local_aggregate.`root_count`, 0),
    shop.`comments` = COALESCE(local_aggregate.`root_count`, 0),
    shop.`local_score` = local_aggregate.`root_score`;

-- Keep external source observations separate. NYC_REVIEW_GENERATED observations are
-- intentionally excluded because they describe the local test corpus.
UPDATE `tb_shop` shop
SET shop.`external_score` = (
        SELECT ROUND(CAST(JSON_UNQUOTE(observation.`value_json`) AS DECIMAL(6,3)) * 10)
        FROM `tb_shop_field_observation` observation
        WHERE observation.`shop_id` = shop.`id`
          AND observation.`field_name` = 'rating'
          AND observation.`provider` <> 'NYC_REVIEW_GENERATED'
        ORDER BY observation.`source_priority` DESC, observation.`observed_at` DESC, observation.`id` DESC
        LIMIT 1
    ),
    shop.`external_rating_count` = (
        SELECT CAST(JSON_UNQUOTE(observation.`value_json`) AS UNSIGNED)
        FROM `tb_shop_field_observation` observation
        WHERE observation.`shop_id` = shop.`id`
          AND observation.`field_name` = 'ratingCount'
          AND observation.`provider` <> 'NYC_REVIEW_GENERATED'
        ORDER BY observation.`source_priority` DESC, observation.`observed_at` DESC, observation.`id` DESC
        LIMIT 1
    );

-- score remains the compatibility display score; 20 local roots are enough to
-- prefer the local aggregate. rating_count remains an external-only alias for
-- older Agent clients.
UPDATE `tb_shop`
SET `score` = COALESCE(`local_score`, `external_score`, `score`),
    `rating_count` = `external_rating_count`;
