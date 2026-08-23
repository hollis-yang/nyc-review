package com.hmdp.mapper;

import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.mapping.SqlSource;
import org.apache.ibatis.scripting.xmltags.XMLLanguageDriver;
import org.apache.ibatis.session.Configuration;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ShopMapperMapContractTest {

    @Test
    void dynamicMapQueriesAreValidMyBatisScripts() {
        Configuration configuration = new Configuration();
        configuration.setVariables(new java.util.Properties());
        XMLLanguageDriver languageDriver = new XMLLanguageDriver();

        for (String method : List.of(
                "selectBoroughMapAggregates",
                "selectNeighborhoodMapAggregates",
                "countMapShops",
                "selectMapShops"
        )) {
            SqlSource source = languageDriver.createSqlSource(configuration, sql(method), Map.class);
            assertTrue(source != null, "Could not parse mapper script for " + method);
        }
    }

    @Test
    void mapQueriesUseTheP7ProjectionAndPreAggregateTables() {
        String borough = sql("selectBoroughMapAggregates");
        String neighborhood = sql("selectNeighborhoodMapAggregates");
        String count = sql("countMapShops");
        String markers = sql("selectMapShops");

        assertTrue(borough.contains("tb_borough_shop_count"));
        assertTrue(borough.contains("counts.min_x AS west"));
        assertTrue(borough.contains("HAVING east >="));
        assertTrue(neighborhood.contains("tb_neighborhood_shop_count"));
        assertTrue(neighborhood.contains("tb_neighborhood neighborhood"));
        assertTrue(neighborhood.contains("neighborhood.code AS group_id"));
        assertTrue(neighborhood.contains("location.neighborhood_code IS NULL"));
        assertTrue(neighborhood.contains("CONCAT('UNASSIGNED:', shop.borough)"));
        assertTrue(neighborhood.contains("UNION ALL"));
        assertTrue(count.contains("FROM tb_shop_map_location"));
        assertTrue(count.contains("MBRIntersects("));
        assertTrue(count.contains("axis-order=long-lat"));
        assertTrue(count.contains("ST_Longitude(location.location) BETWEEN"));
        assertTrue(count.contains("ST_Latitude(location.location) BETWEEN"));
        assertTrue(markers.contains("FROM tb_shop_map_location"));
        assertTrue(markers.contains("MBRIntersects("));
        assertTrue(markers.contains("INNER JOIN tb_shop shop"));
        assertTrue(markers.contains("LEFT JOIN tb_neighborhood neighborhood"));
        assertTrue(markers.contains("ST_Latitude(location.location) AS lat"));
        assertTrue(markers.contains("ST_Longitude(location.location) AS lng"));
        assertTrue(markers.contains("LIMIT #{limit}"));
        assertFalse(markers.contains("ST_X(location.location)"));
        assertFalse(markers.contains("ST_Y(location.location)"));
        assertFalse(markers.contains("SELECT *"));
    }

    private String sql(String methodName) {
        Method method = Arrays.stream(ShopMapper.class.getDeclaredMethods())
                .filter(candidate -> candidate.getName().equals(methodName))
                .findFirst()
                .orElseThrow();
        return String.join("\n", method.getAnnotation(Select.class).value());
    }
}
