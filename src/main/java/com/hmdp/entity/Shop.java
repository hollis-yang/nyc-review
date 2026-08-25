package com.hmdp.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;
import java.util.List;

import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;

@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@TableName(value = "tb_shop", autoResultMap = true)
public class Shop implements Serializable {

    private static final long serialVersionUID = 1L;

    /**
     * 主键
     */
    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /**
     * 商铺名称
     */
    private String name;

    /**
     * 商铺类型的id
     */
    private Long typeId;

    /**
     * NYC 子分类 id
     */
    private Long subcategoryId;

    /**
     * 商铺图片，多个图片以','隔开
     */
    private String images;

    /**
     * 商圈，例如陆家嘴
     */
    private String area;

    /**
     * NYC borough
     */
    private String borough;

    /**
     * 地址
     */
    private String address;

    /**
     * 商户介绍，供传统详情页与 RAG 使用
     */
    private String description;

    /**
     * 经度
     */
    private Double x;

    /**
     * 维度
     */
    private Double y;

    /**
     * 均价，取整数
     */
    private Long avgPrice;

    /**
     * 价格等级 1~4
     */
    private Integer priceLevel;

    /**
     * 销量
     */
    private Integer sold;

    /**
     * Legacy local root-review count. New clients should use
     * {@link #localReviewCount}; both values are kept equal by imports and
     * live review writes.
     */
    private Integer comments;

    /** Number of depth-zero reviews that can be browsed through /shop-review. */
    private Integer localReviewCount;

    /**
     * 评分，1~5分，乘10保存，避免小数
     */
    private Integer score;

    /** Local depth-zero review average, multiplied by ten. */
    private Integer localScore;

    /**
     * 营业时间，例如 10:00-22:00
     */
    private String openHours;

    private String phone;

    private String website;

    private String reservationUrl;

    private String businessStatus;

    /**
     * Legacy alias for externalRatingCount. It must never be presented as the
     * number of locally browsable reviews.
     */
    private Integer ratingCount;

    /** Source-observed aggregate rating, multiplied by ten. */
    private Integer externalScore;

    /** Source-observed aggregate rating/review count; content is not local. */
    private Integer externalRatingCount;

    private String priceRangeText;

    private String healthGrade;

    private LocalDateTime lastEnrichedAt;

    private String timezone;

    private String sourceType;

    private String externalId;

    private String sourceName;

    private String sourceUrl;

    private LocalDateTime sourceFetchedAt;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<String> syntheticFields;

    private String dataVersion;

    /**
     * Ordered image attribution returned on the detail endpoint. The legacy
     * images string remains available for list, map, and older clients.
     */
    @TableField(exist = false)
    private List<ShopImage> imageAssets;

    /**
     * 创建时间
     */
    private LocalDateTime createTime;

    /**
     * 更新时间
     */
    private LocalDateTime updateTime;


    @TableField(exist = false)
    private Double distance;

    /**
     * Runtime-only platform engagement score used by the popularity ranking.
     * It is calculated from reviews, blog likes, favorites and valid voucher
     * orders; it is not persisted as a merchant-supplied fact.
     */
    @TableField(exist = false)
    private Double popularityScore;
}
