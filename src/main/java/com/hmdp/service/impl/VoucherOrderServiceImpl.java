package com.hmdp.service.impl;

import com.hmdp.dto.Result;
import com.hmdp.entity.Voucher;
import com.hmdp.entity.VoucherOrder;
import com.hmdp.mapper.VoucherOrderMapper;
import com.hmdp.messaging.VoucherOrderMessage;
import com.hmdp.messaging.VoucherOrderPublisher;
import com.hmdp.service.ISeckillVoucherService;
import com.hmdp.service.IVoucherOrderService;
import com.hmdp.service.IVoucherService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmdp.utils.RedisIdWorker;
import com.hmdp.utils.UserHolder;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import jakarta.annotation.Resource;
import java.util.Collections;

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
            return Result.fail(r == 1 ? "库存不足" : "不能重复购买");
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
            throw new IllegalStateException("Database stock is insufficient or the flash-sale voucher does not exist");
        }

        if (!save(voucherOrder)) {
            throw new IllegalStateException("Failed to save the flash-sale order");
        }
    }
}
