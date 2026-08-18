package com.hmdp.agentapi.service;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AgentShopToolServiceTest {

    @Test
    void clampsSearchAndEvidenceLimits() {
        assertEquals(5, AgentShopToolService.normalizeLimit(null));
        assertEquals(1, AgentShopToolService.normalizeLimit(-10));
        assertEquals(20, AgentShopToolService.normalizeLimit(100));
        assertEquals(20, AgentShopToolService.normalizeEvidenceLimit(null));
        assertEquals(50, AgentShopToolService.normalizeEvidenceLimit(100));
    }

    @Test
    void excerptsNeverExposeUnboundedUserContent() {
        String content = "x".repeat(800);

        assertEquals(500, AgentShopToolService.excerpt(content).length());
        assertEquals("", AgentShopToolService.excerpt(null));
    }

    @Test
    void calculatesPlausibleNycDistanceInMeters() {
        int meters = AgentShopToolService.haversineMeters(
                40.7614,
                -73.9776,
                40.7484,
                -73.9857
        );

        assertTrue(meters > 1_000);
        assertTrue(meters < 2_500);
    }
}
