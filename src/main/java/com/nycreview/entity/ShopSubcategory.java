package com.nycreview.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

@Data
@Accessors(chain = true)
@TableName("tb_shop_subcategory")
public class ShopSubcategory implements Serializable {

    @TableId(value = "id", type = IdType.INPUT)
    private Long id;
    private Long typeId;
    private String name;
    private String slug;
    private LocalDateTime createTime;
    private LocalDateTime updateTime;
}
