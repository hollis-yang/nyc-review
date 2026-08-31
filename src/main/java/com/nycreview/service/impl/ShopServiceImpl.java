package com.nycreview.service.impl;

import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.nycreview.dto.Result;
import com.nycreview.entity.Shop;
import com.nycreview.entity.ShopImage;
import com.nycreview.mapper.ShopImageMapper;
import com.nycreview.mapper.ShopMapper;
import com.nycreview.service.IShopService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.nycreview.utils.CacheClient;
import com.nycreview.utils.SystemConstants;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.geo.Distance;
import org.springframework.data.geo.GeoResult;
import org.springframework.data.geo.GeoResults;
import org.springframework.data.redis.connection.RedisGeoCommands;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.domain.geo.GeoReference;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import jakarta.annotation.Resource;

import java.util.*;
import java.util.concurrent.TimeUnit;

import static com.nycreview.utils.RedisConstants.*;

@Service
@Slf4j
public class ShopServiceImpl extends ServiceImpl<ShopMapper, Shop> implements IShopService {

    @Resource
    private CacheClient cacheClient;
    @Resource
    private StringRedisTemplate stringRedisTemplate;
    @Resource
    private ShopImageMapper shopImageMapper;

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

        List<ShopImage> imageAssets = shopImageMapper.selectList(
                new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ShopImage>()
                        .eq(ShopImage::getShopId, shop.getId())
                        .eq(StrUtil.isNotBlank(shop.getDataVersion()), ShopImage::getDataVersion, shop.getDataVersion())
                        .eq(ShopImage::getAvailabilityStatus, "AVAILABLE")
                        .orderByDesc(ShopImage::getIsPrimary)
                        .orderByAsc(ShopImage::getDisplayOrder)
                        .orderByAsc(ShopImage::getSortOrder)
                        .orderByAsc(ShopImage::getId)
        );
        shop.setImageAssets(imageAssets == null ? List.of() : List.copyOf(imageAssets));

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
        String sortMode = resolveSortColumn(sortBy);
        if (StrUtil.isNotBlank(sortBy) && sortMode == null) {
            return Result.fail("Invalid sort field");
        }
        if (!isSortOrderValid(sortOrder)) {
            return Result.fail("Invalid sort direction");
        }
        if (typeId == null || typeId <= 0 || current == null || current <= 0) {
            return Result.fail("Invalid pagination parameters");
        }
        if (!areCoordinatesValid(x, y)) {
            return Result.fail("Invalid coordinates");
        }

        String effectiveSortMode = sortMode == null ? "distance" : sortMode;
        boolean sortAscending = StrUtil.isBlank(sortOrder)
                ? "distance".equals(effectiveSortMode)
                : "asc".equalsIgnoreCase(sortOrder);

        if ("popularity".equals(effectiveSortMode)) {
            return queryByPopularity(typeId, current, x, y, sortAscending);
        }
        if ("rating".equals(effectiveSortMode)) {
            return queryByRating(typeId, current, x, y, sortAscending);
        }

        // Distance ranking needs an origin. API clients that omit it retain a
        // stable database fallback, while the React client always sends either
        // browser coordinates or its explicit Times Square fallback.
        if (x == null || y == null) {
            Page<Shop> page = query()
                    .eq("type_id", typeId)
                    .eq("business_status", "OPERATIONAL")
                    .orderByAsc("id")
                    .page(new Page<>(current, SystemConstants.DEFAULT_PAGE_SIZE));
            return Result.ok(page.getRecords());
        }

        int from = (current - 1) * SystemConstants.DEFAULT_PAGE_SIZE;
        int end = current * SystemConstants.DEFAULT_PAGE_SIZE;
        String geoKey = SHOP_GEO_KEY + typeId;
        RedisGeoCommands.GeoSearchCommandArgs geoArgs = RedisGeoCommands.GeoSearchCommandArgs
                .newGeoSearchArgs()
                .includeDistance()
                .limit(end);
        if (sortAscending) {
            geoArgs.sortAscending();
        } else {
            geoArgs.sortDescending();
        }
        GeoResults<RedisGeoCommands.GeoLocation<String>> results = stringRedisTemplate.opsForGeo()
                .search(geoKey,
                        GeoReference.fromCoordinate(x, y),
                        // Covers any browser origin on Earth. Keeping the unit
                        // in meters preserves the existing Shop.distance API.
                        new Distance(21_000_000),
                        geoArgs);
        if (results == null) {
            return Result.ok(Collections.emptyList());
        }
        List<GeoResult<RedisGeoCommands.GeoLocation<String>>> list = results.getContent();
        if (list.size() <= from) {
            return Result.ok(Collections.emptyList());
        }

        List<Long> ids = new ArrayList<>(SystemConstants.DEFAULT_PAGE_SIZE);
        Map<String, Distance> distanceMap = new HashMap<>(SystemConstants.DEFAULT_PAGE_SIZE);
        list.stream().skip(from).limit(SystemConstants.DEFAULT_PAGE_SIZE).forEach(result -> {
            String shopIdStr = result.getContent().getName();
            ids.add(Long.valueOf(shopIdStr));
            Distance distance = result.getDistance();
            distanceMap.put(shopIdStr, distance);
        });
        List<Shop> shops = query().in("id", ids)
                .eq("business_status", "OPERATIONAL")
                .last("ORDER BY FIELD(id," + StrUtil.join(",", ids) + ")")
                .list();
        shops.forEach(shop -> {
            Distance distance = distanceMap.get(shop.getId().toString());
            if (distance != null) {
                shop.setDistance(distance.getValue());
            }
        });
        return Result.ok(shops);
    }

    @Override
    public Result queryLinkOptions(Integer typeId, String search, Integer current, Integer size) {
        int safeCurrent = current == null ? 1 : Math.max(1, current);
        int safeSize = size == null ? 30 : Math.max(1, Math.min(50, size));
        if (typeId != null && typeId <= 0) {
            return Result.fail("Invalid category");
        }
        String normalizedSearch = StrUtil.trim(search);
        Page<Shop> page = query()
                .eq(typeId != null, "type_id", typeId)
                .like(StrUtil.isNotBlank(normalizedSearch), "name", normalizedSearch)
                .eq("business_status", "OPERATIONAL")
                .orderByAsc("name")
                .orderByAsc("id")
                .page(new Page<>(safeCurrent, safeSize));
        return Result.ok(page.getRecords(), page.getTotal());
    }

    private Result queryByPopularity(
            Integer typeId,
            Integer current,
            Double x,
            Double y,
            boolean sortAscending
    ) {
        long offset = (long) (current - 1) * SystemConstants.DEFAULT_PAGE_SIZE;
        List<Shop> shops = baseMapper.selectByPlatformPopularity(
                typeId.longValue(),
                sortAscending,
                offset,
                SystemConstants.DEFAULT_PAGE_SIZE
        );
        attachDistances(shops, x, y);
        return Result.ok(shops);
    }

    private Result queryByRating(
            Integer typeId,
            Integer current,
            Double x,
            Double y,
            boolean sortAscending
    ) {
        var ranked = query()
                .eq("type_id", typeId)
                .eq("business_status", "OPERATIONAL")
                // Unrated merchants always follow rated merchants.
                .orderByAsc("score IS NULL")
                .orderBy(true, sortAscending, "score")
                .orderBy(true, false, "COALESCE(rating_count, comments, 0)")
                .orderByAsc("id");
        Page<Shop> page = ranked.page(new Page<>(current, SystemConstants.DEFAULT_PAGE_SIZE));
        List<Shop> shops = page.getRecords();
        attachDistances(shops, x, y);
        return Result.ok(shops);
    }

    private void attachDistances(List<Shop> shops, Double originLongitude, Double originLatitude) {
        if (originLongitude == null || originLatitude == null) {
            return;
        }
        shops.forEach(shop -> {
            if (shop.getX() != null && shop.getY() != null) {
                shop.setDistance(distanceInMeters(
                        originLongitude,
                        originLatitude,
                        shop.getX(),
                        shop.getY()
                ));
            }
        });
    }

    static double distanceInMeters(
            double originLongitude,
            double originLatitude,
            double destinationLongitude,
            double destinationLatitude
    ) {
        double latitudeDelta = Math.toRadians(destinationLatitude - originLatitude);
        double longitudeDelta = Math.toRadians(destinationLongitude - originLongitude);
        double originLatitudeRadians = Math.toRadians(originLatitude);
        double destinationLatitudeRadians = Math.toRadians(destinationLatitude);
        double a = Math.sin(latitudeDelta / 2) * Math.sin(latitudeDelta / 2)
                + Math.cos(originLatitudeRadians) * Math.cos(destinationLatitudeRadians)
                * Math.sin(longitudeDelta / 2) * Math.sin(longitudeDelta / 2);
        double clampedA = Math.max(0, Math.min(1, a));
        return 6_371_008.8 * 2 * Math.atan2(Math.sqrt(clampedA), Math.sqrt(1 - clampedA));
    }

    static String resolveSortColumn(String sortBy) {
        if (StrUtil.isBlank(sortBy)) {
            return null;
        }
        return switch (sortBy) {
            case "distance" -> "distance";
            case "popularity", "comments" -> "popularity";
            case "rating", "score" -> "rating";
            default -> null;
        };
    }

    static boolean areCoordinatesValid(Double longitude, Double latitude) {
        if (longitude == null && latitude == null) {
            return true;
        }
        return longitude != null
                && latitude != null
                && Double.isFinite(longitude)
                && Double.isFinite(latitude)
                && longitude >= -180
                && longitude <= 180
                && latitude >= -85.05112878
                && latitude <= 85.05112878;
    }

    static boolean isSortOrderValid(String sortOrder) {
        return StrUtil.isBlank(sortOrder)
                || "asc".equalsIgnoreCase(sortOrder)
                || "desc".equalsIgnoreCase(sortOrder);
    }
}
