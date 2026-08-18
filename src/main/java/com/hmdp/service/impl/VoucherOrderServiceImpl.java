package com.hmdp.service.impl;

import com.hmdp.dto.Result;
import com.hmdp.entity.Voucher;
import com.hmdp.entity.VoucherOrder;
import com.hmdp.mapper.VoucherOrderMapper;
import com.hmdp.service.ISeckillVoucherService;
import com.hmdp.service.IVoucherOrderService;
import com.hmdp.service.IVoucherService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmdp.utils.RedisIdWorker;
import com.hmdp.utils.UserHolder;
import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.ApplicationContext;
import org.springframework.context.event.EventListener;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.domain.Range;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.connection.stream.Consumer;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.PendingMessage;
import org.springframework.data.redis.connection.stream.PendingMessages;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.connection.stream.StreamReadOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import jakarta.annotation.Resource;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static com.hmdp.utils.RedisConstants.SECKILL_ORDER_DEAD_LETTER_STREAM_KEY;
import static com.hmdp.utils.RedisConstants.SECKILL_ORDER_GROUP;
import static com.hmdp.utils.RedisConstants.SECKILL_ORDER_STREAM_KEY;

@Slf4j
@Service
public class VoucherOrderServiceImpl extends ServiceImpl<VoucherOrderMapper, VoucherOrder> implements IVoucherOrderService {

    @Resource
    private RedisIdWorker redisIdWorker;

    @Resource
    private StringRedisTemplate stringRedisTemplate;

    @Resource
    private ISeckillVoucherService seckillVoucherService;

    @Resource
    private IVoucherService voucherService;

    @Resource
    private ApplicationContext applicationContext;

    private static final DefaultRedisScript<Long> SECKILL_SCRIPT;
    static {
        SECKILL_SCRIPT = new DefaultRedisScript<>();
        SECKILL_SCRIPT.setLocation(new ClassPathResource("seckill.lua"));
        SECKILL_SCRIPT.setResultType(Long.class);
    }

    private final ExecutorService seckillOrderExecutor = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "voucher-order-stream-consumer");
        thread.setDaemon(true);
        return thread;
    });
    private final String consumerName = "consumer-" + UUID.randomUUID();
    private volatile boolean running = true;
    private static final Duration PENDING_MIN_IDLE = Duration.ofSeconds(30);
    private static final Duration PENDING_SCAN_INTERVAL = Duration.ofSeconds(5);
    private static final int MAX_DELIVERY_ATTEMPTS = 5;

    private IVoucherOrderService proxy;

    @EventListener(ApplicationReadyEvent.class)
    void init() {
        proxy = applicationContext.getBean(IVoucherOrderService.class);
        ensureConsumerGroup();
        seckillOrderExecutor.submit(new VoucherOrderHandler());
    }

    @PreDestroy
    void shutdown() {
        running = false;
        seckillOrderExecutor.shutdownNow();
        try {
            if (!seckillOrderExecutor.awaitTermination(3, TimeUnit.SECONDS)) {
                log.warn("秒杀订单消费者未在超时时间内停止");
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private void ensureConsumerGroup() {
        try {
            if (Boolean.FALSE.equals(stringRedisTemplate.hasKey(SECKILL_ORDER_STREAM_KEY))) {
                stringRedisTemplate.opsForStream().add(
                        SECKILL_ORDER_STREAM_KEY,
                        Map.of("type", "bootstrap")
                );
            }
            stringRedisTemplate.opsForStream().createGroup(
                    SECKILL_ORDER_STREAM_KEY,
                    ReadOffset.from("0"),
                    SECKILL_ORDER_GROUP
            );
        } catch (DataAccessException e) {
            if (!containsBusyGroup(e)) {
                throw e;
            }
        }
    }

    private boolean containsBusyGroup(Throwable error) {
        Throwable current = error;
        while (current != null) {
            if (current.getMessage() != null && current.getMessage().contains("BUSYGROUP")) {
                return true;
            }
            current = current.getCause();
        }
        return false;
    }

    private class VoucherOrderHandler implements Runnable {
        @Override
        public void run() {
            long nextPendingScan = 0L;
            while (running && !Thread.currentThread().isInterrupted()) {
                try {
                    long now = System.nanoTime();
                    if (now >= nextPendingScan) {
                        recoverStalePendingMessages();
                        nextPendingScan = now + PENDING_SCAN_INTERVAL.toNanos();
                    }
                    List<MapRecord<String, Object, Object>> records = stringRedisTemplate.opsForStream().read(
                            Consumer.from(SECKILL_ORDER_GROUP, consumerName),
                            StreamReadOptions.empty().count(1).block(Duration.ofSeconds(2)),
                            StreamOffset.create(SECKILL_ORDER_STREAM_KEY, ReadOffset.lastConsumed())
                    );
                    if (records == null || records.isEmpty()) {
                        continue;
                    }
                    processSafely(records.get(0));
                } catch (Exception e) {
                    log.error("处理订单异常", e);
                    handlePendingList();
                }
            }
        }
    }

    private void handlePendingList() {
        while (running && !Thread.currentThread().isInterrupted()) {
            try {
                List<MapRecord<String, Object, Object>> records = stringRedisTemplate.opsForStream().read(
                        Consumer.from(SECKILL_ORDER_GROUP, consumerName),
                        StreamReadOptions.empty().count(1),
                        StreamOffset.create(SECKILL_ORDER_STREAM_KEY, ReadOffset.from("0"))
                );
                if (records == null || records.isEmpty()) {
                    return;
                }
                if (!processSafely(records.get(0))) {
                    sleepBeforeRetry();
                    return;
                }
            } catch (Exception pendingError) {
                log.error("处理Pending订单异常", pendingError);
                sleepBeforeRetry();
                return;
            }
        }
    }

    private void recoverStalePendingMessages() {
        PendingMessages pending = stringRedisTemplate.opsForStream().pending(
                SECKILL_ORDER_STREAM_KEY,
                SECKILL_ORDER_GROUP,
                Range.unbounded(),
                10
        );
        List<RecordId> staleRecordIds = new ArrayList<>();
        for (PendingMessage pendingMessage : pending) {
            if (pendingMessage.getElapsedTimeSinceLastDelivery().compareTo(PENDING_MIN_IDLE) >= 0) {
                staleRecordIds.add(pendingMessage.getId());
            }
        }
        if (staleRecordIds.isEmpty()) {
            return;
        }
        List<MapRecord<String, Object, Object>> claimed = stringRedisTemplate.opsForStream().claim(
                SECKILL_ORDER_STREAM_KEY,
                SECKILL_ORDER_GROUP,
                consumerName,
                PENDING_MIN_IDLE,
                staleRecordIds.toArray(RecordId[]::new)
        );
        for (MapRecord<String, Object, Object> record : claimed) {
            if (!processSafely(record)) {
                return;
            }
        }
    }

    private boolean processSafely(MapRecord<String, Object, Object> record) {
        try {
            processAndAcknowledge(record);
            return true;
        } catch (Exception processingError) {
            long deliveryCount = deliveryCount(record.getId());
            if (deliveryCount >= MAX_DELIVERY_ATTEMPTS) {
                moveToDeadLetter(record, processingError, deliveryCount);
                acknowledge(record);
                return true;
            }
            log.warn(
                    "秒杀订单处理失败，将由Pending重试 recordId={}, deliveryCount={}",
                    record.getId(),
                    deliveryCount,
                    processingError
            );
            return false;
        }
    }

    private long deliveryCount(RecordId recordId) {
        String id = recordId.getValue();
        PendingMessages pending = stringRedisTemplate.opsForStream().pending(
                SECKILL_ORDER_STREAM_KEY,
                SECKILL_ORDER_GROUP,
                Range.closed(id, id),
                1
        );
        return pending.isEmpty() ? 1L : pending.get(0).getTotalDeliveryCount();
    }

    private void moveToDeadLetter(
            MapRecord<String, Object, Object> record,
            Exception processingError,
            long deliveryCount
    ) {
        Map<String, String> deadLetter = new HashMap<>();
        record.getValue().forEach((key, value) -> deadLetter.put(String.valueOf(key), String.valueOf(value)));
        deadLetter.put("originalRecordId", record.getId().getValue());
        deadLetter.put("deliveryCount", Long.toString(deliveryCount));
        deadLetter.put("failedAt", Instant.now().toString());
        deadLetter.put("failureType", processingError.getClass().getSimpleName());
        deadLetter.put("failureMessage", truncate(processingError.getMessage(), 300));
        stringRedisTemplate.opsForStream().add(SECKILL_ORDER_DEAD_LETTER_STREAM_KEY, deadLetter);
        log.error("秒杀订单进入死信流 recordId={}, deliveryCount={}", record.getId(), deliveryCount);
    }

    private String truncate(String value, int maxLength) {
        if (value == null) {
            return "";
        }
        return value.length() <= maxLength ? value : value.substring(0, maxLength);
    }

    private void processAndAcknowledge(MapRecord<String, Object, Object> record) {
        Map<Object, Object> values = record.getValue();
        if ("bootstrap".equals(String.valueOf(values.get("type")))) {
            acknowledge(record);
            return;
        }
        VoucherOrder voucherOrder = toVoucherOrder(values);
        try {
            proxy.createVoucherOrder(voucherOrder);
        } catch (DuplicateKeyException duplicate) {
            // 数据库唯一约束是最终幂等防线；重复投递可以安全确认。
            log.info("秒杀订单已存在，确认重复消息 orderId={}", voucherOrder.getId());
        }
        acknowledge(record);
    }

    private void acknowledge(MapRecord<String, Object, Object> record) {
        stringRedisTemplate.opsForStream().acknowledge(
                SECKILL_ORDER_STREAM_KEY,
                SECKILL_ORDER_GROUP,
                record.getId()
        );
    }

    private void sleepBeforeRetry() {
        try {
            Thread.sleep(500);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    static VoucherOrder toVoucherOrder(Map<Object, Object> values) {
        VoucherOrder voucherOrder = new VoucherOrder();
        voucherOrder.setId(Long.valueOf(requiredStreamValue(values, "id")));
        voucherOrder.setUserId(Long.valueOf(requiredStreamValue(values, "userId")));
        voucherOrder.setVoucherId(Long.valueOf(requiredStreamValue(values, "voucherId")));
        return voucherOrder;
    }

    private static String requiredStreamValue(Map<Object, Object> values, String field) {
        Object value = values.get(field);
        if (value == null) {
            throw new IllegalArgumentException("秒杀订单消息缺少字段: " + field);
        }
        return value.toString();
    }

    @Override
    public Result seckillVoucher(Long voucherId) {
        // 获取用户
        Long userId = UserHolder.getUser().getId();
        long orderId = redisIdWorker.nextId("order");
        // 1.执行lua脚本
        Long result = stringRedisTemplate.execute(SECKILL_SCRIPT,
                Collections.emptyList(),
                voucherId.toString(),
                userId.toString(),
                Long.toString(orderId));
        if (result == null) {
            return Result.fail("秒杀服务暂时不可用");
        }
        // 2.判断结果是否为0
        int r = result.intValue();
        if (r != 0) {
            // 2-1.不为0，没有购买资格
            return Result.fail(r == 1 ? "库存不足" : "不能重复购买");
        }
        // Lua已将订单写入Redis Stream，直接返回订单id供前端查询。
        return Result.ok(orderId);
    }

    @Override
    @Transactional
    public Result purchaseVoucher(Long voucherId) {
        Long userId = UserHolder.getUser().getId();
        long count = query().eq("user_id", userId).eq("voucher_id", voucherId).count();
        if (count > 0) {
            return Result.fail("您已购买过该优惠券");
        }
        Voucher voucher = voucherService.getById(voucherId);
        if (voucher == null) {
            return Result.fail("优惠券不存在");
        }
        if (voucher.getType() != 0) {
            return Result.fail("该优惠券不支持普通购买，请参与秒杀");
        }
        VoucherOrder voucherOrder = new VoucherOrder();
        long orderId = redisIdWorker.nextId("order");
        voucherOrder.setId(orderId);
        voucherOrder.setUserId(userId);
        voucherOrder.setVoucherId(voucherId);
        save(voucherOrder);
        return Result.ok(orderId);
    }

    @Transactional
    public void createVoucherOrder(VoucherOrder voucherOrder) {
        // 优化：一人一单
        Long userId = voucherOrder.getUserId();

        // (1) 查询订单
        long count = query().eq("user_id", userId).eq("voucher_id", voucherOrder.getVoucherId()).count();
        // (2) 判断是否存在
        if (count > 0) {
            log.error("用户已经购买过一次了");
            return;
        }

        // 5.扣减库存
        boolean stockUpdated = seckillVoucherService.update()
                .setSql("stock = stock - 1")
                .eq("voucher_id", voucherOrder.getVoucherId())
                .gt("stock", 0)
                .update();
        if (!stockUpdated) {
            throw new IllegalStateException("数据库库存不足或秒杀券不存在");
        }

        if (!save(voucherOrder)) {
            throw new IllegalStateException("秒杀订单保存失败");
        }
    }
}
