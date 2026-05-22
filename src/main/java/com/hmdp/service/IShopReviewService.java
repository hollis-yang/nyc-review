package com.hmdp.service;

import com.hmdp.dto.Result;
import com.hmdp.entity.ShopReview;
import com.baomidou.mybatisplus.extension.service.IService;

public interface IShopReviewService extends IService<ShopReview> {

    Result queryByShopId(Long shopId, Integer current);
}
