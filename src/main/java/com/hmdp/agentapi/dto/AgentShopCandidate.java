package com.hmdp.agentapi.dto;

import java.util.List;

public record AgentShopCandidate(
        Long shopId,
        String name,
        Long typeId,
        String category,
        Long subcategoryId,
        String subcategory,
        String borough,
        String neighborhood,
        String address,
        String description,
        Double latitude,
        Double longitude,
        Long avgPriceCents,
        Integer priceLevel,
        Double score,
        Integer comments,
        Integer distanceMeters,
        String timezone,
        String dataVersion,
        List<String> tags,
        List<AgentBusinessHours> businessHours
) {
}
