from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import discover_context as dc
import validate_artifacts as va


class TestTrailerGate(unittest.TestCase):
    def _make_repo(self, tmp: Path) -> Path:
        (tmp / "specs" / "001-test").mkdir(parents=True)
        (tmp / "specs" / "001-test" / "spec.md").write_text(
            "# Spec\nFR-001 do thing.\n\n## Success Criteria\n- x.\n",
            encoding="utf-8",
        )
        return tmp

    def test_missing_trailer_is_fail(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            dc.main(["--phase", "specify", "--root", str(root)])
            data = va.validate(root, "specify", run_checks=False, require_llm_review=False, require_trailer=True)
            categories = {f["category"] for f in data["findings"]}
            self.assertIn("Grounding trailer", categories)
            self.assertEqual(data["verdict"], "FAIL")

    def test_valid_trailer_passes_trailer_check(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            dc.main(["--phase", "specify", "--root", str(root)])
            disc = json.loads(
                (root / ".specify" / "context-grounding" / "discovery-specify.json").read_text()
            )
            sha = disc["content_sha256"]
            spec_path = root / "specs" / "001-test" / "spec.md"
            spec_path.write_text(
                spec_path.read_text()
                + f"\n<!-- grounded-by: .specify/context-grounding/discovery-specify.json sha256={sha} -->\n",
                encoding="utf-8",
            )
            data = va.validate(root, "specify", run_checks=False, require_llm_review=False, require_trailer=True)
            categories = {f["category"] for f in data["findings"]}
            self.assertNotIn("Grounding trailer", categories)

    def test_stale_trailer_sha_mismatch_is_fail(self) -> None:
        """Re-running discover invalidates an old trailer SHA."""
        with TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            dc.main(["--phase", "specify", "--root", str(root)])
            stale_sha = "a" * 64
            spec_path = root / "specs" / "001-test" / "spec.md"
            spec_path.write_text(
                spec_path.read_text()
                + f"\n<!-- grounded-by: .specify/context-grounding/discovery-specify.json sha256={stale_sha} -->\n",
                encoding="utf-8",
            )
            data = va.validate(root, "specify", run_checks=False, require_llm_review=False, require_trailer=True)
            categories = {f["category"] for f in data["findings"]}
            self.assertIn("Grounding trailer", categories)
            self.assertEqual(data["verdict"], "FAIL")

    def test_path_traversal_trailer_is_rejected(self) -> None:
        """A trailer pointing outside .specify/context-grounding/ must be rejected."""
        with TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            dc.main(["--phase", "specify", "--root", str(root)])
            fake_sha = "b" * 64
            spec_path = root / "specs" / "001-test" / "spec.md"
            spec_path.write_text(
                spec_path.read_text()
                + f"\n<!-- grounded-by: ../../evil.json sha256={fake_sha} -->\n",
                encoding="utf-8",
            )
            data = va.validate(root, "specify", run_checks=False, require_llm_review=False, require_trailer=True)
            categories = {f["category"] for f in data["findings"]}
            self.assertIn("Grounding trailer", categories)
            self.assertEqual(data["verdict"], "FAIL")

    def test_no_require_flags_yield_not_run(self) -> None:
        """--no-require-* flags produce NOT_RUN rows, not FAIL."""
        with TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            dc.main(["--phase", "specify", "--root", str(root)])
            data = va.validate(root, "specify", run_checks=False, require_llm_review=False, require_trailer=False)
            compat = {r["check"]: r["result"] for r in data["repository_compatibility"]}
            self.assertEqual(compat.get("Grounding trailer"), "NOT_RUN")
            self.assertEqual(compat.get("LLM review"), "NOT_RUN")


if __name__ == "__main__":
    unittest.main()
