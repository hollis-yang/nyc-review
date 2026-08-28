package com.nycreview.service;

import com.nycreview.dto.Result;
import com.nycreview.entity.ShopType;
import com.baomidou.mybatisplus.extension.service.IService;

public interface IShopTypeService extends IService<ShopType> {

    Result queryTypeList();
}
