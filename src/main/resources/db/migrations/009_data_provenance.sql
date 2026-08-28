-- P6 shop provenance. Apply once after p7_p5_mcp_ui.sql and before importing nyc-mock-v2/nyc-hybrid-v1.
-- The public-source fields describe establishment identity only; synthetic_fields names all generated fields.

ALTER TABLE tb_shop
    ADD COLUMN external_id VARCHAR(160) NULL AFTER source_type,
    ADD COLUMN source_name VARCHAR(160) NULL AFTER external_id,
    ADD COLUMN source_url VARCHAR(768) NULL AFTER source_name,
    ADD COLUMN source_fetched_at DATETIME NULL AFTER source_url,
    ADD COLUMN synthetic_fields JSON NULL AFTER source_fetched_at,
    ADD UNIQUE KEY uk_shop_source_external (source_type, external_id),
    ADD INDEX idx_shop_source_type (source_type),
    ADD INDEX idx_shop_source_fetched_at (source_fetched_at);
