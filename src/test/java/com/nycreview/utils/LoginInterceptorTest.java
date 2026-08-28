package com.nycreview.utils;

import com.nycreview.dto.UserDTO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class LoginInterceptorTest {

    private final LoginInterceptor interceptor = new LoginInterceptor();

    @AfterEach
    void clearUser() {
        UserHolder.removeUser();
    }

    @ParameterizedTest
    @CsvSource({
            "GET, /shop/1",
            "GET, /shop/list",
            "GET, /shop/map",
            "GET, /shop/of/type",
            "GET, /shop/of/name",
            "GET, /shop-review/1",
            "GET, /voucher/list/1",
            "GET, /shop-type/list",
            "GET, /blog/hot",
            "GET, /blog/1",
            "GET, /blog/likes/1",
            "GET, /blog/of/user",
            "GET, /blog-comments",
            "GET, /user/1",
            "GET, /user/info/1",
            "HEAD, /blog/1",
            "POST, /user/code",
            "POST, /user/login",
            "POST, /user/register"
    })
    void allowsPublicRequests(String method, String path) throws Exception {
        MockHttpServletResponse response = new MockHttpServletResponse();

        assertTrue(interceptor.preHandle(request(method, path), response, new Object()));
        assertEquals(200, response.getStatus());
    }

    @ParameterizedTest
    @CsvSource({
            "POST, /shop",
            "PUT, /shop",
            "POST, /shop-review",
            "POST, /voucher",
            "POST, /voucher/seckill",
            "POST, /upload/blog",
            "GET, /upload/blog/delete",
            "POST, /blog",
            "PUT, /blog/like/1",
            "DELETE, /blog/1",
            "GET, /blog/of/me",
            "GET, /blog/of/follow",
            "POST, /blog-comments",
            "DELETE, /blog-comments/1",
            "GET, /user/me",
            "PUT, /user/me",
            "POST, /user/logout",
            "GET, /follow/or/not/1",
            "POST, /translate/blog"
    })
    void rejectsAnonymousProtectedRequests(String method, String path) throws Exception {
        MockHttpServletResponse response = new MockHttpServletResponse();

        assertFalse(interceptor.preHandle(request(method, path), response, new Object()));
        assertEquals(401, response.getStatus());
    }

    @Test
    void allowsAuthenticatedRequests() throws Exception {
        UserDTO user = new UserDTO();
        user.setId(1L);
        UserHolder.saveUser(user);
        MockHttpServletResponse response = new MockHttpServletResponse();

        assertTrue(interceptor.preHandle(request("POST", "/shop"), response, new Object()));
        assertEquals(200, response.getStatus());
    }

    private MockHttpServletRequest request(String method, String path) {
        return new MockHttpServletRequest(method, path);
    }
}
