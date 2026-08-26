package com.hmdp.messaging;

import com.hmdp.config.RabbitMqConfig;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.AmqpException;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;

import static com.hmdp.utils.RedisConstants.SECKILL_PENDING_ORDER_INDEX_KEY;
import static com.hmdp.utils.RedisConstants.SECKILL_PENDING_ORDER_KEY;

@Slf4j
@Component
public class VoucherOrderPublisher {

    private final OrderMessageSender messageSender;
    private final PendingOrderStore pendingOrderStore;
    private final Duration confirmTimeout;
    private final int replayBatchSize;

    public VoucherOrderPublisher(
            RabbitTemplate rabbitTemplate,
            StringRedisTemplate stringRedisTemplate,
            @Value("${hmdp.rabbitmq.confirm-timeout:5s}") Duration confirmTimeout,
            @Value("${hmdp.rabbitmq.replay-batch-size:50}") int replayBatchSize
    ) {
        this(
                order -> {
                    CorrelationData correlation = new CorrelationData(order.id().toString());
                    rabbitTemplate.convertAndSend(
                            RabbitMqConfig.ORDER_EXCHANGE,
                            RabbitMqConfig.ORDER_ROUTING_KEY,
                            order,
                            message -> {
                                message.getMessageProperties().setMessageId(order.id().toString());
                                message.getMessageProperties().setDeliveryMode(MessageDeliveryMode.PERSISTENT);
                                return message;
                            },
                            correlation
                    );
                    return correlation;
                },
                new RedisPendingOrderStore(stringRedisTemplate),
                confirmTimeout,
                replayBatchSize
        );
    }

    VoucherOrderPublisher(
            OrderMessageSender messageSender,
            PendingOrderStore pendingOrderStore,
            Duration confirmTimeout,
            int replayBatchSize
    ) {
        this.messageSender = messageSender;
        this.pendingOrderStore = pendingOrderStore;
        this.confirmTimeout = confirmTimeout;
        this.replayBatchSize = Math.max(1, Math.min(replayBatchSize, 500));
    }

    public void publish(VoucherOrderMessage order) {
        CorrelationData correlation = messageSender.send(order);
        try {
            CorrelationData.Confirm confirm = correlation.getFuture()
                    .get(confirmTimeout.toMillis(), TimeUnit.MILLISECONDS);
            if (!confirm.isAck()) {
                throw new AmqpException("RabbitMQ negatively acknowledged order " + order.id());
            }
            if (correlation.getReturned() != null) {
                throw new AmqpException("RabbitMQ returned unroutable order " + order.id());
            }
            removePending(order.id());
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new AmqpException("Interrupted while waiting for RabbitMQ confirm", interrupted);
        } catch (Exception publishFailure) {
            if (publishFailure instanceof AmqpException amqpException) {
                throw amqpException;
            }
            throw new AmqpException("RabbitMQ did not confirm order " + order.id(), publishFailure);
        }
    }

    @Scheduled(fixedDelayString = "${hmdp.rabbitmq.replay-interval-ms:5000}")
    public void replayPendingOrders() {
        Set<String> orderIds = pendingOrderStore.dueOrderIds(
                System.currentTimeMillis(), replayBatchSize
        );
        if (orderIds == null || orderIds.isEmpty()) {
            return;
        }
        for (String orderId : orderIds) {
            Map<Object, Object> values = pendingOrderStore.values(orderId);
            if (values.isEmpty()) {
                pendingOrderStore.remove(orderId);
                continue;
            }
            try {
                publish(fromPending(values));
            } catch (RuntimeException publishFailure) {
                log.warn("RabbitMQ待发布订单重放失败 orderId={}", orderId, publishFailure);
                return;
            }
        }
    }

    static VoucherOrderMessage fromPending(Map<Object, Object> values) {
        return new VoucherOrderMessage(
                requiredLong(values, "id"),
                requiredLong(values, "userId"),
                requiredLong(values, "voucherId")
        );
    }

    private static Long requiredLong(Map<Object, Object> values, String field) {
        Object value = values.get(field);
        if (value == null) {
            throw new IllegalArgumentException("Pending voucher order is missing field: " + field);
        }
        return Long.valueOf(value.toString());
    }

    private void removePending(Long orderId) {
        pendingOrderStore.remove(orderId.toString());
    }

    interface OrderMessageSender {
        CorrelationData send(VoucherOrderMessage order);
    }

    interface PendingOrderStore {
        Set<String> dueOrderIds(long now, int limit);

        Map<Object, Object> values(String orderId);

        void remove(String orderId);
    }

    private static final class RedisPendingOrderStore implements PendingOrderStore {
        private final StringRedisTemplate redisTemplate;

        private RedisPendingOrderStore(StringRedisTemplate redisTemplate) {
            this.redisTemplate = redisTemplate;
        }

        @Override
        public Set<String> dueOrderIds(long now, int limit) {
            return redisTemplate.opsForZSet().rangeByScore(
                    SECKILL_PENDING_ORDER_INDEX_KEY,
                    0,
                    now,
                    0,
                    limit
            );
        }

        @Override
        public Map<Object, Object> values(String orderId) {
            return redisTemplate.opsForHash().entries(SECKILL_PENDING_ORDER_KEY + orderId);
        }

        @Override
        public void remove(String orderId) {
            redisTemplate.delete(SECKILL_PENDING_ORDER_KEY + orderId);
            redisTemplate.opsForZSet().remove(SECKILL_PENDING_ORDER_INDEX_KEY, orderId);
        }
    }
}
