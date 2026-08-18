package com.hmdp.service.impl;

import com.hmdp.config.DeepSeekProperties;
import com.hmdp.dto.Result;
import com.hmdp.entity.Blog;
import com.hmdp.entity.BlogComments;
import com.hmdp.entity.Shop;
import com.hmdp.service.IBlogCommentsService;
import com.hmdp.service.IBlogService;
import com.hmdp.service.IShopService;
import com.hmdp.service.IShopTypeService;
import com.hmdp.service.TranslateService;
import jakarta.annotation.Resource;
import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import java.util.concurrent.TimeUnit;
import org.springframework.web.client.RestTemplate;

import java.util.*;

@Service
public class TranslateServiceImpl implements TranslateService {

    private static final Logger log = LoggerFactory.getLogger(TranslateServiceImpl.class);

    @Resource
    private IBlogService blogService;

    @Resource
    private IBlogCommentsService blogCommentsService;

    @Resource
    private IShopService shopService;

    @Resource
    private IShopTypeService shopTypeService;

    @Resource
    private StringRedisTemplate stringRedisTemplate;

    @Resource
    private RestTemplate restTemplate;

    @Resource
    private DeepSeekProperties deepSeekProperties;

    private static final String TRANSLATE_CACHE_PREFIX = "translate:";
    private static final long CACHE_TTL = 30;

    private static final String API_URL = "https://api.deepseek.com/v1/chat/completions";

    @Override
    public Result translateBlog(Long blogId, String targetLang) {
        String cached = getCached("blog", blogId, targetLang);
        if (cached != null) return Result.ok(cached);
        Blog blog = blogService.getById(blogId);
        if (blog == null) return Result.fail("Blog not found");

        String langName = "en".equals(targetLang) ? "English" : "Chinese";
        String content = blog.getContent();
        if (content == null || content.isBlank()) content = "";
        String text = (blog.getTitle() != null ? blog.getTitle() + "\n\n" : "") + content;

        String translated = callDeepSeek(text, langName);
        if (translated == null) return Result.fail("Translation failed");
        setCached("blog", blogId, targetLang, translated);
        return Result.ok(translated);
    }

    @Override
    public Result translateComment(Long commentId, String targetLang) {
        String cached = getCached("comment", commentId, targetLang);
        if (cached != null) return Result.ok(cached);
        BlogComments comment = blogCommentsService.getById(commentId);
        if (comment == null) return Result.fail("Comment not found");

        String langName = "en".equals(targetLang) ? "English" : "Chinese";
        String translated = callDeepSeek(comment.getContent(), langName);
        if (translated == null) return Result.fail("Translation failed");
        setCached("comment", commentId, targetLang, translated);
        return Result.ok(translated);
    }

    @Override
    public Result translateShop(Long shopId, String targetLang) {
        String cached = getCached("shop", shopId, targetLang);
        if (cached != null) return Result.ok(cached);
        Shop shop = shopService.getById(shopId);
        if (shop == null) return Result.fail("Shop not found");
        String langName = "en".equals(targetLang) ? "English" : "Chinese";
        com.hmdp.entity.ShopType st = shop.getTypeId() != null ? shopTypeService.getById(shop.getTypeId()) : null;
        String typeName = st != null ? st.getName() : "";
        String text = "Shop name: " + shop.getName()
            + "\nCategory: " + typeName
            + "\nArea: " + (shop.getArea() != null ? shop.getArea() : "")
            + "\nAddress: " + (shop.getAddress() != null ? shop.getAddress() : "");
        String translated = callDeepSeek(text, "Translate the following shop info to " + langName + ". Keep the format: Name: xxx, Area: xxx, Address: xxx. Return ONLY the translated lines, one per field, no explanations.");
        if (translated == null) return Result.fail("Translation failed");
        setCached("shop", shopId, targetLang, translated);
        return Result.ok(translated);
    }

    private String getCached(String type, Long id, String lang) {
        return stringRedisTemplate.opsForValue().get(TRANSLATE_CACHE_PREFIX + type + ":" + id + ":" + lang);
    }

    private void setCached(String type, Long id, String lang, String value) {
        stringRedisTemplate.opsForValue().set(TRANSLATE_CACHE_PREFIX + type + ":" + id + ":" + lang, value, CACHE_TTL, TimeUnit.DAYS);
    }

    private String callDeepSeek(String text, String targetLang) {
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.setBearerAuth(deepSeekProperties.getApiKey());

            Map<String, Object> systemMsg = new LinkedHashMap<>();
            systemMsg.put("role", "system");
            systemMsg.put("content", "You are a translator. Translate the following text to " + targetLang + ". Return ONLY the translation, no explanations.");

            Map<String, Object> userMsg = new LinkedHashMap<>();
            userMsg.put("role", "user");
            userMsg.put("content", text);

            Map<String, Object> body = new LinkedHashMap<>();
            body.put("model", deepSeekProperties.getModel());
            body.put("messages", List.of(systemMsg, userMsg));
            body.put("temperature", 0.3);
            body.put("max_tokens", 2048);

            HttpEntity<Map<String, Object>> request = new HttpEntity<>(body, headers);
            ResponseEntity<Map> response = restTemplate.postForEntity(API_URL, request, Map.class);

            if (response.getBody() != null) {
                List<Map<String, Object>> choices = (List<Map<String, Object>>) response.getBody().get("choices");
                if (choices != null && !choices.isEmpty()) {
                    Map<String, Object> msg = (Map<String, Object>) choices.get(0).get("message");
                    if (msg != null) {
                        return (String) msg.get("content");
                    }
                }
            }
        } catch (Exception e) {
            log.error("DeepSeek translation error: {}", e.getMessage());
        }
        return null;
    }
}
