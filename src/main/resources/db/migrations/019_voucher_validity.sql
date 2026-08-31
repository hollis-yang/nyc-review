-- Add an explicit post-acquisition validity period to every voucher.
-- Existing promotions receive a deterministic value between 7 and 183 days.

SET NAMES utf8mb4;

SET @NYC_REVIEW_ADD_VOUCHER_VALIDITY = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'tb_voucher'
          AND COLUMN_NAME = 'valid_days'
    ),
    'SET @NYC_REVIEW_VOUCHER_VALIDITY_READY = 1',
    'ALTER TABLE tb_voucher ADD COLUMN valid_days SMALLINT UNSIGNED NULL AFTER status'
);
PREPARE nyc_review_voucher_validity_statement FROM @NYC_REVIEW_ADD_VOUCHER_VALIDITY;
EXECUTE nyc_review_voucher_validity_statement;
DEALLOCATE PREPARE nyc_review_voucher_validity_statement;

UPDATE tb_voucher
SET valid_days = 7 + MOD(CRC32(CONCAT('voucher-validity-v1:', id)), 177)
WHERE valid_days IS NULL OR valid_days < 7 OR valid_days > 183;

ALTER TABLE tb_voucher
    MODIFY COLUMN valid_days SMALLINT UNSIGNED NOT NULL DEFAULT 30
    COMMENT 'Days valid after acquisition';
