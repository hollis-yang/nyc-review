package com.nycreview.profile.service;

import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class ProfileAssetsServiceTest {

    @Test
    void memoryValuesAreTrimmedAndBoundedBeforeAnyWrite() {
        assertEquals("quiet dinners", ProfileAssetsService.validateMemoryValue("  quiet dinners  "));
        assertThrows(IllegalArgumentException.class, () -> ProfileAssetsService.validateMemoryValue(" "));
        assertThrows(
                IllegalArgumentException.class,
                () -> ProfileAssetsService.validateMemoryValue("x".repeat(501))
        );
    }

    @Test
    void reminderStatusReflectsManualPurchaseAndElapsedSchedule() {
        LocalDateTime now = LocalDateTime.of(2026, 8, 31, 12, 0);
        assertEquals("PURCHASED", ProfileAssetsService.effectiveReminderStatus(
                true, now.plusDays(1), now.plusHours(1), "PENDING", now));
        assertEquals("EXPIRED", ProfileAssetsService.effectiveReminderStatus(
                false, now.minusMinutes(1), now.minusDays(1), "PENDING", now));
        assertEquals("SENT", ProfileAssetsService.effectiveReminderStatus(
                false, now.plusDays(1), now.minusMinutes(1), "PENDING", now));
        assertEquals("PENDING", ProfileAssetsService.effectiveReminderStatus(
                false, now.plusDays(1), now.plusMinutes(1), "PENDING", now));
        assertEquals("CANCELLED", ProfileAssetsService.effectiveReminderStatus(
                false, now.minusDays(1), now.minusDays(2), "CANCELLED", now));
    }
}
