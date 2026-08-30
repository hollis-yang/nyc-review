import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from collections import Counter
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name("generate.py")
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("nyc_mock_generator", MODULE_PATH)
GENERATOR = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = GENERATOR
SPEC.loader.exec_module(GENERATOR)

NYC_OPEN_DATA_PATH = MODULE_PATH.with_name("nyc_open_data.py")
NYC_SPEC = importlib.util.spec_from_file_location("nyc_open_data_test", NYC_OPEN_DATA_PATH)
NYC_OPEN_DATA = importlib.util.module_from_spec(NYC_SPEC)
assert NYC_SPEC and NYC_SPEC.loader
sys.modules[NYC_SPEC.name] = NYC_OPEN_DATA
NYC_SPEC.loader.exec_module(NYC_OPEN_DATA)
NYC_NTA_PATH = MODULE_PATH.with_name("nyc_nta.py")
NYC_NTA_SPEC = importlib.util.spec_from_file_location("nyc_nta", NYC_NTA_PATH)
NYC_NTA = importlib.util.module_from_spec(NYC_NTA_SPEC)
assert NYC_NTA_SPEC and NYC_NTA_SPEC.loader
sys.modules[NYC_NTA_SPEC.name] = NYC_NTA
NYC_NTA_SPEC.loader.exec_module(NYC_NTA)
P7_IMPORT_PATH = MODULE_PATH.with_name("build_neighborhood_import.py")
P7_IMPORT_SPEC = importlib.util.spec_from_file_location(
    "build_neighborhood_import_test", P7_IMPORT_PATH
)
P7_IMPORT = importlib.util.module_from_spec(P7_IMPORT_SPEC)
assert P7_IMPORT_SPEC and P7_IMPORT_SPEC.loader
sys.modules[P7_IMPORT_SPEC.name] = P7_IMPORT
P7_IMPORT_SPEC.loader.exec_module(P7_IMPORT)
OSM_PATH = MODULE_PATH.with_name("osm_places.py")
OSM_SPEC = importlib.util.spec_from_file_location("osm_places_test", OSM_PATH)
OSM_PLACES = importlib.util.module_from_spec(OSM_SPEC)
assert OSM_SPEC and OSM_SPEC.loader
sys.modules[OSM_SPEC.name] = OSM_PLACES
OSM_SPEC.loader.exec_module(OSM_PLACES)
VALIDATOR_PATH = MODULE_PATH.with_name("validate_dataset.py")
VALIDATOR_SPEC = importlib.util.spec_from_file_location("validate_dataset_test", VALIDATOR_PATH)
VALIDATOR = importlib.util.module_from_spec(VALIDATOR_SPEC)
assert VALIDATOR_SPEC and VALIDATOR_SPEC.loader
sys.modules[VALIDATOR_SPEC.name] = VALIDATOR
VALIDATOR_SPEC.loader.exec_module(VALIDATOR)
VOUCHER_OVERLAY_PATH = MODULE_PATH.with_name("build_voucher_overlay.py")
VOUCHER_OVERLAY_SPEC = importlib.util.spec_from_file_location(
    "build_voucher_overlay_test", VOUCHER_OVERLAY_PATH
)
VOUCHER_OVERLAY = importlib.util.module_from_spec(VOUCHER_OVERLAY_SPEC)
assert VOUCHER_OVERLAY_SPEC and VOUCHER_OVERLAY_SPEC.loader
sys.modules[VOUCHER_OVERLAY_SPEC.name] = VOUCHER_OVERLAY
VOUCHER_OVERLAY_SPEC.loader.exec_module(VOUCHER_OVERLAY)
USER_SOCIAL_OVERLAY_PATH = MODULE_PATH.with_name("build_user_social_overlay.py")
USER_SOCIAL_OVERLAY_SPEC = importlib.util.spec_from_file_location(
    "build_user_social_overlay_test", USER_SOCIAL_OVERLAY_PATH
)
USER_SOCIAL_OVERLAY = importlib.util.module_from_spec(USER_SOCIAL_OVERLAY_SPEC)
assert USER_SOCIAL_OVERLAY_SPEC and USER_SOCIAL_OVERLAY_SPEC.loader
sys.modules[USER_SOCIAL_OVERLAY_SPEC.name] = USER_SOCIAL_OVERLAY
USER_SOCIAL_OVERLAY_SPEC.loader.exec_module(USER_SOCIAL_OVERLAY)
SNAPSHOT_PATH = MODULE_PATH.parents[1] / ".." / "data" / "sources" / "nyc-open-data-restaurants-2026-08-23.json"
OSM_FIXTURE_PATH = MODULE_PATH.with_name("fixtures") / "osm_places_fixture.json"
IMAGE_CATALOG_PATH = MODULE_PATH.parents[1] / ".." / "data" / "sources" / "wikimedia-illustrative-images-v1.json"


def parse_resp_commands(payload: bytes) -> list[list[bytes]]:
    commands: list[list[bytes]] = []
    offset = 0
    while offset < len(payload):
        assert payload[offset : offset + 1] == b"*"
        line_end = payload.index(b"\r\n", offset)
        argument_count = int(payload[offset + 1 : line_end])
        offset = line_end + 2
        arguments: list[bytes] = []
        for _ in range(argument_count):
            assert payload[offset : offset + 1] == b"$"
            line_end = payload.index(b"\r\n", offset)
            length = int(payload[offset + 1 : line_end])
            offset = line_end + 2
            arguments.append(payload[offset : offset + length])
            offset += length
            assert payload[offset : offset + 2] == b"\r\n"
            offset += 2
        commands.append(arguments)
    return commands


class GenerateDatasetTest(unittest.TestCase):
    def test_osm_opening_hours_parser_covers_split_closed_and_overnight_rules(self):
        hours = GENERATOR.parse_osm_opening_hours(
            "Mo-Fr 11:30-15:00,17:00-22:00; Sa 17:00-01:00; Su off",
            42,
        )

        self.assertEqual(7, len(hours))
        self.assertEqual("11:30", hours[0]["openTime"])
        self.assertEqual("22:00", hours[0]["closeTime"])
        self.assertTrue(hours[5]["closesNextDay"])
        self.assertEqual("01:00", hours[5]["closeTime"])
        self.assertTrue(hours[6]["closed"])

    def test_osm_opening_hours_parser_supports_all_day_records(self):
        hours = GENERATOR.parse_osm_opening_hours("24/7", 7)

        self.assertEqual(7, len(hours))
        self.assertTrue(all(item["closesNextDay"] for item in hours))

    def test_small_profile_is_deterministic_and_referentially_valid(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_manifest = GENERATOR.generate_dataset("small", 12345, Path(first))
            second_manifest = GENERATOR.generate_dataset("small", 12345, Path(second))

            self.assertEqual(first_manifest["counts"], second_manifest["counts"])
            self.assertEqual(first_manifest["files"], second_manifest["files"])

            shops = json.loads((Path(first) / "shops.json").read_text())
            users = json.loads((Path(first) / "users.json").read_text())
            reviews = json.loads((Path(first) / "shop_reviews.json").read_text())
            blogs = json.loads((Path(first) / "blogs.json").read_text())
            blog_comments = json.loads((Path(first) / "blog_comments.json").read_text())
            follows = json.loads((Path(first) / "follows.json").read_text())
            blog_likes = json.loads((Path(first) / "blog_likes.json").read_text())
            vouchers = json.loads((Path(first) / "vouchers.json").read_text())
            seckill = json.loads((Path(first) / "seckill_vouchers.json").read_text())
            import_manifest = json.loads((Path(first) / "import_manifest.json").read_text())
            mysql_sql = (Path(first) / "mysql_import.sql").read_text()
            redis_resp = (Path(first) / "redis_seed.resp").read_bytes()

            shop_ids = {shop["id"] for shop in shops}
            user_ids = {user["id"] for user in users}
            voucher_ids = {voucher["id"] for voucher in vouchers}
            voucher_by_id = {voucher["id"]: voucher for voucher in vouchers}
            standard_shop_ids = {
                voucher["shopId"] for voucher in vouchers if voucher["type"] == 0
            }
            seckill_shop_ids = {
                voucher_by_id[item["voucherId"]]["shopId"] for item in seckill
            }
            blog_ids = {blog["id"] for blog in blogs}
            blog_by_id = {blog["id"]: blog for blog in blogs}
            comment_ids = {comment["id"] for comment in blog_comments}

            self.assertEqual(36, len(shops))
            self.assertTrue(all(review["shopId"] in shop_ids for review in reviews))
            self.assertTrue(all(review["userId"] in user_ids for review in reviews))
            self.assertTrue(all(voucher["shopId"] in shop_ids for voucher in vouchers))
            self.assertTrue(all(item["voucherId"] in voucher_ids for item in seckill))
            self.assertTrue(all(item["manualOnly"] for item in seckill))
            self.assertEqual(GENERATOR.PROFILES["small"].standard_vouchers, len(standard_shop_ids))
            self.assertEqual(GENERATOR.PROFILES["small"].seckill_vouchers, len(seckill_shop_ids))
            self.assertFalse(standard_shop_ids & seckill_shop_ids)
            self.assertTrue(all(comment["blogId"] in blog_ids for comment in blog_comments))
            self.assertTrue(
                all(
                    comment["parentId"] == 0 or comment["parentId"] in comment_ids
                    for comment in blog_comments
                )
            )
            self.assertTrue(any(comment["parentId"] > 0 for comment in blog_comments))
            self.assertEqual(
                len(reviews),
                sum(shop["comments"] for shop in shops),
            )
            self.assertEqual(
                len(blog_comments),
                sum(blog["comments"] for blog in blogs),
            )
            self.assertTrue(all(shop["x"] < 0 for shop in shops))
            self.assertTrue(all(shop["sourceType"] == "MOCK" for shop in shops))
            self.assertTrue(all(shop["externalId"].startswith("mock:") for shop in shops))
            self.assertTrue(all(shop["syntheticFields"] for shop in shops))
            self.assertGreaterEqual(len({user["icon"] for user in users}), 8)
            self.assertGreaterEqual(len({user["city"] for user in users}), 10)
            self.assertGreaterEqual(len({user["introduce"] for user in users}), 12)
            outgoing = Counter(item["userId"] for item in follows)
            incoming = Counter(item["followUserId"] for item in follows)
            self.assertTrue(all(user["followee"] == outgoing[user["id"]] for user in users))
            self.assertTrue(all(user["fans"] == incoming[user["id"]] for user in users))
            follow_pairs = {(item["userId"], item["followUserId"]) for item in follows}
            self.assertTrue(any((target, source) in follow_pairs for source, target in follow_pairs))
            self.assertTrue(blog_likes)
            self.assertTrue(all(item["blogId"] in blog_ids for item in blog_likes))
            self.assertTrue(all(item["userId"] in user_ids for item in blog_likes))
            self.assertTrue(all(
                blog_by_id[item["blogId"]]["userId"] != item["userId"]
                for item in blog_likes
            ))

            expected_shop_ids = sorted(shop_ids)
            expected_shop_ids_sha = hashlib.sha256(
                json.dumps(expected_shop_ids, separators=(",", ":")).encode()
            ).hexdigest()
            self.assertEqual(expected_shop_ids, import_manifest["shopIds"])
            self.assertEqual(expected_shop_ids_sha, import_manifest["shopIdsSha256"])
            self.assertEqual(first_manifest["datasetSha256"], import_manifest["datasetSha256"])
            self.assertEqual({"MOCK": 36}, import_manifest["provenance"]["sourceCounts"])

            self.assertIn("NYC_IMPORT_BUNDLE_V1", mysql_sql)
            self.assertNotIn("legacy_hangzhou_", mysql_sql)
            self.assertNotIn("tb_legacy_archive_state", mysql_sql)
            self.assertNotIn("tb_sign", mysql_sql)
            self.assertIn("INSERT INTO `tb_shop_tag`", mysql_sql)
            self.assertIn("INSERT INTO `tb_shop_business_hours`", mysql_sql)
            self.assertIn("INSERT INTO `tb_data_import`", mysql_sql)
            self.assertIn("`external_id`", mysql_sql)
            self.assertIn("`synthetic_fields`", mysql_sql)
            self.assertIn("tb_shop_map_location", mysql_sql)
            self.assertIn("tb_neighborhood_shop_count", mysql_sql)
            self.assertIn("tb_borough_shop_count", mysql_sql)
            self.assertIn("ON DUPLICATE KEY UPDATE", mysql_sql)
            self.assertIn("America/New_York", mysql_sql)
            pin_utc = mysql_sql.index("SET SESSION time_zone = '+00:00'")
            first_shop_insert = mysql_sql.index("INSERT INTO `tb_shop`")
            restore_time_zone = mysql_sql.rindex("SET SESSION time_zone = @NYC_REVIEW_OLD_TIME_ZONE")
            self.assertLess(pin_utc, first_shop_insert)
            self.assertGreater(restore_time_zone, first_shop_insert)
            self.assertIn(b"GEOADD", redis_resp)
            self.assertIn(b"shop:geo:1", redis_resp)
            self.assertIn(b"blog:liked:", redis_resp)
            for item in seckill:
                self.assertIn(f"seckill:stock:{item['voucherId']}".encode(), redis_resp)

            redis_commands = parse_resp_commands(redis_resp)
            self.assertEqual(b"EVAL", redis_commands[0][0])
            cleanup_patterns = set(redis_commands[0][3:])
            self.assertTrue(
                {
                    b"translate:shop:*",
                    b"translate:review:*",
                    b"translate:blog:*",
                    b"translate:comment:*",
                }.issubset(cleanup_patterns)
            )
            self.assertNotIn(b"translate:text:*", cleanup_patterns)
            geo_members = sum(
                (len(command) - 2) // 3
                for command in redis_commands
                if command[0] == b"GEOADD"
            )
            stock_sets = [
                command
                for command in redis_commands
                if command[0] == b"SET" and command[1].startswith(b"seckill:stock:")
            ]
            self.assertEqual(len(shops), geo_members)
            self.assertEqual(len(seckill), len(stock_sets))

            for filename in ("mysql_import.sql", "redis_seed.resp", "import_manifest.json"):
                self.assertIn(filename, first_manifest["files"])

    def test_six_top_level_categories_are_stable(self):
        self.assertEqual(6, len(GENERATOR.CATEGORIES))
        self.assertEqual(
            [1, 2, 3, 4, 5, 6],
            [category["id"] for category in GENERATOR.CATEGORIES],
        )

    def test_user_social_overlay_is_scoped_and_seeds_likes(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "dataset"
            overlay = Path(directory) / "overlay"
            GENERATOR.generate_dataset("small", 12345, dataset)

            report = USER_SOCIAL_OVERLAY.build_overlay(dataset, overlay, 12345)
            mysql_sql = (overlay / "user_social_overlay.sql").read_text()
            redis_commands = parse_resp_commands(
                (overlay / "user_social_overlay.resp").read_bytes()
            )

            self.assertEqual(16, report["users"])
            self.assertGreaterEqual(report["uniqueAvatars"], 8)
            self.assertEqual(16, report["blogAuthorCoverage"])
            self.assertEqual(16, report["commentAuthorCoverage"])
            self.assertEqual(16, report["usersWithLikes"])
            self.assertIn("Generated user identity mismatch", mysql_sql)
            self.assertIn("DELETE f FROM `tb_follow`", mysql_sql)
            self.assertIn("tmp_nyc_review_persona_target", mysql_sql)
            self.assertNotIn(
                "JOIN `tmp_nyc_review_persona` target_user",
                mysql_sql,
            )
            self.assertNotIn("DELETE FROM `tb_user`", mysql_sql)
            self.assertTrue(redis_commands)
            self.assertTrue(all(command[0] == b"ZADD" for command in redis_commands))

    def test_medium_profile_expands_demo_scale_without_changing_load_profile(self):
        medium = GENERATOR.PROFILES["medium"]
        self.assertEqual(2_000, medium.shops)
        self.assertEqual(16_000, medium.reviews)
        self.assertGreater(GENERATOR.PROFILES["load"].shops, medium.shops)
        self.assertEqual(5_000, GENERATOR.PROFILES["real-medium"].shops)
        self.assertEqual(10_000, GENERATOR.PROFILES["real-large"].shops)
        self.assertEqual(15_000, GENERATOR.PROFILES["real-load"].shops)

    def test_real_profiles_target_60_30_disjoint_voucher_coverage(self):
        for profile_name in ("real-medium", "real-large", "real-load"):
            with self.subTest(profile=profile_name):
                profile = GENERATOR.PROFILES[profile_name]
                self.assertEqual(profile.shops * 60 // 100, profile.standard_vouchers)
                self.assertEqual(profile.shops * 30 // 100, profile.seckill_vouchers)
                self.assertEqual(
                    profile.shops * 90 // 100,
                    profile.standard_vouchers + profile.seckill_vouchers,
                )

    def test_voucher_assignment_is_stable_and_disjoint(self):
        shops = [
            {"id": shop_id, "dataVersion": "nyc-real-test"}
            for shop_id in range(1, 101)
        ]
        first = GENERATOR.generate_vouchers(__import__("random").Random(7), 60, 30, shops)
        second = GENERATOR.generate_vouchers(__import__("random").Random(7), 60, 30, shops)

        self.assertEqual(first, second)
        vouchers, seckill = first
        voucher_by_id = {voucher["id"]: voucher for voucher in vouchers}
        standard_shop_ids = {voucher["shopId"] for voucher in vouchers if voucher["type"] == 0}
        seckill_shop_ids = {
            voucher_by_id[item["voucherId"]]["shopId"] for item in seckill
        }
        self.assertEqual(60, len(standard_shop_ids))
        self.assertEqual(30, len(seckill_shop_ids))
        self.assertFalse(standard_shop_ids & seckill_shop_ids)

    def test_voucher_overlay_builds_guarded_non_destructive_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "dataset"
            output = root / "overlay"
            GENERATOR.generate_dataset("small", 12345, dataset)

            report = VOUCHER_OVERLAY.build_overlay(dataset, output)
            sql = (output / "voucher_coverage_overlay.sql").read_text()
            commands = parse_resp_commands(
                (output / "voucher_coverage_redis.resp").read_bytes()
            )

            self.assertEqual(36, report["shops"])
            self.assertEqual(22, report["standardVoucherShops"])
            self.assertEqual(11, report["seckillVoucherShops"])
            self.assertEqual(0, report["assignmentOverlap"])
            self.assertIn("CHECK (`shop_count` = 36)", sql)
            self.assertIn("UPDATE `tb_voucher` SET `status` = 2", sql)
            self.assertNotIn("DELETE FROM `tb_voucher`", sql)
            self.assertEqual(3, sum(command[0] == b"DEL" for command in commands))
            self.assertEqual(11, sum(command[0] == b"SETNX" for command in commands))

    def test_real_data_version_is_scoped_by_profile_snapshot_and_seed(self):
        snapshot_sha = "a" * 64
        small = GENERATOR.build_real_data_version(snapshot_sha, 20260817, "real-small")
        medium = GENERATOR.build_real_data_version(snapshot_sha, 20260817, "real-medium")

        self.assertEqual("nyc-real-v1-aaaaaaaa-s20260817", small)
        self.assertEqual("nyc-real-v1-aaaaaaaa-m20260817", medium)
        self.assertNotEqual(small, medium)
        self.assertLessEqual(len(small), 32)
        self.assertLessEqual(len(medium), 32)

    def test_hybrid_profile_uses_official_identity_and_discloses_synthetic_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            manifest = GENERATOR.generate_dataset(
                "small",
                12345,
                output,
                real_shops_path=SNAPSHOT_PATH.resolve(),
            )
            shops = json.loads((output / "shops.json").read_text())
            public_shops = [shop for shop in shops if shop["sourceType"] == "NYC_OPEN_DATA"]

            self.assertEqual("nyc-hybrid-v1", manifest["dataVersion"])
            self.assertEqual(len(public_shops), manifest["provenance"]["publicSourceBackedShops"])
            self.assertGreater(len(public_shops), 0)
            self.assertEqual(64, len(manifest["provenance"]["sourceSnapshotSha256"]))
            self.assertEqual(
                {"Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"},
                {shop["borough"] for shop in public_shops},
            )
            self.assertTrue(all(shop["externalId"].startswith("43nn-pn8j:") for shop in public_shops))
            self.assertTrue(all("reviews" in shop["syntheticFields"] for shop in public_shops))
            import_manifest = json.loads((output / "import_manifest.json").read_text())
            # Even when a tiny hybrid profile happens to be fully overlaid by
            # public rows, its contract remains HYBRID because the generator
            # mode/dataVersion—not observed source counts—defines semantics.
            self.assertEqual("HYBRID", import_manifest["merchantIdentityMode"])

    def test_real_only_profile_has_no_mock_identity_and_builds_review_trees(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            manifest = GENERATOR.generate_dataset(
                "real-small",
                20260817,
                output,
                real_places_path=OSM_FIXTURE_PATH,
                illustrative_images_path=IMAGE_CATALOG_PATH,
            )
            shops = json.loads((output / "shops.json").read_text())
            images = json.loads((output / "shop_images.json").read_text())
            hours = json.loads((output / "shop_business_hours.json").read_text())
            reviews = json.loads((output / "shop_reviews.json").read_text())
            blogs = json.loads((output / "blogs.json").read_text())
            blog_comments = json.loads((output / "blog_comments.json").read_text())
            users = json.loads((output / "users.json").read_text())
            follows = json.loads((output / "follows.json").read_text())
            blog_likes = json.loads((output / "blog_likes.json").read_text())
            vouchers = json.loads((output / "vouchers.json").read_text())
            import_manifest = json.loads((output / "import_manifest.json").read_text())
            mysql_sql = (output / "mysql_import.sql").read_text()

            source_sha = hashlib.sha256(OSM_FIXTURE_PATH.read_bytes()).hexdigest()
            expected_version = f"nyc-real-v1-{source_sha[:8]}-s20260817"
            self.assertEqual(expected_version, manifest["dataVersion"])
            self.assertLessEqual(len(manifest["dataVersion"]), 32)
            self.assertEqual("REAL_ONLY", manifest["merchantIdentityMode"])
            self.assertEqual(0, manifest["provenance"]["mockShops"])
            self.assertEqual(len(shops), manifest["provenance"]["realShops"])
            self.assertEqual({"OPENSTREETMAP": 12}, manifest["provenance"]["sourceCounts"])
            self.assertEqual({1, 2, 3, 4, 5, 6}, {shop["typeId"] for shop in shops})
            self.assertTrue(all(shop["sourceType"] == "OPENSTREETMAP" for shop in shops))
            self.assertTrue(all(shop["dataVersion"] == expected_version for shop in shops))
            self.assertTrue(all(shop["avgPriceCents"] > 0 for shop in shops))
            self.assertTrue(all(shop["priceLevel"] in {1, 2, 3, 4} for shop in shops))
            self.assertTrue(all(shop["score"] is not None for shop in shops))
            self.assertTrue(all(shop["tags"] for shop in shops))
            self.assertEqual(len(shops) * 7, len(hours))
            self.assertTrue(all("synthetic" not in shop["description"].casefold() for shop in shops))
            self.assertTrue(all(shop["sourceUrl"].startswith("https://www.openstreetmap.org/") for shop in shops))
            self.assertEqual(len(shops), len(images))
            self.assertTrue(all(image["imageType"] == "ILLUSTRATIVE" for image in images))
            self.assertTrue(all(image["sourceName"] == "Wikimedia Commons" for image in images))
            self.assertTrue(all(image["dataVersion"] == expected_version for image in images))
            self.assertTrue(all(image["licenseUrl"].startswith("https://creativecommons.org/") for image in images))

            by_id = {review["id"]: review for review in reviews}
            self.assertEqual({0, 1, 2}, {review["depth"] for review in reviews})
            self.assertTrue(all(review["sourceType"] == "SYNTHETIC" for review in reviews))
            self.assertTrue(all("[synthetic" not in review["content"].casefold() for review in reviews))
            self.assertTrue(all(review["rating"] is None for review in reviews if review["depth"] > 0))
            self.assertTrue(
                all(
                    review["parentId"] is None
                    or by_id[review["parentId"]]["depth"] == review["depth"] - 1
                    for review in reviews
                )
            )
            roots = [review for review in reviews if review["depth"] == 0]
            self.assertEqual(len(roots), sum(shop["comments"] for shop in shops))
            self.assertTrue(all(review["evidenceTags"] for review in roots))
            self.assertTrue(any(shop["name"] in review["content"] for shop in shops for review in roots if review["shopId"] == shop["id"]))
            for content_rows in (blogs, blog_comments, vouchers):
                self.assertTrue(all(item["sourceType"] == "SYNTHETIC" for item in content_rows))
                self.assertTrue(all(item["dataVersion"] == expected_version for item in content_rows))
            self.assertTrue(all("synthetic" not in blog["content"].casefold() for blog in blogs))
            self.assertTrue(all("a practical visit to" not in blog["title"].casefold() for blog in blogs))
            self.assertGreater(len({blog["content"] for blog in blogs}), len(shops))
            self.assertEqual(len(users), len({blog["userId"] for blog in blogs}))
            self.assertEqual(len(users), len({user["icon"] for user in users}))
            self.assertTrue(follows)
            self.assertTrue(blog_likes)
            self.assertEqual("REAL_ONLY", import_manifest["merchantIdentityMode"])
            self.assertEqual(expected_version, import_manifest["dataVersion"])
            self.assertEqual(0, import_manifest["provenance"]["mockShops"])
            self.assertEqual(len(shops), import_manifest["provenance"]["realShops"])
            self.assertIn("INSERT INTO `tb_shop_image`", mysql_sql)
            self.assertIn("`source_type`, `data_version`", mysql_sql)
            self.assertIn("bootstrap-schema.sql", mysql_sql)
            for table in (
                "tb_agent_action_audit",
                "tb_seckill_reminder",
                "tb_saved_itinerary",
                "tb_shop_favorite",
                "tb_agent_user_memory",
            ):
                optional_delete = f"'DELETE FROM `{table}`'"
                self.assertIn(optional_delete, mysql_sql)
                self.assertLess(mysql_sql.index(optional_delete), mysql_sql.index("DELETE FROM `tb_user`;"))
            self.assertIn("`root_id`", mysql_sql)
            self.assertNotIn("legacy_hangzhou_", mysql_sql)
            report = VALIDATOR.validate_dataset(output)
            self.assertEqual("REAL_ONLY", report["merchantIdentityMode"])
            self.assertEqual(1.0, report["publicSourceRatio"])

            blogs[0]["sourceType"] = "USER_SUBMITTED"
            (output / "blogs.json").write_text(json.dumps(blogs))
            with self.assertRaisesRegex(ValueError, "blog .* is not marked SYNTHETIC"):
                VALIDATOR.validate_dataset(output)

    def test_real_only_generation_fails_closed_without_all_six_categories(self):
        snapshot = json.loads(OSM_FIXTURE_PATH.read_text())
        snapshot["records"] = [record for record in snapshot["records"] if record["typeId"] != 6]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path = root / "missing-category.json"
            snapshot_path.write_text(json.dumps(snapshot))
            with self.assertRaisesRegex(ValueError, "missing shop categories"):
                GENERATOR.generate_dataset(
                    "real-small",
                    20260817,
                    root / "output",
                    real_places_path=snapshot_path,
                    illustrative_images_path=IMAGE_CATALOG_PATH,
                )

    def test_osm_snapshot_rejects_source_fields_that_do_not_fit_database(self):
        snapshot = json.loads(OSM_FIXTURE_PATH.read_text())
        external_id = snapshot["records"][0]["externalId"]
        snapshot["records"][0]["name"] = "x" * 129
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "overlong.json"
            path.write_text(json.dumps(snapshot))
            with self.assertRaisesRegex(ValueError, external_id):
                OSM_PLACES.load_snapshot(path)

    def test_real_only_validator_rejects_mock_identity_or_orphan_reply(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            GENERATOR.generate_dataset(
                "real-small",
                20260817,
                output,
                real_places_path=OSM_FIXTURE_PATH,
                illustrative_images_path=IMAGE_CATALOG_PATH,
            )
            shop_path = output / "shops.json"
            shops = json.loads(shop_path.read_text())
            shops[0]["sourceType"] = "MOCK"
            shop_path.write_text(json.dumps(shops))
            with self.assertRaisesRegex(ValueError, "mock, legacy or unknown"):
                VALIDATOR.validate_dataset(output)

            shops[0]["sourceType"] = "OPENSTREETMAP"
            shop_path.write_text(json.dumps(shops))
            review_path = output / "shop_reviews.json"
            reviews = json.loads(review_path.read_text())
            reply = next(review for review in reviews if review["depth"] == 1)
            reply["parentId"] = 999_999
            review_path.write_text(json.dumps(reviews))
            with self.assertRaisesRegex(ValueError, "missing or later parent"):
                VALIDATOR.validate_dataset(output)

    def test_osm_classifier_covers_all_six_product_categories(self):
        fixtures = [
            ({"amenity": "restaurant", "cuisine": "italian"}, (1, "Italian")),
            ({"amenity": "cafe"}, (2, "Coffee Shop")),
            ({"amenity": "pub"}, (3, "Pub")),
            ({"tourism": "museum"}, (4, "Museum")),
            ({"leisure": "fitness_centre"}, (5, "Gym")),
            ({"shop": "nail_salon"}, (6, "Nail Salon")),
        ]
        for tags, expected in fixtures:
            category = OSM_PLACES.classify_tags(tags)
            self.assertIsNotNone(category)
            self.assertEqual(expected, (category["typeId"], category["subcategory"]))

    def test_overpass_retry_uses_retry_after_for_rate_limit(self):
        rate_limit = urllib.error.HTTPError(
            "https://overpass.example/interpreter",
            429,
            "Too Many Requests",
            {"Retry-After": "7"},
            None,
        )
        response = io.BytesIO(b'{"elements": []}')
        with patch.object(
            OSM_PLACES.urllib.request,
            "urlopen",
            side_effect=[rate_limit, response],
        ), patch.object(OSM_PLACES.time, "sleep") as sleep:
            payload = OSM_PLACES._post_overpass(
                "https://overpass.example/interpreter",
                "[out:json];node(0,0,1,1);out;",
                user_agent="test",
                retries=2,
                retry_base_delay=5,
                max_retry_delay=60,
            )

        self.assertEqual([], payload["elements"])
        sleep.assert_called_once_with(7.0)

    def test_open_data_normalization_deduplicates_camis(self):
        records = NYC_OPEN_DATA.normalize_records(
            [
                {
                    "camis": "1",
                    "dba": "Fixture",
                    "boro": "Queens",
                    "building": "1",
                    "street": "Main St",
                    "zipcode": "11354",
                    "latitude": "40.75",
                    "longitude": "-73.84",
                },
                {
                    "camis": "1",
                    "dba": "Fixture",
                    "boro": "Queens",
                    "latitude": "40.75",
                    "longitude": "-73.84",
                },
            ]
        )
        self.assertEqual(1, len(records))

    def test_nta_geometry_respects_polygon_holes(self):
        geometry = {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
                    [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]],
                ]
            ],
        }
        self.assertTrue(NYC_NTA.contains_point(geometry, 0.5, 0.5))
        self.assertFalse(NYC_NTA.contains_point(geometry, 2, 2))
        self.assertTrue(NYC_NTA.contains_point(geometry, 0, 2))

    def test_p7_import_assigns_official_polygon_and_preserves_agent_area(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "dataset"
            dataset.mkdir()
            shops = [
                {
                    "id": 1,
                    "typeId": 1,
                    "dataVersion": "test-v1",
                    "x": -73.99,
                    "y": 40.75,
                    "borough": "Manhattan",
                    "area": "Midtown",
                    "sourceType": "NYC_OPEN_DATA",
                },
                {
                    "id": 2,
                    "typeId": 1,
                    "dataVersion": "test-v1",
                    "x": -74.5,
                    "y": 41.5,
                    "borough": "Manhattan",
                    "area": "Midtown",
                    "sourceType": "MOCK",
                },
            ]
            shop_ids = [1, 2]
            shop_ids_sha256 = hashlib.sha256(
                json.dumps(shop_ids, separators=(",", ":")).encode()
            ).hexdigest()
            (dataset / "shops.json").write_text(json.dumps(shops))
            (dataset / "import_manifest.json").write_text(
                json.dumps(
                    {
                        "dataVersion": "test-v1",
                        "datasetSha256": "d" * 64,
                        "shopIds": shop_ids,
                        "shopIdsSha256": shop_ids_sha256,
                    }
                )
            )
            snapshot_document = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "nta2020": "MN0001",
                            "ntaname": "Fixture NTA",
                            "boroname": "Manhattan",
                            "ntatype": "0",
                            "cdta2020": "MN00",
                        },
                        "geometry": {
                            "type": "MultiPolygon",
                            "coordinates": [
                                [[
                                    [-74.1, 40.6],
                                    [-73.8, 40.6],
                                    [-73.8, 40.9],
                                    [-74.1, 40.9],
                                    [-74.1, 40.6],
                                ]]
                            ],
                        },
                    }
                ],
            }
            snapshot_payload = json.dumps(snapshot_document, separators=(",", ":")).encode()
            snapshot = root / "nta.geojson"
            snapshot.write_bytes(snapshot_payload)
            snapshot_sha256 = hashlib.sha256(snapshot_payload).hexdigest()
            nta_manifest = root / "nta-manifest.json"
            nta_manifest.write_text(
                json.dumps(
                    {
                        "contentLength": len(snapshot_payload),
                        "datasetId": "fixture",
                        "datasetVersion": "fixture-v1",
                        "downloadUrl": "https://example.invalid/fixture.geojson",
                        "featureCount": 1,
                        "revisionDate": "2026-01-01",
                        "sha256": snapshot_sha256,
                        "sourcePageUrl": "https://example.invalid/source",
                        "verifiedAt": "2026-01-02T00:00:00Z",
                    }
                )
            )
            output = root / "p7.sql"
            report = P7_IMPORT.build_import(
                dataset,
                snapshot,
                output,
                nta_manifest_path=nta_manifest,
            )
            sql = output.read_text()

            self.assertEqual(
                {"POINT_IN_POLYGON": 1, "UNASSIGNED": 1},
                report["assignmentMethods"],
            )
            self.assertEqual(
                {"assigned": 1, "unassigned": 0},
                report["coverageBySource"]["NYC_OPEN_DATA"],
            )
            self.assertIn("NYC_REVIEW_P7_NEIGHBORHOOD_IMPORT_V1", sql)
            self.assertIn(
                "SET NAMES utf8mb4 COLLATE utf8mb4_general_ci;",
                sql,
            )
            self.assertIn(
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;",
                sql,
            )
            self.assertIn("ST_GeomFromGeoJSON", sql)
            self.assertIn("axis-order=long-lat", sql)
            self.assertIn("CREATE TEMPORARY TABLE `nyc_review_p7_expected_shop`", sql)
            self.assertIn("CHECK (`ok` = 1)", sql)
            self.assertIn("`dataset_sha256`='" + "d" * 64 + "'", sql)
            self.assertIn("ABS(actual.`x` - expected.`longitude`)", sql)
            self.assertLess(
                sql.index("CREATE TEMPORARY TABLE `nyc_review_p7_dataset_guard`"),
                sql.index("START TRANSACTION;"),
            )
            self.assertLess(
                sql.index("START TRANSACTION;"),
                sql.index("INSERT INTO `tb_neighborhood`"),
            )
            self.assertIn("SET s.`neighborhood_code`=ml.`neighborhood_code`", sql)
            self.assertNotIn("s.`area`=", sql)
            self.assertIn("'Midtown'", sql)
            self.assertIn(snapshot_sha256, sql)

    def test_p7_assignment_exposes_unassigned_public_source_shop(self):
        shops = [
            {
                "id": 1,
                "dataVersion": "test-v1",
                "x": -74.5,
                "y": 41.5,
                "borough": "Manhattan",
                "area": "Midtown",
                "sourceType": "NYC_OPEN_DATA",
            }
        ]
        assignments = P7_IMPORT.assign_shops(
            shops,
            [
                {
                    "code": "MN0001",
                    "name": "Fixture NTA",
                    "borough": "Manhattan",
                    "ntaType": "0",
                    "minX": -74.1,
                    "minY": 40.6,
                    "maxX": -73.8,
                    "maxY": 40.9,
                    "geometry": {
                        "type": "MultiPolygon",
                        "coordinates": [[[
                            [-74.1, 40.6],
                            [-73.8, 40.6],
                            [-73.8, 40.9],
                            [-74.1, 40.9],
                            [-74.1, 40.6],
                        ]]],
                    },
                }
            ],
        )
        self.assertEqual("UNASSIGNED", assignments[0]["assignmentMethod"])
        self.assertEqual("NYC_OPEN_DATA", assignments[0]["sourceType"])


if __name__ == "__main__":
    unittest.main()
