-- Historical upgrade: enforce one voucher order per user and voucher.
-- The unique key is the final idempotency guard for asynchronous MQ redelivery.
-- The original fixture contains one duplicate user/voucher pair. Stage every
-- non-canonical row temporarily, retain the earliest order, then add the guard
-- idempotently without leaving a permanent migration archive table.

DROP TEMPORARY TABLE IF EXISTS tmp_voucher_order_conflicts;
CREATE TEMPORARY TABLE tmp_voucher_order_conflicts LIKE tb_voucher_order;

START TRANSACTION;

INSERT IGNORE INTO tmp_voucher_order_conflicts
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

DROP TEMPORARY TABLE IF EXISTS tmp_voucher_order_conflicts;

SET @NYC_REVIEW_ADD_ORDER_UNIQUE_INDEX = IF(
    EXISTS(
        SELECT 1
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'tb_voucher_order'
          AND index_name = 'uk_voucher_order_user_voucher'
    ),
    'SET @NYC_REVIEW_ORDER_UNIQUE_INDEX_EXISTS = 1',
    'ALTER TABLE tb_voucher_order ADD UNIQUE KEY uk_voucher_order_user_voucher (user_id, voucher_id)'
);

PREPARE nyc_review_order_unique_index_statement FROM @NYC_REVIEW_ADD_ORDER_UNIQUE_INDEX;
EXECUTE nyc_review_order_unique_index_statement;
DEALLOCATE PREPARE nyc_review_order_unique_index_statement;
