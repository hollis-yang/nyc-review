package com.hmdp.agentapi.dto;

import java.time.LocalDateTime;

public record AgentEvidenceCitation(
        String citationId,
        Long shopId,
        String contentType,
        String sourceId,
        String excerpt,
        LocalDateTime createdAt,
        boolean untrustedContent
) {
}
