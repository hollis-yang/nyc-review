package com.hmdp.dto.map;

import java.util.List;
import java.util.Map;

/**
 * Lightweight, viewport-scoped map response. Map clients must use {@code items}
 * rather than the full shop entity endpoint so the payload remains bounded as
 * the dataset grows.
 */
public record ShopMapResponse(
        Mode mode,
        int zoom,
        int detailZoom,
        String dataVersion,
        long matchedCount,
        boolean truncated,
        Boolean tooDense,
        Integer minZoomRequired,
        List<Item> items
) {

    public enum Mode {
        BOROUGH_CLUSTERS,
        NEIGHBORHOOD_CLUSTERS,
        SHOP_MARKERS
    }

    public sealed interface Item permits ClusterItem, ShopItem {
    }

    public record Bounds(
            double west,
            double south,
            double east,
            double north
    ) {
    }

    public record ClusterItem(
            String kind,
            String id,
            String name,
            String borough,
            double lat,
            double lng,
            long count,
            Bounds bounds,
            Map<Long, Long> countsByType
    ) implements Item {
    }

    public record ShopItem(
            String kind,
            long id,
            String name,
            long typeId,
            double lat,
            double lng,
            Integer score,
            Long avgPrice,
            String neighborhood,
            String thumbnailUrl,
            String sourceType
    ) implements Item {
    }
}
