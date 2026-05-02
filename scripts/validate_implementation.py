#!/usr/bin/env python3
"""Repository-grounded implementation validator for Spec Kit artifacts.

This script is intentionally conservative:
- no package installation
- no destructive commands
- no source edits
- only stdlib parsing and safe subprocess checks with timeouts
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
BLOCKING_HIGH_CATEGORIES = {
    "Artifacts",
    "Executable checks",
    "Implementation",
    "Referenced files",
    "Requirement coverage",
}
PATH_TOKEN = re.compile(
    r"(?:`([^`\n]+\.[A-Za-z0-9][^`\n]*)`)|"
    r"(?<![\w/.-])([A-Za-z0-9_./\\-]+/[A-Za-z0-9_./\\-]+\.[A-Za-z0-9_./\\-]+)"
)
FR_ID = re.compile(r"\bFR-\d{3,}\b", re.IGNORECASE)
SCENARIO = re.compile(r"^\s*#{2,4}\s+.*(?:scenario|user story|acceptance|journey|flow).*", re.IGNORECASE)


@dataclass
class Finding:
    severity: str
    category: str
    location: str
    evidence: str
    recommendation: str


@dataclass
class CommandResult:
    command: str
    result: str
    notes: str


def run(args: list[str], cwd: Path, timeout: int = 120) -> tuple[int, str]:
    command = args[:]
    if command and not Path(command[0]).is_absolute():
        resolved = shutil.which(command[0])
        if resolved:
            command[0] = resolved

    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            shell=False,
        )
        output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
        return completed.returncode, output[-2000:]
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(
            part.strip() for part in (exc.stdout or "", exc.stderr or "") if isinstance(part, str) and part.strip()
        )
        return 124, f"Timed out after {timeout}s. {output[-1000:]}"
    except FileNotFoundError:
        return 127, f"Command not found: {args[0]}"


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def find_feature_dir(root: Path) -> Path | None:
    specs = root / "specs"
    if not specs.exists():
        return None

    candidates = [p for p in specs.iterdir() if p.is_dir()]
    if not candidates:
        return None

    branch = git_output(root, ["branch", "--show-current"]).strip()
    if branch:
        for candidate in candidates:
            if candidate.name == branch or candidate.name in branch or branch in candidate.name:
                return candidate

    with_tasks = [p for p in candidates if (p / "tasks.md").exists()]
    if len(with_tasks) == 1:
        return with_tasks[0]

    with_plan = [p for p in candidates if (p / "plan.md").exists()]
    if len(with_plan) == 1:
        return with_plan[0]

    return max(candidates, key=lambda p: p.stat().st_mtime)


def git_output(root: Path, args: list[str]) -> str:
    if not command_exists("git"):
        return ""
    code, out = run(["git", *args], root, timeout=30)
    return out if code == 0 else ""


def changed_files(root: Path) -> list[str]:
    status = git_output(root, ["status", "--short", "--untracked-files=all"])
    files: list[str] = []
    for line in status.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        files.append(path.replace("\\", "/"))
    return files


def extract_paths(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in PATH_TOKEN.finditer(line):
            token = (match.group(1) or match.group(2) or "").strip()
            if not token or token.startswith(("http://", "https://")):
                continue
            if token.lower().endswith((".md", ".txt")) and token.startswith("#"):
                continue
            found.append((token.replace("\\", "/"), str(lineno)))
    return found


def nearby_new_marker(line: str) -> bool:
    lowered = line.lower()
    markers = ("new", "create", "add", "generate", "planned", "新規", "作成", "追加")
    return any(marker in lowered for marker in markers)


def path_status(path_text: str, root: Path, artifacts_dir: Path, source_line: str) -> tuple[str, str]:
    normalized = path_text.strip().strip(".,:;")
    candidates = []
    raw = Path(normalized)
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(root / normalized)
        candidates.append(artifacts_dir / normalized)

    if any(candidate.exists() for candidate in candidates):
        return "exists", "Referenced path exists"

    if nearby_new_marker(source_line):
        return "planned-new", "Referenced path appears to be explicitly planned as new"

    return "missing", "Referenced path was not found from repository root or feature artifact directory"


def load_artifacts(feature_dir: Path | None) -> dict[str, tuple[Path, str]]:
    if feature_dir is None:
        return {}
    artifacts: dict[str, tuple[Path, str]] = {}
    for name in ("spec.md", "plan.md", "tasks.md", "research.md", "data-model.md", "quickstart.md"):
        path = feature_dir / name
        if path.exists():
            artifacts[name] = (path, read_text(path))
    return artifacts


def package_scripts(root: Path) -> dict[str, str]:
    package_json = root / "package.json"
    if not package_json.exists():
        return {}
    try:
        data = json.loads(read_text(package_json))
    except json.JSONDecodeError:
        return {}
    scripts = data.get("scripts", {})
    return scripts if isinstance(scripts, dict) else {}


def python_dependency_text(root: Path) -> str:
    chunks: list[str] = []
    for name in ("pyproject.toml", "requirements.txt", "requirements-dev.txt"):
        path = root / name
        if path.exists():
            chunks.append(read_text(path).lower())
    return "\n".join(chunks)


def safe_commands(root: Path) -> list[list[str]]:
    commands: list[list[str]] = []
    scripts = package_scripts(root)

    test_script = scripts.get("test", "")
    if test_script and "no test specified" not in test_script.lower():
        if (root / "pnpm-lock.yaml").exists() and command_exists("pnpm"):
            commands.append(["pnpm", "test"])
        elif (root / "yarn.lock").exists() and command_exists("yarn"):
            commands.append(["yarn", "test"])
        elif command_exists("npm"):
            commands.append(["npm", "test"])

    if scripts.get("lint"):
        if (root / "pnpm-lock.yaml").exists() and command_exists("pnpm"):
            commands.append(["pnpm", "lint"])
        elif (root / "yarn.lock").exists() and command_exists("yarn"):
            commands.append(["yarn", "lint"])
        elif command_exists("npm"):
            commands.append(["npm", "run", "lint"])

    py_deps = python_dependency_text(root)
    if "pytest" in py_deps and command_exists("pytest"):
        commands.append(["pytest", "-q"])
    if "ruff" in py_deps and command_exists("ruff"):
        commands.append(["ruff", "check", "."])

    if (root / "go.mod").exists() and command_exists("go"):
        commands.append(["go", "test", "./..."])
    if (root / "Cargo.toml").exists() and command_exists("cargo"):
        commands.append(["cargo", "test"])
    if (root / "pom.xml").exists() and command_exists("mvn"):
        commands.append(["mvn", "test"])
    gradlew = root / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if gradlew.exists():
        commands.append([str(gradlew), "test"])

    deduped: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for command in commands:
        key = tuple(command)
        if key not in seen:
            seen.add(key)
            deduped.append(command)
    return deduped


def run_safe_commands(root: Path) -> list[CommandResult]:
    results: list[CommandResult] = []
    commands = safe_commands(root)
    if not commands:
        return [CommandResult("N/A", "NOT_RUN", "No safe project check was detected from manifests or docs.")]

    for command in commands:
        code, output = run(command, root, timeout=120)
        label = "PASS" if code == 0 else "FAIL"
        note = output.splitlines()[-1] if output.strip() else f"exit code {code}"
        results.append(CommandResult(" ".join(command), label, note))
    return results


def artifact_line_map(artifacts: dict[str, tuple[Path, str]], artifact_name: str, lineno: str) -> str:
    path, _ = artifacts[artifact_name]
    return f"{path.as_posix()}:{lineno}"


def validate(root: Path, phase: str) -> str:
    findings: list[Finding] = []
    compatibility: list[tuple[str, str, str]] = []
    coverage: list[tuple[str, str, str, str]] = []

    feature_dir = find_feature_dir(root)
    artifacts = load_artifacts(feature_dir)
    required = ("spec.md", "plan.md", "tasks.md")

    if feature_dir is None:
        findings.append(
            Finding(
                "CRITICAL",
                "Artifacts",
                "specs/",
                "No feature directory was found under specs/.",
                "Run the Spec Kit phases that create feature artifacts before implementation validation.",
            )
        )
    else:
        compatibility.append(("Feature directory", "PASS", rel(feature_dir, root)))

    for name in required:
        if name not in artifacts:
            location = rel(feature_dir / name, root) if feature_dir else f"specs/<feature>/{name}"
            findings.append(
                Finding(
                    "CRITICAL",
                    "Artifacts",
                    location,
                    f"Required artifact {name} is missing.",
                    f"Create {name} before validating implementation.",
                )
            )
        else:
            compatibility.append((f"{name} present", "PASS", rel(artifacts[name][0], root)))

    changed = changed_files(root)
    if changed:
        compatibility.append(("Changed files", "PASS", ", ".join(changed[:12])))
    else:
        findings.append(
            Finding(
                "HIGH",
                "Implementation",
                "git status --short",
                "No changed files were reported by git.",
                "Run implementation before validating, or ensure changes are committed only after validation.",
            )
        )

    referenced_paths: list[tuple[str, str, str, str]] = []
    if feature_dir:
        for artifact_name, (_, text) in artifacts.items():
            lines = text.splitlines()
            for path_text, lineno in extract_paths(text):
                line = lines[int(lineno) - 1] if int(lineno) <= len(lines) else ""
                status, evidence = path_status(path_text, root, feature_dir, line)
                location = artifact_line_map(artifacts, artifact_name, lineno)
                referenced_paths.append((path_text, status, location, evidence))
                if status == "missing":
                    findings.append(
                        Finding(
                            "HIGH",
                            "Referenced files",
                            location,
                            f"`{path_text}` was referenced but not found.",
                            "Fix the artifact path, create the planned file, or mark it explicitly as new.",
                        )
                    )

    if referenced_paths:
        missing = sum(1 for _, status, _, _ in referenced_paths if status == "missing")
        result = "FAIL" if missing else "PASS"
        compatibility.append(("Referenced files exist or are planned-new", result, f"{len(referenced_paths) - missing}/{len(referenced_paths)} valid"))
    else:
        compatibility.append(("Referenced files", "MANUAL", "No file path references were extracted from artifacts."))

    spec_text = artifacts.get("spec.md", (Path(), ""))[1]
    tasks_text = artifacts.get("tasks.md", (Path(), ""))[1]
    plan_text = artifacts.get("plan.md", (Path(), ""))[1]

    fr_ids = sorted(set(match.upper() for match in FR_ID.findall(spec_text)))
    for fr_id in fr_ids:
        covered_by_task = bool(re.search(rf"\b{re.escape(fr_id)}\b", tasks_text, re.IGNORECASE))
        covered_by_change = any(fragment.lower() in " ".join(changed).lower() for fragment in [fr_id.lower()])
        covered = "YES" if covered_by_task or covered_by_change else "NO"
        evidence = "tasks.md references requirement" if covered_by_task else "No task or changed-file evidence found"
        coverage.append((fr_id, covered, evidence, "Mechanical coverage only; semantic correctness still needs review."))
        if covered == "NO":
            findings.append(
                Finding(
                    "HIGH",
                    "Requirement coverage",
                    rel(artifacts["spec.md"][0], root) if "spec.md" in artifacts else "spec.md",
                    f"{fr_id} appears in spec.md but not in tasks.md or changed-file names.",
                    "Add explicit task or implementation evidence for this requirement.",
                )
            )

    scenarios = [line.strip() for line in spec_text.splitlines() if SCENARIO.match(line)]
    for scenario in scenarios:
        normalized = re.sub(r"[^a-z0-9]+", " ", scenario.lower()).strip()
        keywords = [word for word in normalized.split() if len(word) > 4][:5]
        haystack = (tasks_text + "\n" + "\n".join(changed)).lower()
        hits = [word for word in keywords if word in haystack]
        covered = "YES" if hits else "UNKNOWN"
        coverage.append((scenario.lstrip("# "), covered, ", ".join(hits) or "No keyword evidence", "Scenario coverage is heuristic."))

    if not fr_ids and "spec.md" in artifacts:
        findings.append(
            Finding(
                "MEDIUM",
                "Requirement coverage",
                rel(artifacts["spec.md"][0], root),
                "No FR-### requirement IDs were found.",
                "Use stable requirement IDs so validation can map implementation and tests back to requirements.",
            )
        )

    if plan_text and changed:
        plan_paths = {path for path, _, _, _ in referenced_paths if path in plan_text}
        changed_set = set(changed)
        overlap = [path for path in plan_paths if path in changed_set or any(path in changed for changed in changed_set)]
        result = "PASS" if overlap or not plan_paths else "MANUAL"
        evidence = ", ".join(overlap[:8]) if overlap else "No direct changed-file overlap with extracted plan paths."
        compatibility.append(("Architecture matches plan paths", result, evidence))

    constitution = root / ".specify" / "memory" / "constitution.md"
    if constitution.exists():
        compatibility.append(("Constitution loaded", "PASS", rel(constitution, root)))
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

    command_results = run_safe_commands(root)
    for result in command_results:
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

    verdict = "PASS"
    if any(f.severity == "CRITICAL" for f in findings):
        verdict = "FAIL"
    elif any(f.severity == "HIGH" and f.category in BLOCKING_HIGH_CATEGORIES for f in findings):
        verdict = "FAIL"
    elif sum(1 for f in findings if f.severity == "HIGH") >= 2:
        verdict = "FAIL"
    elif findings:
        verdict = "PASS_WITH_WARNINGS"

    out_dir = root / ".specify" / "context-grounding"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"validation-{phase}.md"
    report = render_report(phase, verdict, findings, coverage, compatibility, command_results)
    report_path.write_text(report, encoding="utf-8")
    return report


def table_cell(value: str) -> str:
    return value.replace("\n", "<br>").replace("|", "\\|")


def render_report(
    phase: str,
    verdict: str,
    findings: list[Finding],
    coverage: list[tuple[str, str, str, str]],
    compatibility: list[tuple[str, str, str]],
    command_results: list[CommandResult],
) -> str:
    ordered = sorted(findings, key=lambda finding: SEVERITY_ORDER[finding.severity], reverse=True)
    lines = [
        f"# Validation Report: {phase}",
        "",
        "## Verdict",
        verdict,
        "",
        "## Summary",
        summary(verdict, ordered),
        "",
        "## Findings",
        "| ID | Severity | Category | Location | Evidence | Recommendation |",
        "|----|----------|----------|----------|----------|----------------|",
    ]
    if ordered:
        for index, finding in enumerate(ordered, start=1):
            lines.append(
                "| V-{id:03d} | {severity} | {category} | {location} | {evidence} | {recommendation} |".format(
                    id=index,
                    severity=finding.severity,
                    category=table_cell(finding.category),
                    location=table_cell(finding.location),
                    evidence=table_cell(finding.evidence),
                    recommendation=table_cell(finding.recommendation),
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
    if coverage:
        for requirement, covered, evidence, notes in coverage:
            lines.append(
                f"| {table_cell(requirement)} | {covered} | {table_cell(evidence)} | {table_cell(notes)} |"
            )
    else:
        lines.append("| Manual review required | UNKNOWN | No requirements or scenarios were extracted. | Check spec.md manually. |")

    lines.extend(
        [
            "",
            "## Repository Compatibility",
            "| Check | Result | Evidence |",
            "|-------|--------|----------|",
        ]
    )
    for check, result, evidence in compatibility:
        lines.append(f"| {table_cell(check)} | {result} | {table_cell(evidence)} |")

    lines.extend(
        [
            "",
            "## Executed Commands",
            "| Command | Result | Notes |",
            "|---------|--------|-------|",
        ]
    )
    for result in command_results:
        lines.append(f"| {table_cell(result.command)} | {result.result} | {table_cell(result.notes)} |")

    lines.extend(["", "## Next Actions", next_actions(verdict), ""])
    return "\n".join(lines)


def summary(verdict: str, findings: list[Finding]) -> str:
    if verdict == "FAIL":
        return "Implementation validation failed. Do not proceed to the next Spec Kit phase until blocking findings are resolved."
    if verdict == "PASS_WITH_WARNINGS":
        return f"Implementation validation completed with {len(findings)} finding(s). Review the risks before proceeding."
    return "Implementation validation passed against available repository evidence and safe project checks."


def next_actions(verdict: str) -> str:
    if verdict == "FAIL":
        return "Do not proceed. Fix CRITICAL/HIGH findings, rerun implementation validation, and only continue after the verdict improves."
    if verdict == "PASS_WITH_WARNINGS":
        return "Review the listed warnings. Proceed only if the residual risks are acceptable for this feature."
    return "Proceed with review or the next appropriate Spec Kit command."


def main(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="implement", choices=("specify", "plan", "tasks", "implement"))
    parser.add_argument("--root", default=".")
    args = parser.parse_args(list(argv))

    root = Path(args.root).resolve()
    report = validate(root, args.phase)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
