package com.nycreview.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

/** An attributed merchant-specific or fallback image assigned to a shop. */
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

    private String matchType;

    private Boolean isPrimary;

    private Integer displayOrder;

    private Integer width;

    private Integer height;

    private String sha256;

    private String contentSha256;

    private Integer sortOrder;

    private LocalDateTime fetchedAt;

    private LocalDateTime lastCheckedAt;

    private String availabilityStatus;

    private String cachedUrl;

    private String dataVersion;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}
