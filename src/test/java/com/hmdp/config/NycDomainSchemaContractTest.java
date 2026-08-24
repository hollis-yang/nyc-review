package com.hmdp.config;

import com.hmdp.agentapi.dto.AgentShopCandidate;
import com.hmdp.entity.Shop;
import com.hmdp.entity.ShopImage;
import com.hmdp.entity.Blog;
import com.hmdp.entity.BlogComments;
import com.hmdp.entity.Voucher;
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
                "dataVersion",
                "ratingCount",
                "priceRangeText",
                "businessStatus",
                "healthGrade"
        )));
    }

    @Test
    void p11MigrationDefinesFieldObservationsAndImageResolution() throws Exception {
        try (InputStream input = getClass().getResourceAsStream("/db/p11_p2_p3_shop_enrichment.sql")) {
            assertNotNull(input);
            String migration = new String(input.readAllBytes(), StandardCharsets.UTF_8);

            assertTrue(migration.contains("CREATE TABLE IF NOT EXISTS `tb_shop_source_match`"));
            assertTrue(migration.contains("CREATE TABLE IF NOT EXISTS `tb_shop_field_observation`"));
            assertTrue(migration.contains("ROW_FORMAT=DYNAMIC"));
            assertTrue(migration.contains("MODIFY COLUMN `images` TEXT"));
            assertTrue(migration.contains("ADD COLUMN `website` TEXT"));
            assertTrue(migration.contains("COLUMN_NAME='business_status'"));
            assertTrue(migration.contains("COLUMN_NAME='rating_count'"));
            assertTrue(migration.contains("COLUMN_NAME='price_range_text'"));
            assertTrue(migration.contains("COLUMN_NAME='match_type'"));
            assertTrue(migration.contains("COLUMN_NAME='availability_status'"));
        }

        assertNotNull(Shop.class.getDeclaredField("phone"));
        assertNotNull(Shop.class.getDeclaredField("website"));
        assertNotNull(Shop.class.getDeclaredField("businessStatus"));
        assertNotNull(Shop.class.getDeclaredField("ratingCount"));
        assertNotNull(ShopImage.class.getDeclaredField("matchType"));
        assertNotNull(ShopImage.class.getDeclaredField("isPrimary"));
        assertNotNull(ShopImage.class.getDeclaredField("availabilityStatus"));
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

    @Test
    void p10MigrationDefinesIllustrativeImagesAndThreeLevelReviewThreads() throws Exception {
        try (InputStream input = getClass().getResourceAsStream("/db/p10_p8_real_content.sql")) {
            assertNotNull(input);
            String migration = new String(input.readAllBytes(), StandardCharsets.UTF_8);

            assertTrue(migration.contains("CREATE TABLE IF NOT EXISTS `tb_shop_image`"));
            assertTrue(migration.contains("MODIFY COLUMN `score` INT UNSIGNED NULL"));
            assertTrue(migration.contains("DEFAULT 'ILLUSTRATIVE'"));
            assertTrue(migration.contains("`source_page_url`"));
            assertTrue(migration.contains("`license_name`"));
            assertTrue(migration.contains("`root_id`"));
            assertTrue(migration.contains("`parent_id`"));
            assertTrue(migration.contains("`reply_to_user_id`"));
            assertTrue(migration.contains("`depth` BETWEEN 0 AND 2"));
            assertTrue(migration.contains("DEFAULT ''LEGACY''"));
            assertTrue(migration.contains("TABLE_NAME='tb_blog' AND COLUMN_NAME='source_type'"));
            assertTrue(migration.contains("TABLE_NAME='tb_blog' AND COLUMN_NAME='data_version'"));
            assertTrue(migration.contains("TABLE_NAME='tb_blog_comments' AND COLUMN_NAME='source_type'"));
            assertTrue(migration.contains("TABLE_NAME='tb_blog_comments' AND COLUMN_NAME='data_version'"));
            assertTrue(migration.contains("TABLE_NAME='tb_voucher' AND COLUMN_NAME='source_type'"));
            assertTrue(migration.contains("TABLE_NAME='tb_voucher' AND COLUMN_NAME='data_version'"));
            assertTrue(migration.contains("idx_shop_review_thread"));
            assertTrue(migration.contains("DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"));
        }

        assertNotNull(Shop.class.getDeclaredField("imageAssets"));
        assertNotNull(ShopImage.class.getDeclaredField("imageType"));
        assertNotNull(ShopImage.class.getDeclaredField("sourcePageUrl"));
        assertNotNull(Blog.class.getDeclaredField("sourceType"));
        assertNotNull(Blog.class.getDeclaredField("dataVersion"));
        assertNotNull(BlogComments.class.getDeclaredField("sourceType"));
        assertNotNull(BlogComments.class.getDeclaredField("dataVersion"));
        assertNotNull(Voucher.class.getDeclaredField("sourceType"));
        assertNotNull(Voucher.class.getDeclaredField("dataVersion"));
    }

    @Test
    void voucherListApiSelectsSeedProvenance() throws IOException {
        try (InputStream input = getClass().getResourceAsStream("/mapper/VoucherMapper.xml")) {
            assertNotNull(input);
            String mapper = new String(input.readAllBytes(), StandardCharsets.UTF_8);

            assertTrue(mapper.contains("v.`source_type`"));
            assertTrue(mapper.contains("v.`data_version`"));
        }
    }
}
