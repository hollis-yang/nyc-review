CREATE TABLE IF NOT EXISTS `tb_shop_favorite` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `shop_id` bigint unsigned NOT NULL,
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_shop_favorite_user_shop` (`user_id`,`shop_id`),
  KEY `idx_shop_favorite_user_time` (`user_id`,`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `tb_saved_itinerary` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `run_id` varchar(64) NOT NULL,
  `title` varchar(120) NOT NULL,
  `content_json` json NOT NULL,
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_saved_itinerary_user_run` (`user_id`,`run_id`),
  KEY `idx_saved_itinerary_user_time` (`user_id`,`update_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `tb_seckill_reminder` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `voucher_id` bigint unsigned NOT NULL,
  `remind_at` datetime NOT NULL,
  `status` varchar(24) NOT NULL DEFAULT 'PENDING',
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_seckill_reminder_user_voucher` (`user_id`,`voucher_id`),
  KEY `idx_seckill_reminder_due` (`status`,`remind_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `tb_agent_action_audit` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `run_id` varchar(64) NOT NULL,
  `action_id` varchar(64) NOT NULL,
  `action_type` varchar(48) NOT NULL,
  `status` varchar(24) NOT NULL,
  `request_json` json NOT NULL,
  `result_json` json DEFAULT NULL,
  `error_message` varchar(500) DEFAULT NULL,
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_agent_action_user_action` (`user_id`,`action_id`),
  KEY `idx_agent_action_run` (`run_id`,`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
