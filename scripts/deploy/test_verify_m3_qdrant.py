from __future__ import annotations

import importlib.util
import io
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("verify-m3-qdrant.py")
SPEC = importlib.util.spec_from_file_location("verify_m3_qdrant", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def collection(
    status: str,
    *,
    optimizer_status: object = "ok",
    queue_length: int = 0,
) -> dict[str, object]:
    return {
        "status": status,
        "optimizer_status": optimizer_status,
        "update_queue": {"length": queue_length},
        "points_count": 145_000,
        "indexed_vectors_count": 288_232,
        "segments_count": 5,
    }


class VerifyM3QdrantReadinessTest(unittest.TestCase):
    def test_waits_for_yellow_and_grey_without_sending_updates(self) -> None:
        responses = iter(
            [
                {"result": collection("yellow")},
                {"result": collection("grey")},
                {"result": collection("green", queue_length=1)},
                {"result": collection("green")},
            ]
        )
        calls: list[tuple[str, object]] = []

        def request(
            _base_url: str, path: str, payload: object = None
        ) -> dict[str, object]:
            calls.append((path, payload))
            return next(responses)

        ticks = iter([0.0, 0.1, 0.2, 0.3])
        sleeps: list[float] = []
        stderr = io.StringIO()
        with (
            mock.patch.object(VERIFY, "_request", side_effect=request),
            redirect_stderr(stderr),
        ):
            result = VERIFY.wait_until_ready(
                "http://qdrant.test",
                wait_seconds=10,
                poll_seconds=1,
                sleep=sleeps.append,
                monotonic=lambda: next(ticks),
            )

        self.assertEqual(result["status"], "green")
        self.assertEqual(len(sleeps), 3)
        self.assertTrue(all(payload is None for _, payload in calls))
        self.assertEqual(
            [path for path, _ in calls],
            [f"/collections/{VERIFY.COLLECTION}"] * 4,
        )
        self.assertIn(
            "without sending an optimizer-triggering update", stderr.getvalue()
        )

    def test_red_fails_immediately_with_bounded_safe_diagnostics(self) -> None:
        calls: list[tuple[str, object]] = []
        red = collection("red", optimizer_status={"error": "segment failure"})
        red["payload"] = {"private": "must-not-appear"}

        def request(
            _base_url: str, path: str, payload: object = None
        ) -> dict[str, object]:
            calls.append((path, payload))
            if path.endswith("/optimizations?with=queued"):
                return {
                    "result": {
                        "summary": {
                            "queued_optimizations": 1,
                            "queued_points": 145_000,
                        },
                        "running": [],
                        "queued": [
                            {
                                "optimizer": "indexing",
                                "status": "queued",
                                "segments": [],
                            }
                        ],
                    }
                }
            return {"result": red}

        with (
            mock.patch.object(VERIFY, "_request", side_effect=request),
            redirect_stderr(io.StringIO()),
            self.assertRaisesRegex(RuntimeError, "entered red state") as raised,
        ):
            VERIFY.wait_until_ready(
                "http://qdrant.test",
                wait_seconds=30,
                poll_seconds=1,
                sleep=lambda _seconds: self.fail("red readiness must not sleep"),
                monotonic=lambda: 0,
            )

        message = str(raised.exception)
        self.assertIn('"queuedCount": 1', message)
        self.assertNotIn("must-not-appear", message)
        self.assertTrue(all(payload is None for _, payload in calls))

    def test_timeout_reports_state_without_triggering_grey_optimizer(self) -> None:
        calls: list[tuple[str, object]] = []

        def request(
            _base_url: str, path: str, payload: object = None
        ) -> dict[str, object]:
            calls.append((path, payload))
            if path.endswith("/optimizations?with=queued"):
                return {
                    "result": {
                        "summary": {"queued_optimizations": 1},
                        "running": [],
                        "queued": [],
                    }
                }
            return {"result": collection("grey")}

        with (
            mock.patch.object(VERIFY, "_request", side_effect=request),
            redirect_stderr(io.StringIO()),
            self.assertRaisesRegex(RuntimeError, "within 0 seconds"),
        ):
            VERIFY.wait_until_ready(
                "http://qdrant.test",
                wait_seconds=0,
                poll_seconds=1,
                sleep=lambda _seconds: self.fail(
                    "zero-second readiness must not sleep"
                ),
                monotonic=lambda: 0,
            )

        self.assertTrue(all(payload is None for _, payload in calls))
        self.assertFalse(any(path.endswith("/points/count") for path, _ in calls))


if __name__ == "__main__":
    unittest.main()
