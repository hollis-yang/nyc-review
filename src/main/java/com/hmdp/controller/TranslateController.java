package com.hmdp.controller;

import com.hmdp.dto.Result;
import com.hmdp.dto.TranslateTextRequest;
import com.hmdp.service.TranslateService;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/translate")
public class TranslateController {

    @Resource
    private TranslateService translateService;

    @PostMapping("/blog")
    public Result translateBlog(@RequestParam Long blogId, @RequestParam(defaultValue = "en") String targetLang) {
        return translateService.translateBlog(blogId, targetLang);
    }

    @PostMapping("/comment")
    public Result translateComment(@RequestParam Long commentId, @RequestParam(defaultValue = "en") String targetLang) {
        return translateService.translateComment(commentId, targetLang);
    }

    @PostMapping("/review")
    public Result translateReview(@RequestParam Long reviewId, @RequestParam(defaultValue = "en") String targetLang) {
        return translateService.translateReview(reviewId, targetLang);
    }

    @PostMapping("/shop")
    public Result translateShop(@RequestParam Long shopId, @RequestParam(defaultValue = "en") String targetLang) {
        return translateService.translateShop(shopId, targetLang);
    }

    @PostMapping("/text")
    public Result translateText(@RequestBody TranslateTextRequest request) {
        if (request == null || request.getText() == null || request.getText().isBlank()) {
            return Result.fail("Text cannot be empty");
        }
        if (request.getText().length() > 5000) {
            return Result.fail("Text cannot exceed 5,000 characters");
        }
        return translateService.translateText(request.getText(), request.getTargetLang());
    }
}
