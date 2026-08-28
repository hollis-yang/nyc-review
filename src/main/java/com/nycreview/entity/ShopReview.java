package com.nycreview.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;
import java.util.List;

@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@TableName(value = "tb_shop_review", autoResultMap = true)
public class ShopReview implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    private Long shopId;

    /** Root review ID. A depth-0 review points to itself. */
    private Long rootId;

    /** Direct parent review; null for a depth-0 review. */
    private Long parentId;

    /** 0=root review, 1=reply, 2=reply to a reply. */
    private Integer depth;

    private Long userId;

    private Long replyToUserId;

    /** USER or MERCHANT for generated scenarios; API posts are always USER. */
    private String authorRole;

    /** SYNTHETIC, USER_SUBMITTED, or LEGACY. */
    private String sourceType;

    private String language;

    private String sentiment;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<String> topicTags;

    private Boolean securityTest;

    private Integer rating;

    private String content;

    private String images;

    private Integer liked;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;

    @TableField(exist = false)
    private String nickName;

    @TableField(exist = false)
    private String icon;

    @TableField(exist = false)
    private Boolean isLike;

    @TableField(exist = false)
    private String replyToNickName;

    @TableField(exist = false)
    private List<ShopReview> children;
}
