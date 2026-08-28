package com.nycreview.messaging;

import com.nycreview.service.IVoucherOrderService;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.AmqpException;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DuplicateKeyException;

import java.lang.reflect.Constructor;
import java.lang.reflect.Proxy;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class VoucherOrderRabbitReliabilityTest {

    @Test
    void productionConstructorIsExplicitlySelectedForSpringInjection() {
        Constructor<?> productionConstructor = java.util.Arrays.stream(
                        VoucherOrderPublisher.class.getConstructors()
                )
                .filter(constructor -> constructor.getParameterCount() == 4)
                .findFirst()
                .orElseThrow();

        assertTrue(productionConstructor.isAnnotationPresent(Autowired.class));
    }

    @Test
    void publisherAckRemovesRecoveryRecordOnlyAfterBrokerConfirmation() {
        FakePendingOrderStore pending = new FakePendingOrderStore();
        pending.put(1001L, 42L, 7L);
        VoucherOrderPublisher publisher = publisher(new ConfirmingSender(true), pending);

        publisher.publish(new VoucherOrderMessage(1001L, 42L, 7L));

        assertFalse(pending.contains("1001"));
        assertEquals(Set.of("1001"), pending.removed);
    }

    @Test
    void publisherNackKeepsRecoveryRecordForScheduledReplay() {
        FakePendingOrderStore pending = new FakePendingOrderStore();
        pending.put(1002L, 43L, 7L);
        VoucherOrderPublisher publisher = publisher(new ConfirmingSender(false), pending);

        assertThrows(
                AmqpException.class,
                () -> publisher.publish(new VoucherOrderMessage(1002L, 43L, 7L))
        );

        assertTrue(pending.contains("1002"));
        assertTrue(pending.removed.isEmpty());
    }

    @Test
    void replayPublishesTypedPendingMessageAndThenRemovesRecoveryRecord() {
        FakePendingOrderStore pending = new FakePendingOrderStore();
        pending.put(1003L, 44L, 8L);
        ConfirmingSender sender = new ConfirmingSender(true);
        VoucherOrderPublisher publisher = publisher(sender, pending);

        publisher.replayPendingOrders();

        assertEquals(
                new VoucherOrderMessage(1003L, 44L, 8L),
                sender.sent.iterator().next()
        );
        assertFalse(pending.contains("1003"));
    }

    @Test
    void missingPendingHashIsRemovedFromIndexWithoutPublishingGarbage() {
        FakePendingOrderStore pending = new FakePendingOrderStore();
        pending.due.add("1004");
        ConfirmingSender sender = new ConfirmingSender(true);
        VoucherOrderPublisher publisher = publisher(sender, pending);

        publisher.replayPendingOrders();

        assertEquals(Set.of("1004"), pending.removed);
        assertTrue(sender.sent.isEmpty());
    }

    @Test
    void duplicateDeliveryIsAnIdempotentConsumerOutcome() {
        int[] calls = {0};
        IVoucherOrderService service = (IVoucherOrderService) Proxy.newProxyInstance(
                IVoucherOrderService.class.getClassLoader(),
                new Class<?>[]{IVoucherOrderService.class},
                (proxy, method, arguments) -> {
                    if ("createVoucherOrder".equals(method.getName())) {
                        calls[0]++;
                        throw new DuplicateKeyException("duplicate");
                    }
                    if (method.getDeclaringClass() == Object.class) {
                        return switch (method.getName()) {
                            case "toString" -> "DuplicateOrderService";
                            case "hashCode" -> System.identityHashCode(proxy);
                            case "equals" -> proxy == arguments[0];
                            default -> null;
                        };
                    }
                    throw new UnsupportedOperationException(method.getName());
                }
        );
        VoucherOrderConsumer consumer = new VoucherOrderConsumer(service);

        assertDoesNotThrow(
                () -> consumer.consume(new VoucherOrderMessage(1005L, 45L, 9L))
        );

        assertEquals(1, calls[0]);
    }

    private VoucherOrderPublisher publisher(
            VoucherOrderPublisher.OrderMessageSender sender,
            VoucherOrderPublisher.PendingOrderStore pending
    ) {
        return new VoucherOrderPublisher(sender, pending, Duration.ofSeconds(1), 50);
    }

    private static final class ConfirmingSender implements VoucherOrderPublisher.OrderMessageSender {
        private final boolean acknowledged;
        private final Set<VoucherOrderMessage> sent = new LinkedHashSet<>();

        private ConfirmingSender(boolean acknowledged) {
            this.acknowledged = acknowledged;
        }

        @Override
        public CorrelationData send(VoucherOrderMessage order) {
            sent.add(order);
            CorrelationData correlation = new CorrelationData(order.id().toString());
            correlation.getFuture().complete(new CorrelationData.Confirm(
                    acknowledged,
                    acknowledged ? null : "p14 simulated nack"
            ));
            return correlation;
        }
    }

    private static final class FakePendingOrderStore
            implements VoucherOrderPublisher.PendingOrderStore {
        private final Set<String> due = new LinkedHashSet<>();
        private final Map<String, Map<Object, Object>> records = new LinkedHashMap<>();
        private final Set<String> removed = new LinkedHashSet<>();

        private void put(long id, long userId, long voucherId) {
            String orderId = Long.toString(id);
            due.add(orderId);
            records.put(orderId, Map.of(
                    "id", orderId,
                    "userId", Long.toString(userId),
                    "voucherId", Long.toString(voucherId)
            ));
        }

        private boolean contains(String orderId) {
            return due.contains(orderId) || records.containsKey(orderId);
        }

        @Override
        public Set<String> dueOrderIds(long now, int limit) {
            return due.stream().limit(limit).collect(java.util.stream.Collectors.toCollection(
                    LinkedHashSet::new
            ));
        }

        @Override
        public Map<Object, Object> values(String orderId) {
            return records.getOrDefault(orderId, Map.of());
        }

        @Override
        public void remove(String orderId) {
            due.remove(orderId);
            records.remove(orderId);
            removed.add(orderId);
        }
    }
}
