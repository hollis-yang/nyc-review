package com.hmdp.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

@Data
@Accessors(chain = true)
@TableName("tb_shop_tag")
public class ShopTag implements Serializable {

    private Long shopId;
    private String tag;
    private LocalDateTime createTime;
}
