package com.hmdp.agentapi.service;

import com.hmdp.entity.ShopReview;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AgentShopToolServiceTest {

    @Test
    void clampsSearchAndEvidenceLimits() {
        assertEquals(5, AgentShopToolService.normalizeLimit(null));
        assertEquals(1, AgentShopToolService.normalizeLimit(-10));
        assertEquals(100, AgentShopToolService.normalizeLimit(100));
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
    void excerptsRemoveLegacyGeneratorAndThreadMarkup() {
        String content = "[Level 1 | USER | rating=4/5] [Synthetic demo review] A calm room.";

        assertEquals("A calm room.", AgentShopToolService.excerpt(content));
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

    @Test
    void rendersReviewEvidenceAsACompleteBoundedThread() {
        ShopReview grandchild = new ShopReview()
                .setId(3L)
                .setDepth(2)
                .setSourceType("USER_SUBMITTED")
                .setContent("Third-level clarification")
                .setChildren(List.of());
        ShopReview child = new ShopReview()
                .setId(2L)
                .setDepth(1)
                .setSourceType("SYNTHETIC")
                .setContent("Second-level reply")
                .setChildren(List.of(grandchild));
        ShopReview root = new ShopReview()
                .setId(1L)
                .setRootId(1L)
                .setDepth(0)
                .setSourceType("SYNTHETIC")
                .setContent("Top-level synthetic review")
                .setChildren(List.of(child));

        String evidence = AgentShopToolService.reviewThreadText(root);

        assertTrue(evidence.startsWith("Top-level synthetic review"));
        assertTrue(evidence.contains("Second-level reply"));
        assertTrue(evidence.contains("Third-level clarification"));
        assertFalse(evidence.contains("[root]"));
        assertFalse(evidence.contains("reply depth="));
        assertEquals(2, AgentShopToolService.maxThreadDepth(root));
        assertEquals(2, AgentShopToolService.threadReplyCount(root));
        assertEquals("MIXED", AgentShopToolService.threadSourceType(root));
        assertFalse(AgentShopToolService.threadIsSynthetic(root));
    }
}
