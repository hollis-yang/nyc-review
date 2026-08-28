package com.nycreview.service.impl;

import com.nycreview.dto.Result;
import com.nycreview.mapper.ShopMapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.mapping.SqlSource;
import org.apache.ibatis.scripting.xmltags.XMLLanguageDriver;
import org.apache.ibatis.session.Configuration;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ShopServiceImplSortValidationTest {

    @Test
    void shouldAllowOnlySupportedSortColumns() {
        assertEquals("distance", ShopServiceImpl.resolveSortColumn("distance"));
        assertEquals("rating", ShopServiceImpl.resolveSortColumn("rating"));
        assertEquals("popularity", ShopServiceImpl.resolveSortColumn("popularity"));
        assertEquals("rating", ShopServiceImpl.resolveSortColumn("score"));
        assertEquals("popularity", ShopServiceImpl.resolveSortColumn("comments"));
        assertNull(ShopServiceImpl.resolveSortColumn(null));
        assertNull(ShopServiceImpl.resolveSortColumn(""));
        assertNull(ShopServiceImpl.resolveSortColumn("   "));
    }

    @Test
    void shouldRejectUnknownColumnsAndSqlExpressions() {
        assertNull(ShopServiceImpl.resolveSortColumn("sold"));
        assertNull(ShopServiceImpl.resolveSortColumn("RAND()"));
        assertNull(ShopServiceImpl.resolveSortColumn("score desc"));
        assertNull(ShopServiceImpl.resolveSortColumn("score, comments"));
        assertNull(ShopServiceImpl.resolveSortColumn("Score"));
    }

    @Test
    void shouldAllowOnlySupportedSortOrders() {
        assertTrue(ShopServiceImpl.isSortOrderValid(null));
        assertTrue(ShopServiceImpl.isSortOrderValid(""));
        assertTrue(ShopServiceImpl.isSortOrderValid("asc"));
        assertTrue(ShopServiceImpl.isSortOrderValid("DESC"));
        assertFalse(ShopServiceImpl.isSortOrderValid("ascending"));
        assertFalse(ShopServiceImpl.isSortOrderValid("desc; drop table tb_shop"));
    }

    @Test
    void shouldRejectInvalidParametersBeforeAccessingDataSources() {
        ShopServiceImpl service = new ShopServiceImpl();

        Result invalidColumn = service.queryShopByType(1, 1, null, null, "RAND()", "asc");
        assertFalse(invalidColumn.getSuccess());
        assertEquals("Invalid sort field", invalidColumn.getErrorMsg());

        Result invalidGeoColumn = service.queryShopByType(1, 1, 120.1, 30.2, "score desc", "asc");
        assertFalse(invalidGeoColumn.getSuccess());
        assertEquals("Invalid sort field", invalidGeoColumn.getErrorMsg());

        Result invalidOrder = service.queryShopByType(1, 1, null, null, "score", "sideways");
        assertFalse(invalidOrder.getSuccess());
        assertEquals("Invalid sort direction", invalidOrder.getErrorMsg());

        Result partialCoordinates = service.queryShopByType(1, 1, -73.98, null, "distance", "asc");
        assertFalse(partialCoordinates.getSuccess());
        assertEquals("Invalid coordinates", partialCoordinates.getErrorMsg());

        Result invalidLatitude = service.queryShopByType(1, 1, -73.98, 91.0, "distance", "asc");
        assertFalse(invalidLatitude.getSuccess());
        assertEquals("Invalid coordinates", invalidLatitude.getErrorMsg());
    }

    @Test
    void shouldCalculateDistanceInMeters() {
        double distance = ShopServiceImpl.distanceInMeters(
                -73.9855,
                40.7580,
                -73.9772,
                40.7527
        );

        assertTrue(distance > 800);
        assertTrue(distance < 1_000);
    }

    @Test
    void shouldValidateCoordinatePairs() {
        assertTrue(ShopServiceImpl.areCoordinatesValid(null, null));
        assertTrue(ShopServiceImpl.areCoordinatesValid(-73.9855, 40.758));
        assertFalse(ShopServiceImpl.areCoordinatesValid(null, 40.758));
        assertFalse(ShopServiceImpl.areCoordinatesValid(-181.0, 40.758));
        assertFalse(ShopServiceImpl.areCoordinatesValid(-73.9855, Double.NaN));
    }

    @Test
    void popularityMapperBuildsSafeGlobalRankingSql() throws NoSuchMethodException {
        Select annotation = ShopMapper.class
                .getDeclaredMethod(
                        "selectByPlatformPopularity",
                        long.class,
                        boolean.class,
                        long.class,
                        long.class
                )
                .getAnnotation(Select.class);
        SqlSource sqlSource = new XMLLanguageDriver().createSqlSource(
                new Configuration(),
                String.join(" ", annotation.value()),
                Map.class
        );

        String descending = sqlSource.getBoundSql(Map.of(
                "typeId", 1L,
                "ascending", false,
                "offset", 0L,
                "pageSize", 10L
        )).getSql().replaceAll("\\s+", " ");
        String ascending = sqlSource.getBoundSql(Map.of(
                "typeId", 1L,
                "ascending", true,
                "offset", 10L,
                "pageSize", 10L
        )).getSql().replaceAll("\\s+", " ");

        assertTrue(descending.contains("popularity_score DESC"));
        assertTrue(ascending.contains("popularity_score ASC"));
        assertTrue(descending.contains("tb_shop_favorite"));
        assertTrue(descending.contains("tb_voucher_order"));
        assertFalse(descending.contains("${"));
    }
}
