from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RELEASE_SCRIPT = REPOSITORY_ROOT / "scripts/deploy/release-production.sh"


class ReleaseProductionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = Path(self.temp_dir.name) / "repository"
        self.repository.mkdir()

        self._run_git("init", "-b", "main")
        self._run_git("config", "user.name", "Release Test")
        self._run_git("config", "user.email", "release-test@example.com")

        deploy_dir = self.repository / "scripts/deploy"
        deploy_dir.mkdir(parents=True)
        shutil.copy2(RELEASE_SCRIPT, deploy_dir / "release-production.sh")
        self._write_executable(
            deploy_dir / "package-production-bundle.sh",
            '#!/usr/bin/env bash\nset -euo pipefail\nmkdir -p "$(dirname -- "$1")"\n: > "$1"\n',
        )
        self._write_executable(
            deploy_dir / "package-database-release.sh",
            """#!/usr/bin/env bash
set -euo pipefail
project_root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
mkdir -p "$project_root/dist"
: > "$project_root/dist/nyc-review-database-release-$1.tar.gz"
""",
        )
        for script_name in (
            "check-production-config.sh",
            "apply-production-release.sh",
            "update-production.sh",
        ):
            self._write_executable(deploy_dir / script_name, "#!/usr/bin/env bash\nexit 0\n")

        self._write("compose.production.yml", "services: {}\n")
        self._write(".env.production.example", "IMAGE_TAG=sha-example\n")
        self._write(
            "deploy/production/database-release.tsv",
            """# change_id\tkind\tsql_path\tredis_resp_path
tracked_change\tschema\trelease-assets/declared.sql\t-
ignored_overlay\toverlay\tdata/generated/release/overlay.sql\t-
""",
        )
        self._write("src/main/resources/db/schema.sql", "SELECT 1;\n")
        self._write("release-assets/declared.sql", "SELECT 2;\n")
        self._write(".gitignore", "/data/\n/dist/\n")
        self._write("data/generated/release/overlay.sql", "SELECT 3;\n")
        self._write("agent-service/tracked.txt", "committed\n")

        self.mock_bin = self.repository / "mock-bin"
        self.mock_bin.mkdir()
        self._write_executable(self.mock_bin / "scp", "#!/usr/bin/env bash\nexit 0\n")
        self._write_executable(self.mock_bin / "ssh", "#!/usr/bin/env bash\nexit 0\n")
        self.ssh_key = self.repository / "test-key.pem"
        self.ssh_key.write_text("test key\n", encoding="utf-8")

        self._run_git("add", ".")
        self._run_git("commit", "-m", "fixture")
        self.commit_sha = self._run_git("rev-parse", "HEAD").stdout.strip()
        self._run_git("update-ref", "refs/remotes/origin/main", self.commit_sha)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write(self, relative_path: str, content: str) -> None:
        path = self.repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _write_executable(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def _run_git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("git", *args),
            cwd=self.repository,
            check=True,
            text=True,
            capture_output=True,
        )

    def _run_release(self, sha: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PATH"] = f"{self.mock_bin}:{environment['PATH']}"
        environment["LIGHTSAIL_SSH_KEY"] = str(self.ssh_key)
        environment["LIGHTSAIL_SSH_TARGET"] = "release-test@example.com"
        environment["NYC_REVIEW_REMOTE_ROOT"] = "/opt/nyc-review-test"
        return subprocess.run(
            (str(self.repository / "scripts/deploy/release-production.sh"), sha),
            cwd=self.repository,
            text=True,
            capture_output=True,
            env=environment,
        )

    def test_unrelated_dirty_and_untracked_files_do_not_block_release(self) -> None:
        self._write("agent-service/tracked.txt", "work in progress\n")
        self._write("agent-service/untracked.txt", "not committed\n")
        self._write("data/generated/release/overlay.sql", "updated generated payload\n")

        result = self._run_release(self.commit_sha)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"Production release completed: sha-{self.commit_sha}", result.stdout)

    def test_dirty_release_inputs_still_block_release(self) -> None:
        self._write("compose.production.yml", "services:\n  dirty: {}\n")
        self._write("deploy/production/untracked.txt", "not committed\n")

        result = self._run_release(self.commit_sha)

        self.assertEqual(result.returncode, 1)
        self.assertIn("Local release-package inputs have uncommitted or untracked files", result.stderr)
        self.assertIn("compose.production.yml", result.stderr)
        self.assertIn("deploy/production/untracked.txt", result.stderr)

    def test_dirty_tracked_file_declared_by_manifest_blocks_release(self) -> None:
        self._write("release-assets/declared.sql", "uncommitted change\n")

        result = self._run_release(self.commit_sha)

        self.assertEqual(result.returncode, 1)
        self.assertIn("release-assets/declared.sql", result.stderr)

    def test_requested_sha_must_match_head(self) -> None:
        wrong_sha = "0" * 40

        result = self._run_release(wrong_sha)

        self.assertEqual(result.returncode, 1)
        self.assertIn("The requested SHA is not the current local commit", result.stderr)

    def test_requested_sha_must_match_origin_main(self) -> None:
        tree_sha = self._run_git("rev-parse", "HEAD^{tree}").stdout.strip()
        different_sha = self._run_git(
            "commit-tree",
            tree_sha,
            "-m",
            "different origin",
        ).stdout.strip()
        self._run_git("update-ref", "refs/remotes/origin/main", different_sha)

        result = self._run_release(self.commit_sha)

        self.assertEqual(result.returncode, 1)
        self.assertIn("The requested SHA is not the current origin/main commit", result.stderr)


if __name__ == "__main__":
    unittest.main()
