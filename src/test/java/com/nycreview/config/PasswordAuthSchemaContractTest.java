package com.nycreview.config;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PasswordAuthSchemaContractTest {

    @Test
    void migrationKeepsE164UniqueAndConvertsBlankPasswordsToNull() throws IOException {
        try (InputStream stream = getClass().getClassLoader()
                .getResourceAsStream("db/auth_password_registration.sql")) {
            assertNotNull(stream);
            String migration = new String(stream.readAllBytes(), StandardCharsets.UTF_8);

            assertTrue(migration.contains("VARCHAR(20)"));
            assertTrue(migration.contains("uk_user_phone"));
            assertTrue(migration.contains("CONCAT('+86', legacy_user.phone)"));
            assertTrue(migration.contains("SET password = NULL"));
            assertTrue(migration.contains("indexed_columns = 1"));
            assertFalse(migration.contains("DROP TABLE tb_user"));
        }
    }
}
