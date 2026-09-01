from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
STAGE_SCRIPT = REPOSITORY_ROOT / "scripts/deploy/stage-m3-qdrant.sh"
PROMOTE_SCRIPT = REPOSITORY_ROOT / "scripts/deploy/promote-m3-production.sh"
SNAPSHOT_SHA256 = "13cbf7ea033d6801df374e823432318107944568d8fcf76560872049e8eef574"


class StageM3QdrantTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = Path(self.temp_dir.name) / "repository"
        self.deploy_dir = self.repository / "scripts/deploy"
        self.deploy_dir.mkdir(parents=True)
        shutil.copy2(STAGE_SCRIPT, self.deploy_dir / "stage-m3-qdrant.sh")
        self._write_executable(
            self.deploy_dir / "verify-m3-qdrant.py",
            "#!/usr/bin/env python3\n",
        )
        self.snapshot = self.repository / "m3.snapshot"
        self.snapshot.write_bytes(b"snapshot fixture")

        self.mock_bin = self.repository / "mock-bin"
        self.mock_bin.mkdir()
        self.call_log = self.repository / "calls.log"
        self._write_executable(
            self.mock_bin / "sha256sum",
            f"#!/usr/bin/env bash\nprintf '%s  %s\\n' '{SNAPSHOT_SHA256}' \"$1\"\n",
        )
        self._write_executable(
            self.mock_bin / "docker",
            """#!/usr/bin/env bash
printf 'docker %s\n' "$*" >> "$M3_TEST_CALL_LOG"
if [[ "$1" == "container" && "$2" == "inspect" ]]; then
  exit 1
fi
if [[ "$1" == "volume" && "$2" == "inspect" ]]; then
  if [[ "$*" == *"com.nyc-review.rag-profile"* ]]; then
    printf '%s\n' 'm3-quality-v1'
  elif [[ "$*" == *"com.nyc-review.snapshot-sha256"* ]]; then
    printf '%s\n' '13cbf7ea033d6801df374e823432318107944568d8fcf76560872049e8eef574'
  fi
  exit 0
fi
if [[ "$1" == "ps" ]]; then
  [[ -n "${M3_TEST_VOLUME_USERS:-}" ]] && printf '%s\n' "$M3_TEST_VOLUME_USERS"
  exit 0
fi
exit 0
""",
        )
        self._write_executable(
            self.mock_bin / "curl",
            """#!/usr/bin/env bash
printf 'curl %s\n' "$*" >> "$M3_TEST_CALL_LOG"
exit 0
""",
        )
        self._write_executable(
            self.mock_bin / "python3",
            """#!/usr/bin/env bash
printf 'python3 %s\n' "$*" >> "$M3_TEST_CALL_LOG"
exit "${M3_TEST_VERIFY_EXIT:-0}"
""",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def _write_executable(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def _run_stage(
        self,
        *,
        volume_users: str = "",
        verify_exit: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PATH"] = f"{self.mock_bin}:{environment['PATH']}"
        environment["M3_TEST_CALL_LOG"] = str(self.call_log)
        environment["M3_TEST_VOLUME_USERS"] = volume_users
        environment["M3_TEST_VERIFY_EXIT"] = str(verify_exit)
        return subprocess.run(
            (str(self.deploy_dir / "stage-m3-qdrant.sh"), str(self.snapshot)),
            cwd=self.repository,
            check=False,
            text=True,
            capture_output=True,
            env=environment,
        )

    def _calls(self) -> str:
        if not self.call_log.exists():
            return ""
        return self.call_log.read_text(encoding="utf-8")

    def test_refuses_any_existing_container_reference_to_m3_volume(self) -> None:
        result = self._run_stage(volume_users="nyc-review-m3-qdrant-diagnose")

        self.assertEqual(result.returncode, 1)
        self.assertIn("another container references it", result.stderr)
        self.assertIn("nyc-review-m3-qdrant-diagnose", result.stderr)
        self.assertNotIn("docker run ", self._calls())

    def test_success_waits_boundedly_and_stops_container_gracefully(self) -> None:
        result = self._run_stage()

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self._calls()
        self.assertIn("--wait-seconds 1800 --poll-seconds 5", calls)
        self.assertIn("docker stop --time 120 nyc-review-m3-qdrant-stage", calls)
        self.assertIn("docker rm nyc-review-m3-qdrant-stage", calls)
        self.assertNotIn("docker rm -f", calls)

    def test_failed_readiness_preserves_container_and_volume_for_diagnosis(
        self,
    ) -> None:
        result = self._run_stage(verify_exit=1)

        self.assertEqual(result.returncode, 1)
        calls = self._calls()
        self.assertIn("docker inspect --format", calls)
        self.assertIn("docker stats --no-stream nyc-review-m3-qdrant-stage", calls)
        self.assertNotIn("docker stop ", calls)
        self.assertNotIn("docker rm ", calls)
        self.assertIn("Preserving failed staging container", result.stderr)

    def test_promotion_uses_the_same_bounded_readiness_contract(self) -> None:
        script = PROMOTE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("--wait-seconds 1800", script)
        self.assertIn("--poll-seconds 5", script)


if __name__ == "__main__":
    unittest.main()
