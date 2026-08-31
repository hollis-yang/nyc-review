-- User-level likes for shop reviews and replies.
-- Safe to rerun against an existing database.

CREATE TABLE IF NOT EXISTS `tb_shop_review_like` (
  `review_id` BIGINT UNSIGNED NOT NULL,
  `user_id` BIGINT UNSIGNED NOT NULL,
  `create_time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`review_id`, `user_id`),
  KEY `idx_shop_review_like_user` (`user_id`, `create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
