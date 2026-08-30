package com.nycreview.service.impl;

import cn.hutool.core.bean.BeanUtil;
import cn.hutool.core.bean.copier.CopyOptions;
import cn.hutool.core.lang.UUID;
import cn.hutool.core.util.RandomUtil;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.nycreview.dto.LoginFormDTO;
import com.nycreview.dto.RegisterFormDTO;
import com.nycreview.dto.Result;
import com.nycreview.dto.UserDTO;
import com.nycreview.entity.User;
import com.nycreview.mapper.UserMapper;
import com.nycreview.entity.UserInfo;
import com.nycreview.service.AuthRateLimiter;
import com.nycreview.service.IUserInfoService;
import com.nycreview.service.IUserService;
import com.nycreview.utils.PasswordEncoder;
import com.nycreview.utils.PasswordPolicy;
import com.nycreview.utils.PhoneNumberNormalizer;
import com.nycreview.utils.UserHolder;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.data.redis.connection.BitFieldSubCommands;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import jakarta.annotation.Resource;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import static com.nycreview.utils.RedisConstants.*;
import static com.nycreview.utils.SystemConstants.USER_NICK_NAME_PREFIX;

@Slf4j
@Service
public class UserServiceImpl extends ServiceImpl<UserMapper, User> implements IUserService {
    private static final int DEFAULT_AVATAR_COUNT = 12;

    @Resource
    private StringRedisTemplate stringRedisTemplate;

    @Resource
    private IUserInfoService userInfoService;

    @Resource
    private PhoneNumberNormalizer phoneNumberNormalizer;

    @Resource
    private PasswordEncoder passwordEncoder;

    @Resource
    private AuthRateLimiter authRateLimiter;

    @Override
    public Result sign() {
        // 1.获取当前登录用户
        Long userId = UserHolder.getUser().getId();
        // 2.获取日期
        LocalDateTime now = LocalDateTime.now();
        // 3.拼接key
        String keySuffix = now.format(DateTimeFormatter.ofPattern(":yyyyMM"));
        String key = USER_SIGN_KEY + userId + keySuffix;
        // 4.获取今天是本月的第几天
        int dayOfMonth = now.getDayOfMonth();
        // 5.写入Redis SETBIT key offset 1，返回旧值判断是否已签到
        Boolean alreadySigned = stringRedisTemplate.opsForValue()
                .setBit(key, dayOfMonth - 1, true);
        if (Boolean.TRUE.equals(alreadySigned)) {
            return Result.fail("You have already checked in today");
        }
        return Result.ok();
    }

    @Override
    public Result signCount() {
        // 1.获取当前登录用户
        Long userId = UserHolder.getUser().getId();
        // 2.获取日期
        LocalDateTime now = LocalDateTime.now();
        // 3.拼接key
        String keySuffix = now.format(DateTimeFormatter.ofPattern(":yyyyMM"));
        String key = USER_SIGN_KEY + userId + keySuffix;
        // 4.获取今天是本月的第几天
        int dayOfMonth = now.getDayOfMonth();
        // 5.获取本月截止今天为止的所有的签到记录，返回的是一个十进制的数字 BITFIELD sign:5:202203 GET u14 0
        List<Long> result = stringRedisTemplate.opsForValue().bitField(
                key,
                BitFieldSubCommands.create()
                        .get(BitFieldSubCommands.BitFieldType.unsigned(dayOfMonth)).valueAt(0)
        );
        if (result == null || result.isEmpty()) {
            // 没有任何签到结果
            return Result.ok(0);
        }
        Long num = result.get(0);
        if (num == null || num == 0) {
            return Result.ok(0);
        }
        // 6.循环遍历
        int count = 0;
        while (true) {
            // 6.1.让这个数字与1做与运算，得到数字的最后一个bit位  // 判断这个bit位是否为0
            if ((num & 1) == 0) {
                // 如果为0，说明未签到，结束
                break;
            } else {
                // 如果不为0，说明已签到，计数器+1
                count++;
            }
            // 把数字右移一位，抛弃最后一个bit位，继续下一个bit位
            num >>>= 1;
        }
        return Result.ok(count);
    }

    @Override
    public Result login(LoginFormDTO loginForm, String clientAddress) {
        if (loginForm == null) {
            throw new IllegalArgumentException("Login request is required");
        }
        PasswordPolicy.validateLoginInput(loginForm.getPassword());
        String phone = phoneNumberNormalizer.normalize(
                loginForm.getRegionCode(),
                loginForm.getPhoneNumber(),
                loginForm.getPhone()
        );
        if (!authRateLimiter.allowLoginAttempt(phone, clientAddress)) {
            return Result.fail("Too many login attempts. Please try again later");
        }

        User user = query().eq("phone", phone).one();
        if (user == null || !passwordEncoder.matches(user.getPassword(), loginForm.getPassword())) {
            authRateLimiter.recordLoginFailure(phone);
            return Result.fail("Invalid phone number or password");
        }

        if (passwordEncoder.needsUpgrade(user.getPassword())) {
            update().eq("id", user.getId())
                    .set("password", passwordEncoder.encode(loginForm.getPassword()))
                    .update();
        }
        authRateLimiter.recordLoginSuccess(phone);
        return issueToken(user);
    }

    @Override
    @Transactional
    public Result register(RegisterFormDTO registerForm, String clientAddress) {
        if (registerForm == null) {
            throw new IllegalArgumentException("Registration request is required");
        }
        if (!authRateLimiter.allowRegistration(clientAddress)) {
            return Result.fail("Too many registration attempts. Please try again later");
        }
        PasswordPolicy.validate(registerForm.getPassword());
        String phone = phoneNumberNormalizer.normalize(
                registerForm.getRegionCode(),
                registerForm.getPhoneNumber(),
                registerForm.getPhone()
        );
        if (query().eq("phone", phone).count() > 0) {
            return Result.fail("This phone number is already registered");
        }

        try {
            User user = createUserWithPhone(
                    phone,
                    passwordEncoder.encode(registerForm.getPassword()),
                    registerForm.getNickName()
            );
            return issueToken(user);
        } catch (DuplicateKeyException e) {
            throw new IllegalArgumentException("This phone number is already registered");
        }
    }

    private Result issueToken(User user) {
        String token = UUID.randomUUID().toString(true);
        UserDTO userDTO = BeanUtil.copyProperties(user, UserDTO.class);
        Map<String, Object> userMap = BeanUtil.beanToMap(userDTO, new HashMap<>(),
                CopyOptions.create()
                        .setIgnoreNullValue(true)
                        .setFieldValueEditor((fieldName, fieldValue) -> fieldValue.toString()));
        stringRedisTemplate.opsForHash().putAll(LOGIN_USER_KEY + token, userMap);
        stringRedisTemplate.expire(LOGIN_USER_KEY + token, LOGIN_USER_TTL, TimeUnit.SECONDS);
        return Result.ok(token);
    }

    private User createUserWithPhone(String phone, String encodedPassword, String requestedNickName) {
        User user = new User();
        user.setPhone(phone);
        user.setPassword(encodedPassword);
        user.setNickName(normalizeNickName(requestedNickName));
        int avatarNumber = Math.floorMod(phone.hashCode(), DEFAULT_AVATAR_COUNT) + 1;
        user.setIcon(String.format("/imgs/avatars/avatar-%02d.svg", avatarNumber));

        save(user);
        UserInfo userInfo = new UserInfo();
        userInfo.setUserId(user.getId());
        userInfo.setFans(0);
        userInfo.setFollowee(0);
        userInfo.setCredits(0);
        userInfo.setLevel(false);
        if (!userInfoService.save(userInfo)) {
            throw new IllegalStateException("Failed to initialize the user profile");
        }
        return user;
    }

    private String normalizeNickName(String requestedNickName) {
        if (requestedNickName == null || requestedNickName.isBlank()) {
            return USER_NICK_NAME_PREFIX + RandomUtil.randomString(10);
        }
        String nickName = requestedNickName.trim();
        if (nickName.codePointCount(0, nickName.length()) > 32) {
            throw new IllegalArgumentException("Nickname cannot exceed 32 characters");
        }
        return nickName;
    }
}
