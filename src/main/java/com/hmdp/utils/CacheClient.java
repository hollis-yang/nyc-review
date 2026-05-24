package com.hmdp.utils;

import cn.hutool.core.util.BooleanUtil;
import cn.hutool.core.util.StrUtil;
import cn.hutool.json.JSONObject;
import cn.hutool.json.JSONUtil;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.function.Function;

import static com.hmdp.utils.RedisConstants.*;

@Slf4j
@Component
public class CacheClient {

    private final StringRedisTemplate stringRedisTemplate;

    public CacheClient(StringRedisTemplate stringRedisTemplate) {
        this.stringRedisTemplate = stringRedisTemplate;
    }

    public void set(String key, Object value, Long time, TimeUnit timeUnit) {
        stringRedisTemplate.opsForValue().set(key, JSONUtil.toJsonStr(value), time, timeUnit);
    }

    public void setWithLogicalExpire(String key, Object value, Long time, TimeUnit timeUnit) {
        RedisData redisData = new RedisData();
        redisData.setData(value);
        // 逻辑过期时间加随机偏移，避免大量 key 同时触发重建
        long seconds = timeUnit.toSeconds(time);
        long offset = ThreadLocalRandom.current().nextLong(seconds / 5 + 1);
        redisData.setExpireTime(LocalDateTime.now().plusSeconds(seconds + offset));
        stringRedisTemplate.opsForValue().set(key, JSONUtil.toJsonStr(redisData));
    }

    public <R, ID> R queryWithPassThrough(String keyPrefix, ID id,
                                          Class<R> type, Function<ID, R> dbFallback,
                                          Long time, TimeUnit timeUnit) {
        String key = keyPrefix + id;

        String json = stringRedisTemplate.opsForValue().get(key);

        // 命中数据
        if (StrUtil.isNotBlank(json)) {
            return JSONUtil.toBean(json, type);
        }
        // 命中是否空值
        if (json != null) {
            return null;
        }
        // 未命中，查询数据库
        R r = dbFallback.apply(id);
        if (r == null) {
            // 空值写入redis
            stringRedisTemplate.opsForValue().set(key, "", CACHE_NULL_TTL, TimeUnit.MINUTES);
            return null;
        }

        this.set(key, r, time, timeUnit);
        return r;
    }

    public <R, ID> R queryWithMutex(String keyPrefix, ID id,
                                     Class<R> type, Function<ID, R> dbFallback,
                                     Long time, TimeUnit timeUnit,
                                     Long lockTtl) {
        String key = keyPrefix + id;

        String json = stringRedisTemplate.opsForValue().get(key);

        // 命中数据
        if (StrUtil.isNotBlank(json)) {
            return JSONUtil.toBean(json, type);
        }
        // 命中空值
        if (json != null) {
            return null;
        }

        // 未命中，尝试获取互斥锁
        String lockKey = "lock:" + keyPrefix + id;
        boolean isLock = tryLock(lockKey, lockTtl);
        if (!isLock) {
            // 获取失败，休眠后重试
            try {
                Thread.sleep(50);
            } catch (InterruptedException e) {
                throw new RuntimeException(e);
            }
            return queryWithMutex(keyPrefix, id, type, dbFallback, time, timeUnit, lockTtl);
        }

        try {
            // Double Check
            json = stringRedisTemplate.opsForValue().get(key);
            if (StrUtil.isNotBlank(json)) {
                return JSONUtil.toBean(json, type);
            }
            if (json != null) {
                return null;
            }

            // 查数据库
            R r = dbFallback.apply(id);
            if (r == null) {
                stringRedisTemplate.opsForValue().set(key, "", CACHE_NULL_TTL, TimeUnit.MINUTES);
                return null;
            }
            // TTL 加随机偏移，避免大量缓存同时过期（雪崩）
            long ttl = time + ThreadLocalRandom.current().nextLong(time / 5 + 1);
            this.set(key, r, ttl, timeUnit);
            return r;
        } finally {
            unlock(lockKey);
        }
    }

    private static final ExecutorService CACHE_REBUILD_EXECUTOR = Executors.newFixedThreadPool(10);

    public <R, ID> R queryWithLogicalExpire(String keyPrefix, ID id,
                                            Class<R> type, Function<ID, R> dbFallback,
                                            Long time, TimeUnit timeUnit,
                                            Long lockTtl) {
        String key = keyPrefix+ id;

        String json = stringRedisTemplate.opsForValue().get(key);

        // 未命中
        if (StrUtil.isBlank(json)) {
            return null;
        }

        // 命中，先把json反序列化为对象
        RedisData redisData = JSONUtil.toBean(json, RedisData.class);
        JSONObject data = (JSONObject) redisData.getData();
        R r = JSONUtil.toBean(data, type);
        LocalDateTime expireTime = redisData.getExpireTime();
        // 判断是否过期
        if (expireTime.isAfter(LocalDateTime.now())) {
            // 1.未过期，直接返回
            return r;
        }
        // 2.已过期，缓存重建
        String lockKey = "lock:" + keyPrefix + id;
        // 2-1 尝试获取互斥锁
        boolean isLock = tryLock(lockKey, lockTtl);
        if (isLock) {
            // 2-2 成功获取锁，Double Check Redis缓存是否已被其他线程写入
            String freshJson = stringRedisTemplate.opsForValue().get(key);
            if (StrUtil.isNotBlank(freshJson)) {
                RedisData freshData = JSONUtil.toBean(freshJson, RedisData.class);
                if (freshData.getExpireTime().isAfter(LocalDateTime.now())) {
                    // 已有线程重建完毕，释放锁并返回新数据
                    unlock(lockKey);
                    JSONObject freshInner = (JSONObject) freshData.getData();
                    return JSONUtil.toBean(freshInner, type);
                }
            }
            // 确认仍未过期，开启独立线程重建缓存
            CACHE_REBUILD_EXECUTOR.submit(() -> {
                try {
                    R r1 = dbFallback.apply(id);
                    this.setWithLogicalExpire(key, r1, time, timeUnit);
                } catch (Exception e) {
                    log.error("缓存重建失败, id={}", id, e);
                } finally {
                    // 释放锁
                    unlock(lockKey);
                }
            });
        }
        // 2-3 返回过期信息
        return r;
    }

    private boolean tryLock(String key, Long ttl) {
        Boolean flag = stringRedisTemplate.opsForValue().setIfAbsent(key, "1", ttl, TimeUnit.SECONDS);
        return BooleanUtil.isTrue(flag);
    }

    private void unlock(String key) {
        stringRedisTemplate.delete(key);
    }
}
