package com.nycreview.utils;

import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.util.DigestUtils;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** Password hashing with a read-only bridge for the original salted-MD5 format. */
@Component
public class PasswordEncoder {

    private static final String BCRYPT_PREFIX = "$2";
    private final BCryptPasswordEncoder bcrypt = new BCryptPasswordEncoder(12);

    public String encode(String rawPassword) {
        PasswordPolicy.validate(rawPassword);
        return bcrypt.encode(rawPassword);
    }

    public boolean matches(String encodedPassword, String rawPassword) {
        if (encodedPassword == null || encodedPassword.isBlank() || rawPassword == null) {
            return false;
        }
        if (isBcrypt(encodedPassword)) {
            try {
                return bcrypt.matches(rawPassword, encodedPassword);
            } catch (IllegalArgumentException ignored) {
                return false;
            }
        }
        return matchesLegacySaltedMd5(encodedPassword, rawPassword);
    }

    public boolean needsUpgrade(String encodedPassword) {
        return encodedPassword != null && !encodedPassword.isBlank() && !isBcrypt(encodedPassword);
    }

    private boolean isBcrypt(String encodedPassword) {
        return encodedPassword.startsWith(BCRYPT_PREFIX);
    }

    private boolean matchesLegacySaltedMd5(String encodedPassword, String rawPassword) {
        int separator = encodedPassword.indexOf('@');
        if (separator <= 0 || separator == encodedPassword.length() - 1) {
            return false;
        }
        String salt = encodedPassword.substring(0, separator);
        String digest = DigestUtils.md5DigestAsHex(
                (rawPassword + salt).getBytes(StandardCharsets.UTF_8)
        );
        return MessageDigest.isEqual(
                encodedPassword.getBytes(StandardCharsets.UTF_8),
                (salt + "@" + digest).getBytes(StandardCharsets.UTF_8)
        );
    }
}
