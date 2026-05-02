#!/usr/bin/env python3
"""Validate Spec Kit artifacts and implementation against repository evidence."""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from context_grounding import (
    PHASES,
    BLOCKING_HIGH_CATEGORIES,
    Finding,
    append_audit,
    detect_project_types,
    feature_path,
    find_feature_dir,
    finding_dicts,
    implementation_changed_files,
    load_artifacts,
    out_dir,
    package_dependencies,
    referenced_paths,
    rel,
    requirement_ids,
    resolve_phase,
    run_safe_commands,
    safe_commands,
    scenario_headers,
    table_cell,
    task_entries,
    verdict_from_findings,
    write_json,
)


def add_missing_artifact_findings(
    root: Path,
    feature_dir: Path | None,
    artifacts: dict[str, tuple[Path, str]],
    required: Iterable[str],
    findings: list[Finding],
) -> None:
    for name in required:
        if name in artifacts:
            continue
        location = rel(feature_dir / name, root) if feature_dir else f"specs/<feature>/{name}"
        findings.append(
            Finding(
                "CRITICAL",
                "Artifacts",
                location,
                f"Required artifact {name} is missing.",
                f"Create {name} before validating this phase.",
            )
        )


def add_feature_resolution_findings(root: Path, findings: list[Finding]) -> tuple[Any, Path | None]:
    resolution = find_feature_dir(root)
    if resolution.ambiguous:
        findings.append(
            Finding(
                "CRITICAL",
                "Feature resolution",
                "specs/",
                f"{resolution.reason} Candidates: {', '.join(resolution.candidates)}",
                "Resolve the active Spec Kit feature directory before running validation.",
            )
        )
    elif resolution.feature_dir is None:
        findings.append(
            Finding(
                "CRITICAL",
                "Feature resolution",
                "specs/",
                resolution.reason,
                "Run the Spec Kit phase that creates the feature directory before validation.",
            )
        )
    return resolution, feature_path(root, resolution)


def check_referenced_paths(
    root: Path,
    feature_dir: Path | None,
    artifacts: dict[str, tuple[Path, str]],
    names: Iterable[str],
    findings: list[Finding],
) -> list[dict[str, str]]:
    if feature_dir is None:
        return []
    refs = referenced_paths(root, feature_dir, artifacts, names)
    for ref in refs:
        if ref.status == "missing":
            findings.append(
                Finding(
                    "HIGH",
                    "Referenced files",
                    ref.location,
                    f"`{ref.path}` was referenced but not found.",
                    "Fix the path, create the planned file, or mark it explicitly as new.",
                )
            )
    return [asdict(ref) for ref in refs]


def validate_specify(
    root: Path,
    feature_dir: Path | None,
    artifacts: dict[str, tuple[Path, str]],
    findings: list[Finding],
    coverage: list[dict[str, str]],
    compatibility: list[dict[str, str]],
) -> None:
    add_missing_artifact_findings(root, feature_dir, artifacts, ("spec.md",), findings)
    if "spec.md" not in artifacts:
        return

    path, spec_text = artifacts["spec.md"]
    path_label = rel(path, root)
    fr_ids = requirement_ids(spec_text)
    scenarios = scenario_headers(spec_text)

    if not fr_ids:
        findings.append(
            Finding(
                "MEDIUM",
                "Requirement coverage",
                path_label,
                "No FR-### requirement IDs were found.",
                "Use stable requirement IDs so later validation can map tasks and implementation back to requirements.",
            )
        )
    else:
        for fr_id in fr_ids:
            coverage.append(
                {
                    "requirement": fr_id,
                    "covered": "YES",
                    "evidence": "Requirement ID appears in spec.md.",
                    "notes": "Later phases must map this ID to tasks and implementation.",
                }
            )

    if "[NEEDS CLARIFICATION" in spec_text:
        findings.append(
            Finding(
                "HIGH",
                "Spec clarity",
                path_label,
                "Spec contains [NEEDS CLARIFICATION].",
                "Resolve clarification markers before planning.",
            )
        )

    placeholder_hits = [line.strip() for line in spec_text.splitlines() if re.search(r"\b(TODO|TBD|FIXME)\b", line, re.I)]
    if placeholder_hits:
        findings.append(
            Finding(
                "MEDIUM",
                "Spec clarity",
                path_label,
                f"Placeholder text remains: {placeholder_hits[0][:120]}",
                "Replace placeholders with testable requirements or explicit out-of-scope notes.",
            )
        )

    has_success = re.search(r"success criteria|measurable|acceptance criteria", spec_text, re.I)
    if not has_success:
        findings.append(
            Finding(
                "HIGH",
                "Spec testability",
                path_label,
                "No success criteria or acceptance criteria section was detected.",
                "Add measurable success criteria before planning.",
            )
        )

    if not scenarios:
        findings.append(
            Finding(
                "MEDIUM",
                "Spec testability",
                path_label,
                "No scenario/user story/acceptance headers were detected.",
                "Add scenario or user story sections that can drive validation.",
            )
        )
    for scenario in scenarios:
        coverage.append(
            {
                "requirement": scenario,
                "covered": "YES",
                "evidence": "Scenario-like heading appears in spec.md.",
                "notes": "Later phases must schedule tasks or tests for this scenario.",
            }
        )

    refs = referenced_paths(root, feature_dir or root, artifacts, ("spec.md",))
    if refs:
        findings.append(
            Finding(
                "LOW",
                "Spec abstraction",
                path_label,
                f"Spec contains {len(refs)} file path reference(s).",
                "Keep spec user-facing; move implementation paths to plan.md unless explicitly needed.",
            )
        )

    compatibility.append({"check": "spec.md present", "result": "PASS", "evidence": path_label})


def validate_plan(
    root: Path,
    feature_dir: Path | None,
    artifacts: dict[str, tuple[Path, str]],
    findings: list[Finding],
    compatibility: list[dict[str, str]],
    path_refs: list[dict[str, str]],
) -> None:
    add_missing_artifact_findings(root, feature_dir, artifacts, ("spec.md", "plan.md"), findings)
    if "plan.md" not in artifacts:
        return

    path, plan_text = artifacts["plan.md"]
    path_label = rel(path, root)
    refs = check_referenced_paths(root, feature_dir, artifacts, ("plan.md",), findings)
    path_refs.extend(refs)
    missing = sum(1 for ref in refs if ref["status"] == "missing")
    compatibility.append(
        {
            "check": "plan.md referenced paths",
            "result": "FAIL" if missing else "PASS",
            "evidence": f"{len(refs) - missing}/{len(refs)} valid",
        }
    )

    commands = safe_commands(root)
    if commands and not re.search(r"\b(test|tests|lint|validation|pytest|ruff|npm|pnpm|go test|cargo test)\b", plan_text, re.I):
        findings.append(
            Finding(
                "MEDIUM",
                "Test strategy",
                path_label,
                "Detected safe project checks, but plan.md does not mention a validation strategy.",
                "Include the detected test/lint commands or explain why they are not applicable.",
            )
        )

    package_deps = package_dependencies(root)
    possible_new_deps = sorted(
        set(re.findall(r"(?:add|install|dependency|package|library)\s+`?(@?[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+|[A-Za-z0-9_.-]+)`?", plan_text, re.I))
    )
    unknown = [dep for dep in possible_new_deps if dep not in package_deps]
    if unknown:
        findings.append(
            Finding(
                "MEDIUM",
                "Dependencies",
                path_label,
                f"Plan appears to introduce or reference dependencies not found in package.json: {', '.join(unknown[:8])}",
                "Confirm dependencies are already present or explicitly justify adding them.",
            )
        )

    project_types = ", ".join(detect_project_types(root))
    compatibility.append({"check": "Project type detected", "result": "PASS", "evidence": project_types})
    compatibility.append({"check": "plan.md present", "result": "PASS", "evidence": path_label})


def validate_tasks(
    root: Path,
    feature_dir: Path | None,
    artifacts: dict[str, tuple[Path, str]],
    findings: list[Finding],
    coverage: list[dict[str, str]],
    compatibility: list[dict[str, str]],
    path_refs: list[dict[str, str]],
) -> None:
    add_missing_artifact_findings(root, feature_dir, artifacts, ("spec.md", "plan.md", "tasks.md"), findings)
    if "tasks.md" not in artifacts:
        return

    path, tasks_text = artifacts["tasks.md"]
    path_label = rel(path, root)
    spec_text = artifacts.get("spec.md", (Path(), ""))[1]
    refs = check_referenced_paths(root, feature_dir, artifacts, ("tasks.md",), findings)
    path_refs.extend(refs)

    entries = task_entries(tasks_text)
    if not entries:
        findings.append(
            Finding(
                "HIGH",
                "Task feasibility",
                path_label,
                "No checkbox task entries were detected.",
                "Use concrete checkbox tasks with file-level detail.",
            )
        )

    vague = [f"{lineno}: {body}" for lineno, _, body in entries if re.search(r"\bimplement (the )?feature\b", body, re.I)]
    if vague:
        findings.append(
            Finding(
                "HIGH",
                "Task feasibility",
                f"{path_label}:{vague[0].split(':', 1)[0]}",
                f"Vague task detected: {vague[0]}",
                "Break vague work into concrete file-level implementation and test tasks.",
            )
        )

    fr_ids = requirement_ids(spec_text)
    for fr_id in fr_ids:
        found = bool(re.search(rf"\b{re.escape(fr_id)}\b", tasks_text, re.I))
        coverage.append(
            {
                "requirement": fr_id,
                "covered": "YES" if found else "NO",
                "evidence": "tasks.md references requirement" if found else "No matching task found.",
                "notes": "Mechanical coverage only; semantic correctness still needs review.",
            }
        )
        if not found:
            findings.append(
                Finding(
                    "HIGH",
                    "Requirement coverage",
                    rel(artifacts.get("spec.md", (path, ""))[0], root),
                    f"{fr_id} appears in spec.md but not in tasks.md.",
                    "Add explicit tasks for this functional requirement.",
                )
            )

    scenarios = scenario_headers(spec_text)
    for scenario in scenarios:
        keywords = [word for word in re.sub(r"[^a-z0-9]+", " ", scenario.lower()).split() if len(word) > 4][:5]
        hits = [word for word in keywords if word in tasks_text.lower()]
        coverage.append(
            {
                "requirement": scenario,
                "covered": "YES" if hits else "UNKNOWN",
                "evidence": ", ".join(hits) if hits else "No keyword evidence in tasks.md.",
                "notes": "Scenario coverage is heuristic.",
            }
        )

    parallel_paths: dict[str, list[str]] = {}
    for lineno, _, body in entries:
        if "[P]" not in body:
            continue
        for match in re.finditer(r"`([^`]+\.[A-Za-z0-9][^`]*)`", body):
            token = match.group(1).replace("\\", "/")
            parallel_paths.setdefault(token, []).append(str(lineno))
    conflicts = {path_text: lines for path_text, lines in parallel_paths.items() if len(lines) > 1}
    if conflicts:
        path_text, lines = next(iter(conflicts.items()))
        findings.append(
            Finding(
                "HIGH",
                "Task feasibility",
                f"{path_label}:{lines[0]}",
                f"Parallel [P] tasks share file `{path_text}` on lines {', '.join(lines)}.",
                "Remove [P] or split the tasks so parallel tasks touch disjoint files.",
            )
        )

    test_lines = [lineno for lineno, _, body in entries if re.search(r"\b(test|tests|pytest|spec)\b", body, re.I)]
    impl_lines = [lineno for lineno, _, body in entries if re.search(r"\b(implement|modify|update|create|add)\b", body, re.I)]
    if test_lines and impl_lines and min(test_lines) > min(impl_lines):
        findings.append(
            Finding(
                "LOW",
                "Task ordering",
                f"{path_label}:{min(impl_lines)}",
                "Implementation tasks appear before the first test task.",
                "Prefer tests before or alongside implementation when practical.",
            )
        )

    compatibility.append({"check": "tasks.md present", "result": "PASS", "evidence": path_label})
    compatibility.append({"check": "Checkbox task entries", "result": "PASS" if entries else "FAIL", "evidence": str(len(entries))})


def validate_implement(
    root: Path,
    feature_dir: Path | None,
    artifacts: dict[str, tuple[Path, str]],
    findings: list[Finding],
    coverage: list[dict[str, str]],
    compatibility: list[dict[str, str]],
    path_refs: list[dict[str, str]],
    run_checks: bool,
) -> list[dict[str, str]]:
    if "plan.md" in artifacts:
        path_refs.extend(check_referenced_paths(root, feature_dir, artifacts, ("plan.md",), findings))
    validate_tasks(root, feature_dir, artifacts, findings, coverage, compatibility, path_refs)

    changed, changed_source = implementation_changed_files(root)
    if changed:
        compatibility.append({"check": "Implementation changes", "result": "PASS", "evidence": f"{changed_source}: {', '.join(changed[:12])}"})
    else:
        findings.append(
            Finding(
                "HIGH",
                "Implementation",
                "git diff/status",
                changed_source,
                "Run implementation before validating, or validate against a branch/commit with feature changes.",
            )
        )

    plan_text = artifacts.get("plan.md", (Path(), ""))[1]
    if plan_text and changed:
        planned_paths = {ref["path"] for ref in path_refs if ref["location"].endswith("plan.md") or "plan.md:" in ref["location"]}
        overlap = [path for path in planned_paths if path in changed or any(path in changed_path for changed_path in changed)]
        result = "PASS" if overlap or not planned_paths else "MANUAL"
        evidence = ", ".join(overlap[:8]) if overlap else "No direct changed-file overlap with extracted plan paths."
        compatibility.append({"check": "Changed files align with plan paths", "result": result, "evidence": evidence})

    command_results: list[dict[str, str]] = []
    if run_checks:
        for result in run_safe_commands(root):
            command_results.append(asdict(result))
            if result.result == "FAIL":
                findings.append(
                    Finding(
                        "HIGH",
                        "Executable checks",
                        result.command,
                        result.notes,
                        "Fix the failing safe project check before proceeding.",
                    )
                )
    else:
        command_results.append({"command": "N/A", "result": "NOT_RUN", "notes": "Executable checks disabled."})
    return command_results


def validate(root: Path, phase: str, run_checks: bool) -> dict[str, Any]:
    findings: list[Finding] = []
    coverage: list[dict[str, str]] = []
    compatibility: list[dict[str, str]] = []
    path_refs: list[dict[str, str]] = []
    command_results: list[dict[str, str]] = []

    resolution, feature_dir = add_feature_resolution_findings(root, findings)
    artifacts = load_artifacts(root, feature_dir)

    if feature_dir is not None:
        compatibility.append({"check": "Feature directory", "result": "PASS", "evidence": rel(feature_dir, root)})

    constitution = root / ".specify" / "memory" / "constitution.md"
    if constitution.exists():
        compatibility.append({"check": "Constitution loaded", "result": "PASS", "evidence": rel(constitution, root)})
    else:
        findings.append(
            Finding(
                "LOW",
                "Constitution",
                ".specify/memory/constitution.md",
                "Constitution file was not found.",
                "Create or restore the project constitution if this project requires constitutional gates.",
            )
        )

    if phase == "specify":
        validate_specify(root, feature_dir, artifacts, findings, coverage, compatibility)
    elif phase == "plan":
        validate_plan(root, feature_dir, artifacts, findings, compatibility, path_refs)
    elif phase == "tasks":
        validate_tasks(root, feature_dir, artifacts, findings, coverage, compatibility, path_refs)
    elif phase == "implement":
        command_results = validate_implement(
            root, feature_dir, artifacts, findings, coverage, compatibility, path_refs, run_checks
        )

    if phase != "implement":
        command_results = [{"command": "N/A", "result": "NOT_RUN", "notes": "Executable checks run only for implement validation."}]

    if path_refs:
        missing = sum(1 for ref in path_refs if ref["status"] == "missing")
        compatibility.append(
            {
                "check": "Referenced files exist or are planned-new",
                "result": "FAIL" if missing else "PASS",
                "evidence": f"{len(path_refs) - missing}/{len(path_refs)} valid",
            }
        )

    if not coverage:
        coverage.append(
            {
                "requirement": "Manual review required",
                "covered": "UNKNOWN",
                "evidence": "No requirements or scenarios were extracted for this phase.",
                "notes": "Check artifacts manually.",
            }
        )

    verdict = verdict_from_findings(findings)
    return {
        "phase": phase,
        "verdict": verdict,
        "feature_resolution": asdict(resolution),
        "findings": finding_dicts(findings),
        "coverage": coverage,
        "repository_compatibility": compatibility,
        "path_references": path_refs,
        "executed_commands": command_results,
        "blocking_categories": sorted(BLOCKING_HIGH_CATEGORIES),
    }


def summary(verdict: str, finding_count: int) -> str:
    if verdict == "FAIL":
        return "Validation failed. Do not proceed to the next Spec Kit phase until blocking findings are resolved."
    if verdict == "PASS_WITH_WARNINGS":
        return f"Validation completed with {finding_count} finding(s). Review residual risks before proceeding."
    return "Validation passed against available repository evidence and safe project checks."


def next_actions(verdict: str, phase: str) -> str:
    if verdict == "FAIL":
        return "Do not proceed. Fix CRITICAL/HIGH findings, rerun validation, and only continue after the verdict improves."
    if verdict == "PASS_WITH_WARNINGS":
        return "Proceed only if the listed risks are acceptable for this feature."
    next_phase = {"specify": "plan", "plan": "tasks", "tasks": "implement", "implement": "review"}.get(phase, "next")
    return f"Proceed to {next_phase}."


def render_markdown(data: dict[str, Any]) -> str:
    lines = [
        f"# Validation Report: {data['phase']}",
        "",
        "## Verdict",
        data["verdict"],
        "",
        "## Summary",
        summary(data["verdict"], len(data["findings"])),
        "",
        "## Findings",
        "| ID | Severity | Category | Location | Evidence | Recommendation |",
        "|----|----------|----------|----------|----------|----------------|",
    ]
    if data["findings"]:
        for index, finding in enumerate(data["findings"], start=1):
            lines.append(
                "| V-{id:03d} | {severity} | {category} | {location} | {evidence} | {recommendation} |".format(
                    id=index,
                    severity=finding["severity"],
                    category=table_cell(finding["category"]),
                    location=table_cell(finding["location"]),
                    evidence=table_cell(finding["evidence"]),
                    recommendation=table_cell(finding["recommendation"]),
                )
            )
    else:
        lines.append("| - | - | - | - | No findings. | - |")

    lines.extend(
        [
            "",
            "## Coverage",
            "| Requirement / Scenario | Covered? | Evidence | Notes |",
            "|------------------------|----------|----------|-------|",
        ]
    )
    for item in data["coverage"]:
        lines.append(
            f"| {table_cell(item['requirement'])} | {item['covered']} | {table_cell(item['evidence'])} | {table_cell(item['notes'])} |"
        )

    lines.extend(
        [
            "",
            "## Repository Compatibility",
            "| Check | Result | Evidence |",
            "|-------|--------|----------|",
        ]
    )
    for item in data["repository_compatibility"]:
        lines.append(f"| {table_cell(item['check'])} | {item['result']} | {table_cell(item['evidence'])} |")

    lines.extend(
        [
            "",
            "## Executed Commands",
            "| Command | Result | Notes |",
            "|---------|--------|-------|",
        ]
    )
    for item in data["executed_commands"]:
        lines.append(f"| {table_cell(item['command'])} | {item['result']} | {table_cell(item['notes'])} |")

    lines.extend(["", "## Next Actions", next_actions(data["verdict"], data["phase"]), ""])
    return "\n".join(lines)


def main(argv: Iterable[str]) -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser()
    parser.add_argument("phase_arg", nargs="?", choices=PHASES)
    parser.add_argument("--phase", choices=PHASES)
    parser.add_argument("--root", default=".")
    parser.add_argument("--skip-checks", action="store_true", help="Do not run implement-stage safe project checks.")
    args = parser.parse_args(list(argv))

    root = Path(args.root).resolve()
    phase = resolve_phase(root, args.phase or args.phase_arg)
    data = validate(root, phase, run_checks=(phase == "implement" and not args.skip_checks))
    markdown = render_markdown(data)

    directory = out_dir(root)
    md_path = directory / f"validation-{phase}.md"
    json_path = directory / f"validation-{phase}.json"
    md_path.write_text(markdown, encoding="utf-8")
    write_json(json_path, data)
    append_audit(
        root,
        "validation",
        {
            "phase": phase,
            "verdict": data["verdict"],
            "report": str(md_path),
            "json": str(json_path),
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
        },
    )

    print(markdown)
    return 1 if data["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
