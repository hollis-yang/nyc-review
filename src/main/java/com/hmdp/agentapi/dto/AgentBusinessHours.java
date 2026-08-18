package com.hmdp.agentapi.dto;

import java.time.LocalTime;

public record AgentBusinessHours(
        Integer dayOfWeek,
        boolean closed,
        LocalTime openTime,
        LocalTime closeTime,
        boolean closesNextDay
) {
}
