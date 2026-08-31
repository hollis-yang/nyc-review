package com.nycreview.profile.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.nycreview.dto.UserDTO;
import com.nycreview.utils.UserHolder;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.time.LocalDateTime;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ProfileAssetsServiceTest {

    @AfterEach
    void clearUser() {
        UserHolder.removeUser();
    }

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

    @Test
    void favoriteStateUsesTheSameTableAsProfileFavorites() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        ProfileAssetsService service = new ProfileAssetsService(jdbcTemplate, mock(ObjectMapper.class));
        signInAs(42L);

        when(jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM tb_shop_favorite WHERE user_id = ? AND shop_id = ?",
                Long.class,
                42L,
                4630L
        )).thenReturn(1L);

        assertTrue(service.isFavorite(4630L));
    }

    @Test
    void favoriteAndUnfavoriteAreIdempotentForTheSignedInUser() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        ProfileAssetsService service = new ProfileAssetsService(jdbcTemplate, mock(ObjectMapper.class));
        signInAs(42L);
        when(jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM tb_shop WHERE id = ?",
                Long.class,
                4630L
        )).thenReturn(1L);

        service.favoriteShop(4630L);
        service.unfavoriteShop(4630L);

        verify(jdbcTemplate).update(
                "INSERT INTO tb_shop_favorite(user_id, shop_id, create_time) VALUES (?, ?, NOW()) " +
                        "ON DUPLICATE KEY UPDATE create_time = create_time",
                42L,
                4630L
        );
        verify(jdbcTemplate).update(
                "DELETE FROM tb_shop_favorite WHERE user_id = ? AND shop_id = ?",
                42L,
                4630L
        );
    }

    @Test
    void favoriteRejectsMissingShopsBeforeWriting() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        ProfileAssetsService service = new ProfileAssetsService(jdbcTemplate, mock(ObjectMapper.class));
        signInAs(42L);
        when(jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM tb_shop WHERE id = ?",
                Long.class,
                9999L
        )).thenReturn(0L);

        assertThrows(IllegalArgumentException.class, () -> service.favoriteShop(9999L));
    }

    private static void signInAs(Long userId) {
        UserDTO user = new UserDTO();
        user.setId(userId);
        UserHolder.saveUser(user);
    }
}
