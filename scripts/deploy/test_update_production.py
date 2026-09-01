from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
UPDATE_SCRIPT = REPOSITORY_ROOT / "scripts/deploy/update-production.sh"

OLD_SHA = "1" * 40
NEW_SHA = "2" * 40
AGENT_SHA = "3" * 40


class UpdateProductionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = Path(self.temp_dir.name) / "repository"
        deploy_dir = self.repository / "scripts/deploy"
        deploy_dir.mkdir(parents=True)
        shutil.copy2(UPDATE_SCRIPT, deploy_dir / "update-production.sh")
        self._write_executable(
            deploy_dir / "check-production-config.sh",
            "#!/usr/bin/env bash\nexit 0\n",
        )
        self._write("compose.production.yml", "services: {}\n")

        self.mock_bin = self.repository / "mock-bin"
        self.mock_bin.mkdir()
        self._write_executable(
            self.mock_bin / "docker",
            """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DOCKER_CALL_LOG"
if [[ "${FAIL_DOCKER_UP:-0}" == "1" && " $* " == *" up "* && ! -f "$DOCKER_FAIL_MARKER" ]]; then
  : > "$DOCKER_FAIL_MARKER"
  exit 1
fi
exit 0
""",
        )
        self.docker_call_log = self.repository / "docker-calls.log"
        self.docker_fail_marker = self.repository / "docker-failed-once"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write(self, relative_path: str, content: str) -> None:
        path = self.repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _write_executable(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def _write_environment(self, *, include_agent_tag: bool = True) -> None:
        lines = [f"IMAGE_TAG=sha-{OLD_SHA}"]
        if include_agent_tag:
            lines.append(f"AGENT_IMAGE_TAG=sha-{AGENT_SHA}")
        self._write(".env.production", "\n".join(lines) + "\n")

    def _run_update(self, *, fail_up: bool = False) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PATH"] = f"{self.mock_bin}:{environment['PATH']}"
        environment["DOCKER_CALL_LOG"] = str(self.docker_call_log)
        environment["DOCKER_FAIL_MARKER"] = str(self.docker_fail_marker)
        if fail_up:
            environment["FAIL_DOCKER_UP"] = "1"
        return subprocess.run(
            (str(self.repository / "scripts/deploy/update-production.sh"), NEW_SHA),
            cwd=self.repository,
            text=True,
            capture_output=True,
            env=environment,
        )

    def _environment_values(self) -> dict[str, str]:
        return dict(
            line.split("=", 1)
            for line in (self.repository / ".env.production")
            .read_text(encoding="utf-8")
            .splitlines()
        )

    def test_missing_agent_tag_fails_before_changing_release(self) -> None:
        self._write_environment(include_agent_tag=False)

        result = self._run_update()

        self.assertEqual(result.returncode, 1)
        self.assertIn("AGENT_IMAGE_TAG is missing or invalid", result.stderr)
        self.assertEqual(self._environment_values()["IMAGE_TAG"], f"sha-{OLD_SHA}")

    def test_success_updates_all_application_tags(self) -> None:
        self._write_environment()

        result = self._run_update()

        self.assertEqual(result.returncode, 0, result.stderr)
        values = self._environment_values()
        self.assertEqual(values["IMAGE_TAG"], f"sha-{NEW_SHA}")
        self.assertEqual(values["AGENT_IMAGE_TAG"], f"sha-{NEW_SHA}")
        self.assertIn(f"Previous Agent release: sha-{AGENT_SHA}", result.stdout)

    def test_failed_startup_restores_all_application_tags(self) -> None:
        self._write_environment()

        result = self._run_update(fail_up=True)

        self.assertEqual(result.returncode, 1)
        values = self._environment_values()
        self.assertEqual(values["IMAGE_TAG"], f"sha-{OLD_SHA}")
        self.assertEqual(values["AGENT_IMAGE_TAG"], f"sha-{AGENT_SHA}")
        self.assertIn("Container rollback completed", result.stderr)
        up_calls = [
            line
            for line in self.docker_call_log.read_text(encoding="utf-8").splitlines()
            if " up " in f" {line} "
        ]
        self.assertEqual(len(up_calls), 2)


if __name__ == "__main__":
    unittest.main()
