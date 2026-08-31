package com.nycreview.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.nycreview.dto.Result;
import com.nycreview.entity.Voucher;
import com.nycreview.mapper.VoucherMapper;
import com.nycreview.entity.SeckillVoucher;
import com.nycreview.service.ISeckillVoucherService;
import com.nycreview.service.IVoucherService;
import com.nycreview.utils.ContentSourceTypes;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import jakarta.annotation.Resource;
import java.util.List;

import static com.nycreview.utils.RedisConstants.SECKILL_STOCK_KEY;

@Service
public class VoucherServiceImpl extends ServiceImpl<VoucherMapper, Voucher> implements IVoucherService {

    @Resource
    private ISeckillVoucherService seckillVoucherService;

    @Resource
    private StringRedisTemplate stringRedisTemplate;

    @Override
    public Result queryVoucherOfShop(Long shopId) {
        // 查询优惠券信息
        List<Voucher> vouchers = getBaseMapper().queryVoucherOfShop(shopId);
        // 返回结果
        return Result.ok(vouchers);
    }

    @Override
    public void addVoucher(Voucher voucher) {
        markApiSubmitted(voucher);
        save(voucher);
    }

    @Override
    @Transactional
    public void addSeckillVoucher(Voucher voucher) {
        // 保存优惠券
        markApiSubmitted(voucher);
        save(voucher);
        // 保存秒杀信息
        SeckillVoucher seckillVoucher = new SeckillVoucher();
        seckillVoucher.setVoucherId(voucher.getId());
        seckillVoucher.setStock(voucher.getStock());
        seckillVoucher.setBeginTime(voucher.getBeginTime());
        seckillVoucher.setEndTime(voucher.getEndTime());
        seckillVoucherService.save(seckillVoucher);

        // 保存秒杀库存到redis
        stringRedisTemplate.opsForValue().set(
                SECKILL_STOCK_KEY + voucher.getId(), 
                voucher.getStock().toString());
    }

    static void markApiSubmitted(Voucher voucher) {
        // Generated promotions are inserted only by the validated import
        // bundle. Public API callers cannot label a voucher as SYNTHETIC.
        voucher.setSourceType(ContentSourceTypes.USER_SUBMITTED);
        voucher.setDataVersion(null);
        if (voucher.getValidDays() == null || voucher.getValidDays() < 7 || voucher.getValidDays() > 183) {
            voucher.setValidDays(30);
        }
    }
}
