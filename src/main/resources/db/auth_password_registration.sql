-- Password-only authentication and international phone registration.
-- Safe to rerun after all dataset imports. Existing blank-password content
-- authors remain readable but cannot authenticate until a password is set.

SET NAMES utf8mb4;

ALTER TABLE tb_user
    MODIFY COLUMN phone VARCHAR(20) NOT NULL COMMENT 'Canonical E.164 phone number',
    MODIFY COLUMN password VARCHAR(100) NULL DEFAULT NULL COMMENT 'BCrypt or transitional legacy password hash';

-- The original application stored mainland-China numbers in national format.
-- Normalize those rows when doing so cannot collide with an existing E.164
-- account. Seeded NYC users already use +1 and are left untouched.
UPDATE tb_user legacy_user
LEFT JOIN tb_user e164_user
    ON e164_user.phone = CONCAT('+86', legacy_user.phone)
   AND e164_user.id <> legacy_user.id
SET legacy_user.phone = CONCAT('+86', legacy_user.phone)
WHERE legacy_user.phone REGEXP '^1[3-9][0-9]{9}$'
  AND e164_user.id IS NULL;

UPDATE tb_user
SET password = NULL
WHERE password IS NOT NULL AND TRIM(password) = '';

SET @NYC_REVIEW_PHONE_INDEX_NAME = (
    SELECT exact_indexes.INDEX_NAME
    FROM (
        SELECT INDEX_NAME,
               COUNT(*) AS indexed_columns,
               SUM(CASE WHEN COLUMN_NAME = 'phone' THEN 1 ELSE 0 END) AS phone_columns
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'tb_user'
          AND NON_UNIQUE = 0
          AND INDEX_NAME <> 'PRIMARY'
        GROUP BY INDEX_NAME
    ) exact_indexes
    WHERE exact_indexes.indexed_columns = 1
      AND exact_indexes.phone_columns = 1
    LIMIT 1
);

SET @NYC_REVIEW_RENAME_PHONE_INDEX = IF(
    @NYC_REVIEW_PHONE_INDEX_NAME IS NULL,
    'ALTER TABLE tb_user ADD UNIQUE KEY uk_user_phone (phone)',
    IF(
        @NYC_REVIEW_PHONE_INDEX_NAME = 'uk_user_phone',
        'SET @NYC_REVIEW_PHONE_INDEX_READY = 1',
        CONCAT('ALTER TABLE tb_user RENAME INDEX `', @NYC_REVIEW_PHONE_INDEX_NAME, '` TO `uk_user_phone`')
    )
);

PREPARE nyc_review_phone_index_statement FROM @NYC_REVIEW_RENAME_PHONE_INDEX;
EXECUTE nyc_review_phone_index_statement;
DEALLOCATE PREPARE nyc_review_phone_index_statement;
