package com.nycreview.dto.map;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Internal projection containing only fields required by an individual map marker.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class ShopMapShopRow {
    private Long id;
    private String name;
    private Long typeId;
    private Double lat;
    private Double lng;
    private Integer score;
    private Long avgPrice;
    private String neighborhood;
    private String thumbnailUrl;
    private String sourceType;
    private Boolean illustrativeImage;
    private Boolean syntheticScore;
    private String dataVersion;
}
