package com.nycreview.service.impl;

import com.nycreview.dto.Result;
import com.nycreview.entity.ShopReview;
import com.nycreview.entity.User;
import com.nycreview.mapper.ShopReviewMapper;
import com.nycreview.service.IShopReviewService;
import com.nycreview.service.IShopService;
import com.nycreview.service.IUserService;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.nycreview.utils.PageCacheClient;
import com.nycreview.utils.RedisPatternCleaner;
import com.nycreview.utils.SystemConstants;
import com.nycreview.utils.TransactionHooks;
import com.nycreview.utils.UserHolder;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import jakarta.annotation.Resource;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

import static com.nycreview.utils.RedisConstants.*;

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
        int safeCurrent = current == null ? 1 : Math.max(1, current);
        String key = CACHE_SHOP_REVIEW_KEY + shopId + ":" + safeCurrent;

        List<ShopReview> records = pageCacheClient.queryWithMutex(
                key, ShopReview.class,
                () -> loadThreads(shopId, safeCurrent, SystemConstants.DEFAULT_PAGE_SIZE, true),
                CACHE_SHOP_REVIEW_TTL, TimeUnit.MINUTES,
                LOCK_SHOP_TTL);

        long total = query()
                .eq("shop_id", shopId)
                .and(wrapper -> wrapper.isNull("parent_id").or().eq("parent_id", 0))
                .count();
        return Result.ok(records, total);
    }

    @Override
    public List<ShopReview> queryThreadsForEvidence(Long shopId, int limit) {
        if (shopId == null || shopId <= 0 || limit <= 0) {
            return List.of();
        }
        return loadThreads(shopId, 1, Math.min(limit, 50), false);
    }

    @Override
    @Transactional
    public Result addReview(ShopReview review) {
        if (review == null || review.getShopId() == null) {
            return Result.fail("Shop ID is required");
        }
        if (review.getContent() == null || review.getContent().trim().isEmpty()) {
            return Result.fail("Review content is required");
        }
        review.setContent(review.getContent().trim());
        if (review.getContent().length() > 2_000) {
            return Result.fail("Review content cannot exceed 2000 characters");
        }
        if (shopService.getById(review.getShopId()) == null) {
            return Result.fail("Shop not found");
        }

        Long requestedParentId = review.getParentId();
        boolean reply = requestedParentId != null && requestedParentId > 0;
        if (!reply && (review.getRating() == null || review.getRating() < 1 || review.getRating() > 5)) {
            return Result.fail("Rating must be between 1 and 5");
        }

        if (UserHolder.getUser() == null || UserHolder.getUser().getId() == null) {
            return Result.fail("Please sign in first");
        }
        Long userId = UserHolder.getUser().getId();

        // Every provenance and hierarchy field is server-controlled for live
        // writes. Synthetic rows are created only by the offline import.
        review.setId(null);
        review.setUserId(userId);
        review.setLiked(0);
        review.setSourceType("USER_SUBMITTED");
        review.setAuthorRole("USER");
        review.setLanguage(null);
        review.setSentiment(null);
        review.setTopicTags(null);
        review.setSecurityTest(false);
        review.setCreateTime(null);
        review.setUpdateTime(null);
        review.setNickName(null);
        review.setIcon(null);
        review.setIsLike(null);
        review.setChildren(null);
        review.setReplyToNickName(null);

        if (reply) {
            ShopReview parent = getById(requestedParentId);
            if (parent == null || !Objects.equals(parent.getShopId(), review.getShopId())) {
                return Result.fail("Parent review not found");
            }
            int depth = reviewDepth(parent) + 1;
            if (depth > 2) {
                return Result.fail("Review replies cannot be nested beyond level 3");
            }
            review.setParentId(parent.getId());
            review.setRootId(parent.getRootId() == null ? parent.getId() : parent.getRootId());
            review.setReplyToUserId(parent.getUserId());
            review.setDepth(depth);
            review.setRating(null);
        } else {
            review.setParentId(null);
            review.setRootId(null);
            review.setReplyToUserId(null);
            review.setDepth(0);
        }

        if (!save(review)) {
            throw new IllegalStateException("Failed to save the review");
        }

        if (!reply) {
            review.setRootId(review.getId());
            if (!updateById(review)) {
                throw new IllegalStateException("Failed to initialize the review thread");
            }
            int ratingScore = review.getRating() * 10;
            if (!updateShopReviewAggregate(review.getShopId(), ratingScore)) {
                throw new IllegalStateException("Failed to update shop review statistics");
            }
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

    boolean updateShopReviewAggregate(Long shopId, int ratingScore) {
        String currentCount = "COALESCE(local_review_count, comments, 0)";
        String currentScore = "COALESCE(local_score, score, 0)";
        String updatedScore = "ROUND((" + currentScore + " * " + currentCount + " + "
                + ratingScore + ") / (" + currentCount + " + 1))";
        String updatedCount = currentCount + " + 1";
        return shopService.update()
                .setSql("score = " + updatedScore)
                .setSql("local_score = " + updatedScore)
                .setSql("comments = " + updatedCount)
                .setSql("local_review_count = " + updatedCount)
                .eq("id", shopId)
                .update();
    }

    private List<ShopReview> loadThreads(
            Long shopId,
            long current,
            long pageSize,
            boolean includeUsers
    ) {
        Page<ShopReview> page = query()
                .eq("shop_id", shopId)
                .and(wrapper -> wrapper.isNull("parent_id").or().eq("parent_id", 0))
                .orderByDesc("create_time")
                .orderByDesc("id")
                .page(new Page<>(current, pageSize));
        List<ShopReview> roots = new ArrayList<>(page.getRecords());
        if (roots.isEmpty()) {
            return roots;
        }

        List<Long> rootIds = roots.stream()
                .map(review -> review.getRootId() == null ? review.getId() : review.getRootId())
                .filter(Objects::nonNull)
                .toList();
        List<ShopReview> replies = rootIds.isEmpty()
                ? List.of()
                : query()
                        .eq("shop_id", shopId)
                        .in("root_id", rootIds)
                        .gt("depth", 0)
                        .le("depth", 2)
                        .orderByAsc("depth")
                        .orderByAsc("create_time")
                        .orderByAsc("id")
                        .list();

        List<ShopReview> all = new ArrayList<>(roots.size() + replies.size());
        all.addAll(roots);
        all.addAll(replies);
        if (includeUsers) {
            hydrateUsers(all);
        }
        return buildThreadForest(roots, replies);
    }

    private void hydrateUsers(List<ShopReview> reviews) {
        Set<Long> userIds = reviews.stream()
                .flatMap(review -> java.util.stream.Stream.of(review.getUserId(), review.getReplyToUserId()))
                .filter(Objects::nonNull)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        if (userIds.isEmpty()) {
            return;
        }
        Map<Long, User> userMap = userService.listByIds(userIds).stream()
                .collect(Collectors.toMap(User::getId, user -> user, (first, ignored) -> first));
        reviews.forEach(review -> {
            User user = userMap.get(review.getUserId());
            if (user != null) {
                review.setNickName(user.getNickName());
                review.setIcon(user.getIcon());
            }
            User repliedTo = userMap.get(review.getReplyToUserId());
            if (repliedTo != null) {
                review.setReplyToNickName(repliedTo.getNickName());
            }
        });
    }

    static List<ShopReview> buildThreadForest(List<ShopReview> roots, List<ShopReview> replies) {
        Map<Long, ShopReview> byId = new HashMap<>();
        for (ShopReview review : roots) {
            review.setChildren(new ArrayList<>());
            byId.put(review.getId(), review);
        }
        for (ShopReview reply : replies) {
            reply.setChildren(new ArrayList<>());
            byId.put(reply.getId(), reply);
        }
        for (ShopReview reply : replies) {
            ShopReview parent = byId.get(reply.getParentId());
            int depth = reviewDepth(reply);
            if (parent != null
                    && parent != reply
                    && depth >= 1
                    && depth <= 2
                    && reviewDepth(parent) == depth - 1
                    && Objects.equals(
                            parent.getRootId() == null ? parent.getId() : parent.getRootId(),
                            reply.getRootId()
                    )) {
                parent.getChildren().add(reply);
            }
        }
        return roots;
    }

    static int reviewDepth(ShopReview review) {
        if (review.getDepth() != null) {
            return review.getDepth();
        }
        return review.getParentId() == null ? 0 : 1;
    }
}
