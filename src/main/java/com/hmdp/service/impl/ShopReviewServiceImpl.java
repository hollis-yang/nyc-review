package com.hmdp.service.impl;

import com.hmdp.dto.Result;
import com.hmdp.entity.ShopReview;
import com.hmdp.entity.User;
import com.hmdp.mapper.ShopReviewMapper;
import com.hmdp.service.IShopReviewService;
import com.hmdp.service.IShopService;
import com.hmdp.service.IUserService;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmdp.utils.PageCacheClient;
import com.hmdp.utils.RedisPatternCleaner;
import com.hmdp.utils.SystemConstants;
import com.hmdp.utils.TransactionHooks;
import com.hmdp.utils.UserHolder;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import jakarta.annotation.Resource;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

import static com.hmdp.utils.RedisConstants.*;

@Service
public class ShopReviewServiceImpl extends ServiceImpl<ShopReviewMapper, ShopReview> implements IShopReviewService {

    @Resource
    private IUserService userService;

    @Resource
    private PageCacheClient pageCacheClient;

    @Resource
    private IShopService shopService;

    @Resource
    private RedisPatternCleaner redisPatternCleaner;

    @Resource
    private StringRedisTemplate stringRedisTemplate;

    @Override
    public Result queryByShopId(Long shopId, Integer current) {
        String key = CACHE_SHOP_REVIEW_KEY + shopId + ":" + current;

        List<ShopReview> records = pageCacheClient.queryWithMutex(
                key, ShopReview.class,
                () -> {
                    Page<ShopReview> page = query()
                            .eq("shop_id", shopId)
                            .orderByDesc("create_time")
                            .page(new Page<>(current, SystemConstants.DEFAULT_PAGE_SIZE));
                    List<ShopReview> list = page.getRecords();
                    List<Long> userIds = list.stream()
                            .map(ShopReview::getUserId)
                            .distinct()
                            .collect(Collectors.toList());
                    if (!userIds.isEmpty()) {
                        Map<Long, User> userMap = userService.listByIds(userIds).stream()
                                .collect(Collectors.toMap(User::getId, u -> u));
                        list.forEach(review -> {
                            User user = userMap.get(review.getUserId());
                            if (user != null) {
                                review.setNickName(user.getNickName());
                                review.setIcon(user.getIcon());
                            }
                        });
                    }
                    return list;
                },
                CACHE_SHOP_REVIEW_TTL, TimeUnit.MINUTES,
                LOCK_SHOP_TTL);

        long total = query().eq("shop_id", shopId).count();
        return Result.ok(records, total);
    }

    @Override
    @Transactional
    public Result addReview(ShopReview review) {
        if (review.getShopId() == null) {
            return Result.fail("Shop ID is required");
        }
        if (review.getRating() == null || review.getRating() < 1 || review.getRating() > 5) {
            return Result.fail("Rating must be between 1 and 5");
        }
        if (review.getContent() == null || review.getContent().trim().isEmpty()) {
            return Result.fail("Review content is required");
        }
        if (shopService.getById(review.getShopId()) == null) {
            return Result.fail("Shop not found");
        }
        Long userId = UserHolder.getUser().getId();
        review.setUserId(userId);
        review.setLiked(0);
        if (!save(review)) {
            throw new IllegalStateException("Failed to save the review");
        }
        int ratingScore = review.getRating() * 10;
        boolean aggregateUpdated = shopService.update()
                .setSql("score = ROUND((COALESCE(score, 0) * COALESCE(comments, 0) + "
                        + ratingScore + ") / (COALESCE(comments, 0) + 1))")
                .setSql("comments = COALESCE(comments, 0) + 1")
                .eq("id", review.getShopId())
                .update();
        if (!aggregateUpdated) {
            throw new IllegalStateException("Failed to update shop review statistics");
        }
        Long shopId = review.getShopId();
        TransactionHooks.afterCommit(() -> {
            try {
                redisPatternCleaner.deleteByPattern(CACHE_SHOP_REVIEW_KEY + shopId + ":*");
                stringRedisTemplate.delete(CACHE_SHOP_KEY + shopId);
            } catch (RuntimeException ignored) {
                // 缓存失效失败不回滚已提交的评价；缓存到期后仍会自动恢复。
            }
        });
        return Result.ok(review.getId());
    }
}
