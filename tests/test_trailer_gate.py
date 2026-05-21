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


if __name__ == "__main__":
    unittest.main()
