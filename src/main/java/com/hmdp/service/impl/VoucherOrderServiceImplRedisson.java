//package com.hmdp.service.impl;
//
//import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
//import com.hmdp.dto.Result;
//import com.hmdp.entity.SeckillVoucher;
//import com.hmdp.entity.VoucherOrder;
//import com.hmdp.mapper.VoucherOrderMapper;
//import com.hmdp.service.ISeckillVoucherService;
//import com.hmdp.service.IVoucherOrderService;
//import com.hmdp.utils.RedisIdWorker;
//import com.hmdp.utils.UserHolder;
//import org.redisson.api.RLock;
//import org.redisson.api.RedissonClient;
//import org.springframework.aop.framework.AopContext;
//import org.springframework.data.redis.core.StringRedisTemplate;
//import org.springframework.stereotype.Service;
//import org.springframework.transaction.annotation.Transactional;
//
//import javax.annotation.Resource;
//import java.time.LocalDateTime;
//import java.util.concurrent.TimeUnit;
//
///**
// * <p>
// *  服务实现类
// * </p>
// *
// * @author 虎哥
// * @since 2021-12-22
// */
//@Service
//public class VoucherOrderServiceImplRedisson extends ServiceImpl<VoucherOrderMapper, VoucherOrder> implements IVoucherOrderService {
//
//    @Resource
//    private ISeckillVoucherService seckillVoucherService;
//
//    @Resource
//    private RedisIdWorker redisIdWorker;
//
//    @Resource
//    private StringRedisTemplate stringRedisTemplate;
//
//    @Resource
//    private RedissonClient redissonClient;
//
//    @Override
//    public Result seckillVoucher(Long voucherId) {
//        // 1.查询优惠券
//        SeckillVoucher voucher = seckillVoucherService.getById(voucherId);
//        // 2.判断秒杀是否开始
//        if (voucher.getBeginTime().isAfter(LocalDateTime.now())) {
//            // 秒杀未开始
//            return Result.fail("秒杀未开始!");
//        }
//        // 3.判断秒杀是否已经结束
//        if (voucher.getEndTime().isBefore(LocalDateTime.now())) {
//            return Result.fail("秒杀已经结束!");
//        }
//        // 4.判断库存是否充足
//        if (voucher.getStock() < 1) {
//            return Result.fail("库存不足!");
//        }
//
//        // 对 userId 加悲观锁，一个用户只能下一单
//        Long userId = UserHolder.getUser().getId();
//
//        // 提交事务后释放锁 确保线程安全
//        /**
//         * synchronized (userId.toString().intern()) {
//         *             // 获取代理对象（事务）
//         *             IVoucherOrderService proxy = (IVoucherOrderService) AopContext.currentProxy();
//         *             return proxy.createVoucherOrder(voucherId);
//         *         }
//         */
//
//        // 创建锁对象
////        SimpleRedisLock lock = new SimpleRedisLock("order:" + userId, stringRedisTemplate);
//        RLock lock = redissonClient.getLock("lock:order:" + userId);
//        // 获取锁
//        boolean isLock = false;
//        try {
//            isLock = lock.tryLock(1, 10, TimeUnit.SECONDS);
//        } catch (InterruptedException e) {
//            throw new RuntimeException(e);
//        }
//        // 判断是否获取锁成功
//        if (!isLock) {
//            // 获取锁失败：返回错误或重试
//            return Result.fail("不允许重复下单!");
//        }
//
//        try {
//            // 获取代理对象（事务）
//            IVoucherOrderService proxy = (IVoucherOrderService) AopContext.currentProxy();
//            return proxy.createVoucherOrder(voucherId);
//        } finally {
//            // 释放锁
//            lock.unlock();
//        }
//    }
//
//    @Transactional
//    public Result createVoucherOrder(Long voucherId) {
//        // 优化：一人一单
//        Long userId = UserHolder.getUser().getId();
//
//        // (1) 查询订单
//        int count = query().eq("user_id", userId).eq("voucher_id", voucherId).count();
//        // (2) 判断是否存在
//        if (count > 0) {
//            return Result.fail("你已经购买过一次了!");
//        }
//
//        // 5.扣减库存
//        // stock > 0 乐观锁
//        boolean success = seckillVoucherService.update()
//                .setSql("stock = stock - 1") // set stock = stock - 1
//                .eq("voucher_id", voucherId) // where voucher_id = ?
//                .gt("stock", 0) // and stock > 0 防止超卖
//                .update();
//        if (!success) {
//            return Result.fail("库存不足!");
//        }
//
//        // 6.创建订单
//        VoucherOrder voucherOrder = new VoucherOrder();
//        // 6.1.订单id
//        long orderId = redisIdWorker.nextId("order");
//        voucherOrder.setId(orderId);
//        // 6.2.用户id
//        voucherOrder.setUserId(userId);
//        // 6.3.代金券id
//        voucherOrder.setVoucherId(voucherId);
//        save(voucherOrder);
//
//        return Result.ok(orderId);
//    }
//}
