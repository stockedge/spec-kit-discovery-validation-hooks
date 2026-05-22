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

    def test_tampered_signature_is_fail(self) -> None:
        """Editing llm_attestation.signature after attestation triggers CRITICAL."""
        with TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            dc.main(["--phase", "specify", "--root", str(root)])
            va.main(["--phase", "specify", "--root", str(root), "--no-require-trailer", "--no-require-llm-review"])
            disc = json.loads(
                (root / ".specify" / "context-grounding" / "discovery-specify.json").read_text()
            )
            review_path = root / "llm-review-specify.json"
            review_path.write_text(
                json.dumps({
                    "reviewer": "manual:test",
                    "phase": "specify",
                    "discovery_sha256": disc["content_sha256"],
                    "no_issues": True,
                    "justification": "trivial",
                    "findings": [],
                }),
                encoding="utf-8",
            )
            att.main(["--phase", "specify", "--findings", str(review_path), "--root", str(root)])
            # tamper the signature
            val_path = root / ".specify" / "context-grounding" / "validation-specify.json"
            val = json.loads(val_path.read_text())
            val["llm_attestation"]["signature"] = "0" * 64
            val_path.write_text(json.dumps(val, indent=2) + "\n")
            data = va.validate(root, "specify", run_checks=False, require_llm_review=True, require_trailer=False)
            categories = {f["category"] for f in data["findings"]}
            self.assertIn("LLM review", categories)
            self.assertEqual(data["verdict"], "FAIL")

    def test_wrong_discovery_sha_in_review_rejected_by_attest(self) -> None:
        """`attest` returns exit code 2 when discovery_sha256 doesn't match."""
        with TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            dc.main(["--phase", "specify", "--root", str(root)])
            va.main(["--phase", "specify", "--root", str(root), "--no-require-trailer", "--no-require-llm-review"])
            review_path = root / "llm-review-specify.json"
            review_path.write_text(
                json.dumps({
                    "reviewer": "manual:test",
                    "phase": "specify",
                    "discovery_sha256": "c" * 64,
                    "no_issues": True,
                    "justification": "wrong sha",
                    "findings": [],
                }),
                encoding="utf-8",
            )
            rc = att.main(["--phase", "specify", "--findings", str(review_path), "--root", str(root)])
            self.assertEqual(rc, 2)

    def test_load_review_rejects_no_issues_false_with_empty_findings(self) -> None:
        """`load_review` must reject no_issues=False with findings=[]."""
        import llm_review as lr
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "review.json"
            p.write_text(json.dumps({
                "reviewer": "manual:test",
                "phase": "specify",
                "discovery_sha256": "a" * 64,
                "no_issues": False,
                "justification": "",
                "findings": [],
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                lr.load_review(p)


if __name__ == "__main__":
    unittest.main()
