package com.hmdp.service.impl;

import cn.hutool.json.JSONUtil;
import com.hmdp.dto.Result;
import com.hmdp.dto.UserDTO;
import com.hmdp.entity.Shop;
import com.hmdp.entity.ShopReview;
import com.hmdp.service.IShopService;
import com.hmdp.utils.RedisPatternCleaner;
import com.hmdp.utils.UserHolder;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.Serializable;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ShopReviewServiceImplP8Test {

    private StubReviewService service;
    private IShopService shopService;

    @BeforeEach
    void setUp() {
        service = new StubReviewService();
        shopService = mock(IShopService.class);
        when(shopService.getById(9L)).thenReturn(new Shop().setId(9L));
        ReflectionTestUtils.setField(service, "shopService", shopService);
        ReflectionTestUtils.setField(service, "redisPatternCleaner", mock(RedisPatternCleaner.class));
        ReflectionTestUtils.setField(service, "stringRedisTemplate", mock(StringRedisTemplate.class));
        UserDTO user = new UserDTO();
        user.setId(42L);
        UserHolder.saveUser(user);
    }

    @AfterEach
    void tearDown() {
        UserHolder.removeUser();
    }

    @Test
    void buildsAThreeLevelForestWithoutDetachedReplies() {
        ShopReview root = review(1L, null, 0);
        root.setRootId(1L);
        ShopReview child = review(2L, 1L, 1).setRootId(1L);
        ShopReview grandchild = review(3L, 2L, 2).setRootId(1L);
        ShopReview orphan = review(4L, 999L, 1).setRootId(1L);

        List<ShopReview> result = ShopReviewServiceImpl.buildThreadForest(
                List.of(root),
                List.of(child, grandchild, orphan)
        );

        assertEquals(1, result.size());
        assertEquals(1, result.get(0).getChildren().size());
        assertEquals(2L, result.get(0).getChildren().get(0).getId());
        assertEquals(3L, result.get(0).getChildren().get(0).getChildren().get(0).getId());
    }

    @Test
    void cachedReviewPagesRetainTypedNestedChildren() {
        ShopReview child = review(2L, 1L, 1).setRootId(1L).setChildren(List.of());
        ShopReview root = review(1L, null, 0).setRootId(1L).setChildren(List.of(child));

        List<ShopReview> decoded = JSONUtil.toList(JSONUtil.toJsonStr(List.of(root)), ShopReview.class);

        assertEquals(ShopReview.class, decoded.get(0).getChildren().get(0).getClass());
        assertEquals(2L, decoded.get(0).getChildren().get(0).getId());
    }

    @Test
    void replyUsesServerControlledMetadataAndDoesNotUpdateShopAggregates() {
        ShopReview parent = review(10L, 5L, 1)
                .setShopId(9L)
                .setRootId(5L)
                .setUserId(7L);
        service.rows.put(10L, parent);
        ShopReview request = new ShopReview()
                .setShopId(9L)
                .setParentId(10L)
                .setRating(5)
                .setContent("  Thanks for the context  ")
                .setSourceType("SYNTHETIC")
                .setSecurityTest(true);

        Result result = service.addReview(request);

        assertTrue(result.getSuccess());
        assertEquals(2, request.getDepth());
        assertEquals(5L, request.getRootId());
        assertEquals(7L, request.getReplyToUserId());
        assertEquals(42L, request.getUserId());
        assertEquals("USER_SUBMITTED", request.getSourceType());
        assertEquals("USER", request.getAuthorRole());
        assertEquals("Thanks for the context", request.getContent());
        assertNull(request.getRating());
        assertFalse(request.getSecurityTest());
        verify(shopService, never()).update();
    }

    @Test
    void rejectsCrossShopParentsAndFourthLevelReplies() {
        service.rows.put(20L, review(20L, null, 0).setShopId(8L).setRootId(20L));
        service.rows.put(30L, review(30L, 29L, 2).setShopId(9L).setRootId(28L));

        Result crossShop = service.addReview(new ShopReview()
                .setShopId(9L).setParentId(20L).setContent("reply"));
        Result tooDeep = service.addReview(new ShopReview()
                .setShopId(9L).setParentId(30L).setContent("reply"));

        assertFalse(crossShop.getSuccess());
        assertEquals("Parent review not found", crossShop.getErrorMsg());
        assertFalse(tooDeep.getSuccess());
        assertEquals("Review replies cannot be nested beyond level 3", tooDeep.getErrorMsg());
    }

    @Test
    void topLevelReviewInitializesItsRootAndUpdatesAggregateOnce() {
        ShopReview request = new ShopReview()
                .setShopId(9L)
                .setRating(4)
                .setContent("A user-submitted review");

        Result result = service.addReview(request);

        assertTrue(result.getSuccess());
        assertEquals(request.getId(), request.getRootId());
        assertEquals(0, request.getDepth());
        assertTrue(service.rootInitialized);
        assertEquals(1, service.aggregateUpdates);
    }

    private static ShopReview review(Long id, Long parentId, int depth) {
        return new ShopReview()
                .setId(id)
                .setShopId(9L)
                .setUserId(1L)
                .setParentId(parentId)
                .setDepth(depth)
                .setContent("review " + id);
    }

    private static final class StubReviewService extends ShopReviewServiceImpl {
        private final Map<Long, ShopReview> rows = new HashMap<>();
        private long nextId = 100L;
        private boolean rootInitialized;
        private int aggregateUpdates;

        @Override
        public ShopReview getById(Serializable id) {
            return rows.get(Long.valueOf(id.toString()));
        }

        @Override
        public boolean save(ShopReview review) {
            if (review.getId() == null) {
                review.setId(nextId++);
            }
            rows.put(review.getId(), review);
            return true;
        }

        @Override
        public boolean updateById(ShopReview review) {
            rootInitialized = review.getId() != null && review.getId().equals(review.getRootId());
            rows.put(review.getId(), review);
            return true;
        }

        @Override
        boolean updateShopReviewAggregate(Long shopId, int ratingScore) {
            aggregateUpdates++;
            return true;
        }
    }
}
