#!/usr/bin/env python3
"""Schema utilities for LLM review files consumed by attest_llm_review.py."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REQUIRED_FINDING_KEYS = {"id", "severity", "category", "location", "evidence", "recommendation"}
ALLOWED_SEVERITY = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
MAX_FINDINGS = 500
_HEX64 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def load_review(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("review file must be a JSON object")
    for required in ("reviewer", "phase", "discovery_sha256", "no_issues", "justification", "findings"):
        if required not in data:
            raise ValueError(f"missing key: {required}")
    if not isinstance(data["reviewer"], str) or not data["reviewer"].strip():
        raise ValueError("reviewer must be a non-empty string")
    if not isinstance(data["discovery_sha256"], str) or not _HEX64.match(data["discovery_sha256"]):
        raise ValueError("discovery_sha256 must be a 64-char hex string")
    if not isinstance(data["findings"], list):
        raise ValueError("findings must be a list")
    if len(data["findings"]) > MAX_FINDINGS:
        raise ValueError(f"findings list exceeds maximum allowed length ({MAX_FINDINGS})")
    for i, f in enumerate(data["findings"]):
        if not isinstance(f, dict):
            raise ValueError(f"finding[{i}] must be a JSON object")
        missing = REQUIRED_FINDING_KEYS - set(f)
        if missing:
            raise ValueError(f"finding[{i}] missing: {sorted(missing)}")
        if f["severity"] not in ALLOWED_SEVERITY:
            raise ValueError(f"finding[{i}].severity invalid: {f['severity']}")
    if not data["no_issues"] and not data["findings"]:
        raise ValueError("no_issues=false requires at least one finding")
    return data


if __name__ == "__main__":
    try:
        load_review(Path(sys.argv[1]))
    except Exception as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print("OK")
