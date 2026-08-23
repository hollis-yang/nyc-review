package com.hmdp.service;

import com.hmdp.dto.Result;
import com.hmdp.entity.ShopReview;
import com.baomidou.mybatisplus.extension.service.IService;

import java.util.List;

public interface IShopReviewService extends IService<ShopReview> {

    Result queryByShopId(Long shopId, Integer current);

    Result addReview(ShopReview review);

    /**
     * Return complete, ordered root review threads for evidence construction.
     * The limit applies to roots, never to detached replies.
     */
    List<ShopReview> queryThreadsForEvidence(Long shopId, int limit);
}
