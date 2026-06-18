package com.hmdp.service.impl;

import com.hmdp.config.DeepSeekProperties;
import com.hmdp.dto.Result;
import com.hmdp.entity.Blog;
import com.hmdp.entity.BlogComments;
import com.hmdp.service.IBlogCommentsService;
import com.hmdp.service.IBlogService;
import com.hmdp.service.TranslateService;
import jakarta.annotation.Resource;
import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.*;

@Service
public class TranslateServiceImpl implements TranslateService {

    @Resource
    private IBlogService blogService;

    @Resource
    private IBlogCommentsService blogCommentsService;

    @Resource
    private RestTemplate restTemplate;

    @Resource
    private DeepSeekProperties deepSeekProperties;

    private static final String API_URL = "https://api.deepseek.com/v1/chat/completions";

    @Override
    public Result translateBlog(Long blogId, String targetLang) {
        Blog blog = blogService.getById(blogId);
        if (blog == null) return Result.fail("Blog not found");

        String langName = "en".equals(targetLang) ? "English" : "Chinese";
        String content = blog.getContent();
        if (content == null || content.isBlank()) content = "";
        String text = (blog.getTitle() != null ? blog.getTitle() + "\n\n" : "") + content;

        String translated = callDeepSeek(text, langName);
        if (translated == null) return Result.fail("Translation failed");
        return Result.ok(translated);
    }

    @Override
    public Result translateComment(Long commentId, String targetLang) {
        BlogComments comment = blogCommentsService.getById(commentId);
        if (comment == null) return Result.fail("Comment not found");

        String langName = "en".equals(targetLang) ? "English" : "Chinese";
        String translated = callDeepSeek(comment.getContent(), langName);
        if (translated == null) return Result.fail("Translation failed");
        return Result.ok(translated);
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
            e.printStackTrace();
        }
        return null;
    }
}
