package com.hmdp.agentapi.dto;

import java.util.List;

public record AgentShopCandidate(
        Long shopId,
        String name,
        Long typeId,
        String category,
        String neighborhood,
        String address,
        Double latitude,
        Double longitude,
        Long avgPriceCents,
        Double score,
        Integer comments,
        Integer distanceMeters,
        List<String> tags
) {
}
