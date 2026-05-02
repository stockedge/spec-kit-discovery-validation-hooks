#!/usr/bin/env python3
"""Backward-compatible entrypoint for implementation validation.

The full validator now lives in validate_artifacts.py and supports all Spec Kit
phases. This wrapper preserves the README/extension command documented before
v0.2 while delegating to the shared validator.
"""

from __future__ import annotations

import sys

from validate_artifacts import main


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--phase" not in argv and not any(arg in {"specify", "plan", "tasks", "implement"} for arg in argv):
        argv = ["--phase", "implement", *argv]
    raise SystemExit(main(argv))
