package com.hmdp.service.impl;

import com.hmdp.config.DeepSeekProperties;
import com.hmdp.dto.Result;
import com.hmdp.entity.ShopReview;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.http.HttpEntity;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;

import java.io.Serializable;
import java.lang.reflect.Proxy;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TranslateServiceImplTest {

    private StubShopReviewService shopReviewService;
    private StubStringRedisTemplate stringRedisTemplate;
    private StubRestTemplate restTemplate;
    private TranslateServiceImpl translateService;

    @BeforeEach
    void setUp() {
        DeepSeekProperties deepSeekProperties = new DeepSeekProperties();
        deepSeekProperties.setApiKey("test-key");

        shopReviewService = new StubShopReviewService();
        stringRedisTemplate = new StubStringRedisTemplate();
        restTemplate = new StubRestTemplate();
        translateService = new TranslateServiceImpl();
        ReflectionTestUtils.setField(translateService, "shopReviewService", shopReviewService);
        ReflectionTestUtils.setField(translateService, "stringRedisTemplate", stringRedisTemplate);
        ReflectionTestUtils.setField(translateService, "restTemplate", restTemplate);
        ReflectionTestUtils.setField(translateService, "deepSeekProperties", deepSeekProperties);
    }

    @Test
    void translatesShopReviewAndUsesDedicatedCacheNamespace() {
        shopReviewService.review = new ShopReview()
                .setId(41L)
                .setContent("The room was quiet.");

        Result result = translateService.translateReview(41L, "zh-CN");

        assertTrue(result.getSuccess());
        assertEquals("房间很安静。", result.getData());
        assertEquals(1, shopReviewService.reads);
        assertEquals(1, restTemplate.calls);
        assertEquals("The room was quiet.", restTemplate.lastUserText);
        assertEquals("房间很安静。", stringRedisTemplate.values.get("translate:review:41:zh-CN"));
        assertEquals(30L, stringRedisTemplate.ttl);
        assertEquals(TimeUnit.DAYS, stringRedisTemplate.ttlUnit);
    }

    @Test
    void returnsCachedReviewTranslationWithoutReadingDatabaseOrCallingDeepSeek() {
        stringRedisTemplate.values.put("translate:review:41:zh-CN", "缓存译文");

        Result result = translateService.translateReview(41L, "zh-CN");

        assertTrue(result.getSuccess());
        assertEquals("缓存译文", result.getData());
        assertEquals(0, shopReviewService.reads);
        assertEquals(0, restTemplate.calls);
    }

    @Test
    void reportsMissingShopReviewWithoutCallingDeepSeek() {
        Result result = translateService.translateReview(404L, "zh-CN");

        assertFalse(result.getSuccess());
        assertEquals("Review not found", result.getErrorMsg());
        assertEquals(1, shopReviewService.reads);
        assertEquals(0, restTemplate.calls);
    }

    private static final class StubShopReviewService extends ShopReviewServiceImpl {
        private ShopReview review;
        private int reads;

        @Override
        public ShopReview getById(Serializable id) {
            reads++;
            return review;
        }
    }

    private static final class StubStringRedisTemplate extends StringRedisTemplate {
        private final Map<String, String> values = new HashMap<>();
        private final ValueOperations<String, String> operations = createOperations();
        private Long ttl;
        private TimeUnit ttlUnit;

        @Override
        public ValueOperations<String, String> opsForValue() {
            return operations;
        }

        @SuppressWarnings("unchecked")
        private ValueOperations<String, String> createOperations() {
            return (ValueOperations<String, String>) Proxy.newProxyInstance(
                    ValueOperations.class.getClassLoader(),
                    new Class<?>[]{ValueOperations.class},
                    (proxy, method, args) -> {
                        if ("get".equals(method.getName())) {
                            return values.get(args[0]);
                        }
                        if ("set".equals(method.getName())) {
                            values.put((String) args[0], (String) args[1]);
                            if (args.length == 4) {
                                ttl = (Long) args[2];
                                ttlUnit = (TimeUnit) args[3];
                            }
                            return null;
                        }
                        throw new UnsupportedOperationException(method.getName());
                    }
            );
        }
    }

    private static final class StubRestTemplate extends RestTemplate {
        private int calls;
        private String lastUserText;

        @Override
        @SuppressWarnings("unchecked")
        public <T> ResponseEntity<T> postForEntity(
                String url,
                Object request,
                Class<T> responseType,
                Object... uriVariables
        ) {
            calls++;
            Map<String, Object> requestBody = (Map<String, Object>) ((HttpEntity<?>) request).getBody();
            List<Map<String, Object>> messages = (List<Map<String, Object>>) requestBody.get("messages");
            lastUserText = (String) messages.get(1).get("content");
            Map<String, Object> responseBody = Map.of(
                    "choices", List.of(Map.of("message", Map.of("content", "房间很安静。")))
            );
            return (ResponseEntity<T>) ResponseEntity.ok(responseBody);
        }
    }
}
