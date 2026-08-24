package com.hmdp.mapper;

import com.hmdp.entity.Shop;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.hmdp.dto.map.ShopMapAggregateRow;
import com.hmdp.dto.map.ShopMapShopRow;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

public interface ShopMapper extends BaseMapper<Shop> {

    /**
     * Rank the complete operational category before pagination. The score uses
     * only first-party platform activity and deliberately stays separate from
     * the merchant rating: review volume, blog likes, favorites and valid
     * voucher orders all contribute with logarithmic damping.
     */
    @Select("""
            <script>
            SELECT
                shop.*,
                (
                    LN(1 + GREATEST(COALESCE(shop.rating_count, 0), COALESCE(shop.comments, 0))) * 20
                    + LN(1 + COALESCE(blog_activity.likes, 0)) * 10
                    + LN(1 + COALESCE(shop.sold, 0)) * 5
                    + COALESCE(favorite_activity.favorites, 0) * 5
                    + COALESCE(order_activity.orders, 0) * 3
                ) AS popularity_score
            FROM tb_shop shop
            LEFT JOIN (
                SELECT shop_id, SUM(COALESCE(liked, 0)) AS likes
                FROM tb_blog
                GROUP BY shop_id
            ) blog_activity ON blog_activity.shop_id = shop.id
            LEFT JOIN (
                SELECT shop_id, COUNT(*) AS favorites
                FROM tb_shop_favorite
                GROUP BY shop_id
            ) favorite_activity ON favorite_activity.shop_id = shop.id
            LEFT JOIN (
                SELECT voucher.shop_id, COUNT(*) AS orders
                FROM tb_voucher_order voucher_order
                INNER JOIN tb_voucher voucher ON voucher.id = voucher_order.voucher_id
                WHERE voucher_order.status NOT IN (4, 5, 6)
                GROUP BY voucher.shop_id
            ) order_activity ON order_activity.shop_id = shop.id
            WHERE shop.type_id = #{typeId}
              AND shop.business_status = 'OPERATIONAL'
            ORDER BY
            <choose>
                <when test="ascending">popularity_score ASC</when>
                <otherwise>popularity_score DESC</otherwise>
            </choose>,
            <choose>
                <when test="ascending">shop.score ASC</when>
                <otherwise>shop.score DESC</otherwise>
            </choose>,
            shop.id ASC
            LIMIT #{offset}, #{pageSize}
            </script>
            """)
    List<Shop> selectByPlatformPopularity(
            @Param("typeId") long typeId,
            @Param("ascending") boolean ascending,
            @Param("offset") long offset,
            @Param("pageSize") long pageSize
    );

    @Select("""
            SELECT data_version
            FROM tb_map_data_import
            WHERE active = 1
            ORDER BY imported_at DESC, data_version DESC
            LIMIT 1
            """)
    String selectActiveMapDataVersion();

    @Select("""
            <script>
            WITH active_map AS (
                SELECT data_version
                FROM tb_map_data_import
                WHERE active = 1
                ORDER BY imported_at DESC, data_version DESC
                LIMIT 1
            ),
            filtered_counts AS (
                SELECT counts.*
                FROM tb_borough_shop_count counts
                INNER JOIN active_map active ON active.data_version = counts.data_version
                <if test="typeIds != null and typeIds.size() > 0">
                  WHERE counts.type_id IN
                  <foreach collection="typeIds" item="typeId" open="(" separator="," close=")">
                    #{typeId}
                  </foreach>
                </if>
            ),
            visible_clusters AS (
                SELECT
                    borough,
                    MIN(min_x) AS west,
                    MIN(min_y) AS south,
                    MAX(max_x) AS east,
                    MAX(max_y) AS north
                FROM filtered_counts
                GROUP BY borough
                HAVING east >= #{west}
                   AND west &lt;= #{east}
                   AND north >= #{south}
                   AND south &lt;= #{north}
            )
            SELECT
                counts.borough AS groupId,
                counts.borough AS borough,
                counts.borough AS name,
                counts.type_id AS typeId,
                counts.shop_count AS count,
                counts.centroid_y AS lat,
                counts.centroid_x AS lng,
                counts.min_x AS west,
                counts.min_y AS south,
                counts.max_x AS east,
                counts.max_y AS north,
                counts.data_version AS minDataVersion,
                counts.data_version AS maxDataVersion
            FROM filtered_counts counts
            INNER JOIN visible_clusters visible ON visible.borough = counts.borough
            ORDER BY counts.borough ASC, counts.type_id ASC
            </script>
            """)
    List<ShopMapAggregateRow> selectBoroughMapAggregates(
            @Param("west") double west,
            @Param("south") double south,
            @Param("east") double east,
            @Param("north") double north,
            @Param("typeIds") List<Long> typeIds
    );

    @Select("""
            <script>
            WITH active_map AS (
                SELECT data_version
                FROM tb_map_data_import
                WHERE active = 1
                ORDER BY imported_at DESC, data_version DESC
                LIMIT 1
            ),
            official_counts AS (
                SELECT
                    counts.data_version,
                    neighborhood.code AS group_id,
                    neighborhood.name AS name,
                    neighborhood.borough AS borough,
                    counts.type_id,
                    counts.shop_count,
                    counts.centroid_x,
                    counts.centroid_y,
                    neighborhood.min_x,
                    neighborhood.min_y,
                    neighborhood.max_x,
                    neighborhood.max_y
                FROM tb_neighborhood_shop_count counts
                INNER JOIN active_map active ON active.data_version = counts.data_version
                INNER JOIN tb_neighborhood neighborhood
                    ON neighborhood.code = counts.neighborhood_code
                   AND neighborhood.active = 1
                <if test="typeIds != null and typeIds.size() > 0">
                  WHERE counts.type_id IN
                  <foreach collection="typeIds" item="typeId" open="(" separator="," close=")">
                    #{typeId}
                  </foreach>
                </if>
            ),
            unassigned_counts AS (
                SELECT
                    location.data_version AS data_version,
                    CONCAT('UNASSIGNED:', shop.borough) AS group_id,
                    '__UNASSIGNED__' AS name,
                    shop.borough AS borough,
                    shop.type_id AS type_id,
                    COUNT(*) AS shop_count,
                    AVG(shop.x) AS centroid_x,
                    AVG(shop.y) AS centroid_y,
                    MIN(shop.x) AS min_x,
                    MIN(shop.y) AS min_y,
                    MAX(shop.x) AS max_x,
                    MAX(shop.y) AS max_y
                FROM tb_shop_map_location location
                INNER JOIN active_map active ON active.data_version = location.data_version
                INNER JOIN tb_shop shop
                    ON shop.id = location.shop_id
                   AND shop.data_version = location.data_version
                WHERE location.neighborhood_code IS NULL
                  AND shop.business_status = 'OPERATIONAL'
                <if test="typeIds != null and typeIds.size() > 0">
                  AND shop.type_id IN
                  <foreach collection="typeIds" item="typeId" open="(" separator="," close=")">
                    #{typeId}
                  </foreach>
                </if>
                GROUP BY location.data_version, shop.borough, shop.type_id
            ),
            filtered_counts AS (
                SELECT * FROM official_counts
                UNION ALL
                SELECT * FROM unassigned_counts
            ),
            visible_clusters AS (
                SELECT
                    group_id,
                    MIN(min_x) AS west,
                    MIN(min_y) AS south,
                    MAX(max_x) AS east,
                    MAX(max_y) AS north
                FROM filtered_counts
                GROUP BY group_id
                HAVING east >= #{west}
                   AND west &lt;= #{east}
                   AND north >= #{south}
                   AND south &lt;= #{north}
            )
            SELECT
                counts.group_id AS groupId,
                counts.name AS name,
                counts.borough AS borough,
                counts.type_id AS typeId,
                counts.shop_count AS count,
                counts.centroid_y AS lat,
                counts.centroid_x AS lng,
                counts.min_x AS west,
                counts.min_y AS south,
                counts.max_x AS east,
                counts.max_y AS north,
                counts.data_version AS minDataVersion,
                counts.data_version AS maxDataVersion
            FROM filtered_counts counts
            INNER JOIN visible_clusters visible
                ON visible.group_id = counts.group_id
            ORDER BY counts.borough ASC, counts.name ASC, counts.type_id ASC
            </script>
            """)
    List<ShopMapAggregateRow> selectNeighborhoodMapAggregates(
            @Param("west") double west,
            @Param("south") double south,
            @Param("east") double east,
            @Param("north") double north,
            @Param("typeIds") List<Long> typeIds
    );

    @Select("""
            <script>
            WITH active_map AS (
                SELECT data_version
                FROM tb_map_data_import
                WHERE active = 1
                ORDER BY imported_at DESC, data_version DESC
                LIMIT 1
            )
            SELECT COUNT(*)
            FROM tb_shop_map_location location
            INNER JOIN active_map active ON active.data_version = location.data_version
            INNER JOIN tb_shop shop
                ON shop.id = location.shop_id
               AND shop.data_version = location.data_version
            WHERE MBRIntersects(
                    location.location,
                    ST_GeomFromText(
                        CONCAT(
                            'POLYGON((',
                            #{west}, ' ', #{south}, ',',
                            #{east}, ' ', #{south}, ',',
                            #{east}, ' ', #{north}, ',',
                            #{west}, ' ', #{north}, ',',
                            #{west}, ' ', #{south},
                            '))'
                        ),
                        4326,
                        'axis-order=long-lat'
                    )
                  )
              AND ST_Longitude(location.location) BETWEEN #{west} AND #{east}
              AND ST_Latitude(location.location) BETWEEN #{south} AND #{north}
              AND shop.business_status = 'OPERATIONAL'
            <if test="typeIds != null and typeIds.size() > 0">
              AND shop.type_id IN
              <foreach collection="typeIds" item="typeId" open="(" separator="," close=")">
                #{typeId}
              </foreach>
            </if>
            </script>
            """)
    long countMapShops(
            @Param("west") double west,
            @Param("south") double south,
            @Param("east") double east,
            @Param("north") double north,
            @Param("typeIds") List<Long> typeIds
    );

    @Select("""
            <script>
            WITH active_map AS (
                SELECT data_version
                FROM tb_map_data_import
                WHERE active = 1
                ORDER BY imported_at DESC, data_version DESC
                LIMIT 1
            )
            SELECT
                shop.id AS id,
                shop.name AS name,
                shop.type_id AS typeId,
                ST_Latitude(location.location) AS lat,
                ST_Longitude(location.location) AS lng,
                shop.score AS score,
                shop.avg_price AS avgPrice,
                COALESCE(neighborhood.name, location.source_area) AS neighborhood,
                NULLIF(SUBSTRING_INDEX(shop.images, ',', 1), '') AS thumbnailUrl,
                shop.source_type AS sourceType,
                COALESCE(JSON_CONTAINS(shop.synthetic_fields, '"images"'), 0) AS illustrativeImage,
                COALESCE(JSON_CONTAINS(shop.synthetic_fields, '"score"'), 0) AS syntheticScore,
                location.data_version AS dataVersion
            FROM tb_shop_map_location location
            INNER JOIN active_map active ON active.data_version = location.data_version
            INNER JOIN tb_shop shop
                ON shop.id = location.shop_id
               AND shop.data_version = location.data_version
            LEFT JOIN tb_neighborhood neighborhood
                ON neighborhood.code = location.neighborhood_code
               AND neighborhood.active = 1
            WHERE MBRIntersects(
                    location.location,
                    ST_GeomFromText(
                        CONCAT(
                            'POLYGON((',
                            #{west}, ' ', #{south}, ',',
                            #{east}, ' ', #{south}, ',',
                            #{east}, ' ', #{north}, ',',
                            #{west}, ' ', #{north}, ',',
                            #{west}, ' ', #{south},
                            '))'
                        ),
                        4326,
                        'axis-order=long-lat'
                    )
                  )
              AND ST_Longitude(location.location) BETWEEN #{west} AND #{east}
              AND ST_Latitude(location.location) BETWEEN #{south} AND #{north}
              AND shop.business_status = 'OPERATIONAL'
            <if test="typeIds != null and typeIds.size() > 0">
              AND shop.type_id IN
              <foreach collection="typeIds" item="typeId" open="(" separator="," close=")">
                #{typeId}
              </foreach>
            </if>
            ORDER BY shop.id ASC
            LIMIT #{limit}
            </script>
            """)
    List<ShopMapShopRow> selectMapShops(
            @Param("west") double west,
            @Param("south") double south,
            @Param("east") double east,
            @Param("north") double north,
            @Param("typeIds") List<Long> typeIds,
            @Param("limit") int limit
    );
}
