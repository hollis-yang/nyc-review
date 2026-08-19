package com.hmdp.agentapi.controller;

import com.hmdp.agentapi.dto.AgentShopCandidate;
import com.hmdp.agentapi.dto.AgentShopEvidence;
import com.hmdp.agentapi.dto.AgentShopSearchRequest;
import com.hmdp.agentapi.dto.AgentToolResponse;
import com.hmdp.agentapi.service.AgentShopToolService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/internal/agent/tools/shops")
public class AgentShopToolController {

    private final AgentShopToolService toolService;

    public AgentShopToolController(AgentShopToolService toolService) {
        this.toolService = toolService;
    }

    @PostMapping("/search")
    public AgentToolResponse<List<AgentShopCandidate>> search(
            @RequestBody(required = false) AgentShopSearchRequest request
    ) {
        String traceId = UUID.randomUUID().toString();
        AgentShopToolService.SearchResult result = toolService.search(request);
        return AgentToolResponse.ok("search_shops", traceId, result.candidates(), result.warnings());
    }

    @GetMapping("/{shopId}/evidence")
    public AgentToolResponse<AgentShopEvidence> evidence(
            @PathVariable Long shopId,
            @RequestParam(defaultValue = "20") Integer limit
    ) {
        String traceId = UUID.randomUUID().toString();
        return AgentToolResponse.ok(
                "get_shop_evidence",
                traceId,
                toolService.evidence(shopId, limit)
        );
    }

    @GetMapping("/{shopId}")
    public AgentToolResponse<AgentShopCandidate> detail(@PathVariable Long shopId) {
        String traceId = UUID.randomUUID().toString();
        AgentShopCandidate candidate = toolService.detail(shopId);
        if (candidate == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Shop not found");
        }
        return AgentToolResponse.ok("get_shop_detail", traceId, candidate);
    }
}
