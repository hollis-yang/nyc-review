package com.nycreview.agentapi.dto;

import java.util.List;

public record AgentToolResponse<T>(
        T data,
        AgentToolMetadata metadata,
        List<String> warnings
) {
    public static <T> AgentToolResponse<T> ok(String tool, String traceId, T data) {
        return new AgentToolResponse<>(
                data,
                new AgentToolMetadata(tool, traceId, java.time.Instant.now(), "nyc-review"),
                List.of()
        );
    }

    public static <T> AgentToolResponse<T> ok(
            String tool,
            String traceId,
            T data,
            List<String> warnings
    ) {
        return new AgentToolResponse<>(
                data,
                new AgentToolMetadata(tool, traceId, java.time.Instant.now(), "nyc-review"),
                List.copyOf(warnings)
        );
    }
}
