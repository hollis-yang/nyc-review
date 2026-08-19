package com.hmdp.profile.dto;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

public record ProfileAssetsResponse(
        List<FavoriteShop> favorites,
        List<SavedItinerary> itineraries,
        List<OwnedVoucher> vouchers,
        List<FlashSaleReminder> reminders,
        List<AgentMemory> memories,
        AssetCounts counts
) {
    public record FavoriteShop(
            Long id,
            Long shopId,
            String name,
            String images,
            String address,
            String borough,
            String neighborhood,
            LocalDateTime createdAt
    ) {}

    public record SavedItinerary(
            Long id,
            String runId,
            String title,
            List<Long> shopIds,
            List<String> shopNames,
            Map<String, Object> itinerary,
            LocalDateTime updatedAt
    ) {}

    public record OwnedVoucher(
            Long orderId,
            Long voucherId,
            Long shopId,
            String title,
            String subTitle,
            String shopName,
            Integer type,
            Long payValue,
            Long actualValue,
            Integer orderStatus,
            LocalDateTime createdAt
    ) {}

    public record FlashSaleReminder(
            Long id,
            Long voucherId,
            Long shopId,
            String voucherTitle,
            String shopName,
            LocalDateTime remindAt,
            LocalDateTime saleBeginsAt,
            String status
    ) {}

    public record AgentMemory(
            Long id,
            String key,
            String value,
            String source,
            BigDecimal confidence,
            LocalDateTime updatedAt
    ) {}

    public record AssetCounts(
            int favorites,
            int itineraries,
            int vouchers,
            int reminders,
            int memories
    ) {}
}
