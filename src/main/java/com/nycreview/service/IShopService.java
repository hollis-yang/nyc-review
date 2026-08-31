package com.nycreview.service;

import com.nycreview.dto.Result;
import com.nycreview.entity.Shop;
import com.baomidou.mybatisplus.extension.service.IService;

public interface IShopService extends IService<Shop> {

    Result queryById(Long id);

    Result update(Shop shop);

    Result queryShopByType(Integer typeId, Integer current, Double x, Double y, String sortBy, String sortOrder);

    Result queryLinkOptions(Integer typeId, String query, Integer current, Integer size);
}
