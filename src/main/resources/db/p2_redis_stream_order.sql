-- Apply after hmdp_new.sql in the NYC development database.
-- The unique key is the final idempotency guard for Redis Stream redelivery.

ALTER TABLE tb_voucher_order
    ADD UNIQUE KEY uk_voucher_order_user_voucher (user_id, voucher_id);
