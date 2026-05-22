package com.hmdp.service.impl;

import com.hmdp.dto.Result;
import com.hmdp.entity.ShopReview;
import com.hmdp.entity.User;
import com.hmdp.mapper.ShopReviewMapper;
import com.hmdp.service.IShopReviewService;
import com.hmdp.service.IUserService;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmdp.utils.SystemConstants;
import org.springframework.stereotype.Service;

import javax.annotation.Resource;
import java.util.List;

@Service
public class ShopReviewServiceImpl extends ServiceImpl<ShopReviewMapper, ShopReview> implements IShopReviewService {

    @Resource
    private IUserService userService;

    @Override
    public Result queryByShopId(Long shopId, Integer current) {
        Page<ShopReview> page = query()
                .eq("shop_id", shopId)
                .orderByDesc("create_time")
                .page(new Page<>(current, SystemConstants.DEFAULT_PAGE_SIZE));
        List<ShopReview> records = page.getRecords();
        records.forEach(review -> {
            User user = userService.getById(review.getUserId());
            if (user != null) {
                review.setNickName(user.getNickName());
                review.setIcon(user.getIcon());
            }
        });
        return Result.ok(records, page.getTotal());
    }
}
