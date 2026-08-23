package com.hmdp.config;

import com.hmdp.agentapi.dto.AgentShopCandidate;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class NycDomainSchemaContractTest {

    @Test
    void baseFixturePinsUtcWhileImportingDstSensitiveTimestamps() throws IOException {
        try (InputStream input = getClass().getResourceAsStream("/db/hmdp_new.sql")) {
            assertNotNull(input);
            String fixture = new String(input.readAllBytes(), StandardCharsets.UTF_8);

            int pinUtc = fixture.indexOf("SET SESSION time_zone = '+00:00'");
            int dstGapTimestamp = fixture.indexOf("2026-03-08 02:00:00");
            int restoreTimeZone = fixture.lastIndexOf("SET SESSION time_zone = @HMDP_OLD_TIME_ZONE");
            assertTrue(pinUtc >= 0 && pinUtc < dstGapTimestamp);
            assertTrue(restoreTimeZone > dstGapTimestamp);
        }
    }

    @Test
    void p4MigrationDefinesNycEnrichmentAndDatasetIdentityTables() throws IOException {
        try (InputStream input = getClass().getResourceAsStream("/db/p4_nyc_domain.sql")) {
            assertNotNull(input);
            String migration = new String(input.readAllBytes(), StandardCharsets.UTF_8);

            assertTrue(migration.contains("CREATE TABLE IF NOT EXISTS tb_shop_subcategory"));
            assertTrue(migration.contains("CREATE TABLE IF NOT EXISTS tb_shop_tag"));
            assertTrue(migration.contains("CREATE TABLE IF NOT EXISTS tb_shop_business_hours"));
            assertTrue(migration.contains("CREATE TABLE IF NOT EXISTS tb_data_import"));
            assertTrue(migration.contains("dataset_sha256"));
            assertTrue(migration.contains("data_version"));
        }
    }

    @Test
    void agentCandidateExposesNycEnrichmentAndDataVersion() {
        Set<String> components = Arrays.stream(AgentShopCandidate.class.getRecordComponents())
                .map(component -> component.getName())
                .collect(Collectors.toSet());

        assertTrue(components.containsAll(Set.of(
                "shopId",
                "subcategory",
                "borough",
                "tags",
                "businessHours",
                "sourceType",
                "externalId",
                "sourceName",
                "sourceUrl",
                "sourceFetchedAt",
                "syntheticFields",
                "dataVersion"
        )));
    }

    @Test
    void p8MigrationDefinesShopProvenanceContract() throws IOException {
        try (InputStream input = getClass().getResourceAsStream("/db/p8_p6_data_provenance.sql")) {
            assertNotNull(input);
            String migration = new String(input.readAllBytes(), StandardCharsets.UTF_8);

            assertTrue(migration.contains("external_id"));
            assertTrue(migration.contains("source_name"));
            assertTrue(migration.contains("source_url"));
            assertTrue(migration.contains("source_fetched_at"));
            assertTrue(migration.contains("synthetic_fields JSON"));
            assertTrue(migration.contains("uk_shop_source_external"));
        }
    }

    @Test
    void p9MigrationPinsAndRepairsLegacyCompatibleCollation() throws IOException {
        try (InputStream input = getClass().getResourceAsStream("/db/p9_p7_map_geospatial.sql")) {
            assertNotNull(input);
            String migration = new String(input.readAllBytes(), StandardCharsets.UTF_8);

            String tableCollation = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;";
            String repairCollation =
                    "CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci";
            assertEquals(6, migration.split(tableCollation, -1).length - 1);
            assertEquals(6, migration.split(repairCollation, -1).length - 1);
            assertTrue(migration.contains("COLLATION_NAME <> 'utf8mb4_general_ci'"));
        }
    }
}
