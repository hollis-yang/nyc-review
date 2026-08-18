package com.hmdp.agentapi.service;

import com.hmdp.agentapi.dto.AgentActionExecuteRequest;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class AgentActionExecutionServiceTest {

    @Test
    void acceptsOnlyWhitelistedConfirmedActionTypes() {
        assertNull(AgentActionExecutionService.validate(new AgentActionExecuteRequest(
                "run-1",
                "action-1",
                "favorite_shop",
                Map.of("shopId", 1)
        )));

        assertEquals(
                "Action type is not allowed",
                AgentActionExecutionService.validate(new AgentActionExecuteRequest(
                        "run-1",
                        "action-2",
                        "seckill_voucher",
                        Map.of("voucherId", 7)
                ))
        );
    }

    @Test
    void rejectsMissingPayloadBeforeAnyDatabaseWrite() {
        assertEquals(
                "Action payload is required",
                AgentActionExecutionService.validate(new AgentActionExecuteRequest(
                        "run-1",
                        "action-1",
                        "save_itinerary",
                        null
                ))
        );
    }
}
