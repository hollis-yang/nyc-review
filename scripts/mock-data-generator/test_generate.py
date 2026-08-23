import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

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
SNAPSHOT_PATH = MODULE_PATH.parents[1] / ".." / "data" / "sources" / "nyc-open-data-restaurants-2026-08-23.json"


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
            vouchers = json.loads((Path(first) / "vouchers.json").read_text())
            seckill = json.loads((Path(first) / "seckill_vouchers.json").read_text())
            import_manifest = json.loads((Path(first) / "import_manifest.json").read_text())
            mysql_sql = (Path(first) / "mysql_import.sql").read_text()
            redis_resp = (Path(first) / "redis_seed.resp").read_bytes()

            shop_ids = {shop["id"] for shop in shops}
            user_ids = {user["id"] for user in users}
            voucher_ids = {voucher["id"] for voucher in vouchers}
            blog_ids = {blog["id"] for blog in blogs}
            comment_ids = {comment["id"] for comment in blog_comments}

            self.assertEqual(36, len(shops))
            self.assertTrue(all(review["shopId"] in shop_ids for review in reviews))
            self.assertTrue(all(review["userId"] in user_ids for review in reviews))
            self.assertTrue(all(voucher["shopId"] in shop_ids for voucher in vouchers))
            self.assertTrue(all(item["voucherId"] in voucher_ids for item in seckill))
            self.assertTrue(all(item["manualOnly"] for item in seckill))
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

            expected_shop_ids = sorted(shop_ids)
            expected_shop_ids_sha = hashlib.sha256(
                json.dumps(expected_shop_ids, separators=(",", ":")).encode()
            ).hexdigest()
            self.assertEqual(expected_shop_ids, import_manifest["shopIds"])
            self.assertEqual(expected_shop_ids_sha, import_manifest["shopIdsSha256"])
            self.assertEqual(first_manifest["datasetSha256"], import_manifest["datasetSha256"])
            self.assertEqual({"MOCK": 36}, import_manifest["provenance"]["sourceCounts"])

            self.assertIn("NYC_IMPORT_BUNDLE_V1", mysql_sql)
            self.assertIn("legacy_hangzhou_tb_shop", mysql_sql)
            self.assertIn("tb_legacy_archive_state", mysql_sql)
            self.assertIn("INSERT INTO `tb_shop_tag`", mysql_sql)
            self.assertIn("INSERT INTO `tb_shop_business_hours`", mysql_sql)
            self.assertIn("INSERT INTO `tb_data_import`", mysql_sql)
            self.assertIn("`external_id`", mysql_sql)
            self.assertIn("`synthetic_fields`", mysql_sql)
            self.assertIn("ON DUPLICATE KEY UPDATE", mysql_sql)
            self.assertIn("America/New_York", mysql_sql)
            pin_utc = mysql_sql.index("SET SESSION time_zone = '+00:00'")
            first_shop_insert = mysql_sql.index("INSERT INTO `tb_shop`")
            restore_time_zone = mysql_sql.rindex("SET SESSION time_zone = @HMDP_OLD_TIME_ZONE")
            self.assertLess(pin_utc, first_shop_insert)
            self.assertGreater(restore_time_zone, first_shop_insert)
            self.assertIn(b"GEOADD", redis_resp)
            self.assertIn(b"shop:geo:1", redis_resp)
            for item in seckill:
                self.assertIn(f"seckill:stock:{item['voucherId']}".encode(), redis_resp)

            redis_commands = parse_resp_commands(redis_resp)
            self.assertEqual(b"EVAL", redis_commands[0][0])
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

    def test_medium_profile_expands_demo_scale_without_changing_load_profile(self):
        medium = GENERATOR.PROFILES["medium"]
        self.assertEqual(2_000, medium.shops)
        self.assertEqual(16_000, medium.reviews)
        self.assertGreater(GENERATOR.PROFILES["load"].shops, medium.shops)

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


if __name__ == "__main__":
    unittest.main()
