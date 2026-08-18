package com.hmdp.agentapi.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.hmdp.agentapi.dto.AgentActionExecuteRequest;
import com.hmdp.dto.Result;
import com.hmdp.service.IVoucherOrderService;
import com.hmdp.utils.UserHolder;
import jakarta.annotation.Resource;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Service
public class AgentActionExecutionService {

    static final String FAVORITE_SHOP = "favorite_shop";
    static final String SAVE_ITINERARY = "save_itinerary";
    static final String CLAIM_STANDARD_VOUCHER = "claim_standard_voucher";
    static final String CREATE_SECKILL_REMINDER = "create_seckill_reminder";
    static final Set<String> ALLOWED_ACTIONS = Set.of(
            FAVORITE_SHOP,
            SAVE_ITINERARY,
            CLAIM_STANDARD_VOUCHER,
            CREATE_SECKILL_REMINDER
    );

    @Resource
    private JdbcTemplate jdbcTemplate;

    @Resource
    private ObjectMapper objectMapper;

    @Resource
    private IVoucherOrderService voucherOrderService;

    @Transactional
    public Result execute(AgentActionExecuteRequest request) {
        String validationError = validate(request);
        if (validationError != null) {
            return Result.fail(validationError);
        }

        Long userId = UserHolder.getUser().getId();
        Result previous = beginIdempotentExecution(request, userId);
        if (previous != null) {
            return previous;
        }

        try {
            Map<String, Object> executionResult = switch (request.actionType()) {
                case FAVORITE_SHOP -> favoriteShop(userId, request.payload());
                case SAVE_ITINERARY -> saveItinerary(userId, request.runId(), request.payload());
                case CLAIM_STANDARD_VOUCHER -> claimStandardVoucher(request.payload());
                case CREATE_SECKILL_REMINDER -> createSeckillReminder(userId, request.payload());
                default -> throw new IllegalArgumentException("Action type is not allowed");
            };
            executionResult.put("actionId", request.actionId());
            executionResult.put("actionType", request.actionType());
            executionResult.put("status", "completed");
            String resultJson = writeJson(executionResult);
            jdbcTemplate.update(
                    "UPDATE tb_agent_action_audit SET status = 'COMPLETED', result_json = ?, " +
                            "error_message = NULL, update_time = NOW() WHERE user_id = ? AND action_id = ?",
                    resultJson,
                    userId,
                    request.actionId()
            );
            return Result.ok(executionResult);
        } catch (IllegalArgumentException exception) {
            jdbcTemplate.update(
                    "UPDATE tb_agent_action_audit SET status = 'FAILED', error_message = ?, " +
                            "update_time = NOW() WHERE user_id = ? AND action_id = ?",
                    truncate(exception.getMessage(), 500),
                    userId,
                    request.actionId()
            );
            return Result.fail(exception.getMessage());
        }
    }

    public Result preferences() {
        Long userId = UserHolder.getUser().getId();
        Map<String, Object> preferences = new LinkedHashMap<>();
        preferences.put("category", firstValue(
                "SELECT st.name AS value FROM tb_shop_favorite f " +
                        "JOIN tb_shop s ON s.id = f.shop_id " +
                        "JOIN tb_shop_type st ON st.id = s.type_id " +
                        "WHERE f.user_id = ? GROUP BY st.name " +
                        "ORDER BY COUNT(*) DESC, MAX(f.create_time) DESC LIMIT 1",
                userId
        ));
        preferences.put("neighborhood", firstValue(
                "SELECT s.neighborhood AS value FROM tb_shop_favorite f " +
                        "JOIN tb_shop s ON s.id = f.shop_id " +
                        "WHERE f.user_id = ? AND s.neighborhood IS NOT NULL " +
                        "GROUP BY s.neighborhood ORDER BY COUNT(*) DESC, MAX(f.create_time) DESC LIMIT 1",
                userId
        ));
        List<String> tags = jdbcTemplate.queryForList(
                "SELECT t.tag FROM tb_shop_favorite f " +
                        "JOIN tb_shop_tag t ON t.shop_id = f.shop_id " +
                        "WHERE f.user_id = ? GROUP BY t.tag ORDER BY COUNT(*) DESC, t.tag LIMIT 3",
                String.class,
                userId
        );
        preferences.put("tags", tags);
        Long favoriteCount = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM tb_shop_favorite WHERE user_id = ?",
                Long.class,
                userId
        );
        preferences.put("favoriteCount", favoriteCount == null ? 0 : favoriteCount);
        return Result.ok(preferences);
    }

    private Result beginIdempotentExecution(AgentActionExecuteRequest request, Long userId) {
        try {
            jdbcTemplate.update(
                    "INSERT INTO tb_agent_action_audit " +
                            "(user_id, run_id, action_id, action_type, status, request_json, create_time, update_time) " +
                            "VALUES (?, ?, ?, ?, 'EXECUTING', ?, NOW(), NOW())",
                    userId,
                    request.runId(),
                    request.actionId(),
                    request.actionType(),
                    writeJson(request.payload())
            );
            return null;
        } catch (DuplicateKeyException duplicate) {
            List<Map<String, Object>> rows = jdbcTemplate.queryForList(
                    "SELECT run_id, action_type, status, result_json, error_message " +
                            "FROM tb_agent_action_audit " +
                            "WHERE user_id = ? AND action_id = ?",
                    userId,
                    request.actionId()
            );
            if (rows.isEmpty()) {
                return Result.fail("The action audit record could not be loaded");
            }
            Map<String, Object> row = rows.get(0);
            if (!request.runId().equals(String.valueOf(row.get("run_id"))) ||
                    !request.actionType().equals(String.valueOf(row.get("action_type")))) {
                return Result.fail("actionId is already bound to a different action");
            }
            String status = String.valueOf(row.get("status"));
            if ("COMPLETED".equals(status)) {
                return Result.ok(readJson((String) row.get("result_json")));
            }
            if ("FAILED".equals(status)) {
                jdbcTemplate.update(
                        "UPDATE tb_agent_action_audit SET status = 'EXECUTING', error_message = NULL, " +
                                "update_time = NOW() WHERE user_id = ? AND action_id = ?",
                        userId,
                        request.actionId()
                );
                return null;
            }
            return Result.fail("This approved action is already being executed");
        }
    }

    private String firstValue(String sql, Long userId) {
        List<String> values = jdbcTemplate.queryForList(sql, String.class, userId);
        return values.isEmpty() ? null : values.get(0);
    }

    private Map<String, Object> favoriteShop(Long userId, Map<String, Object> payload) {
        Long shopId = requiredLong(payload, "shopId");
        Long shopCount = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM tb_shop WHERE id = ?",
                Long.class,
                shopId
        );
        if (shopCount == null || shopCount == 0) {
            throw new IllegalArgumentException("Shop not found");
        }
        jdbcTemplate.update(
                "INSERT INTO tb_shop_favorite(user_id, shop_id, create_time) VALUES (?, ?, NOW()) " +
                        "ON DUPLICATE KEY UPDATE create_time = create_time",
                userId,
                shopId
        );
        return mutableResult("shopId", shopId);
    }

    private Map<String, Object> saveItinerary(Long userId, String runId, Map<String, Object> payload) {
        String title = optionalString(payload.get("title"), "NYC AI Guide itinerary", 120);
        Object itinerary = payload.get("itinerary");
        Object shopIds = payload.get("shopIds");
        if (!(shopIds instanceof List<?> list) || list.isEmpty() || list.size() > 20) {
            throw new IllegalArgumentException("An itinerary must contain between 1 and 20 shops");
        }
        String contentJson = writeJson(Map.of(
                "shopIds", shopIds,
                "itinerary", itinerary == null ? Map.of() : itinerary
        ));
        if (contentJson.length() > 50_000) {
            throw new IllegalArgumentException("The itinerary payload is too large");
        }
        jdbcTemplate.update(
                "INSERT INTO tb_saved_itinerary(user_id, run_id, title, content_json, create_time, update_time) " +
                        "VALUES (?, ?, ?, ?, NOW(), NOW()) " +
                        "ON DUPLICATE KEY UPDATE title = VALUES(title), content_json = VALUES(content_json), " +
                        "update_time = NOW()",
                userId,
                runId,
                title,
                contentJson
        );
        Map<String, Object> result = mutableResult("runId", runId);
        result.put("title", title);
        result.put("shopCount", list.size());
        return result;
    }

    private Map<String, Object> claimStandardVoucher(Map<String, Object> payload) {
        Long voucherId = requiredLong(payload, "voucherId");
        Result purchase = voucherOrderService.purchaseVoucher(voucherId);
        if (!Boolean.TRUE.equals(purchase.getSuccess())) {
            throw new IllegalArgumentException(purchase.getErrorMsg());
        }
        Map<String, Object> result = mutableResult("voucherId", voucherId);
        result.put("orderId", purchase.getData());
        return result;
    }

    private Map<String, Object> createSeckillReminder(Long userId, Map<String, Object> payload) {
        Long voucherId = requiredLong(payload, "voucherId");
        Integer voucherType = jdbcTemplate.queryForObject(
                "SELECT type FROM tb_voucher WHERE id = ?",
                Integer.class,
                voucherId
        );
        if (voucherType == null || voucherType != 1) {
            throw new IllegalArgumentException("Only flash-sale vouchers can have a flash-sale reminder");
        }
        LocalDateTime remindAt = parseRemindAt(payload.get("remindAt"));
        if (remindAt == null) {
            LocalDateTime beginTime = jdbcTemplate.queryForObject(
                    "SELECT begin_time FROM tb_seckill_voucher WHERE voucher_id = ?",
                    LocalDateTime.class,
                    voucherId
            );
            if (beginTime == null) {
                throw new IllegalArgumentException("Flash-sale schedule not found");
            }
            remindAt = beginTime.minusMinutes(10);
        }
        jdbcTemplate.update(
                "INSERT INTO tb_seckill_reminder(user_id, voucher_id, remind_at, status, create_time, update_time) " +
                        "VALUES (?, ?, ?, 'PENDING', NOW(), NOW()) " +
                        "ON DUPLICATE KEY UPDATE remind_at = VALUES(remind_at), status = 'PENDING', update_time = NOW()",
                userId,
                voucherId,
                remindAt
        );
        Map<String, Object> result = mutableResult("voucherId", voucherId);
        result.put("remindAt", remindAt.toString());
        result.put("manualPurchaseRequired", true);
        return result;
    }

    static String validate(AgentActionExecuteRequest request) {
        if (request == null) return "Action request is required";
        if (request.runId() == null || request.runId().isBlank() || request.runId().length() > 64) {
            return "A valid runId is required";
        }
        if (request.actionId() == null || request.actionId().isBlank() || request.actionId().length() > 64) {
            return "A valid actionId is required";
        }
        if (!ALLOWED_ACTIONS.contains(request.actionType())) {
            return "Action type is not allowed";
        }
        if (request.payload() == null) {
            return "Action payload is required";
        }
        return null;
    }

    private static Long requiredLong(Map<String, Object> payload, String field) {
        Object value = payload.get(field);
        if (value instanceof Number number) return number.longValue();
        if (value instanceof String string) {
            try {
                return Long.valueOf(string);
            } catch (NumberFormatException ignored) {
                // Converted to a controlled validation error below.
            }
        }
        throw new IllegalArgumentException("Action payload is missing a valid " + field);
    }

    private static LocalDateTime parseRemindAt(Object value) {
        if (!(value instanceof String string) || string.isBlank()) return null;
        try {
            return LocalDateTime.parse(string);
        } catch (RuntimeException exception) {
            throw new IllegalArgumentException("remindAt must be an ISO local date-time");
        }
    }

    private static String optionalString(Object value, String fallback, int maxLength) {
        String result = value == null ? fallback : value.toString().trim();
        if (result.isEmpty()) result = fallback;
        return result.length() <= maxLength ? result : result.substring(0, maxLength);
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("Action payload cannot be serialized");
        }
    }

    private Map<String, Object> readJson(String value) {
        if (value == null || value.isBlank()) return Map.of();
        try {
            return objectMapper.readValue(value, new TypeReference<>() {});
        } catch (JsonProcessingException exception) {
            return Map.of("status", "completed");
        }
    }

    private static Map<String, Object> mutableResult(String key, Object value) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put(key, value);
        return result;
    }

    private static String truncate(String value, int maxLength) {
        if (value == null) return "Action execution failed";
        return value.length() <= maxLength ? value : value.substring(0, maxLength);
    }
}
