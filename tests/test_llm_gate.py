from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import attest_llm_review as att
import discover_context as dc
import validate_artifacts as va


class TestLLMGate(unittest.TestCase):
    def _make_repo(self, tmp: Path) -> Path:
        (tmp / "specs" / "001-test").mkdir(parents=True)
        (tmp / "specs" / "001-test" / "spec.md").write_text(
            "# Spec\nFR-001 do.\n\n## Success Criteria\n- x.\n",
            encoding="utf-8",
        )
        return tmp

    def test_missing_attestation_is_fail(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            dc.main(["--phase", "specify", "--root", str(root)])
            va.main(["--phase", "specify", "--root", str(root), "--no-require-trailer"])
            data = va.validate(root, "specify", run_checks=False, require_llm_review=True, require_trailer=False)
            categories = {f["category"] for f in data["findings"]}
            self.assertIn("LLM review", categories)
            self.assertEqual(data["verdict"], "FAIL")

    def test_attestation_pipeline(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            dc.main(["--phase", "specify", "--root", str(root)])
            va.main(["--phase", "specify", "--root", str(root), "--no-require-trailer", "--no-require-llm-review"])
            disc = json.loads(
                (root / ".specify" / "context-grounding" / "discovery-specify.json").read_text()
            )
            review_path = root / "llm-review-specify.json"
            review_path.write_text(
                json.dumps(
                    {
                        "reviewer": "manual:test",
                        "phase": "specify",
                        "discovery_sha256": disc["content_sha256"],
                        "no_issues": True,
                        "justification": "trivial spec, no issues",
                        "findings": [],
                    }
                ),
                encoding="utf-8",
            )
            rc = att.main(["--phase", "specify", "--findings", str(review_path), "--root", str(root)])
            self.assertEqual(rc, 0)
            data = va.validate(root, "specify", run_checks=False, require_llm_review=True, require_trailer=False)
            categories = {f["category"] for f in data["findings"]}
            self.assertNotIn("LLM review", categories)


if __name__ == "__main__":
    unittest.main()
