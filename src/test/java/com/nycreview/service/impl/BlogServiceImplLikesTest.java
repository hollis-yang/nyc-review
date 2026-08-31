package com.nycreview.service.impl;

import com.nycreview.dto.Result;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Collections;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class BlogServiceImplLikesTest {

    @Test
    void queriesMostRecentLikersForVisibleAvatars() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked")
        ZSetOperations<String, String> zSet = mock(ZSetOperations.class);
        when(redis.opsForZSet()).thenReturn(zSet);
        when(zSet.reverseRange("blog:liked:42", 0, 4)).thenReturn(Collections.emptySet());

        BlogServiceImpl service = new BlogServiceImpl();
        ReflectionTestUtils.setField(service, "stringRedisTemplate", redis);

        Result result = service.queryBlogLikes(42L);

        assertEquals(Collections.emptyList(), result.getData());
        verify(zSet).reverseRange("blog:liked:42", 0, 4);
    }
}
