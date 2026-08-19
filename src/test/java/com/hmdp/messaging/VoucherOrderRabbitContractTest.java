package com.hmdp.messaging;

import com.hmdp.config.RabbitMqConfig;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.rabbit.annotation.RabbitListener;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

import static com.hmdp.utils.RedisConstants.SECKILL_PENDING_ORDER_INDEX_KEY;
import static com.hmdp.utils.RedisConstants.SECKILL_PENDING_ORDER_KEY;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class VoucherOrderRabbitContractTest {

    @Test
    void luaAtomicallyCreatesRabbitPublisherRecoveryRecordWithoutUsingRedisStream() throws IOException {
        try (InputStream stream = getClass().getClassLoader().getResourceAsStream("seckill.lua")) {
            assertNotNull(stream, "seckill.lua must exist");
            String lua = new String(stream.readAllBytes(), StandardCharsets.UTF_8);

            assertTrue(lua.contains("ARGV[4]"));
            assertTrue(lua.contains("hset"));
            assertTrue(lua.contains("zadd"));
            assertTrue(lua.contains("seckill:pending:orders"));
            assertFalse(lua.contains("xadd"));
            assertFalse(lua.contains("stream:orders"));
        }
    }

    @Test
    void pendingRedisRecordConvertsToTypedRabbitMessage() {
        Map<Object, Object> values = new HashMap<>();
        values.put("id", "10001");
        values.put("userId", "42");
        values.put("voucherId", "7");

        VoucherOrderMessage message = VoucherOrderPublisher.fromPending(values);

        assertEquals(10001L, message.id());
        assertEquals(42L, message.userId());
        assertEquals(7L, message.voucherId());
    }

    @Test
    void malformedPendingRecordIsRejectedBeforePublishing() {
        Map<Object, Object> values = Map.of("id", "10001", "userId", "42");

        assertThrows(IllegalArgumentException.class, () -> VoucherOrderPublisher.fromPending(values));
    }

    @Test
    void durableRabbitTopologyAndConsumerContractAreSeparatedFromRedisRecoveryKeys()
            throws NoSuchMethodException {
        assertEquals("hmdp.voucher.order.queue", RabbitMqConfig.ORDER_QUEUE);
        assertEquals("hmdp.voucher.order.error.queue", RabbitMqConfig.ERROR_QUEUE);
        assertEquals("seckill:pending:order:", SECKILL_PENDING_ORDER_KEY);
        assertEquals("seckill:pending:orders", SECKILL_PENDING_ORDER_INDEX_KEY);

        RabbitListener listener = VoucherOrderConsumer.class
                .getDeclaredMethod("consume", VoucherOrderMessage.class)
                .getAnnotation(RabbitListener.class);
        assertNotNull(listener);
        assertEquals(RabbitMqConfig.ORDER_QUEUE, listener.queues()[0]);
    }

    @Test
    void uniqueIndexMigrationStillProvidesTheFinalIdempotencyBoundary() throws IOException {
        try (InputStream stream = getClass().getClassLoader()
                .getResourceAsStream("db/p2_redis_stream_order.sql")) {
            assertNotNull(stream, "P2 unique-index migration must exist");
            String migration = new String(stream.readAllBytes(), StandardCharsets.UTF_8);

            assertTrue(migration.contains("tb_voucher_order_conflict_archive"));
            assertTrue(migration.contains("uk_voucher_order_user_voucher"));
        }
    }
}
