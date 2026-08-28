CREATE TABLE IF NOT EXISTS `tb_agent_user_memory` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `memory_key` varchar(64) NOT NULL,
  `memory_value` varchar(500) NOT NULL,
  `source` varchar(32) NOT NULL DEFAULT 'favorite',
  `confidence` decimal(4,3) NOT NULL DEFAULT 1.000,
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_agent_memory_user_key` (`user_id`,`memory_key`),
  KEY `idx_agent_memory_user_time` (`user_id`,`update_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
