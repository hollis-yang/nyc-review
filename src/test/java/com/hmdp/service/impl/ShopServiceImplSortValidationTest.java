package com.hmdp.service.impl;

import com.hmdp.dto.Result;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ShopServiceImplSortValidationTest {

    @Test
    void shouldAllowOnlySupportedSortColumns() {
        assertEquals("score", ShopServiceImpl.resolveSortColumn("score"));
        assertEquals("comments", ShopServiceImpl.resolveSortColumn("comments"));
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
    }
}
