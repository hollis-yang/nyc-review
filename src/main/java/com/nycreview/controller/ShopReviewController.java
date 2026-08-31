package com.nycreview.controller;

import com.nycreview.dto.Result;
import com.nycreview.entity.ShopReview;
import com.nycreview.service.IShopReviewService;
import org.springframework.web.bind.annotation.*;

import jakarta.annotation.Resource;

@RestController
@RequestMapping("/shop-review")
public class ShopReviewController {

    @Resource
    public IShopReviewService shopReviewService;

    @GetMapping("/{shopId}")
    public Result queryByShopId(
            @PathVariable("shopId") Long shopId,
            @RequestParam(value = "current", defaultValue = "1") Integer current) {
        return shopReviewService.queryByShopId(shopId, current);
    }

    @PostMapping
    public Result addReview(@RequestBody ShopReview review) {
        return shopReviewService.addReview(review);
    }

    @PutMapping("/{reviewId}/like")
    public Result toggleLike(@PathVariable("reviewId") Long reviewId) {
        return shopReviewService.toggleLike(reviewId);
    }
}
