package com.nycreview.service;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.HexFormat;
import java.util.Collections;

@Component
public class AuthRateLimiter {

    private static final int PHONE_FAILURE_LIMIT = 5;
    private static final Duration PHONE_FAILURE_WINDOW = Duration.ofMinutes(15);
    private static final int IP_LOGIN_LIMIT = 60;
    private static final Duration IP_LOGIN_WINDOW = Duration.ofMinutes(10);
    private static final int IP_REGISTER_LIMIT = 10;
    private static final Duration IP_REGISTER_WINDOW = Duration.ofHours(1);
    private static final DefaultRedisScript<Long> INCREMENT_WITH_EXPIRY =
            new DefaultRedisScript<>("""
                    local count = redis.call('INCR', KEYS[1])
                    if count == 1 then
                        redis.call('EXPIRE', KEYS[1], ARGV[1])
                    end
                    return count
                    """, Long.class);

    private final StringRedisTemplate redisTemplate;

    public AuthRateLimiter(StringRedisTemplate redisTemplate) {
        this.redisTemplate = redisTemplate;
    }

    public boolean allowLoginAttempt(String phone, String clientAddress) {
        return belowLimit("auth:login:phone:", phone, PHONE_FAILURE_LIMIT)
                && consume("auth:login:ip:", clientAddress, IP_LOGIN_LIMIT, IP_LOGIN_WINDOW) <= IP_LOGIN_LIMIT;
    }

    public void recordLoginFailure(String phone) {
        consume("auth:login:phone:", phone, PHONE_FAILURE_LIMIT, PHONE_FAILURE_WINDOW);
    }

    public void recordLoginSuccess(String phone) {
        redisTemplate.delete(key("auth:login:phone:", phone));
    }

    public boolean allowRegistration(String clientAddress) {
        return consume("auth:register:ip:", clientAddress, IP_REGISTER_LIMIT, IP_REGISTER_WINDOW)
                <= IP_REGISTER_LIMIT;
    }

    private boolean belowLimit(String prefix, String identifier, int limit) {
        String value = redisTemplate.opsForValue().get(key(prefix, identifier));
        if (value == null) {
            return true;
        }
        try {
            return Long.parseLong(value) < limit;
        } catch (NumberFormatException ignored) {
            return false;
        }
    }

    private long consume(String prefix, String identifier, int limit, Duration window) {
        String redisKey = key(prefix, identifier);
        Long count = redisTemplate.execute(
                INCREMENT_WITH_EXPIRY,
                Collections.singletonList(redisKey),
                Long.toString(window.toSeconds())
        );
        return count == null ? limit + 1L : count;
    }

    private String key(String prefix, String identifier) {
        String safeIdentifier = identifier == null || identifier.isBlank() ? "unknown" : identifier;
        return prefix + sha256(safeIdentifier);
    }

    static String sha256(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is unavailable", e);
        }
    }
}
