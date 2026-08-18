package com.hmdp.agentapi.dto;

import java.time.Instant;

public record AgentToolMetadata(
        String tool,
        String traceId,
        Instant fetchedAt,
        String source
) {
}
