package com.nycreview.utils;

import org.springframework.web.servlet.HandlerInterceptor;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

public class LoginInterceptor implements HandlerInterceptor {

    private static final Set<String> PUBLIC_GET_PATHS = Set.of(
            "/shop/list",
            "/shop/map",
            "/shop/of/type",
            "/shop/of/name",
            "/shop/link-options",
            "/shop-type/list",
            "/blog/hot",
            "/blog/of/user",
            "/blog-comments"
    );

    private static final List<Pattern> PUBLIC_GET_PATH_PATTERNS = List.of(
            Pattern.compile("^/shop/\\d+$"),
            Pattern.compile("^/shop-review/\\d+$"),
            Pattern.compile("^/voucher/list/\\d+$"),
            Pattern.compile("^/blog/\\d+$"),
            Pattern.compile("^/blog/likes/\\d+$"),
            Pattern.compile("^/user/\\d+$"),
            Pattern.compile("^/user/info/\\d+$"),
            Pattern.compile("^/internal/agent/tools/shops/\\d+$"),
            Pattern.compile("^/internal/agent/tools/shops/\\d+/evidence$")
    );

    private static final Set<String> PUBLIC_POST_PATHS = Set.of(
            "/user/code",
            "/user/login",
            "/user/register",
            "/user/password/reset",
            "/internal/agent/tools/shops/search",
            "/internal/agent/tools/shops/details"
    );

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws Exception {
        if (isPublicRequest(request)) {
            return true;
        }

        // 判断是否要拦截(ThreadLocal中是否有用户)
        if (UserHolder.getUser() == null) {
            response.setStatus(401);
            return false;
        }
        return true;
    }

    static boolean isPublicRequest(HttpServletRequest request) {
        String method = request.getMethod();
        String contextPath = request.getContextPath();
        String requestUri = request.getRequestURI();
        String path = requestUri.substring(contextPath.length());

        if ("/error".equals(path)) {
            return true;
        }

        if ("POST".equalsIgnoreCase(method)) {
            return PUBLIC_POST_PATHS.contains(path);
        }

        if (!"GET".equalsIgnoreCase(method) && !"HEAD".equalsIgnoreCase(method)) {
            return false;
        }

        if (PUBLIC_GET_PATHS.contains(path)) {
            return true;
        }
        return PUBLIC_GET_PATH_PATTERNS.stream()
                .anyMatch(pattern -> pattern.matcher(path).matches());
    }
}
