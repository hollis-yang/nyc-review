package com.hmdp.agentapi.dto;

import java.util.List;

public record AgentShopEvidence(
        Long shopId,
        List<AgentEvidenceCitation> citations
) {
}
