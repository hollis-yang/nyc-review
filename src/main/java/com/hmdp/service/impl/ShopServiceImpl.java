package com.hmdp.service.impl;

import cn.hutool.core.util.BooleanUtil;
import cn.hutool.core.util.StrUtil;
import cn.hutool.json.JSONObject;
import cn.hutool.json.JSONUtil;
import com.hmdp.dto.Result;
import com.hmdp.entity.Shop;
import com.hmdp.mapper.ShopMapper;
import com.hmdp.service.IShopService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmdp.utils.RedisData;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import javax.annotation.Resource;

import java.time.LocalDateTime;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static com.hmdp.utils.RedisConstants.*;

/**
 * <p>
 *  服务实现类
 * </p>
 *
 * @author 虎哥
 * @since 2021-12-22
 */
@Service
@Slf4j
public class ShopServiceImpl extends ServiceImpl<ShopMapper, Shop> implements IShopService {

    @Resource
    private StringRedisTemplate stringRedisTemplate;

    @Override
    public Result queryById(Long id) {
        // 缓存穿透
//        Shop shop = queryWithPassThrough(id);

        // 互斥锁解决缓存击穿
        Shop shop = queryWithMutex(id);

        // 逻辑过期解决缓存击穿
//        Shop shop = queryWithLogicalExpire(id);

        if (shop == null) {
            return Result.fail("店铺不存在!");
        }

        return Result.ok(shop);
    }

    private static final ExecutorService CACHE_REBUILD_EXECUTOR = Executors.newFixedThreadPool(10);

    public Shop queryWithLogicalExpire(Long id) {
        String key = CACHE_SHOP_KEY + id;

        String shopJson = stringRedisTemplate.opsForValue().get(key);

        // 未命中
        if (StrUtil.isBlank(shopJson)) {
            return null;
        }

        // 命中，先把json反序列化为对象
        RedisData redisData = JSONUtil.toBean(shopJson, RedisData.class);
        JSONObject data = (JSONObject) redisData.getData();
        Shop shop = JSONUtil.toBean(data, Shop.class);
        LocalDateTime expireTime = redisData.getExpireTime();
        // 判断是否过期
        if (expireTime.isAfter(LocalDateTime.now())) {
            // 1.未过期，直接返回
            return shop;
        }
        // 2.已过期，缓存重建
        String lockKey = LOCK_SHOP_KEY + id;
        // 2-1 尝试获取互斥锁
        boolean isLock = tryLock(lockKey);
        if (isLock) {
            // 2-2 成功获取锁，Double Check Redis缓存是否已被其他线程写入
            String freshJson = stringRedisTemplate.opsForValue().get(key);
            if (StrUtil.isNotBlank(freshJson)) {
                RedisData freshData = JSONUtil.toBean(freshJson, RedisData.class);
                if (freshData.getExpireTime().isAfter(LocalDateTime.now())) {
                    // 已有线程重建完毕，释放锁并返回新数据
                    unlock(lockKey);
                    JSONObject freshInner = (JSONObject) freshData.getData();
                    return JSONUtil.toBean(freshInner, Shop.class);
                }
            }
            // 确认仍未过期，开启独立线程重建缓存
            CACHE_REBUILD_EXECUTOR.submit(() -> {
               try {
                   this.saveShop2Redis(id, CACHE_LOGICAL_EXPIRE);
               } catch (Exception e) {
                   log.error("缓存重建失败, shopId={}", id, e);
               } finally {
                   // 释放锁
                   unlock(lockKey);
               }
            });
        }
        // 2-3 返回过期信息
        return shop;
    }

    public Shop queryWithMutex(Long id) {
        String key = CACHE_SHOP_KEY + id;

        String shopJson = stringRedisTemplate.opsForValue().get(key);

        // 命中数据
        if (StrUtil.isNotBlank(shopJson)) {
            return JSONUtil.toBean(shopJson, Shop.class);
        }
        // 命中是否空值
        if (shopJson != null) {
            return null;
        }

        // 未命中
        // 1.获取互斥锁
        String lockKey = LOCK_SHOP_KEY + id;
        Shop shop = null;
        try {
            boolean isLock = tryLock(lockKey);
            // 2.判断锁是否获取成功
            if (!isLock) {
                // 3.获取失败，休眠并重试
                Thread.sleep(50);
                return queryWithMutex(id);
            }
            // 4.获取成功，Double Check Redis缓存是否已被其他线程写入
            shopJson = stringRedisTemplate.opsForValue().get(key);
            if (StrUtil.isNotBlank(shopJson)) {
                return JSONUtil.toBean(shopJson, Shop.class);
            }
            if (shopJson != null) {
                return null;
            }

            // 5.缓存仍不存在，查数据库
            shop = getById(id);
            if (shop == null) {
                // 空值写入redis
                stringRedisTemplate.opsForValue().set(key, "", CACHE_NULL_TTL, TimeUnit.MINUTES);
                return null;
            }
            stringRedisTemplate.opsForValue().set(key, JSONUtil.toJsonStr(shop), CACHE_SHOP_TTL, TimeUnit.MINUTES);
        } catch (InterruptedException e) {
            throw new RuntimeException(e);
        } finally {
            // 6.查完数据库，释放锁
            unlock(lockKey);
        }
        return shop;
    }


    public Shop queryWithPassThrough(Long id) {
        String key = CACHE_SHOP_KEY + id;

        String shopJson = stringRedisTemplate.opsForValue().get(key);

        // 命中数据
        if (StrUtil.isNotBlank(shopJson)) {
            return JSONUtil.toBean(shopJson, Shop.class);
        }
        // 命中是否空值
        if (shopJson != null) {
            return null;
        }
        // 未命中，查询数据库
        Shop shop = getById(id);
        if (shop == null) {
            // 空值写入redis
            stringRedisTemplate.opsForValue().set(key, "", CACHE_NULL_TTL, TimeUnit.MINUTES);
            return null;
        }
        stringRedisTemplate.opsForValue().set(key, JSONUtil.toJsonStr(shop), CACHE_SHOP_TTL, TimeUnit.MINUTES);
        return shop;
    }

    private boolean tryLock(String key) {
        Boolean flag = stringRedisTemplate.opsForValue().setIfAbsent(key, "1", LOCK_SHOP_TTL, TimeUnit.SECONDS);
        return BooleanUtil.isTrue(flag);
    }

    private void unlock(String key) {
        stringRedisTemplate.delete(key);
    }

    public void saveShop2Redis(Long id, Long expireSeconds) {
        Shop shop = getById(id);

        RedisData redisData = new RedisData();
        redisData.setData(shop);
        redisData.setExpireTime(LocalDateTime.now().plusSeconds(expireSeconds));

        stringRedisTemplate.opsForValue().set(CACHE_SHOP_KEY + id, JSONUtil.toJsonStr(redisData));
    }

    @Override
    @Transactional
    public Result update(Shop shop) {
        Long id = shop.getId();
        if (id == null) {
            return Result.fail("店铺id不能为空!");
        }

        updateById(shop);

//        stringRedisTemplate.delete(CACHE_SHOP_KEY + id);
        saveShop2Redis(id, CACHE_LOGICAL_EXPIRE);
        return Result.ok();
    }
}
