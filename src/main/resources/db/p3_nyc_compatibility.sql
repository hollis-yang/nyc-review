-- Apply after hmdp_new.sql before importing NYC data.
-- NYC longitude is negative, so the legacy UNSIGNED longitude column must become signed.
-- E.164 phone numbers can include a leading plus sign and up to 15 digits.

ALTER TABLE tb_shop
    MODIFY COLUMN x DOUBLE NOT NULL COMMENT 'longitude',
    MODIFY COLUMN y DOUBLE NOT NULL COMMENT 'latitude';

ALTER TABLE tb_user
    MODIFY COLUMN phone VARCHAR(20) NOT NULL COMMENT 'E.164 phone number';
