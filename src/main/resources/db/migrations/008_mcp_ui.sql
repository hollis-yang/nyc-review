-- P5 UI metadata: use six distinct NYC category icons.
-- This migration is idempotent. Clear Redis key cache:shopType:list after applying it.
UPDATE `tb_shop_type` SET `icon` = '/types/nyc-dining.svg' WHERE `id` = 1;
UPDATE `tb_shop_type` SET `icon` = '/types/nyc-cafe.svg' WHERE `id` = 2;
UPDATE `tb_shop_type` SET `icon` = '/types/nyc-nightlife.svg' WHERE `id` = 3;
UPDATE `tb_shop_type` SET `icon` = '/types/nyc-entertainment.svg' WHERE `id` = 4;
UPDATE `tb_shop_type` SET `icon` = '/types/nyc-wellness.svg' WHERE `id` = 5;
UPDATE `tb_shop_type` SET `icon` = '/types/nyc-beauty.svg' WHERE `id` = 6;
