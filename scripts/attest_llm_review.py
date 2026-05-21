#!/usr/bin/env python3
"""Inject LLM findings + attestation into validation-<phase>.json atomically."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from context_grounding import (
    PHASES,
    append_audit,
    compute_attestation_signature,
    compute_discovery_hash,
    out_dir,
)
from llm_review import load_review


def main(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=PHASES)
    parser.add_argument("--findings", required=True, help="Path to LLM review JSON file")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(list(argv))

    root = Path(args.root).resolve()
    review_path = Path(args.findings).resolve()

    try:
        review = load_review(review_path)
    except Exception as exc:
        print(f"ERROR: invalid review file: {exc}", file=sys.stderr)
        return 2

    if review["phase"] != args.phase:
        print(f"ERROR: phase mismatch (review={review['phase']}, cli={args.phase})", file=sys.stderr)
        return 2

    directory = out_dir(root)
    validation_path = directory / f"validation-{args.phase}.json"
    discovery_path = directory / f"discovery-{args.phase}.json"

    if not validation_path.exists():
        print(f"ERROR: {validation_path} not found. Run validate_artifacts.py first.", file=sys.stderr)
        return 2
    if not discovery_path.exists():
        print(f"ERROR: {discovery_path} not found. Run discover_context.py first.", file=sys.stderr)
        return 2

    discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
    expected_sha = discovery.get("content_sha256") or compute_discovery_hash(discovery)
    if review["discovery_sha256"] != expected_sha:
        print(
            f"ERROR: review.discovery_sha256 ({review['discovery_sha256'][:12]}…) "
            f"!= discovery sha ({expected_sha[:12]}…). Re-run discover or rebase review.",
            file=sys.stderr,
        )
        return 2

    findings = review["findings"]
    generated_at = datetime.now(timezone.utc).isoformat()
    signature = compute_attestation_signature(
        findings=findings,
        reviewer=review["reviewer"],
        generated_at=generated_at,
        discovery_sha256=expected_sha,
    )
    attestation = {
        "reviewer": review["reviewer"],
        "generated_at": generated_at,
        "finding_count": len(findings),
        "no_issues": bool(review["no_issues"]),
        "justification": review.get("justification", ""),
        "discovery_sha256": expected_sha,
        "signature": signature,
    }

    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    validation["llm_findings"] = findings
    validation["llm_attestation"] = attestation
    validation_path.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    append_audit(
        root,
        "llm_attestation",
        {
            "phase": args.phase,
            "reviewer": attestation["reviewer"],
            "finding_count": attestation["finding_count"],
            "no_issues": attestation["no_issues"],
            "discovery_sha256": expected_sha,
            "signature": signature,
        },
    )
    print(json.dumps(attestation, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
