package com.nycreview.service;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.nycreview.dto.ChangePasswordDTO;
import com.nycreview.dto.ResetPasswordDTO;
import com.nycreview.entity.User;
import com.nycreview.mapper.UserMapper;
import com.nycreview.utils.PasswordEncoder;
import com.nycreview.utils.PhoneNumberNormalizer;
import com.nycreview.utils.RecoveryKeyEncoder;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AccountSecurityServiceTest {

    private UserMapper userMapper;
    private PasswordEncoder passwordEncoder;
    private RecoveryKeyEncoder recoveryKeyEncoder;
    private AuthRateLimiter rateLimiter;
    private StringRedisTemplate redis;
    private AccountSecurityService service;

    @BeforeEach
    void setUp() {
        userMapper = mock(UserMapper.class);
        passwordEncoder = mock(PasswordEncoder.class);
        recoveryKeyEncoder = mock(RecoveryKeyEncoder.class);
        rateLimiter = mock(AuthRateLimiter.class);
        redis = mock(StringRedisTemplate.class);
        service = new AccountSecurityService(
                userMapper,
                passwordEncoder,
                recoveryKeyEncoder,
                new PhoneNumberNormalizer(),
                rateLimiter,
                redis
        );
    }

    @Test
    void statusOnlyDisclosesWhetherARecoveryHashExists() {
        User user = user(7L);
        when(userMapper.selectById(7L)).thenReturn(user);

        assertFalse(service.status(7L).get("recoveryKeyConfigured"));

        user.setRecoveryKeyHash("$2a$12$hashed-value");
        assertTrue(service.status(7L).get("recoveryKeyConfigured"));
    }

    @Test
    void passwordChangeConfirmsCurrentPasswordAndInvalidatesTheCurrentToken() {
        User user = user(7L);
        when(userMapper.selectById(7L)).thenReturn(user);
        when(rateLimiter.allowLoginAttempt(user.getPhone(), "198.51.100.7")).thenReturn(true);
        when(passwordEncoder.matches(user.getPassword(), "Current1!")).thenReturn(true);
        when(passwordEncoder.matches(user.getPassword(), "Different2!")).thenReturn(false);
        when(passwordEncoder.encode("Different2!")).thenReturn("new-hash");
        ChangePasswordDTO request = new ChangePasswordDTO();
        request.setCurrentPassword("Current1!");
        request.setNewPassword("Different2!");

        service.changePassword(7L, request, "current-token", "198.51.100.7");

        verify(userMapper).updateById(user);
        verify(redis).delete("login:token:current-token");
        verify(rateLimiter).recordLoginSuccess(user.getPhone());
    }

    @Test
    void unknownAccountsUseDummyBcryptAndTheSameGenericResetFailure() {
        when(rateLimiter.allowPasswordResetAttempt("+12125550123", "198.51.100.7")).thenReturn(true);
        when(userMapper.selectOne(any(Wrapper.class))).thenReturn(null);
        when(recoveryKeyEncoder.matchesOrDummy(null, "Recovery-Key-123!")).thenReturn(false);

        IllegalArgumentException error = assertThrows(
                IllegalArgumentException.class,
                () -> service.resetPassword(resetRequest(), "198.51.100.7")
        );

        assertTrue(error.getMessage().contains("Unable to reset password"));
        verify(recoveryKeyEncoder).matchesOrDummy(null, "Recovery-Key-123!");
        verify(rateLimiter).recordPasswordResetFailure("+12125550123");
    }

    @Test
    void validRecoveryKeyReplacesThePasswordHash() {
        User user = user(7L);
        user.setRecoveryKeyHash("recovery-hash");
        when(rateLimiter.allowPasswordResetAttempt("+12125550123", "198.51.100.7")).thenReturn(true);
        when(userMapper.selectOne(any(Wrapper.class))).thenReturn(user);
        when(recoveryKeyEncoder.matchesOrDummy("recovery-hash", "Recovery-Key-123!")).thenReturn(true);
        when(passwordEncoder.encode("New-password-2!")).thenReturn("new-password-hash");

        service.resetPassword(resetRequest(), "198.51.100.7");

        verify(userMapper).updateById(user);
        verify(rateLimiter).recordPasswordResetSuccess("+12125550123");
        assertEquals("new-password-hash", user.getPassword());
    }

    private ResetPasswordDTO resetRequest() {
        ResetPasswordDTO request = new ResetPasswordDTO();
        request.setRegionCode("US");
        request.setPhoneNumber("2125550123");
        request.setRecoveryKey("Recovery-Key-123!");
        request.setNewPassword("New-password-2!");
        return request;
    }

    private User user(long id) {
        User user = new User();
        user.setId(id);
        user.setPhone("+12125550123");
        user.setPassword("current-hash");
        return user;
    }
}
