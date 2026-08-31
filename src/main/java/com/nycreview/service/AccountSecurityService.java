package com.nycreview.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.nycreview.dto.ChangePasswordDTO;
import com.nycreview.dto.RecoveryKeyDTO;
import com.nycreview.dto.ResetPasswordDTO;
import com.nycreview.entity.User;
import com.nycreview.mapper.UserMapper;
import com.nycreview.utils.PasswordEncoder;
import com.nycreview.utils.PasswordPolicy;
import com.nycreview.utils.PhoneNumberNormalizer;
import com.nycreview.utils.RecoveryKeyEncoder;
import com.nycreview.utils.RecoveryKeyPolicy;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Map;

import static com.nycreview.utils.RedisConstants.LOGIN_USER_KEY;

@Service
public class AccountSecurityService {

    private static final String RESET_REJECTED = "Unable to reset password with those details";

    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;
    private final RecoveryKeyEncoder recoveryKeyEncoder;
    private final PhoneNumberNormalizer phoneNumberNormalizer;
    private final AuthRateLimiter authRateLimiter;
    private final StringRedisTemplate redisTemplate;

    public AccountSecurityService(
            UserMapper userMapper,
            PasswordEncoder passwordEncoder,
            RecoveryKeyEncoder recoveryKeyEncoder,
            PhoneNumberNormalizer phoneNumberNormalizer,
            AuthRateLimiter authRateLimiter,
            StringRedisTemplate redisTemplate
    ) {
        this.userMapper = userMapper;
        this.passwordEncoder = passwordEncoder;
        this.recoveryKeyEncoder = recoveryKeyEncoder;
        this.phoneNumberNormalizer = phoneNumberNormalizer;
        this.authRateLimiter = authRateLimiter;
        this.redisTemplate = redisTemplate;
    }

    public Map<String, Boolean> status(long userId) {
        User user = requireUser(userId);
        return Map.of(
                "recoveryKeyConfigured",
                user.getRecoveryKeyHash() != null && !user.getRecoveryKeyHash().isBlank()
        );
    }

    @Transactional
    public void setRecoveryKey(long userId, RecoveryKeyDTO request, String clientAddress) {
        if (request == null) {
            throw new IllegalArgumentException("Recovery-key request is required");
        }
        User user = requireUser(userId);
        confirmCurrentPassword(user, request.getCurrentPassword(), clientAddress);
        RecoveryKeyPolicy.validate(request.getRecoveryKey());
        user.setRecoveryKeyHash(recoveryKeyEncoder.encode(request.getRecoveryKey()));
        userMapper.updateById(user);
    }

    @Transactional
    public void changePassword(long userId, ChangePasswordDTO request, String token, String clientAddress) {
        if (request == null) {
            throw new IllegalArgumentException("Password-change request is required");
        }
        User user = requireUser(userId);
        confirmCurrentPassword(user, request.getCurrentPassword(), clientAddress);
        PasswordPolicy.validate(request.getNewPassword());
        if (passwordEncoder.matches(user.getPassword(), request.getNewPassword())) {
            throw new IllegalArgumentException("New password must be different from the current password");
        }
        user.setPassword(passwordEncoder.encode(request.getNewPassword()));
        userMapper.updateById(user);

        if (token != null && !token.isBlank()) {
            redisTemplate.delete(LOGIN_USER_KEY + token);
        }
    }

    @Transactional
    public void resetPassword(ResetPasswordDTO request, String clientAddress) {
        if (request == null) {
            throw new IllegalArgumentException("Password-reset request is required");
        }
        String phone = phoneNumberNormalizer.normalize(
                request.getRegionCode(),
                request.getPhoneNumber(),
                request.getPhone()
        );
        if (!authRateLimiter.allowPasswordResetAttempt(phone, clientAddress)) {
            throw new IllegalArgumentException("Too many password reset attempts. Please try again later");
        }
        PasswordPolicy.validate(request.getNewPassword());

        User user = userMapper.selectOne(
                new LambdaQueryWrapper<User>().eq(User::getPhone, phone).last("LIMIT 1")
        );
        String storedRecoveryKey = user == null ? null : user.getRecoveryKeyHash();
        boolean validRecoveryKey = RecoveryKeyPolicy.isStrong(request.getRecoveryKey())
                && recoveryKeyEncoder.matchesOrDummy(storedRecoveryKey, request.getRecoveryKey());
        if (!validRecoveryKey) {
            // The same message and BCrypt work are used for unknown accounts and invalid keys.
            if (!RecoveryKeyPolicy.isStrong(request.getRecoveryKey())) {
                recoveryKeyEncoder.matchesOrDummy(storedRecoveryKey, request.getRecoveryKey());
            }
            authRateLimiter.recordPasswordResetFailure(phone);
            throw new IllegalArgumentException(RESET_REJECTED);
        }

        user.setPassword(passwordEncoder.encode(request.getNewPassword()));
        userMapper.updateById(user);
        authRateLimiter.recordPasswordResetSuccess(phone);
    }

    private User requireUser(long userId) {
        User user = userMapper.selectById(userId);
        if (user == null) {
            throw new IllegalArgumentException("Account is unavailable");
        }
        return user;
    }

    private void confirmCurrentPassword(User user, String currentPassword, String clientAddress) {
        PasswordPolicy.validateLoginInput(currentPassword);
        if (!authRateLimiter.allowLoginAttempt(user.getPhone(), clientAddress)) {
            throw new IllegalArgumentException("Too many login attempts. Please try again later");
        }
        if (!passwordEncoder.matches(user.getPassword(), currentPassword)) {
            authRateLimiter.recordLoginFailure(user.getPhone());
            throw new IllegalArgumentException("Current password is incorrect");
        }
        authRateLimiter.recordLoginSuccess(user.getPhone());
    }
}
