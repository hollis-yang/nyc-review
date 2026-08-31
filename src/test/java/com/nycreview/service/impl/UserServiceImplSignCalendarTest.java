package com.nycreview.service.impl;

import com.nycreview.dto.SignCalendarDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDate;
import java.time.YearMonth;
import java.time.ZoneId;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class UserServiceImplSignCalendarTest {

    private UserServiceImpl service;
    private ValueOperations<String, String> values;

    @BeforeEach
    void setUp() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked")
        ValueOperations<String, String> mockedValues = mock(ValueOperations.class);
        values = mockedValues;
        when(redis.opsForValue()).thenReturn(values);
        service = new UserServiceImpl();
        ReflectionTestUtils.setField(service, "stringRedisTemplate", redis);
    }

    @Test
    void returnsMonthlyDaysAndTheDemoAccountsSevenDayStreak() {
        when(values.getBit(anyString(), anyLong())).thenAnswer(invocation -> {
            String key = invocation.getArgument(0);
            long offset = invocation.getArgument(1);
            return key.equals("sign:1001:202608") && offset >= 24 && offset <= 30;
        });

        SignCalendarDTO calendar = service.signCalendarFor(
                1001L,
                YearMonth.of(2026, 8),
                LocalDate.of(2026, 8, 31)
        );

        assertEquals(List.of(25, 26, 27, 28, 29, 30, 31), calendar.checkedDays());
        assertEquals(7, calendar.currentStreak());
        assertTrue(calendar.signedToday());
        assertEquals("2026-08-31", calendar.today());
    }

    @Test
    void streakCanContinueAcrossRedisMonthlyBitmapKeys() {
        when(values.getBit(anyString(), anyLong())).thenAnswer(invocation -> {
            String key = invocation.getArgument(0);
            long offset = invocation.getArgument(1);
            return (key.equals("sign:42:202602") && offset == 0)
                    || (key.equals("sign:42:202601") && offset == 30);
        });

        SignCalendarDTO calendar = service.signCalendarFor(
                42L,
                YearMonth.of(2026, 2),
                LocalDate.of(2026, 2, 1)
        );

        assertEquals(List.of(1), calendar.checkedDays());
        assertEquals(2, calendar.currentStreak());
        assertTrue(calendar.signedToday());
    }

    @Test
    void checkInDatesUseTheNewYorkCalendarAndStableRedisKeyFormat() {
        assertEquals(LocalDate.now(ZoneId.of("America/New_York")), UserServiceImpl.nycToday());
        assertEquals("sign:1002:202608", UserServiceImpl.signKey(1002L, YearMonth.of(2026, 8)));
    }
}
