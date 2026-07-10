package com.hmdp.utils;

import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.core.Cursor;
import org.springframework.data.redis.core.ScanOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

@Component
@RequiredArgsConstructor
public class RedisPatternCleaner {

    private final StringRedisTemplate stringRedisTemplate;

    public void deleteByPattern(String pattern) {
        List<String> keys = scan(pattern);
        if (!keys.isEmpty()) {
            stringRedisTemplate.delete(keys);
        }
    }

    public void removeZSetMemberByPattern(String pattern, String member) {
        for (String key : scan(pattern)) {
            stringRedisTemplate.opsForZSet().remove(key, member);
        }
    }

    private List<String> scan(String pattern) {
        List<String> keys = new ArrayList<>();
        ScanOptions options = ScanOptions.scanOptions().match(pattern).count(200).build();
        try (Cursor<String> cursor = stringRedisTemplate.scan(options)) {
            cursor.forEachRemaining(keys::add);
        }
        return keys;
    }
}
