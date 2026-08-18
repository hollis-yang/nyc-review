package com.hmdp.service.impl;

import com.hmdp.entity.VoucherOrder;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static com.hmdp.utils.RedisConstants.SECKILL_ORDER_DEAD_LETTER_STREAM_KEY;
import static com.hmdp.utils.RedisConstants.SECKILL_ORDER_STREAM_KEY;

class VoucherOrderStreamContractTest {

    @Test
    void luaAtomicallyPublishesAcceptedOrderToRedisStream() throws IOException {
        try (InputStream stream = getClass().getClassLoader().getResourceAsStream("seckill.lua")) {
            assertTrue(stream != null, "seckill.lua must exist");
            String lua = new String(stream.readAllBytes(), StandardCharsets.UTF_8);

            assertTrue(lua.contains("ARGV[3]"));
            assertTrue(lua.contains("xadd"));
            assertTrue(lua.contains("stream:orders"));
            assertTrue(lua.contains("voucherId"));
            assertTrue(lua.contains("userId"));
        }
    }

    @Test
    void streamRecordConvertsToVoucherOrder() {
        Map<Object, Object> values = new HashMap<>();
        values.put("id", "10001");
        values.put("userId", "42");
        values.put("voucherId", "7");

        VoucherOrder order = VoucherOrderServiceImpl.toVoucherOrder(values);

        assertEquals(10001L, order.getId());
        assertEquals(42L, order.getUserId());
        assertEquals(7L, order.getVoucherId());
    }

    @Test
    void malformedStreamRecordIsRejectedInsteadOfAcknowledgedAsAnOrder() {
        Map<Object, Object> values = Map.of("id", "10001", "userId", "42");

        assertThrows(
                IllegalArgumentException.class,
                () -> VoucherOrderServiceImpl.toVoucherOrder(values)
        );
    }

    @Test
    void orderAndDeadLetterStreamsAreSeparated() {
        assertEquals("stream:orders", SECKILL_ORDER_STREAM_KEY);
        assertEquals("stream:orders:dead-letter", SECKILL_ORDER_DEAD_LETTER_STREAM_KEY);
    }
}
