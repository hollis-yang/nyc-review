package com.hmdp.agentapi.dto;

import java.util.Map;

public record AgentActionExecuteRequest(
        String runId,
        String actionId,
        String actionType,
        Map<String, Object> payload
) {
}
