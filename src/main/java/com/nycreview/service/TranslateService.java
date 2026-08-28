package com.nycreview.service;

import com.nycreview.dto.Result;

public interface TranslateService {
    Result translateBlog(Long blogId, String targetLang);
    Result translateComment(Long commentId, String targetLang);
    Result translateReview(Long reviewId, String targetLang);
    Result translateShop(Long shopId, String targetLang);
    Result translateText(String text, String targetLang);
}
