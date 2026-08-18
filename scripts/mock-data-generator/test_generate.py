import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("generate.py")
SPEC = importlib.util.spec_from_file_location("nyc_mock_generator", MODULE_PATH)
GENERATOR = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = GENERATOR
SPEC.loader.exec_module(GENERATOR)


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

    def test_six_top_level_categories_are_stable(self):
        self.assertEqual(6, len(GENERATOR.CATEGORIES))
        self.assertEqual(
            [1, 2, 3, 4, 5, 6],
            [category["id"] for category in GENERATOR.CATEGORIES],
        )


if __name__ == "__main__":
    unittest.main()
