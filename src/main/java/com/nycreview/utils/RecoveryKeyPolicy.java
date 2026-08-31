package com.nycreview.utils;

import java.nio.charset.StandardCharsets;

public final class RecoveryKeyPolicy {

    public static final int MIN_CHARACTERS = 12;
    public static final int MAX_CHARACTERS = 64;
    private static final int BCRYPT_MAX_BYTES = 72;

    private RecoveryKeyPolicy() {
    }

    public static void validate(String recoveryKey) {
        if (!isStrong(recoveryKey)) {
            throw new IllegalArgumentException(
                    "Recovery key must be 12-64 characters and include a letter, a number, and a special character"
            );
        }
    }

    public static boolean isStrong(String recoveryKey) {
        if (recoveryKey == null) {
            return false;
        }
        int characters = recoveryKey.codePointCount(0, recoveryKey.length());
        int bytes = recoveryKey.getBytes(StandardCharsets.UTF_8).length;
        if (characters < MIN_CHARACTERS || characters > MAX_CHARACTERS || bytes > BCRYPT_MAX_BYTES) {
            return false;
        }

        boolean letter = false;
        boolean digit = false;
        boolean special = false;
        for (int offset = 0; offset < recoveryKey.length();) {
            int codePoint = recoveryKey.codePointAt(offset);
            if (Character.isLetter(codePoint)) {
                letter = true;
            } else if (Character.isDigit(codePoint)) {
                digit = true;
            } else if (!Character.isWhitespace(codePoint)) {
                special = true;
            }
            offset += Character.charCount(codePoint);
        }
        return letter && digit && special;
    }
}
