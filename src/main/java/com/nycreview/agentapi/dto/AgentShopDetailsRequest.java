package com.nycreview.agentapi.dto;

import java.util.List;

public record AgentShopDetailsRequest(
        List<Long> shopIds
) {
    public static final int MAX_SHOP_IDS = 100;

    public AgentShopDetailsRequest {
        if (shopIds != null) {
            if (shopIds.size() > MAX_SHOP_IDS) {
                throw new IllegalArgumentException("shopIds cannot contain more than 100 entries");
            }
            if (shopIds.stream().anyMatch(shopId -> shopId == null || shopId <= 0)) {
                throw new IllegalArgumentException("shopIds must contain only positive IDs");
            }
            shopIds = List.copyOf(shopIds);
        }
    }
}
