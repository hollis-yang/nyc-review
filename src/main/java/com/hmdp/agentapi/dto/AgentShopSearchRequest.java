package com.hmdp.agentapi.dto;

import java.util.List;

public record AgentShopSearchRequest(
        String query,
        Long typeId,
        String neighborhood,
        Long maxAvgPriceCents,
        Double latitude,
        Double longitude,
        Integer radiusMeters,
        List<String> requiredTags,
        Integer limit
) {
}
