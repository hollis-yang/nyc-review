package com.nycreview.config;

import org.junit.jupiter.api.Test;
import org.redisson.config.Config;
import org.springframework.boot.autoconfigure.data.redis.RedisProperties;

import java.io.IOException;

import static org.junit.jupiter.api.Assertions.assertTrue;

class RedissonConfigTest {

    @Test
    void buildsRedissonConfigFromSpringRedisProperties() throws IOException {
        RedisProperties properties = new RedisProperties();
        properties.setHost("redis.internal");
        properties.setPort(6380);
        properties.setDatabase(0);
        properties.setUsername("app-user");
        properties.setPassword("test-password");

        Config config = new RedissonConfig(properties).buildConfig();
        String yaml = config.toYAML();

        assertTrue(yaml.contains("redis://redis.internal:6380"));
        assertTrue(yaml.contains("database: 0"));
        assertTrue(yaml.contains("app-user"));
        assertTrue(yaml.contains("test-password"));
    }
}
