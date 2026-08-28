package com.nycreview.profile.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.nycreview.profile.dto.ProfileAssetsResponse;
import com.nycreview.utils.UserHolder;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class ProfileAssetsService {

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public ProfileAssetsService(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    @Transactional(readOnly = true)
    public ProfileAssetsResponse assets() {
        Long userId = UserHolder.getUser().getId();
        List<ProfileAssetsResponse.FavoriteShop> favorites = favorites(userId);
        List<ProfileAssetsResponse.SavedItinerary> itineraries = itineraries(userId);
        List<ProfileAssetsResponse.OwnedVoucher> vouchers = vouchers(userId);
        List<ProfileAssetsResponse.FlashSaleReminder> reminders = reminders(userId);
        List<ProfileAssetsResponse.AgentMemory> memories = memories(userId);
        return new ProfileAssetsResponse(
                favorites,
                itineraries,
                vouchers,
                reminders,
                memories,
                new ProfileAssetsResponse.AssetCounts(
                        favorites.size(),
                        itineraries.size(),
                        vouchers.size(),
                        reminders.size(),
                        memories.size()
                )
        );
    }

    public boolean updateMemory(Long memoryId, String value) {
        String normalized = validateMemoryValue(value);
        Long userId = UserHolder.getUser().getId();
        return jdbcTemplate.update(
                "UPDATE tb_agent_user_memory SET memory_value = ?, source = 'explicit', " +
                        "confidence = 1.000, update_time = NOW() WHERE id = ? AND user_id = ?",
                normalized,
                memoryId,
                userId
        ) == 1;
    }

    public boolean deleteMemory(Long memoryId) {
        Long userId = UserHolder.getUser().getId();
        return jdbcTemplate.update(
                "DELETE FROM tb_agent_user_memory WHERE id = ? AND user_id = ?",
                memoryId,
                userId
        ) == 1;
    }

    static String validateMemoryValue(String value) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("Memory value is required");
        }
        String normalized = value.trim();
        if (normalized.length() > 500) {
            throw new IllegalArgumentException("Memory value cannot exceed 500 characters");
        }
        return normalized;
    }

    private List<ProfileAssetsResponse.FavoriteShop> favorites(Long userId) {
        return jdbcTemplate.query(
                "SELECT f.id, f.shop_id, s.name, s.images, s.address, s.borough, " +
                        "s.area AS neighborhood, " +
                        "f.create_time FROM tb_shop_favorite f JOIN tb_shop s ON s.id = f.shop_id " +
                        "WHERE f.user_id = ? ORDER BY f.create_time DESC LIMIT 100",
                (rs, row) -> new ProfileAssetsResponse.FavoriteShop(
                        rs.getLong("id"),
                        rs.getLong("shop_id"),
                        rs.getString("name"),
                        rs.getString("images"),
                        rs.getString("address"),
                        rs.getString("borough"),
                        rs.getString("neighborhood"),
                        localDateTime(rs.getTimestamp("create_time"))
                ),
                userId
        );
    }

    private List<ProfileAssetsResponse.SavedItinerary> itineraries(Long userId) {
        Map<Long, String> shopNames = new LinkedHashMap<>();
        for (Map<String, Object> shop : jdbcTemplate.queryForList("SELECT id, name FROM tb_shop")) {
            shopNames.put(
                    ((Number) shop.get("id")).longValue(),
                    String.valueOf(shop.get("name"))
            );
        }
        return jdbcTemplate.query(
                "SELECT id, run_id, title, content_json, update_time FROM tb_saved_itinerary " +
                        "WHERE user_id = ? ORDER BY update_time DESC LIMIT 50",
                (rs, row) -> {
                    Map<String, Object> content = readJson(rs.getString("content_json"));
                    List<Long> shopIds = longList(content.get("shopIds"));
                    Map<String, Object> itinerary = objectMap(content.get("itinerary"));
                    return new ProfileAssetsResponse.SavedItinerary(
                            rs.getLong("id"),
                            rs.getString("run_id"),
                            rs.getString("title"),
                            shopIds,
                            shopIds.stream().map(id -> shopNames.getOrDefault(id, "Shop #" + id)).toList(),
                            itinerary,
                            localDateTime(rs.getTimestamp("update_time"))
                    );
                },
                userId
        );
    }

    private List<ProfileAssetsResponse.OwnedVoucher> vouchers(Long userId) {
        return jdbcTemplate.query(
                "SELECT o.id AS order_id, v.id AS voucher_id, v.shop_id, v.title, v.sub_title, " +
                        "s.name AS shop_name, v.type, v.pay_value, v.actual_value, o.status AS order_status, " +
                        "o.create_time FROM tb_voucher_order o JOIN tb_voucher v ON v.id = o.voucher_id " +
                        "LEFT JOIN tb_shop s ON s.id = v.shop_id WHERE o.user_id = ? " +
                        "ORDER BY o.create_time DESC LIMIT 100",
                (rs, row) -> new ProfileAssetsResponse.OwnedVoucher(
                        rs.getLong("order_id"),
                        rs.getLong("voucher_id"),
                        rs.getObject("shop_id", Long.class),
                        rs.getString("title"),
                        rs.getString("sub_title"),
                        rs.getString("shop_name"),
                        rs.getInt("type"),
                        rs.getLong("pay_value"),
                        rs.getLong("actual_value"),
                        rs.getInt("order_status"),
                        localDateTime(rs.getTimestamp("create_time"))
                ),
                userId
        );
    }

    private List<ProfileAssetsResponse.FlashSaleReminder> reminders(Long userId) {
        return jdbcTemplate.query(
                "SELECT r.id, r.voucher_id, v.shop_id, v.title AS voucher_title, s.name AS shop_name, " +
                        "r.remind_at, sv.begin_time, r.status FROM tb_seckill_reminder r " +
                        "JOIN tb_voucher v ON v.id = r.voucher_id LEFT JOIN tb_shop s ON s.id = v.shop_id " +
                        "LEFT JOIN tb_seckill_voucher sv ON sv.voucher_id = r.voucher_id " +
                        "WHERE r.user_id = ? ORDER BY r.remind_at ASC LIMIT 100",
                (rs, row) -> new ProfileAssetsResponse.FlashSaleReminder(
                        rs.getLong("id"),
                        rs.getLong("voucher_id"),
                        rs.getObject("shop_id", Long.class),
                        rs.getString("voucher_title"),
                        rs.getString("shop_name"),
                        localDateTime(rs.getTimestamp("remind_at")),
                        localDateTime(rs.getTimestamp("begin_time")),
                        rs.getString("status")
                ),
                userId
        );
    }

    private List<ProfileAssetsResponse.AgentMemory> memories(Long userId) {
        return jdbcTemplate.query(
                "SELECT id, memory_key, memory_value, source, confidence, update_time " +
                        "FROM tb_agent_user_memory WHERE user_id = ? ORDER BY update_time DESC",
                (rs, row) -> new ProfileAssetsResponse.AgentMemory(
                        rs.getLong("id"),
                        rs.getString("memory_key"),
                        rs.getString("memory_value"),
                        rs.getString("source"),
                        rs.getBigDecimal("confidence"),
                        localDateTime(rs.getTimestamp("update_time"))
                ),
                userId
        );
    }

    private Map<String, Object> readJson(String value) {
        if (value == null || value.isBlank()) return Map.of();
        try {
            return objectMapper.readValue(value, new TypeReference<>() {});
        } catch (JsonProcessingException exception) {
            return Map.of();
        }
    }

    private static List<Long> longList(Object value) {
        if (!(value instanceof List<?> list)) return List.of();
        List<Long> result = new ArrayList<>();
        for (Object item : list) {
            if (item instanceof Number number) result.add(number.longValue());
            else if (item instanceof String string) {
                try {
                    result.add(Long.valueOf(string));
                } catch (NumberFormatException ignored) {
                    // Ignore a malformed legacy shop ID while preserving the rest of the itinerary.
                }
            }
        }
        return List.copyOf(result);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> objectMap(Object value) {
        return value instanceof Map<?, ?> map ? (Map<String, Object>) map : Map.of();
    }

    private static LocalDateTime localDateTime(Timestamp timestamp) {
        return timestamp == null ? null : timestamp.toLocalDateTime();
    }
}
