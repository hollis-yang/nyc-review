package com.nycreview.utils;

import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Component;

import java.util.UUID;

@Component
public class RecoveryKeyEncoder {

    private final BCryptPasswordEncoder bcrypt = new BCryptPasswordEncoder(12);
    private final String dummyHash = bcrypt.encode(UUID.randomUUID().toString());

    public String encode(String recoveryKey) {
        RecoveryKeyPolicy.validate(recoveryKey);
        return bcrypt.encode(recoveryKey);
    }

    /** Always performs a BCrypt comparison, including for unknown accounts. */
    public boolean matchesOrDummy(String encodedRecoveryKey, String recoveryKey) {
        String candidateHash = encodedRecoveryKey == null || encodedRecoveryKey.isBlank()
                ? dummyHash
                : encodedRecoveryKey;
        String candidateKey = recoveryKey == null ? "" : recoveryKey;
        try {
            return bcrypt.matches(candidateKey, candidateHash)
                    && encodedRecoveryKey != null
                    && !encodedRecoveryKey.isBlank();
        } catch (IllegalArgumentException ignored) {
            return false;
        }
    }
}
