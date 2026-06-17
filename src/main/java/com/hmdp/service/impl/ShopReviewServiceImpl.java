package com.hmdp.service.impl;

import com.hmdp.dto.Result;
import com.hmdp.entity.ShopReview;
import com.hmdp.entity.User;
import com.hmdp.mapper.ShopReviewMapper;
import com.hmdp.service.IShopReviewService;
import com.hmdp.service.IUserService;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmdp.utils.PageCacheClient;
import com.hmdp.utils.SystemConstants;
import com.hmdp.utils.UserHolder;
import org.springframework.stereotype.Service;

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
    public Result addReview(ShopReview review) {
        if (review.getShopId() == null) {
            return Result.fail("店铺ID不能为空");
        }
        if (review.getRating() == null || review.getRating() < 1 || review.getRating() > 5) {
            return Result.fail("评分必须在1-5之间");
        }
        if (review.getContent() == null || review.getContent().trim().isEmpty()) {
            return Result.fail("评价内容不能为空");
        }
        Long userId = UserHolder.getUser().getId();
        review.setUserId(userId);
        review.setLiked(0);
        save(review);
        return Result.ok(review.getId());
    }
}
