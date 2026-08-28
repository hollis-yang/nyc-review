-- Remove pre-NYC archives and one-time migration artifacts from nyc_review.
-- Back up the listed tables before applying this migration to a non-disposable database.
-- The migration is idempotent and does not delete active NYC merchants, content,
-- user assets, vouchers, orders, provenance history, or map projections.

SET NAMES utf8mb4;

-- Avoid a unique-key conflict if a partially renamed database contains both labels.
DELETE legacy_observation
FROM tb_shop_field_observation AS legacy_observation
INNER JOIN tb_shop_field_observation AS current_observation
    ON current_observation.shop_id = legacy_observation.shop_id
    AND current_observation.field_name = legacy_observation.field_name
    AND current_observation.content_sha256 = legacy_observation.content_sha256
    AND current_observation.provider = 'NYC_REVIEW_GENERATED'
WHERE legacy_observation.provider = 'HMDP_GENERATED';

UPDATE tb_shop_field_observation
SET provider = 'NYC_REVIEW_GENERATED'
WHERE provider = 'HMDP_GENERATED';

DROP TABLE IF EXISTS legacy_hangzhou_tb_blog;
DROP TABLE IF EXISTS legacy_hangzhou_tb_blog_comments;
DROP TABLE IF EXISTS legacy_hangzhou_tb_follow;
DROP TABLE IF EXISTS legacy_hangzhou_tb_seckill_voucher;
DROP TABLE IF EXISTS legacy_hangzhou_tb_shop;
DROP TABLE IF EXISTS legacy_hangzhou_tb_shop_review;
DROP TABLE IF EXISTS legacy_hangzhou_tb_shop_type;
DROP TABLE IF EXISTS legacy_hangzhou_tb_sign;
DROP TABLE IF EXISTS legacy_hangzhou_tb_user;
DROP TABLE IF EXISTS legacy_hangzhou_tb_user_info;
DROP TABLE IF EXISTS legacy_hangzhou_tb_voucher;
DROP TABLE IF EXISTS legacy_hangzhou_tb_voucher_order;
DROP TABLE IF EXISTS tb_legacy_archive_state;
DROP TABLE IF EXISTS tb_sign;
DROP TABLE IF EXISTS tb_voucher_order_conflict_archive;
