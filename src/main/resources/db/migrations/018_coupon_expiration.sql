-- Coupon ownership lifecycle for existing and future voucher orders.
-- Existing coupons receive a deterministic 7-183 day validity window from
-- their acquisition time so the migration is safe to rerun.

SET NAMES utf8mb4;

SET @NYC_REVIEW_ADD_COUPON_EXPIRY = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'tb_voucher_order'
          AND COLUMN_NAME = 'expires_at'
    ),
    'SET @NYC_REVIEW_COUPON_EXPIRY_READY = 1',
    'ALTER TABLE tb_voucher_order ADD COLUMN expires_at DATETIME NULL AFTER create_time'
);
PREPARE nyc_review_coupon_expiry_statement FROM @NYC_REVIEW_ADD_COUPON_EXPIRY;
EXECUTE nyc_review_coupon_expiry_statement;
DEALLOCATE PREPARE nyc_review_coupon_expiry_statement;

UPDATE tb_voucher_order
SET expires_at = DATE_ADD(
    create_time,
    INTERVAL (7 + MOD(CRC32(CONCAT(id, ':', user_id, ':', voucher_id)), 177)) DAY
)
WHERE expires_at IS NULL;

SET @NYC_REVIEW_ADD_COUPON_EXPIRY_INDEX = IF(
    EXISTS(
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'tb_voucher_order'
          AND INDEX_NAME = 'idx_voucher_order_user_expiry'
    ),
    'SET @NYC_REVIEW_COUPON_EXPIRY_INDEX_READY = 1',
    'ALTER TABLE tb_voucher_order ADD KEY idx_voucher_order_user_expiry (user_id, expires_at, create_time)'
);
PREPARE nyc_review_coupon_expiry_index_statement FROM @NYC_REVIEW_ADD_COUPON_EXPIRY_INDEX;
EXECUTE nyc_review_coupon_expiry_index_statement;
DEALLOCATE PREPARE nyc_review_coupon_expiry_index_statement;
