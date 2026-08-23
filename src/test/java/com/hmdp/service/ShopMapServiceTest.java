package com.hmdp.service;

import com.hmdp.dto.map.ShopMapAggregateRow;
import com.hmdp.dto.map.ShopMapResponse;
import com.hmdp.dto.map.ShopMapShopRow;
import com.hmdp.mapper.ShopMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ShopMapServiceTest {

    private StubShopMapper stubMapper;
    private ShopMapService service;

    @BeforeEach
    void setUp() {
        stubMapper = new StubShopMapper();
        service = new ShopMapService(stubMapper.proxy());
    }

    @Test
    void returnsMergedBoroughClustersWithStableOrderingAndFullCategoryCounts() {
        List<Long> typeIds = List.of(1L, 2L);
        stubMapper.boroughRows = List.of(
                        aggregate("Manhattan", "Manhattan", 1, 10, 40.75, -73.99,
                                -74.02, 40.70, -73.95, 40.82),
                        aggregate("Manhattan", "Manhattan", 2, 5, 40.77, -73.97,
                                -74.01, 40.71, -73.93, 40.84),
                        aggregate("Brooklyn", "Brooklyn", 1, 20, 40.65, -73.95,
                                -74.04, 40.57, -73.85, 40.74)
                );

        ShopMapResponse response = service.query(
                "-74.1", "40.4", "-73.7", "40.95", "10", "2,1,2"
        );

        assertEquals(ShopMapResponse.Mode.BOROUGH_CLUSTERS, response.mode());
        assertEquals(15, response.detailZoom());
        assertEquals("nyc-hybrid-v1", response.dataVersion());
        assertEquals(35, response.matchedCount());
        assertFalse(response.truncated());
        assertNull(response.tooDense());
        assertNull(response.minZoomRequired());
        assertEquals(2, response.items().size());

        ShopMapResponse.ClusterItem brooklyn = (ShopMapResponse.ClusterItem) response.items().get(0);
        assertEquals("BOROUGH", brooklyn.kind());
        assertEquals("Brooklyn", brooklyn.name());
        assertEquals(20, brooklyn.count());
        assertEquals(20L, brooklyn.countsByType().get(1L));

        ShopMapResponse.ClusterItem manhattan = (ShopMapResponse.ClusterItem) response.items().get(1);
        assertEquals(15, manhattan.count());
        assertEquals(10L, manhattan.countsByType().get(1L));
        assertEquals(5L, manhattan.countsByType().get(2L));
        assertEquals(-74.02, manhattan.bounds().west());
        assertEquals(40.84, manhattan.bounds().north());
        assertEquals((40.75 * 10 + 40.77 * 5) / 15, manhattan.lat(), 0.000001);
        assertEquals(List.of(-74.1, 40.4, -73.7, 40.95, typeIds),
                stubMapper.singleCall("selectBoroughMapAggregates"));
    }

    @Test
    void usesNeighborhoodClustersFromZoomElevenThroughFourteen() {
        stubMapper.neighborhoodRows = List.of(
                        aggregate("Midtown", "Manhattan", 1, 7, 40.754, -73.984,
                                -74.00, 40.74, -73.97, 40.77)
                );

        ShopMapResponse response = service.query(
                "-74.1", "40.4", "-73.7", "40.95", "14", null
        );

        assertEquals(ShopMapResponse.Mode.NEIGHBORHOOD_CLUSTERS, response.mode());
        ShopMapResponse.ClusterItem item = (ShopMapResponse.ClusterItem) response.items().get(0);
        assertEquals("NEIGHBORHOOD", item.kind());
        assertEquals("Midtown", item.name());
        assertEquals("Manhattan", item.borough());
    }

    @Test
    void fallsBackToNeighborhoodClustersWhenDetailedViewportIsTooDense() {
        List<Long> typeIds = List.of(1L, 3L);
        stubMapper.shopCount = 712L;
        stubMapper.neighborhoodRows = List.of(
                aggregate("Midtown", "Manhattan", 1, 712, 40.75, -73.98,
                        -74.00, 40.72, -73.94, 40.79)
        );
        stubMapper.shopRows = List.of(
                        shop(20, "Second", 3, 40.74, -73.96),
                        shop(10, "First", 1, 40.75, -73.98)
                );

        ShopMapResponse response = service.query(
                "-74.0", "40.7", "-73.9", "40.8", "15", "3,1"
        );

        assertEquals(ShopMapResponse.Mode.NEIGHBORHOOD_CLUSTERS, response.mode());
        assertEquals(712, response.matchedCount());
        assertFalse(response.truncated());
        assertEquals(Boolean.TRUE, response.tooDense());
        assertEquals(16, response.minZoomRequired());
        assertEquals(1, response.items().size());
        assertEquals("NEIGHBORHOOD", ((ShopMapResponse.ClusterItem) response.items().get(0)).kind());
        assertTrue(stubMapper.calls.getOrDefault("selectMapShops", List.of()).isEmpty());
        assertEquals(List.of(-74.0, 40.7, -73.9, 40.8, typeIds),
                stubMapper.singleCall("selectNeighborhoodMapAggregates"));
    }

    @Test
    void returnsStableLightweightShopMarkersWhenViewportFitsTheCap() {
        List<Long> typeIds = List.of(1L, 3L);
        stubMapper.shopCount = 2L;
        stubMapper.shopRows = List.of(
                shop(20, "Second", 3, 40.74, -73.96),
                shop(10, "First", 1, 40.75, -73.98)
        );

        ShopMapResponse response = service.query(
                "-74.0", "40.7", "-73.9", "40.8", "15", "3,1"
        );

        assertEquals(ShopMapResponse.Mode.SHOP_MARKERS, response.mode());
        assertEquals(2, response.matchedCount());
        assertFalse(response.truncated());
        assertNull(response.tooDense());
        assertEquals(2, response.items().size());
        ShopMapResponse.ShopItem first = (ShopMapResponse.ShopItem) response.items().get(0);
        assertEquals(10, first.id());
        assertEquals("SHOP", first.kind());
        assertEquals("/shop-10.jpg", first.thumbnailUrl());
        assertEquals("NYC_OPEN_DATA", first.sourceType());
        assertEquals(List.of(-74.0, 40.7, -73.9, 40.8, typeIds, ShopMapService.MAX_POINTS),
                stubMapper.singleCall("selectMapShops"));
    }

    @Test
    void keepsTheActiveDataVersionWhenViewportHasNoShops() {
        stubMapper.shopCount = 0L;
        stubMapper.shopRows = List.of();

        ShopMapResponse response = service.query(
                "-74.0", "40.7", "-73.9", "40.8", "18", null
        );

        assertEquals(0, response.matchedCount());
        assertTrue(response.items().isEmpty());
        assertEquals("nyc-hybrid-v1", response.dataVersion());
        assertFalse(response.truncated());
    }

    @Test
    void failsClearlyWhenTheP7ProjectionHasNotBeenImported() {
        stubMapper.activeDataVersion = null;

        ShopMapService.MapDataUnavailableException exception = assertThrows(
                ShopMapService.MapDataUnavailableException.class,
                () -> service.query("-74.0", "40.7", "-73.9", "40.8", "12", null)
        );

        assertEquals("Map data has not been initialized", exception.getMessage());
        assertTrue(stubMapper.calls.getOrDefault("selectNeighborhoodMapAggregates", List.of()).isEmpty());
    }

    @ParameterizedTest
    @CsvSource({
            "-73.7,40.4,-74.1,40.95,12,,west must be less than east",
            "-74.1,40.95,-73.7,40.4,12,,south must be less than north",
            "NaN,40.4,-73.7,40.95,12,,west is outside the valid coordinate range",
            "-181,40.4,-73.7,40.95,12,,west is outside the valid coordinate range",
            "-74.1,40.4,-73.7,40.95,12.5,,zoom must be an integer",
            "-74.1,40.4,-73.7,40.95,23,,zoom must be between 0 and 22",
            "-74.1,40.4,-73.7,40.95,12,1|,typeIds must be a comma-separated list of positive integers",
            "-74.1,40.4,-73.7,40.95,12,7,typeIds must contain only existing top-level category IDs from 1 to 6",
            "-74.1,40.4,-73.7,40.95,12,0,typeIds must contain only existing top-level category IDs from 1 to 6",
            "-74.1,40.4,-73.7,40.95,12,x,typeIds must be a comma-separated list of positive integers"
    })
    void rejectsMalformedParameters(
            String west,
            String south,
            String east,
            String north,
            String zoom,
            String encodedTypeIds,
            String expectedMessage
    ) {
        String typeIds = encodedTypeIds == null ? null : encodedTypeIds.replace('|', ',');

        IllegalArgumentException exception = assertThrows(
                IllegalArgumentException.class,
                () -> service.query(west, south, east, north, zoom, typeIds)
        );

        assertEquals(expectedMessage, exception.getMessage());
        assertTrue(stubMapper.calls.isEmpty());
    }

    private ShopMapAggregateRow aggregate(
            String name,
            String borough,
            long typeId,
            long count,
            double lat,
            double lng,
            double west,
            double south,
            double east,
            double north
    ) {
        return new ShopMapAggregateRow(
                "Manhattan".equals(name) || "Brooklyn".equals(name) ? name : "MN01",
                name,
                borough,
                typeId,
                count,
                lat,
                lng,
                west,
                south,
                east,
                north,
                "nyc-hybrid-v1",
                "nyc-hybrid-v1"
        );
    }

    private ShopMapShopRow shop(long id, String name, long typeId, double lat, double lng) {
        return new ShopMapShopRow(
                id,
                name,
                typeId,
                lat,
                lng,
                47,
                42L,
                "Midtown",
                "/shop-" + id + ".jpg",
                "NYC_OPEN_DATA",
                "nyc-hybrid-v1"
        );
    }

    /**
     * JDK proxy keeps this test independent from Byte Buddy/agent attachment,
     * which is intentionally unavailable in some CI and sandboxed JDKs.
     */
    private static final class StubShopMapper {
        private List<ShopMapAggregateRow> boroughRows = List.of();
        private List<ShopMapAggregateRow> neighborhoodRows = List.of();
        private List<ShopMapShopRow> shopRows = List.of();
        private long shopCount;
        private String activeDataVersion = "nyc-hybrid-v1";
        private final Map<String, List<List<Object>>> calls = new HashMap<>();

        private ShopMapper proxy() {
            return (ShopMapper) Proxy.newProxyInstance(
                    ShopMapper.class.getClassLoader(),
                    new Class<?>[]{ShopMapper.class},
                    (proxy, method, arguments) -> {
                        if (method.getDeclaringClass() == Object.class) {
                            return switch (method.getName()) {
                                case "toString" -> "StubShopMapper";
                                case "hashCode" -> System.identityHashCode(proxy);
                                case "equals" -> proxy == arguments[0];
                                default -> null;
                            };
                        }
                        List<Object> call = arguments == null ? List.of() : List.of(arguments);
                        calls.computeIfAbsent(method.getName(), ignored -> new ArrayList<>()).add(call);
                        return switch (method.getName()) {
                            case "selectActiveMapDataVersion" -> activeDataVersion;
                            case "selectBoroughMapAggregates" -> boroughRows;
                            case "selectNeighborhoodMapAggregates" -> neighborhoodRows;
                            case "countMapShops" -> shopCount;
                            case "selectMapShops" -> shopRows;
                            default -> throw new UnsupportedOperationException(method.getName());
                        };
                    }
            );
        }

        private List<Object> singleCall(String method) {
            List<List<Object>> methodCalls = calls.getOrDefault(method, List.of());
            assertEquals(1, methodCalls.size(), "Unexpected invocation count for " + method);
            return methodCalls.get(0);
        }
    }
}
