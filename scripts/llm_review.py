#!/usr/bin/env python3
"""Schema utilities for LLM review files consumed by attest_llm_review.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_FINDING_KEYS = {"id", "severity", "category", "location", "evidence", "recommendation"}
ALLOWED_SEVERITY = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def load_review(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("review file must be a JSON object")
    for required in ("reviewer", "phase", "discovery_sha256", "no_issues", "justification", "findings"):
        if required not in data:
            raise ValueError(f"missing key: {required}")
    if not isinstance(data["findings"], list):
        raise ValueError("findings must be a list")
    for i, f in enumerate(data["findings"]):
        if not isinstance(f, dict):
            raise ValueError(f"finding[{i}] must be a JSON object")
        missing = REQUIRED_FINDING_KEYS - set(f)
        if missing:
            raise ValueError(f"finding[{i}] missing: {sorted(missing)}")
        if f["severity"] not in ALLOWED_SEVERITY:
            raise ValueError(f"finding[{i}].severity invalid: {f['severity']}")
    return data


if __name__ == "__main__":
    try:
        load_review(Path(sys.argv[1]))
    except Exception as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print("OK")
