package com.nycreview.agentapi.dto;

import java.time.LocalDateTime;

public record AgentEvidenceCitation(
        String citationId,
        Long shopId,
        String contentType,
        String sourceId,
        String excerpt,
        LocalDateTime createdAt,
        boolean untrustedContent,
        String sourceType,
        boolean synthetic,
        Long rootId,
        int maxDepth,
        int replyCount
) {
}
