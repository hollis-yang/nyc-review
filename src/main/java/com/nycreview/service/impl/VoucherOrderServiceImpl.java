package com.nycreview.service.impl;

import com.nycreview.dto.Result;
import com.nycreview.entity.Voucher;
import com.nycreview.entity.VoucherOrder;
import com.nycreview.entity.SeckillVoucher;
import com.nycreview.mapper.VoucherOrderMapper;
import com.nycreview.messaging.VoucherOrderMessage;
import com.nycreview.messaging.VoucherOrderPublisher;
import com.nycreview.service.ISeckillVoucherService;
import com.nycreview.service.IVoucherOrderService;
import com.nycreview.service.IVoucherService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.nycreview.utils.RedisIdWorker;
import com.nycreview.utils.UserHolder;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import jakarta.annotation.Resource;
import java.time.LocalDateTime;
import java.util.Collections;

import static com.nycreview.utils.RedisConstants.SECKILL_STOCK_KEY;

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
    private VoucherOrderPublisher voucherOrderPublisher;

    private static final DefaultRedisScript<Long> SECKILL_SCRIPT;
    static {
        SECKILL_SCRIPT = new DefaultRedisScript<>();
        SECKILL_SCRIPT.setLocation(new ClassPathResource("seckill.lua"));
        SECKILL_SCRIPT.setResultType(Long.class);
    }

    @Override
    public Result seckillVoucher(Long voucherId) {
        // 获取用户
        Long userId = UserHolder.getUser().getId();
        if (!initializeStockIfMissing(voucherId)) {
            return Result.fail("Flash-sale voucher not found");
        }
        long orderId = redisIdWorker.nextId("order");
        // 1.执行lua脚本
        Long result = stringRedisTemplate.execute(SECKILL_SCRIPT,
                Collections.emptyList(),
                voucherId.toString(),
                userId.toString(),
                Long.toString(orderId),
                Long.toString(System.currentTimeMillis()));
        if (result == null) {
            return Result.fail("The flash-sale service is temporarily unavailable");
        }
        // 2.判断结果是否为0
        int r = result.intValue();
        if (r != 0) {
            // 2-1.不为0，没有购买资格
            return Result.fail(r == 1
                    ? "Flash-sale voucher is out of stock"
                    : "You have already purchased this voucher");
        }
        // Lua已经原子预留库存并保存生产侧待发布记录。RabbitMQ不可用时由定时任务重放。
        try {
            voucherOrderPublisher.publish(new VoucherOrderMessage(orderId, userId, voucherId));
        } catch (RuntimeException publishFailure) {
            log.warn("RabbitMQ暂时不可用，订单将从Redis待发布记录重放 orderId={}", orderId, publishFailure);
        }
        return Result.ok(orderId);
    }

    @Override
    @Transactional
    public Result purchaseVoucher(Long voucherId) {
        Long userId = UserHolder.getUser().getId();
        long count = query().eq("user_id", userId).eq("voucher_id", voucherId).count();
        if (count > 0) {
            return Result.fail("You have already purchased this voucher");
        }
        Voucher voucher = voucherService.getById(voucherId);
        if (voucher == null) {
            return Result.fail("Voucher not found");
        }
        if (voucher.getType() != 0) {
            return Result.fail("This voucher is only available through the manual flash sale");
        }
        VoucherOrder voucherOrder = new VoucherOrder();
        long orderId = redisIdWorker.nextId("order");
        LocalDateTime acquiredAt = LocalDateTime.now();
        voucherOrder.setId(orderId);
        voucherOrder.setUserId(userId);
        voucherOrder.setVoucherId(voucherId);
        voucherOrder.setCreateTime(acquiredAt);
        voucherOrder.setExpiresAt(expirationFor(orderId, acquiredAt));
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
            throw new IllegalStateException("Database stock is insufficient or the flash-sale voucher does not exist");
        }

        LocalDateTime acquiredAt = voucherOrder.getCreateTime() == null
                ? LocalDateTime.now()
                : voucherOrder.getCreateTime();
        voucherOrder.setCreateTime(acquiredAt);
        voucherOrder.setExpiresAt(expirationFor(voucherOrder.getId(), acquiredAt));
        if (!save(voucherOrder)) {
            throw new IllegalStateException("Failed to save the flash-sale order");
        }
    }

    boolean initializeStockIfMissing(Long voucherId) {
        String stockKey = SECKILL_STOCK_KEY + voucherId;
        if (Boolean.TRUE.equals(stringRedisTemplate.hasKey(stockKey))) {
            return true;
        }
        SeckillVoucher voucher = seckillVoucherService.getById(voucherId);
        if (voucher == null || voucher.getStock() == null) {
            return false;
        }
        stringRedisTemplate.opsForValue().setIfAbsent(
                stockKey,
                Integer.toString(Math.max(0, voucher.getStock()))
        );
        return Boolean.TRUE.equals(stringRedisTemplate.hasKey(stockKey));
    }

    static LocalDateTime expirationFor(long orderId, LocalDateTime acquiredAt) {
        int validityDays = 7 + Math.floorMod(Long.hashCode(orderId), 177);
        return acquiredAt.plusDays(validityDays);
    }
}
