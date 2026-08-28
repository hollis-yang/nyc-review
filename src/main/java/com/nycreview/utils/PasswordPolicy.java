package com.nycreview.utils;

import java.nio.charset.StandardCharsets;

public final class PasswordPolicy {

    public static final int MIN_CHARACTERS = 8;
    public static final int MAX_CHARACTERS = 64;
    private static final int BCRYPT_MAX_BYTES = 72;

    private PasswordPolicy() {
    }

    public static void validateLoginInput(String password) {
        if (password == null || password.isEmpty()) {
            throw new IllegalArgumentException("Password is required");
        }
        int characters = password.codePointCount(0, password.length());
        int bytes = password.getBytes(StandardCharsets.UTF_8).length;
        if (characters > MAX_CHARACTERS || bytes > BCRYPT_MAX_BYTES) {
            throw new IllegalArgumentException("Invalid phone number or password");
        }
    }

    public static void validate(String password) {
        if (password == null) {
            throw new IllegalArgumentException("Password is required");
        }
        int characters = password.codePointCount(0, password.length());
        int bytes = password.getBytes(StandardCharsets.UTF_8).length;
        if (characters < MIN_CHARACTERS
                || characters > MAX_CHARACTERS
                || bytes > BCRYPT_MAX_BYTES
                || !containsLetterDigitAndSpecialCharacter(password)) {
            throw new IllegalArgumentException(
                    "Password must be 8-64 characters and include a letter, a number, and a special character"
            );
        }
    }

    private static boolean containsLetterDigitAndSpecialCharacter(String password) {
        boolean letter = false;
        boolean digit = false;
        boolean special = false;
        for (int offset = 0; offset < password.length();) {
            int codePoint = password.codePointAt(offset);
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
