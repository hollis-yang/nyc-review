package com.hmdp.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * An attributed image assigned to a shop for presentation. P8 images are
 * illustrative and must not be represented as photographs of the shop.
 */
@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@TableName("tb_shop_image")
public class ShopImage implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    private Long shopId;

    private String displayUrl;

    private String sourcePageUrl;

    private String sourceName;

    private String authorName;

    private String licenseName;

    private String licenseUrl;

    private String imageType;

    private String sha256;

    private Integer sortOrder;

    private LocalDateTime fetchedAt;

    private String dataVersion;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}
