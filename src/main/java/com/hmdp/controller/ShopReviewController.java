package com.hmdp.controller;

import com.hmdp.dto.Result;
import com.hmdp.service.IShopReviewService;
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
}
