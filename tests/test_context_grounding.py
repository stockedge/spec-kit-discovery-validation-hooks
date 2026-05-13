from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from context_grounding import (
    current_branch,
    find_feature_dir,
    implementation_changed_files,
    is_jj_repo,
    jj_changed_files,
    path_status,
    safe_commands,
)
from validate_artifacts import validate


class ContextGroundingTests(unittest.TestCase):
    def test_feature_resolution_does_not_guess_when_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "specs" / "001-a").mkdir(parents=True)
            (root / "specs" / "002-b").mkdir(parents=True)
            (root / "specs" / "001-a" / "tasks.md").write_text("- [ ] A\n", encoding="utf-8")
            (root / "specs" / "002-b" / "tasks.md").write_text("- [ ] B\n", encoding="utf-8")

            result = find_feature_dir(root)

            self.assertTrue(result.ambiguous)
            self.assertIsNone(result.feature_dir)
            self.assertIn("Multiple feature directories", result.reason)

    def test_planned_new_path_marker_is_not_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_dir = root / "specs" / "001-demo"
            artifact_dir.mkdir(parents=True)

            status, evidence = path_status("src/new_module.py", root, artifact_dir, "Create new `src/new_module.py`")

            self.assertEqual(status, "planned-new")
            self.assertIn("planned", evidence)

    def test_tasks_validation_fails_parallel_same_file_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feature = root / "specs" / "001-demo"
            (root / "src").mkdir()
            feature.mkdir(parents=True)
            (root / "src" / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            (feature / "spec.md").write_text(
                "# Demo\n\n"
                "## User Story 1\n"
                "### Acceptance Scenario\n"
                "User runs the demo.\n\n"
                "## Requirements\n"
                "- FR-001: The demo must update a value.\n\n"
                "## Success Criteria\n"
                "- Operation completes successfully.\n",
                encoding="utf-8",
            )
            (feature / "plan.md").write_text("Modify `src/a.py`.\n", encoding="utf-8")
            (feature / "tasks.md").write_text(
                "- [ ] T001 [P] Update `src/a.py` for FR-001\n"
                "- [ ] T002 [P] Test `src/a.py` for FR-001\n",
                encoding="utf-8",
            )

            result = validate(root, "tasks", run_checks=False)

            self.assertEqual(result["verdict"], "FAIL")
            self.assertTrue(any(f["category"] == "Task feasibility" for f in result["findings"]))

    def test_safe_commands_detect_package_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                '{"scripts": {"test": "vitest run", "lint": "eslint ."}}\n',
                encoding="utf-8",
            )

            labels = [command.label for command in safe_commands(root)]

            self.assertIn("npm test", labels)
            self.assertIn("npm run lint", labels)

    @unittest.skipIf(shutil.which("git") is None, "git is not available")
    def test_committed_changes_count_as_implementation_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "checkout", "-b", "feature/demo"], cwd=root, check=True, capture_output=True, text=True)
            (root / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            subprocess.run(["git", "commit", "-am", "feature"], cwd=root, check=True, capture_output=True, text=True)

            changed, source = implementation_changed_files(root)

            self.assertIn("app.py", changed)
            self.assertIn("committed", source)


JJ = shutil.which("jj") or "jj"


@unittest.skipIf(shutil.which("jj") is None, "jj is not available")
class JujutsuTests(unittest.TestCase):
    def _init_jj_repo(self, root: Path) -> None:
        subprocess.run([JJ, "git", "init"], cwd=root, check=True, capture_output=True, text=True)

    def test_is_jj_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(is_jj_repo(root))
            self._init_jj_repo(root)
            self.assertTrue(is_jj_repo(root))

    def test_current_branch_from_jj_bookmark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_jj_repo(root)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run([JJ, "commit", "-m", "initial"], cwd=root, check=True, capture_output=True)
            subprocess.run(
                ["jj", "bookmark", "create", "feature/demo", "-r", "@"],
                cwd=root, check=True, capture_output=True,
            )

            branch = current_branch(root)

            self.assertEqual(branch, "feature/demo")

    def test_current_branch_falls_back_to_parent_bookmark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_jj_repo(root)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run([JJ, "commit", "-m", "initial"], cwd=root, check=True, capture_output=True)
            subprocess.run(
                ["jj", "bookmark", "create", "feature/demo", "-r", "@-"],
                cwd=root, check=True, capture_output=True,
            )

            branch = current_branch(root)

            self.assertEqual(branch, "feature/demo")

    def test_jj_changed_files_detects_diff_from_trunk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_jj_repo(root)
            (root / "base.py").write_text("BASE = 1\n", encoding="utf-8")
            subprocess.run([JJ, "commit", "-m", "initial on main"], cwd=root, check=True, capture_output=True)
            subprocess.run([JJ, "bookmark", "set", "main", "-r", "@-"], cwd=root, check=True, capture_output=True)
            (root / "feature.py").write_text("FEATURE = 1\n", encoding="utf-8")
            subprocess.run([JJ, "commit", "-m", "add feature"], cwd=root, check=True, capture_output=True)

            changed = jj_changed_files(root)

            self.assertIn("base.py", changed)
            self.assertIn("feature.py", changed)

    def test_implementation_changed_files_in_jj_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_jj_repo(root)
            (root / "base.py").write_text("BASE = 1\n", encoding="utf-8")
            subprocess.run([JJ, "commit", "-m", "initial on main"], cwd=root, check=True, capture_output=True)
            subprocess.run([JJ, "bookmark", "set", "main", "-r", "@-"], cwd=root, check=True, capture_output=True)
            (root / "feature.py").write_text("FEATURE = 1\n", encoding="utf-8")
            subprocess.run([JJ, "commit", "-m", "add feature"], cwd=root, check=True, capture_output=True)

            changed, _source = implementation_changed_files(root)

            self.assertIn("feature.py", changed)

    def test_feature_resolution_with_jj_bookmark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_jj_repo(root)
            (root / "specs" / "feature-demo").mkdir(parents=True)
            (root / "specs" / "feature-demo" / "spec.md").write_text("# Demo\n", encoding="utf-8")
            (root / "specs" / "other-feature").mkdir(parents=True)
            (root / "specs" / "other-feature" / "spec.md").write_text("# Other\n", encoding="utf-8")
            subprocess.run([JJ, "commit", "-m", "initial"], cwd=root, check=True, capture_output=True)
            subprocess.run(
                ["jj", "bookmark", "create", "feature-demo", "-r", "@"],
                cwd=root, check=True, capture_output=True,
            )

            result = find_feature_dir(root)

            self.assertFalse(result.ambiguous)
            self.assertEqual(result.feature_dir, "specs/feature-demo")


if __name__ == "__main__":
    unittest.main()
