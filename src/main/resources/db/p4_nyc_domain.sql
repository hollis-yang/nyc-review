-- P1 NYC domain schema. Apply once after p3_nyc_compatibility.sql.
-- This migration is additive: it does not replace or delete the active dataset.

ALTER TABLE tb_shop_type
    ADD COLUMN slug VARCHAR(64) NULL AFTER name;

ALTER TABLE tb_shop
    ADD COLUMN subcategory_id BIGINT UNSIGNED NULL AFTER type_id,
    ADD COLUMN borough VARCHAR(64) NULL AFTER area,
    ADD COLUMN description VARCHAR(1024) NULL AFTER address,
    ADD COLUMN price_level TINYINT UNSIGNED NULL AFTER avg_price,
    ADD COLUMN timezone VARCHAR(64) NOT NULL DEFAULT 'America/New_York' AFTER open_hours,
    ADD COLUMN source_type VARCHAR(16) NOT NULL DEFAULT 'LEGACY' AFTER timezone,
    ADD COLUMN data_version VARCHAR(32) NULL AFTER source_type,
    ADD INDEX idx_shop_subcategory (subcategory_id),
    ADD INDEX idx_shop_data_version (data_version),
    ADD INDEX idx_shop_area_type (area, type_id);

CREATE TABLE IF NOT EXISTS tb_shop_subcategory (
    id BIGINT UNSIGNED NOT NULL,
    type_id BIGINT UNSIGNED NOT NULL,
    name VARCHAR(64) NOT NULL,
    slug VARCHAR(64) NOT NULL,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_shop_subcategory_slug (type_id, slug),
    KEY idx_shop_subcategory_type (type_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS tb_shop_tag (
    shop_id BIGINT UNSIGNED NOT NULL,
    tag VARCHAR(64) NOT NULL,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (shop_id, tag),
    KEY idx_shop_tag_tag (tag, shop_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS tb_shop_business_hours (
    shop_id BIGINT UNSIGNED NOT NULL,
    day_of_week TINYINT UNSIGNED NOT NULL COMMENT '1=Monday, 7=Sunday',
    closed TINYINT(1) NOT NULL DEFAULT 0,
    open_time TIME NULL,
    close_time TIME NULL,
    closes_next_day TINYINT(1) NOT NULL DEFAULT 0,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (shop_id, day_of_week),
    KEY idx_shop_hours_day (day_of_week, closed)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS tb_data_import (
    import_id CHAR(64) NOT NULL COMMENT 'dataset SHA-256',
    data_version VARCHAR(32) NOT NULL,
    profile VARCHAR(16) NOT NULL,
    seed BIGINT NOT NULL,
    dataset_sha256 CHAR(64) NOT NULL,
    shop_count INT UNSIGNED NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (import_id),
    UNIQUE KEY uk_data_import_sha256 (dataset_sha256),
    KEY idx_data_import_active (active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
