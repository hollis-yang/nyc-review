package com.hmdp.service.impl;

import com.hmdp.dto.Result;
import com.hmdp.entity.Shop;
import com.hmdp.mapper.ShopMapper;
import com.hmdp.service.IShopService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmdp.utils.CacheClient;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import javax.annotation.Resource;

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
    private CacheClient cacheClient;

    @Override
    public Result queryById(Long id) {
        // 缓存穿透
//        Shop shop = cacheClient.queryWithPassThrough(CACHE_SHOP_KEY, id,
//                Shop.class, this::getById, CACHE_SHOP_TTL, TimeUnit.MINUTES);

        // 互斥锁解决缓存击穿
        Shop shop = cacheClient.queryWithMutex(CACHE_SHOP_KEY, id,
                Shop.class, this::getById, CACHE_SHOP_TTL, TimeUnit.MINUTES, LOCK_SHOP_TTL);
        if (shop == null) {
            return Result.fail("店铺不存在!");
        }

        // 逻辑过期解决缓存击穿
//        Shop shop = cacheClient.queryWithLogicalExpire(CACHE_SHOP_KEY, id,
//                Shop.class, this::getById, CACHE_LOGICAL_EXPIRE, TimeUnit.SECONDS, LOCK_SHOP_TTL);

        return Result.ok(shop);
    }

    @Override
    @Transactional
    public Result update(Shop shop) {
        Long id = shop.getId();
        if (id == null) {
            return Result.fail("店铺id不能为空!");
        }

        updateById(shop);

        // 方案A：删除缓存，等下次 queryWithMutex 回源重建（简单可靠）
        // stringRedisTemplate.delete(CACHE_SHOP_KEY + id);

        // 方案B：直接更新缓存
        cacheClient.set(CACHE_SHOP_KEY + id, shop, CACHE_SHOP_TTL, TimeUnit.MINUTES);

        // 方案C：逻辑过期（需配合 queryWithLogicalExpire 使用）
        // cacheClient.setWithLogicalExpire(CACHE_SHOP_KEY + id, shop, CACHE_LOGICAL_EXPIRE, TimeUnit.SECONDS);

        return Result.ok();
    }
}
