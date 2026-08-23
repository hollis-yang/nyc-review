package com.hmdp.dto.map;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Internal projection used by MyBatis for one cluster/category aggregate.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class ShopMapAggregateRow {
    private String groupId;
    private String name;
    private String borough;
    private Long typeId;
    private Long count;
    private Double lat;
    private Double lng;
    private Double west;
    private Double south;
    private Double east;
    private Double north;
    private String minDataVersion;
    private String maxDataVersion;
}
