package com.nycreview.service.impl;

import cn.hutool.core.bean.BeanUtil;
import cn.hutool.core.bean.copier.CopyOptions;
import cn.hutool.core.lang.UUID;
import cn.hutool.core.util.RandomUtil;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.nycreview.dto.LoginFormDTO;
import com.nycreview.dto.RegisterFormDTO;
import com.nycreview.dto.Result;
import com.nycreview.dto.SignCalendarDTO;
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
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import jakarta.annotation.Resource;
import java.time.LocalDate;
import java.time.YearMonth;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
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
    private static final ZoneId NYC_ZONE = ZoneId.of("America/New_York");
    private static final DateTimeFormatter SIGN_KEY_MONTH = DateTimeFormatter.ofPattern("yyyyMM");
    private static final int MAX_STREAK_LOOKBACK_DAYS = 3660;

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
        Long userId = UserHolder.getUser().getId();
        LocalDate today = nycToday();
        String key = signKey(userId, YearMonth.from(today));
        Boolean alreadySigned = stringRedisTemplate.opsForValue()
                .setBit(key, today.getDayOfMonth() - 1L, true);
        if (Boolean.TRUE.equals(alreadySigned)) {
            return Result.fail("You have already checked in today");
        }
        return Result.ok();
    }

    @Override
    public Result signCount() {
        Long userId = UserHolder.getUser().getId();
        return Result.ok(currentStreak(userId, nycToday()));
    }

    @Override
    public Result signCalendar(Integer year, Integer month) {
        Long userId = UserHolder.getUser().getId();
        LocalDate today = nycToday();
        YearMonth requestedMonth;
        if (year == null && month == null) {
            requestedMonth = YearMonth.from(today);
        } else if (year == null || month == null) {
            throw new IllegalArgumentException("Year and month must be provided together");
        } else {
            try {
                requestedMonth = YearMonth.of(year, month);
            } catch (RuntimeException exception) {
                throw new IllegalArgumentException("Invalid calendar month");
            }
        }
        if (requestedMonth.isBefore(YearMonth.of(2000, 1))
                || requestedMonth.isAfter(YearMonth.from(today).plusMonths(12))) {
            throw new IllegalArgumentException("Calendar month is outside the supported range");
        }
        return Result.ok(signCalendarFor(userId, requestedMonth, today));
    }

    SignCalendarDTO signCalendarFor(Long userId, YearMonth requestedMonth, LocalDate today) {
        List<Integer> checkedDays = new ArrayList<>();
        String key = signKey(userId, requestedMonth);
        for (int day = 1; day <= requestedMonth.lengthOfMonth(); day++) {
            if (Boolean.TRUE.equals(stringRedisTemplate.opsForValue().getBit(key, day - 1L))) {
                checkedDays.add(day);
            }
        }
        return new SignCalendarDTO(
                requestedMonth.getYear(),
                requestedMonth.getMonthValue(),
                List.copyOf(checkedDays),
                currentStreak(userId, today),
                hasSigned(userId, today),
                today.toString()
        );
    }

    private int currentStreak(Long userId, LocalDate today) {
        int streak = 0;
        LocalDate cursor = today;
        while (streak < MAX_STREAK_LOOKBACK_DAYS && hasSigned(userId, cursor)) {
            streak++;
            cursor = cursor.minusDays(1);
        }
        return streak;
    }

    private boolean hasSigned(Long userId, LocalDate date) {
        String key = signKey(userId, YearMonth.from(date));
        return Boolean.TRUE.equals(stringRedisTemplate.opsForValue().getBit(key, date.getDayOfMonth() - 1L));
    }

    static String signKey(Long userId, YearMonth month) {
        return USER_SIGN_KEY + userId + ":" + SIGN_KEY_MONTH.format(month);
    }

    static LocalDate nycToday() {
        return LocalDate.now(NYC_ZONE);
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
