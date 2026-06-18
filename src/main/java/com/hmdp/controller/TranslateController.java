package com.hmdp.controller;

import com.hmdp.dto.Result;
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

    @PostMapping("/shop")
    public Result translateShop(@RequestParam Long shopId, @RequestParam(defaultValue = "en") String targetLang) {
        return translateService.translateShop(shopId, targetLang);
    }
}
