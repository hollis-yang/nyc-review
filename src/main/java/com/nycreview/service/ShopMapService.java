package com.nycreview.service;

import com.nycreview.dto.map.ShopMapAggregateRow;
import com.nycreview.dto.map.ShopMapResponse;
import com.nycreview.dto.map.ShopMapShopRow;
import com.nycreview.mapper.ShopMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

import static com.nycreview.dto.map.ShopMapResponse.Mode.BOROUGH_CLUSTERS;
import static com.nycreview.dto.map.ShopMapResponse.Mode.NEIGHBORHOOD_CLUSTERS;
import static com.nycreview.dto.map.ShopMapResponse.Mode.SHOP_MARKERS;

@Service
@RequiredArgsConstructor
public class ShopMapService {

    public static final int DETAIL_ZOOM = 15;
    public static final int MAX_POINTS = 500;
    private static final int BOROUGH_MAX_ZOOM = 10;
    private static final int MAX_ZOOM = 22;
    private static final int MAX_TOP_LEVEL_TYPE_ID = 6;

    private final ShopMapper shopMapper;

    public ShopMapResponse query(
            String westValue,
            String southValue,
            String eastValue,
            String northValue,
            String zoomValue,
            String typeIdsValue
    ) {
        MapQuery query = parseQuery(westValue, southValue, eastValue, northValue, zoomValue, typeIdsValue);
        String activeDataVersion = shopMapper.selectActiveMapDataVersion();
        if (activeDataVersion == null || activeDataVersion.isBlank()) {
            throw new MapDataUnavailableException("Map data has not been initialized");
        }
        if (query.zoom() <= BOROUGH_MAX_ZOOM) {
            return clusterResponse(query, BOROUGH_CLUSTERS, null, false, activeDataVersion);
        }
        if (query.zoom() < DETAIL_ZOOM) {
            return clusterResponse(query, NEIGHBORHOOD_CLUSTERS, null, false, activeDataVersion);
        }
        return shopResponse(query, activeDataVersion);
    }

    private ShopMapResponse clusterResponse(
            MapQuery query,
            ShopMapResponse.Mode mode,
            Long matchedCountOverride,
            boolean forceTooDense,
            String activeDataVersion
    ) {
        List<ShopMapAggregateRow> rows = mode == BOROUGH_CLUSTERS
                ? shopMapper.selectBoroughMapAggregates(
                        query.west(), query.south(), query.east(), query.north(), query.typeIds())
                : shopMapper.selectNeighborhoodMapAggregates(
                        query.west(), query.south(), query.east(), query.north(), query.typeIds());

        String kind = mode == BOROUGH_CLUSTERS ? "BOROUGH" : "NEIGHBORHOOD";
        Map<String, ClusterAccumulator> accumulators = new LinkedHashMap<>();
        Set<String> dataVersions = new LinkedHashSet<>();
        addVersion(dataVersions, activeDataVersion);
        long matchedCount = 0;
        for (ShopMapAggregateRow row : rows) {
            long count = requiredPositiveCount(row.getCount());
            String borough = requiredText(row.getBorough(), "borough");
            String name = requiredText(row.getName(), mode == BOROUGH_CLUSTERS ? "borough" : "neighborhood");
            String sourceGroupId = requiredText(row.getGroupId(), "cluster ID");
            long typeId = requiredPositiveTypeId(row.getTypeId());
            matchedCount += count;
            addVersion(dataVersions, row.getMinDataVersion());
            addVersion(dataVersions, row.getMaxDataVersion());

            String groupKey = kind + '\u0000' + sourceGroupId;
            accumulators.computeIfAbsent(
                            groupKey,
                            ignored -> new ClusterAccumulator(
                                    kind,
                                    stableClusterId(kind, sourceGroupId),
                                    name,
                                    borough
                            )
                    )
                    .add(row, typeId, count);
        }

        List<ShopMapResponse.ClusterItem> allItems = accumulators.values().stream()
                .map(accumulator -> accumulator.toItem(query))
                .sorted(Comparator.comparingLong(ShopMapResponse.ClusterItem::count).reversed()
                        .thenComparing(ShopMapResponse.ClusterItem::borough, String.CASE_INSENSITIVE_ORDER)
                        .thenComparing(ShopMapResponse.ClusterItem::name, String.CASE_INSENSITIVE_ORDER)
                        .thenComparing(ShopMapResponse.ClusterItem::id))
                .toList();
        boolean truncated = allItems.size() > MAX_POINTS;
        boolean tooDense = forceTooDense || truncated;
        List<ShopMapResponse.Item> items = new ArrayList<>(
                allItems.subList(0, Math.min(MAX_POINTS, allItems.size()))
        );
        return new ShopMapResponse(
                mode,
                query.zoom(),
                DETAIL_ZOOM,
                resolveDataVersion(dataVersions),
                matchedCountOverride == null ? matchedCount : matchedCountOverride,
                truncated,
                tooDense ? Boolean.TRUE : null,
                tooDense ? nextZoom(query.zoom()) : null,
                List.copyOf(items)
        );
    }

    private ShopMapResponse shopResponse(MapQuery query, String activeDataVersion) {
        long matchedCount = shopMapper.countMapShops(
                query.west(), query.south(), query.east(), query.north(), query.typeIds());
        if (matchedCount > MAX_POINTS) {
            return clusterResponse(query, NEIGHBORHOOD_CLUSTERS, matchedCount, true, activeDataVersion);
        }
        List<ShopMapShopRow> rows = shopMapper.selectMapShops(
                query.west(), query.south(), query.east(), query.north(), query.typeIds(), MAX_POINTS);
        Set<String> dataVersions = new LinkedHashSet<>();
        addVersion(dataVersions, activeDataVersion);
        List<ShopMapResponse.Item> items = rows.stream()
                .sorted(Comparator.comparingLong(ShopMapShopRow::getId))
                .limit(MAX_POINTS)
                .map(row -> {
                    addVersion(dataVersions, row.getDataVersion());
                    return toShopItem(row);
                })
                .map(ShopMapResponse.Item.class::cast)
                .toList();
        boolean truncated = matchedCount > MAX_POINTS;
        return new ShopMapResponse(
                SHOP_MARKERS,
                query.zoom(),
                DETAIL_ZOOM,
                resolveDataVersion(dataVersions),
                matchedCount,
                truncated,
                truncated ? Boolean.TRUE : null,
                truncated ? nextZoom(query.zoom()) : null,
                items
        );
    }

    private ShopMapResponse.ShopItem toShopItem(ShopMapShopRow row) {
        if (row.getId() == null || row.getId() <= 0) {
            throw new IllegalStateException("Map query returned an invalid shop ID");
        }
        return new ShopMapResponse.ShopItem(
                "SHOP",
                row.getId(),
                requiredText(row.getName(), "shop name"),
                requiredPositiveTypeId(row.getTypeId()),
                requiredCoordinate(row.getLat(), "shop latitude"),
                requiredCoordinate(row.getLng(), "shop longitude"),
                row.getScore(),
                row.getAvgPrice(),
                row.getNeighborhood(),
                row.getThumbnailUrl(),
                row.getSourceType(),
                Boolean.TRUE.equals(row.getIllustrativeImage()),
                Boolean.TRUE.equals(row.getSyntheticScore())
        );
    }

    private static MapQuery parseQuery(
            String westValue,
            String southValue,
            String eastValue,
            String northValue,
            String zoomValue,
            String typeIdsValue
    ) {
        double west = parseCoordinate("west", westValue, -180, 180);
        double south = parseCoordinate("south", southValue, -90, 90);
        double east = parseCoordinate("east", eastValue, -180, 180);
        double north = parseCoordinate("north", northValue, -90, 90);
        if (west >= east) {
            throw new IllegalArgumentException("west must be less than east");
        }
        if (south >= north) {
            throw new IllegalArgumentException("south must be less than north");
        }
        int zoom = parseZoom(zoomValue);
        return new MapQuery(west, south, east, north, zoom, parseTypeIds(typeIdsValue));
    }

    private static double parseCoordinate(String name, String value, double minimum, double maximum) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(name + " is required");
        }
        final double parsed;
        try {
            parsed = Double.parseDouble(value.trim());
        } catch (NumberFormatException exception) {
            throw new IllegalArgumentException(name + " must be a number");
        }
        if (!Double.isFinite(parsed) || parsed < minimum || parsed > maximum) {
            throw new IllegalArgumentException(name + " is outside the valid coordinate range");
        }
        return parsed;
    }

    private static int parseZoom(String value) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("zoom is required");
        }
        final int zoom;
        try {
            zoom = Integer.parseInt(value.trim());
        } catch (NumberFormatException exception) {
            throw new IllegalArgumentException("zoom must be an integer");
        }
        if (zoom < 0 || zoom > MAX_ZOOM) {
            throw new IllegalArgumentException("zoom must be between 0 and " + MAX_ZOOM);
        }
        return zoom;
    }

    private static List<Long> parseTypeIds(String value) {
        if (value == null || value.isBlank()) {
            return List.of();
        }
        String[] tokens = value.split(",", -1);
        Set<Long> ids = new LinkedHashSet<>();
        for (String token : tokens) {
            if (token.isBlank()) {
                throw new IllegalArgumentException("typeIds must be a comma-separated list of positive integers");
            }
            final long id;
            try {
                id = Long.parseLong(token.trim());
            } catch (NumberFormatException exception) {
                throw new IllegalArgumentException("typeIds must be a comma-separated list of positive integers");
            }
            if (id <= 0 || id > MAX_TOP_LEVEL_TYPE_ID) {
                throw new IllegalArgumentException(
                        "typeIds must contain only existing top-level category IDs from 1 to "
                                + MAX_TOP_LEVEL_TYPE_ID
                );
            }
            ids.add(id);
        }
        return ids.stream().sorted().toList();
    }

    private static int nextZoom(int zoom) {
        return Math.min(MAX_ZOOM, zoom + 1);
    }

    private static void addVersion(Set<String> versions, String dataVersion) {
        if (dataVersion != null && !dataVersion.isBlank()) {
            versions.add(dataVersion);
        }
    }

    private static String resolveDataVersion(Set<String> versions) {
        if (versions.isEmpty()) {
            return null;
        }
        if (versions.size() == 1) {
            return versions.iterator().next();
        }
        return "mixed";
    }

    private static String requiredText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new IllegalStateException("Map query returned an invalid " + field);
        }
        return value;
    }

    private static long requiredPositiveTypeId(Long value) {
        if (value == null || value <= 0) {
            throw new IllegalStateException("Map query returned an invalid shop type");
        }
        return value;
    }

    private static long requiredPositiveCount(Long value) {
        if (value == null || value <= 0) {
            throw new IllegalStateException("Map query returned an invalid cluster count");
        }
        return value;
    }

    private static double requiredCoordinate(Double value, String field) {
        if (value == null || !Double.isFinite(value)) {
            throw new IllegalStateException("Map query returned an invalid " + field);
        }
        return value;
    }

    private static String stableClusterId(String kind, String sourceGroupId) {
        if ("NEIGHBORHOOD".equals(kind)) {
            return sourceGroupId;
        }
        return kind.toLowerCase(Locale.ROOT) + ':' + sourceGroupId.toLowerCase(Locale.ROOT);
    }

    private record MapQuery(
            double west,
            double south,
            double east,
            double north,
            int zoom,
            List<Long> typeIds
    ) {
    }

    public static final class MapDataUnavailableException extends RuntimeException {
        public MapDataUnavailableException(String message) {
            super(message);
        }
    }

    private static final class ClusterAccumulator {
        private final String kind;
        private final String id;
        private final String name;
        private final String borough;
        private final Map<Long, Long> countsByType = new TreeMap<>();
        private long count;
        private double weightedLat;
        private double weightedLng;
        private double west = Double.POSITIVE_INFINITY;
        private double south = Double.POSITIVE_INFINITY;
        private double east = Double.NEGATIVE_INFINITY;
        private double north = Double.NEGATIVE_INFINITY;

        private ClusterAccumulator(String kind, String id, String name, String borough) {
            this.kind = kind;
            this.id = id;
            this.name = name;
            this.borough = borough;
        }

        private ClusterAccumulator add(ShopMapAggregateRow row, long typeId, long rowCount) {
            double rowLat = requiredCoordinate(row.getLat(), "cluster latitude");
            double rowLng = requiredCoordinate(row.getLng(), "cluster longitude");
            count += rowCount;
            weightedLat += rowLat * rowCount;
            weightedLng += rowLng * rowCount;
            west = Math.min(west, requiredCoordinate(row.getWest(), "cluster west bound"));
            south = Math.min(south, requiredCoordinate(row.getSouth(), "cluster south bound"));
            east = Math.max(east, requiredCoordinate(row.getEast(), "cluster east bound"));
            north = Math.max(north, requiredCoordinate(row.getNorth(), "cluster north bound"));
            countsByType.merge(typeId, rowCount, Long::sum);
            return this;
        }

        private ShopMapResponse.ClusterItem toItem(MapQuery query) {
            return new ShopMapResponse.ClusterItem(
                    kind,
                    id,
                    name,
                    borough,
                    clamp(weightedLat / count, query.south(), query.north()),
                    clamp(weightedLng / count, query.west(), query.east()),
                    count,
                    new ShopMapResponse.Bounds(west, south, east, north),
                    Collections.unmodifiableMap(new TreeMap<>(countsByType))
            );
        }

        private static double clamp(double value, double minimum, double maximum) {
            return Math.max(minimum, Math.min(maximum, value));
        }
    }
}
