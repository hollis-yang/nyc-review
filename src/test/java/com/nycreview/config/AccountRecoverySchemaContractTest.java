package com.nycreview.config;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AccountRecoverySchemaContractTest {

    @Test
    void migrationAddsOnlyAHashColumnAndIsSafeToRerun() throws IOException {
        try (InputStream stream = getClass().getClassLoader()
                .getResourceAsStream("db/migrations/021_account_recovery.sql")) {
            assertNotNull(stream);
            String migration = new String(stream.readAllBytes(), StandardCharsets.UTF_8);

            assertTrue(migration.contains("recovery_key_hash VARCHAR(100)"));
            assertTrue(migration.contains("information_schema.COLUMNS"));
            assertTrue(migration.contains("BCrypt recovery-key hash"));
            assertFalse(migration.toLowerCase().contains("recovery_key VARCHAR"));
            assertFalse(migration.contains("DROP TABLE"));
        }
    }
}
