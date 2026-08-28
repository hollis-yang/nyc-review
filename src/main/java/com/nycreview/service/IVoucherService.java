package com.nycreview.service;

import com.nycreview.dto.Result;
import com.nycreview.entity.Voucher;
import com.baomidou.mybatisplus.extension.service.IService;

public interface IVoucherService extends IService<Voucher> {

    Result queryVoucherOfShop(Long shopId);

    void addVoucher(Voucher voucher);

    void addSeckillVoucher(Voucher voucher);
}
