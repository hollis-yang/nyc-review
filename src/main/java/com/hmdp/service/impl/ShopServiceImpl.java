package com.hmdp.service.impl;

import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.hmdp.dto.Result;
import com.hmdp.entity.Shop;
import com.hmdp.mapper.ShopMapper;
import com.hmdp.service.IShopService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmdp.utils.CacheClient;
import com.hmdp.utils.SystemConstants;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.geo.Distance;
import org.springframework.data.geo.GeoResult;
import org.springframework.data.geo.GeoResults;
import org.springframework.data.geo.Metrics;
import org.springframework.data.redis.connection.RedisGeoCommands;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.domain.geo.GeoReference;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import jakarta.annotation.Resource;

import java.util.*;
import java.util.concurrent.TimeUnit;

import static com.hmdp.utils.RedisConstants.*;

@Service
@Slf4j
public class ShopServiceImpl extends ServiceImpl<ShopMapper, Shop> implements IShopService {

    @Resource
    private CacheClient cacheClient;
    @Resource
    private StringRedisTemplate stringRedisTemplate;

    @Override
    public Result queryById(Long id) {
        // 缓存穿透
//        Shop shop = cacheClient.queryWithPassThrough(CACHE_SHOP_KEY, id,
//                Shop.class, this::getById, CACHE_SHOP_TTL, TimeUnit.MINUTES);

        // 互斥锁解决缓存击穿
        Shop shop = cacheClient.queryWithMutex(CACHE_SHOP_KEY, id,
                Shop.class, this::getById, CACHE_SHOP_TTL, TimeUnit.MINUTES, LOCK_SHOP_TTL);
        if (shop == null) {
            return Result.fail("Shop not found");
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
            return Result.fail("Shop ID is required");
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

    @Override
    public Result queryShopByType(Integer typeId, Integer current, Double x, Double y, String sortBy, String sortOrder) {
        String sortColumn = resolveSortColumn(sortBy);
        if (StrUtil.isNotBlank(sortBy) && sortColumn == null) {
            return Result.fail("Invalid sort field");
        }
        if (!isSortOrderValid(sortOrder)) {
            return Result.fail("Invalid sort direction");
        }
        boolean sortAscending = "asc".equalsIgnoreCase(sortOrder);

        // 1.判断是否需要根据坐标查询
        if (x == null || y == null) {
            // 不需要坐标查询，按数据库分页查询
            var qw = query().eq("type_id", typeId);
            if (sortColumn != null) {
                qw.orderBy(true, sortAscending, sortColumn);
            }
            Page<Shop> page = qw.page(new Page<>(current, SystemConstants.DEFAULT_PAGE_SIZE));
            // 返回数据
            return Result.ok(page.getRecords());
        }
        // 2.计算分页参数
        int from = (current - 1) * SystemConstants.DEFAULT_PAGE_SIZE;
        int end = current * SystemConstants.DEFAULT_PAGE_SIZE;
        // 3.查询redis，按照距离排序、分页 -> shopId, distance
        String geoKey = SHOP_GEO_KEY + typeId;
        GeoResults<RedisGeoCommands.GeoLocation<String>> results = stringRedisTemplate.opsForGeo()
                .search(geoKey,
                        GeoReference.fromCoordinate(x, y),
                        new Distance(200000),
                        RedisGeoCommands.GeoSearchCommandArgs.newGeoSearchArgs()
                                .includeDistance()
                                .limit(end));
        // 4.解析出shopId
        if (results == null) {
            return Result.ok(Collections.emptyList());
        }
        List<GeoResult<RedisGeoCommands.GeoLocation<String>>> list = results.getContent();
        if (list.size() <= from) {
            // 没有下一页了，结束
            return Result.ok(Collections.emptyList());
        }
        // 4.1.截取 from ~ end 的部分
        List<Long> ids = new ArrayList<>(list.size());
        Map<String, Distance> distanceMap = new HashMap<>(list.size());
        list.stream().skip(from).forEach(result -> {
            String shopIdStr = result.getContent().getName();// shopId
            ids.add(Long.valueOf(shopIdStr));
            Distance distance = result.getDistance();// distance
            distanceMap.put(shopIdStr, distance);
        });
        // 5.根据id查店铺
        List<Shop> shops = query().in("id", ids).last("ORDER BY FIELD(id," + StrUtil.join(",", ids) + ")").list();
        shops.forEach(shop -> {
            shop.setDistance(distanceMap.get(shop.getId().toString()).getValue());
        });
        // 根据白名单字段排序
        if (sortColumn != null) {
            if ("score".equals(sortColumn)) {
                shops.sort((a, b) -> sortAscending ? a.getScore().compareTo(b.getScore()) : b.getScore().compareTo(a.getScore()));
            } else if ("comments".equals(sortColumn)) {
                shops.sort((a, b) -> sortAscending ? Integer.compare(a.getComments(), b.getComments()) : Integer.compare(b.getComments(), a.getComments()));
            }
        } else {
            // 按距离排序（sortBy为空）: GEO默认升序，desc时反转
            if ("desc".equalsIgnoreCase(sortOrder)) {
                java.util.Collections.reverse(shops);
            }
        }
        // 6.返回结果
        return Result.ok(shops);
    }

    static String resolveSortColumn(String sortBy) {
        if (StrUtil.isBlank(sortBy)) {
            return null;
        }
        return switch (sortBy) {
            case "score" -> "score";
            case "comments" -> "comments";
            default -> null;
        };
    }

    static boolean isSortOrderValid(String sortOrder) {
        return StrUtil.isBlank(sortOrder)
                || "asc".equalsIgnoreCase(sortOrder)
                || "desc".equalsIgnoreCase(sortOrder);
    }
}
