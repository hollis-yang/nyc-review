-- User-managed recovery keys for password reset without SMS or email.
-- Only BCrypt hashes are stored; existing accounts remain unset until their
-- owner configures a key after confirming the current password.

SET NAMES utf8mb4;

SET @NYC_REVIEW_ADD_RECOVERY_KEY_HASH = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'tb_user'
          AND COLUMN_NAME = 'recovery_key_hash'
    ),
    'SET @NYC_REVIEW_RECOVERY_KEY_READY = 1',
    'ALTER TABLE tb_user ADD COLUMN recovery_key_hash VARCHAR(100) NULL AFTER password'
);
PREPARE nyc_review_recovery_key_statement FROM @NYC_REVIEW_ADD_RECOVERY_KEY_HASH;
EXECUTE nyc_review_recovery_key_statement;
DEALLOCATE PREPARE nyc_review_recovery_key_statement;

ALTER TABLE tb_user
    MODIFY COLUMN recovery_key_hash VARCHAR(100) NULL DEFAULT NULL
    COMMENT 'BCrypt recovery-key hash';
