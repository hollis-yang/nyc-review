-- Apply after hmdp_new.sql in the NYC development database.
-- The unique key is the final idempotency guard for Redis Stream redelivery.
-- Legacy fixture data contains one duplicate user/voucher pair. Archive every
-- non-canonical row, retain the earliest order, then add the guard idempotently.

CREATE TABLE IF NOT EXISTS tb_voucher_order_conflict_archive LIKE tb_voucher_order;

START TRANSACTION;

INSERT IGNORE INTO tb_voucher_order_conflict_archive
SELECT duplicate_order.*
FROM tb_voucher_order AS duplicate_order
INNER JOIN tb_voucher_order AS retained_order
    ON duplicate_order.user_id = retained_order.user_id
    AND duplicate_order.voucher_id = retained_order.voucher_id
    AND (
        duplicate_order.create_time > retained_order.create_time
        OR (
            duplicate_order.create_time = retained_order.create_time
            AND duplicate_order.id > retained_order.id
        )
    );

DELETE duplicate_order
FROM tb_voucher_order AS duplicate_order
INNER JOIN tb_voucher_order AS retained_order
    ON duplicate_order.user_id = retained_order.user_id
    AND duplicate_order.voucher_id = retained_order.voucher_id
    AND (
        duplicate_order.create_time > retained_order.create_time
        OR (
            duplicate_order.create_time = retained_order.create_time
            AND duplicate_order.id > retained_order.id
        )
    );

COMMIT;

SET @HMDP_ADD_ORDER_UNIQUE_INDEX = IF(
    EXISTS(
        SELECT 1
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'tb_voucher_order'
          AND index_name = 'uk_voucher_order_user_voucher'
    ),
    'SET @HMDP_ORDER_UNIQUE_INDEX_EXISTS = 1',
    'ALTER TABLE tb_voucher_order ADD UNIQUE KEY uk_voucher_order_user_voucher (user_id, voucher_id)'
);

PREPARE hmdp_order_unique_index_statement FROM @HMDP_ADD_ORDER_UNIQUE_INDEX;
EXECUTE hmdp_order_unique_index_statement;
DEALLOCATE PREPARE hmdp_order_unique_index_statement;
