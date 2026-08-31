package com.nycreview.service.impl;

import com.nycreview.entity.SeckillVoucher;
import com.nycreview.service.ISeckillVoucherService;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class VoucherOrderStockRecoveryTest {

    @Test
    void missingRedisStockIsRecoveredFromDatabaseBeforeFlashSale() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked")
        ValueOperations<String, String> values = mock(ValueOperations.class);
        ISeckillVoucherService vouchers = mock(ISeckillVoucherService.class);
        long voucherId = 70_625_703_939L;
        String stockKey = "seckill:stock:" + voucherId;

        when(redis.hasKey(stockKey)).thenReturn(false, true);
        when(redis.opsForValue()).thenReturn(values);
        when(vouchers.getById(voucherId)).thenReturn(
                new SeckillVoucher().setVoucherId(voucherId).setStock(397)
        );

        VoucherOrderServiceImpl service = new VoucherOrderServiceImpl();
        ReflectionTestUtils.setField(service, "stringRedisTemplate", redis);
        ReflectionTestUtils.setField(service, "seckillVoucherService", vouchers);

        assertTrue(service.initializeStockIfMissing(voucherId));
        verify(values).setIfAbsent(stockKey, "397");
    }
}
