#!/usr/bin/env python3
"""Generate phase-scoped repository discovery reports for Spec Kit."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from context_grounding import (
    PHASES,
    append_audit,
    current_branch,
    detect_project_types,
    docs_and_instructions,
    feature_path,
    find_feature_dir,
    git_status_short,
    latest_git_log,
    manifest_paths,
    out_dir,
    read_text,
    rel,
    resolve_phase,
    root_structure,
    safe_commands,
    source_layout,
    status_changed_files,
    table_cell,
    write_json,
)


def summarize_file(path: Path, root: Path) -> str:
    text = read_text(path)
    first_heading = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            first_heading = stripped.lstrip("# ").strip()
            break
    if first_heading:
        return first_heading[:120]
    return f"{len(text.splitlines())} lines"


def discovery_data(root: Path, phase: str) -> dict[str, Any]:
    resolution = find_feature_dir(root)
    feature_dir = feature_path(root, resolution)
    branch = current_branch(root) or "(unknown)"
    status = git_status_short(root)
    changed = status_changed_files(root)
    manifests = manifest_paths(root)
    docs = docs_and_instructions(root)
    layout = source_layout(root)
    commands = safe_commands(root)
    project_types = detect_project_types(root)
    git_log = latest_git_log(root)

    relevant_files: list[dict[str, str]] = []
    if feature_dir:
        for name in ("spec.md", "plan.md", "tasks.md", "research.md", "data-model.md", "quickstart.md"):
            path = feature_dir / name
            if path.exists():
                relevant_files.append(
                    {
                        "path": rel(path, root),
                        "why": f"Current feature artifact for {phase}",
                        "evidence": summarize_file(path, root),
                    }
                )
    for path in docs[:10]:
        relevant_files.append(
            {"path": rel(path, root), "why": "Project or agent instruction context", "evidence": summarize_file(path, root)}
        )
    for path in manifests[:12]:
        relevant_files.append(
            {"path": rel(path, root), "why": "Build, dependency, or validation manifest", "evidence": path.name}
        )
    for path in layout:
        relevant_files.append(
            {"path": rel(path, root), "why": "Existing source or test layout", "evidence": "directory exists"}
        )

    patterns: list[dict[str, str]] = [
        {
            "pattern": "Project type",
            "evidence": ", ".join(project_types),
            "implication": "Use detected manifests and layout before introducing new tools.",
        },
        {
            "pattern": "Git branch/status",
            "evidence": f"branch={branch}; changed_files={len(changed)}",
            "implication": "Ground phase work in the current branch and avoid unrelated dirty files.",
        },
    ]
    if git_log:
        patterns.append(
            {
                "pattern": "Recent repository history",
                "evidence": "; ".join(git_log[:3]),
                "implication": "Prefer conventions visible in recent changes.",
            }
        )

    dependencies = [
        {"tool": rel(path, root), "found_where": path.name, "notes": "manifest present"} for path in manifests[:20]
    ]

    tests = [
        {"command": command.label, "confidence": command.confidence, "source": command.source} for command in commands
    ]

    risks: list[dict[str, str]] = []
    constitution = root / ".specify" / "memory" / "constitution.md"
    if not constitution.exists():
        risks.append(
            {
                "risk": "Constitution unavailable",
                "severity": "LOW",
                "evidence": ".specify/memory/constitution.md not found",
                "mitigation": "Create or restore the constitution if this project uses constitutional gates.",
            }
        )
    if resolution.ambiguous:
        risks.append(
            {
                "risk": "Ambiguous feature directory",
                "severity": "HIGH",
                "evidence": f"{resolution.reason} Candidates: {', '.join(resolution.candidates)}",
                "mitigation": "Pass an explicit phase and resolve the active Spec Kit feature before validation.",
            }
        )
    if not tests:
        risks.append(
            {
                "risk": "No safe project checks detected",
                "severity": "MEDIUM",
                "evidence": "No supported test/lint command was inferred from manifests.",
                "mitigation": "Validate manually or add test/lint scripts to project manifests.",
            }
        )
    if status.strip():
        risks.append(
            {
                "risk": "Dirty worktree",
                "severity": "MEDIUM",
                "evidence": status.strip().splitlines()[0],
                "mitigation": "Avoid mixing unrelated changes with the current Spec Kit feature.",
            }
        )

    guidance = {
        "specify": "Use repository terminology and existing user-facing flows. Do not name APIs or dependencies that discovery did not find.",
        "plan": "Reference exact existing files where possible, and mark new paths explicitly as new.",
        "tasks": "Map tasks to FR IDs and file paths. Only mark tasks parallel when their file sets do not overlap.",
        "implement": "Start from current task file references, keep changes scoped to planned files, then run detected safe checks.",
    }[phase]

    summary = [
        f"Current branch: {branch}.",
        f"Project type(s): {', '.join(project_types)}.",
        f"Root entries sampled: {', '.join(root_structure(root)[:12]) or '(empty)'}.",
        f"Feature directory: {resolution.feature_dir or '(unresolved)'} ({resolution.reason})",
        f"Detected manifest count: {len(manifests)}.",
        f"Detected safe check count: {len(tests)}.",
    ]

    return {
        "phase": phase,
        "summary": summary,
        "feature_resolution": asdict(resolution),
        "branch": branch,
        "git_status": status.strip(),
        "recent_git_log": git_log,
        "root_structure": root_structure(root),
        "relevant_files": relevant_files,
        "existing_patterns": patterns,
        "dependencies_and_tooling": dependencies,
        "test_and_validation_commands": tests,
        "risks": risks,
        "guidance": guidance,
    }


def render_markdown(data: dict[str, Any]) -> str:
    lines = [
        f"# Discovery Report: {data['phase']}",
        "",
        "## Summary",
    ]
    lines.extend(f"- {item}" for item in data["summary"])

    lines.extend(
        [
            "",
            "## Relevant Files",
            "| Path | Why it matters | Evidence |",
            "|------|----------------|----------|",
        ]
    )
    for item in data["relevant_files"] or []:
        lines.append(
            f"| {table_cell(item['path'])} | {table_cell(item['why'])} | {table_cell(item['evidence'])} |"
        )
    if not data["relevant_files"]:
        lines.append("| - | - | No relevant files detected. |")

    lines.extend(
        [
            "",
            "## Existing Patterns",
            "| Pattern | Evidence | Implication |",
            "|---------|----------|-------------|",
        ]
    )
    for item in data["existing_patterns"]:
        lines.append(
            f"| {table_cell(item['pattern'])} | {table_cell(item['evidence'])} | {table_cell(item['implication'])} |"
        )

    lines.extend(
        [
            "",
            "## Dependencies and Tooling",
            "| Tool/Dependency | Found where | Notes |",
            "|-----------------|-------------|-------|",
        ]
    )
    for item in data["dependencies_and_tooling"] or []:
        lines.append(
            f"| {table_cell(item['tool'])} | {table_cell(item['found_where'])} | {table_cell(item['notes'])} |"
        )
    if not data["dependencies_and_tooling"]:
        lines.append("| - | - | No manifests detected. |")

    lines.extend(
        [
            "",
            "## Test and Validation Commands",
            "| Command | Confidence | Source |",
            "|---------|------------|--------|",
        ]
    )
    for item in data["test_and_validation_commands"] or []:
        lines.append(
            f"| {table_cell(item['command'])} | {table_cell(item['confidence'])} | {table_cell(item['source'])} |"
        )
    if not data["test_and_validation_commands"]:
        lines.append("| - | - | No safe commands detected. |")

    lines.extend(
        [
            "",
            "## Risks / Constraints",
            "| Risk | Severity | Evidence | Mitigation |",
            "|------|----------|----------|------------|",
        ]
    )
    for item in data["risks"] or []:
        lines.append(
            f"| {table_cell(item['risk'])} | {item['severity']} | {table_cell(item['evidence'])} | {table_cell(item['mitigation'])} |"
        )
    if not data["risks"]:
        lines.append("| - | - | No material discovery risks detected. | - |")

    lines.extend(["", "## Guidance for Next Phase", data["guidance"], ""])
    return "\n".join(lines)


def main(argv: Iterable[str]) -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser()
    parser.add_argument("phase_arg", nargs="?", choices=PHASES)
    parser.add_argument("--phase", choices=PHASES)
    parser.add_argument("--root", default=".")
    args = parser.parse_args(list(argv))

    root = Path(args.root).resolve()
    phase = resolve_phase(root, args.phase or args.phase_arg)
    data = discovery_data(root, phase)
    markdown = render_markdown(data)

    directory = out_dir(root)
    md_path = directory / f"discovery-{phase}.md"
    json_path = directory / f"discovery-{phase}.json"
    md_path.write_text(markdown, encoding="utf-8")
    write_json(json_path, data)
    append_audit(
        root,
        "discovery",
        {
            "phase": phase,
            "report": str(md_path),
            "json": str(json_path),
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
        },
    )

    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
