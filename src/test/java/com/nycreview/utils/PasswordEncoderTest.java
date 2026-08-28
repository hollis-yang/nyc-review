package com.nycreview.utils;

import org.junit.jupiter.api.Test;
import org.springframework.util.DigestUtils;

import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PasswordEncoderTest {

    private final PasswordEncoder encoder = new PasswordEncoder();

    @Test
    void newPasswordsUseBcrypt() {
        String encoded = encoder.encode("a-safe-password1!");

        assertTrue(encoded.startsWith("$2"));
        assertTrue(encoder.matches(encoded, "a-safe-password1!"));
        assertFalse(encoder.matches(encoded, "wrong-password"));
        assertFalse(encoder.needsUpgrade(encoded));
    }

    @Test
    void legacySaltedMd5CanBeVerifiedOnlyForUpgrade() {
        String salt = "legacy-salt";
        String raw = "legacy-password";
        String digest = DigestUtils.md5DigestAsHex((raw + salt).getBytes(StandardCharsets.UTF_8));
        String legacy = salt + "@" + digest;

        assertTrue(encoder.matches(legacy, raw));
        assertTrue(encoder.needsUpgrade(legacy));
        assertFalse(encoder.matches(legacy, "wrong-password"));
    }

    @Test
    void rejectsShortAndBcryptOversizedPasswords() {
        assertThrows(IllegalArgumentException.class, () -> encoder.encode("short"));
        assertThrows(IllegalArgumentException.class, () -> encoder.encode("你".repeat(25)));
        assertThrows(IllegalArgumentException.class, () -> encoder.encode("letters-only!"));
        assertThrows(IllegalArgumentException.class, () -> encoder.encode("letters123"));
        assertThrows(IllegalArgumentException.class, () -> encoder.encode("12345678!"));
        assertThrows(IllegalArgumentException.class, () -> encoder.encode("Letters123 "));
        assertTrue(encoder.matches(encoder.encode("安全Password1!"), "安全Password1!"));
    }

    @Test
    void loginStillAllowsShortLegacyPasswordsToBeUpgraded() {
        PasswordPolicy.validateLoginInput("old4");
        assertThrows(IllegalArgumentException.class, () -> PasswordPolicy.validateLoginInput(""));
        assertThrows(IllegalArgumentException.class, () -> PasswordPolicy.validateLoginInput("你".repeat(25)));
    }
}
