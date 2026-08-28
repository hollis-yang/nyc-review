"""Offline contracts for the isolated load-test helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import DATABASE, PROJECT, VOUCHER_ID, resp
from prepare_fixtures import build_user_sql
from validate_orders import converged


class LoadTestContractsTest(unittest.TestCase):
    def test_environment_identity_is_never_the_active_development_database(self) -> None:
        self.assertEqual("nyc-review-p14-load", PROJECT)
        self.assertEqual("nyc_review_p14_load", DATABASE)
        self.assertNotEqual("nyc_review", DATABASE)

    def test_fixture_sql_only_targets_the_reserved_load_range(self) -> None:
        sql = build_user_sql(user_count=10, stock=5)
        self.assertIn(f"voucher_id={VOUCHER_ID}", sql)
        self.assertIn("BETWEEN 9000000 AND 9000009", sql)
        self.assertIn("'p14-load-v1'", sql)
        self.assertNotIn("DELETE FROM tb_shop", sql)
        self.assertNotIn("TRUNCATE", sql.upper())

    def test_resp_encoder_is_binary_safe_for_ascii_fixture_commands(self) -> None:
        self.assertEqual(
            "*3\r\n$3\r\nSET\r\n$3\r\nkey\r\n$5\r\nvalue\r\n",
            resp("SET", "key", "value"),
        )

    def test_convergence_requires_every_storage_boundary_to_agree(self) -> None:
        report = {
            "initialStock": 5,
            "acceptedReservations": 5,
            "redis": {"uniqueUsers": 5, "pendingPublisherRecords": 0},
            "mysql": {"orders": 5, "uniqueUsers": 5, "uniqueOrderIds": 5, "stock": 0},
            "rabbitmq": {"ready": 0, "unacknowledged": 0, "errorQueue": 0},
        }
        self.assertTrue(converged(report, allow_error_queue=False))
        report["mysql"]["orders"] = 4
        self.assertFalse(converged(report, allow_error_queue=False))


if __name__ == "__main__":
    unittest.main()
