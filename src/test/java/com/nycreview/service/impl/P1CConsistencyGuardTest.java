package com.nycreview.service.impl;

import com.nycreview.controller.UserController;
import com.nycreview.dto.Result;
import com.nycreview.dto.UserDTO;
import com.nycreview.entity.BlogComments;
import com.nycreview.entity.ShopReview;
import com.nycreview.entity.UserInfo;
import com.nycreview.service.IBlogService;
import com.nycreview.service.IShopService;
import com.nycreview.service.IUserInfoService;
import com.nycreview.utils.TransactionHooks;
import com.nycreview.utils.UserHolder;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.lang.reflect.Proxy;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
class P1CConsistencyGuardTest {

    @AfterEach
    void cleanupThreadLocals() {
        UserHolder.removeUser();
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.clearSynchronization();
        }
    }

    @Test
    void profileUpdateUsesUpsertForMissingDetailRow() {
        AtomicReference<UserInfo> savedInfo = new AtomicReference<>();
        IUserInfoService userInfoService = proxy(IUserInfoService.class, (methodName, args) -> {
            if ("saveOrUpdate".equals(methodName)) {
                savedInfo.set((UserInfo) args[0]);
                return true;
            }
            return null;
        });
        UserController controller = new UserController();
        ReflectionTestUtils.setField(controller, "userInfoService", userInfoService);
        UserDTO currentUser = new UserDTO();
        currentUser.setId(42L);
        UserHolder.saveUser(currentUser);
        UserInfo update = new UserInfo();
        update.setCity("New York City");

        Result result = controller.updateInfo(update);

        assertTrue(result.getSuccess());
        assertEquals(42L, update.getUserId());
        assertEquals(update, savedInfo.get());
    }

    @Test
    void followRejectsSelfAndInvalidArgumentsBeforeWriting() {
        FollowServiceImpl service = new FollowServiceImpl();
        UserDTO currentUser = new UserDTO();
        currentUser.setId(7L);
        UserHolder.saveUser(currentUser);

        Result selfFollow = service.follow(7L, true);
        Result invalid = service.follow(null, true);

        assertFalse(selfFollow.getSuccess());
        assertEquals("You cannot follow yourself", selfFollow.getErrorMsg());
        assertFalse(invalid.getSuccess());
        assertEquals("Invalid follow request", invalid.getErrorMsg());
    }

    @Test
    void commentRejectsMissingBlogBeforeSaving() {
        IBlogService blogService = proxy(IBlogService.class, (methodName, args) -> null);
        BlogCommentsServiceImpl service = new BlogCommentsServiceImpl();
        ReflectionTestUtils.setField(service, "blogService", blogService);
        BlogComments comment = new BlogComments();
        comment.setBlogId(99L);
        comment.setContent("test");

        Result result = service.addComment(comment);

        assertFalse(result.getSuccess());
        assertEquals("Blog not found", result.getErrorMsg());
    }

    @Test
    void reviewRejectsMissingShopBeforeSaving() {
        IShopService shopService = proxy(IShopService.class, (methodName, args) -> null);
        ShopReviewServiceImpl service = new ShopReviewServiceImpl();
        ReflectionTestUtils.setField(service, "shopService", shopService);
        ShopReview review = new ShopReview();
        review.setShopId(99L);
        review.setRating(5);
        review.setContent("test");

        Result result = service.addReview(review);

        assertFalse(result.getSuccess());
        assertEquals("Shop not found", result.getErrorMsg());
    }

    @Test
    void afterCommitHookRunsOnlyAfterSuccessfulCommitCallback() {
        AtomicBoolean executed = new AtomicBoolean(false);
        TransactionSynchronizationManager.initSynchronization();

        TransactionHooks.afterCommit(() -> executed.set(true));

        assertFalse(executed.get());
        for (TransactionSynchronization synchronization
                : TransactionSynchronizationManager.getSynchronizations()) {
            synchronization.afterCommit();
        }
        assertTrue(executed.get());
    }

    @SuppressWarnings("unchecked")
    private static <T> T proxy(Class<T> type, StubInvocation invocation) {
        return (T) Proxy.newProxyInstance(
                type.getClassLoader(),
                new Class<?>[]{type},
                (proxy, method, args) -> {
                    Object value = invocation.invoke(method.getName(), args == null ? new Object[0] : args);
                    if (value != null || !method.getReturnType().isPrimitive()) {
                        return value;
                    }
                    if (method.getReturnType() == boolean.class) {
                        return false;
                    }
                    if (method.getReturnType() == long.class) {
                        return 0L;
                    }
                    if (method.getReturnType() == int.class) {
                        return 0;
                    }
                    return null;
                });
    }

    @FunctionalInterface
    private interface StubInvocation {
        Object invoke(String methodName, Object[] args);
    }
}
