package com.nycreview.service;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.script.RedisScript;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AuthRateLimiterTest {

    @Test
    void blocksAPhoneAtTheFailureLimitWithoutConsumingTheIpBudget() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked")
        ValueOperations<String, String> values = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(values);
        when(values.get(anyString())).thenReturn("5");

        AuthRateLimiter limiter = new AuthRateLimiter(redis);

        assertFalse(limiter.allowLoginAttempt("+12125550123", "203.0.113.9"));
        verify(redis, never()).execute(any(RedisScript.class), anyList(), any(Object[].class));
    }

    @Test
    void hashesIdentifiersAndUsesAnAtomicExpiringCounter() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        when(redis.execute(any(RedisScript.class), anyList(), any(Object[].class))).thenReturn(1L);
        AuthRateLimiter limiter = new AuthRateLimiter(redis);

        assertTrue(limiter.allowRegistration("203.0.113.9"));

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<String>> keys = ArgumentCaptor.forClass(List.class);
        verify(redis).execute(any(RedisScript.class), keys.capture(), any(Object[].class));
        String redisKey = keys.getValue().get(0);
        assertTrue(redisKey.startsWith("auth:register:ip:"));
        assertFalse(redisKey.contains("203.0.113.9"));
        assertNotEquals(AuthRateLimiter.sha256("198.51.100.4"),
                AuthRateLimiter.sha256("203.0.113.9"));
    }
}
