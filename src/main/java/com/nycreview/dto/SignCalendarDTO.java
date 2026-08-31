package com.nycreview.dto;

import java.util.List;

public record SignCalendarDTO(
        int year,
        int month,
        List<Integer> checkedDays,
        int currentStreak,
        boolean signedToday,
        String today
) {
}
