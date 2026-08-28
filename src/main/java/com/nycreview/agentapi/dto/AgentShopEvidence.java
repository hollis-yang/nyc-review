package com.nycreview.agentapi.dto;

import java.util.List;

public record AgentShopEvidence(
        Long shopId,
        List<AgentEvidenceCitation> citations
) {
}
