package com.hmdp.utils;

import cn.hutool.core.util.BooleanUtil;
import cn.hutool.core.util.StrUtil;
import cn.hutool.json.JSONUtil;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.util.Collections;
import java.util.List;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;

import static com.hmdp.utils.RedisConstants.CACHE_NULL_TTL;

@Slf4j
@Component
public class PageCacheClient {

    private final StringRedisTemplate stringRedisTemplate;

    public PageCacheClient(StringRedisTemplate stringRedisTemplate) {
        this.stringRedisTemplate = stringRedisTemplate;
    }

    public void set(String key, Object value, Long time, TimeUnit timeUnit) {
        stringRedisTemplate.opsForValue().set(key, JSONUtil.toJsonStr(value), time, timeUnit);
    }

    public <R> List<R> queryWithPassThrough(String key, Class<R> elementType,
                                             Supplier<List<R>> dbFallback,
                                             Long time, TimeUnit timeUnit) {
        String json = stringRedisTemplate.opsForValue().get(key);

        if (StrUtil.isNotBlank(json)) {
            return JSONUtil.toList(json, elementType);
        }
        if (json != null) {
            return Collections.emptyList();
        }

        List<R> list = dbFallback.get();
        if (list == null || list.isEmpty()) {
            stringRedisTemplate.opsForValue().set(key, "", CACHE_NULL_TTL, TimeUnit.MINUTES);
            return Collections.emptyList();
        }

        long ttl = time + ThreadLocalRandom.current().nextLong(time / 5 + 1);
        stringRedisTemplate.opsForValue().set(key, JSONUtil.toJsonStr(list), ttl, timeUnit);
        return list;
    }

    public <R> List<R> queryWithMutex(String key, Class<R> elementType,
                                       Supplier<List<R>> dbFallback,
                                       Long time, TimeUnit timeUnit,
                                       Long lockTtl) {
        String json = stringRedisTemplate.opsForValue().get(key);

        if (StrUtil.isNotBlank(json)) {
            return JSONUtil.toList(json, elementType);
        }
        if (json != null) {
            return Collections.emptyList();
        }

        String lockKey = "lock:" + key;
        boolean isLock = tryLock(lockKey, lockTtl);
        if (!isLock) {
            try {
                Thread.sleep(50);
            } catch (InterruptedException e) {
                throw new RuntimeException(e);
            }
            return queryWithMutex(key, elementType, dbFallback, time, timeUnit, lockTtl);
        }

        try {
            json = stringRedisTemplate.opsForValue().get(key);
            if (StrUtil.isNotBlank(json)) {
                return JSONUtil.toList(json, elementType);
            }
            if (json != null) {
                return Collections.emptyList();
            }

            List<R> list = dbFallback.get();
            if (list == null || list.isEmpty()) {
                stringRedisTemplate.opsForValue().set(key, "", CACHE_NULL_TTL, TimeUnit.MINUTES);
                return Collections.emptyList();
            }

            long ttl = time + ThreadLocalRandom.current().nextLong(time / 5 + 1);
            stringRedisTemplate.opsForValue().set(key, JSONUtil.toJsonStr(list), ttl, timeUnit);
            return list;
        } finally {
            unlock(lockKey);
        }
    }

    private boolean tryLock(String key, Long ttl) {
        Boolean flag = stringRedisTemplate.opsForValue().setIfAbsent(key, "1", ttl, TimeUnit.SECONDS);
        return BooleanUtil.isTrue(flag);
    }

    private void unlock(String key) {
        stringRedisTemplate.delete(key);
    }
}
