package com.hmdp.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;
import java.time.LocalTime;

@Data
@Accessors(chain = true)
@TableName("tb_shop_business_hours")
public class ShopBusinessHours implements Serializable {

    private Long shopId;
    private Integer dayOfWeek;
    private Boolean closed;
    private LocalTime openTime;
    private LocalTime closeTime;
    private Boolean closesNextDay;
    private LocalDateTime createTime;
    private LocalDateTime updateTime;
}
