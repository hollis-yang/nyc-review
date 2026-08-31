package com.nycreview.service.impl;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CouponExpirationContractTest {

    @Test
    void migrationAddsAndBackfillsCouponExpiration() throws IOException {
        try (InputStream stream = getClass().getClassLoader()
                .getResourceAsStream("db/migrations/018_coupon_expiration.sql")) {
            assertNotNull(stream);
            String sql = new String(stream.readAllBytes(), StandardCharsets.UTF_8);
            assertTrue(sql.contains("expires_at"));
            assertTrue(sql.contains("INTERVAL (7 + MOD"));
            assertTrue(sql.contains("idx_voucher_order_user_expiry"));
        }
    }

    @Test
    void generatedValidityAlwaysFallsBetweenOneWeekAndSixMonths() {
        LocalDateTime acquired = LocalDateTime.of(2026, 8, 30, 12, 0);
        for (long orderId = 1; orderId <= 1_000; orderId++) {
            LocalDateTime expiration = VoucherOrderServiceImpl.expirationFor(orderId, acquired);
            assertTrue(!expiration.isBefore(acquired.plusDays(7)));
            assertTrue(!expiration.isAfter(acquired.plusDays(183)));
        }
    }
}
