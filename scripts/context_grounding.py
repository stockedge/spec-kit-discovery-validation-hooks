"""Shared repository-grounding helpers for Spec Kit extension scripts.

The helpers in this module are intentionally stdlib-only and conservative:
they inspect local repository state, write artifacts under
.specify/context-grounding, and only execute known project checks when a
validator asks for them.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PHASES = ("specify", "plan", "tasks", "implement")
SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
BLOCKING_HIGH_CATEGORIES = {
    "Artifacts",
    "Executable checks",
    "Feature resolution",
    "Implementation",
    "Referenced files",
    "Requirement coverage",
    "Task feasibility",
}

PATH_TOKEN = re.compile(
    r"(?:`([^`\n]+\.[A-Za-z0-9][^`\n]*)`)|"
    r"(?<![\w/.-])([A-Za-z0-9_./\\-]+/[A-Za-z0-9_./\\-]+\.[A-Za-z0-9_./\\-]+)"
)
FR_ID = re.compile(r"\bFR-\d{3,}\b", re.IGNORECASE)
SCENARIO = re.compile(
    r"^\s*#{2,5}\s+.*(?:scenario|user story|acceptance|journey|flow|test scenario).*",
    re.IGNORECASE,
)
PLACEHOLDER = re.compile(r"\[(?:NEEDS CLARIFICATION|TODO|TBD)[^\]]*\]|\b(?:TODO|TBD|FIXME)\b", re.IGNORECASE)
TASK_LINE = re.compile(r"^\s*[-*]\s+\[(?P<state>[ xX])\]\s*(?P<body>.*)")


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


@dataclass
class FeatureResolution:
    feature_dir: str | None
    candidates: list[str]
    ambiguous: bool
    reason: str


@dataclass
class PathReference:
    path: str
    status: str
    location: str
    evidence: str


@dataclass
class SafeCommand:
    command: list[str]
    confidence: str
    source: str

    @property
    def label(self) -> str:
        return " ".join(self.command)


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
        return completed.returncode, output[-4000:]
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
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def table_cell(value: Any) -> str:
    return str(value).replace("\n", "<br>").replace("|", "\\|")


def out_dir(root: Path) -> Path:
    path = root / ".specify" / "context-grounding"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_audit(root: Path, record_type: str, data: dict[str, Any]) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "record_type": record_type,
        **data,
    }
    log_path = out_dir(root) / "grounding-log.jsonl"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")


def git_output(root: Path, args: list[str]) -> str:
    if not command_exists("git"):
        return ""
    code, output = run(["git", *args], root, timeout=30)
    return output if code == 0 else ""


def jj_bookmarks(root: Path, revset: str) -> str:
    if not command_exists("jj"):
        return ""
    code, output = run(["jj", "log", "-r", revset, "--no-graph", "-T", "bookmarks"], root, timeout=10)
    if code != 0 or not output.strip():
        return ""
    return output.strip().split()[0]


def is_jj_repo(root: Path) -> bool:
    return (root / ".jj").is_dir()


def current_branch(root: Path) -> str:
    branch = git_output(root, ["branch", "--show-current"]).strip()
    if branch:
        return branch
    if is_jj_repo(root):
        for rev in ("@", "@-"):
            bookmark = jj_bookmarks(root, rev)
            if bookmark:
                return bookmark
    return ""


def git_status_short(root: Path) -> str:
    return git_output(root, ["status", "--short", "--untracked-files=all"])


def status_changed_files(root: Path) -> list[str]:
    status = git_status_short(root)
    files: list[str] = []
    for line in status.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path:
            files.append(path.replace("\\", "/"))
    return sorted(set(files))


def jj_changed_files(root: Path) -> set[str]:
    if not command_exists("jj"):
        return set()
    code, output = run(["jj", "diff", "--from", "trunk()", "--to", "@-", "--summary"], root, timeout=30)
    if code != 0:
        return set()
    files: set[str] = set()
    for line in output.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            files.add(parts[1].strip().replace("\\", "/"))
    return files


def committed_changed_files(root: Path) -> list[str]:
    files: set[str] = set()
    branch = current_branch(root)

    if is_jj_repo(root) and not git_output(root, ["branch", "--show-current"]).strip():
        files = jj_changed_files(root)
        if files:
            return sorted(files)

    if branch and branch not in {"main", "master"}:
        for base in ("origin/main", "origin/master", "main", "master"):
            merge_base = git_output(root, ["merge-base", base, "HEAD"]).strip()
            if merge_base:
                diff = git_output(root, ["diff", "--name-only", f"{merge_base}..HEAD"])
                files.update(line.strip().replace("\\", "/") for line in diff.splitlines() if line.strip())
                break
        if not files and git_output(root, ["rev-parse", "--verify", "HEAD~1"]).strip():
            diff = git_output(root, ["diff", "--name-only", "HEAD~1..HEAD"])
            files.update(line.strip().replace("\\", "/") for line in diff.splitlines() if line.strip())

    return sorted(files)


def implementation_changed_files(root: Path) -> tuple[list[str], str]:
    dirty = status_changed_files(root)
    committed = committed_changed_files(root)
    combined = sorted(set(dirty) | set(committed))
    if dirty and committed:
        return combined, "git status and committed branch diff"
    if dirty:
        return combined, "git status --short"
    if committed:
        return combined, "committed diff"
    return [], "git status and committed diff found no changed files"


def find_feature_dir(root: Path) -> FeatureResolution:
    specs = root / "specs"
    if not specs.exists():
        return FeatureResolution(None, [], False, "No specs/ directory exists.")

    candidates = sorted([p for p in specs.iterdir() if p.is_dir()], key=lambda p: p.name)
    candidate_labels = [rel(p, root) for p in candidates]
    if not candidates:
        return FeatureResolution(None, [], False, "No feature directories exist under specs/.")

    branch = current_branch(root)
    if branch:
        exact = [p for p in candidates if p.name == branch]
        if len(exact) == 1:
            return FeatureResolution(rel(exact[0], root), candidate_labels, False, "Matched current branch exactly.")

        contained = [p for p in candidates if p.name in branch or branch in p.name]
        if len(contained) == 1:
            return FeatureResolution(rel(contained[0], root), candidate_labels, False, "Matched current branch by name.")
        if len(contained) > 1:
            return FeatureResolution(None, candidate_labels, True, "Multiple feature directories match current branch.")

    with_tasks = [p for p in candidates if (p / "tasks.md").exists()]
    if len(with_tasks) == 1:
        return FeatureResolution(rel(with_tasks[0], root), candidate_labels, False, "Only one feature directory has tasks.md.")
    if len(with_tasks) > 1:
        return FeatureResolution(None, candidate_labels, True, "Multiple feature directories have tasks.md.")

    with_plan = [p for p in candidates if (p / "plan.md").exists()]
    if len(with_plan) == 1:
        return FeatureResolution(rel(with_plan[0], root), candidate_labels, False, "Only one feature directory has plan.md.")
    if len(with_plan) > 1:
        return FeatureResolution(None, candidate_labels, True, "Multiple feature directories have plan.md.")

    with_spec = [p for p in candidates if (p / "spec.md").exists()]
    if len(with_spec) == 1:
        return FeatureResolution(rel(with_spec[0], root), candidate_labels, False, "Only one feature directory has spec.md.")
    if len(with_spec) > 1:
        return FeatureResolution(None, candidate_labels, True, "Multiple feature directories have spec.md.")

    if len(candidates) == 1:
        return FeatureResolution(rel(candidates[0], root), candidate_labels, False, "Only one feature directory exists.")

    return FeatureResolution(None, candidate_labels, True, "Multiple feature directories exist and none matched branch/artifacts.")


def feature_path(root: Path, resolution: FeatureResolution) -> Path | None:
    return root / resolution.feature_dir if resolution.feature_dir else None


def load_artifacts(root: Path, feature_dir: Path | None) -> dict[str, tuple[Path, str]]:
    artifacts: dict[str, tuple[Path, str]] = {}
    if feature_dir is None:
        return artifacts
    for name in (
        "spec.md",
        "plan.md",
        "tasks.md",
        "research.md",
        "data-model.md",
        "quickstart.md",
    ):
        path = feature_dir / name
        if path.exists():
            artifacts[name] = (path, read_text(path))
    contracts = feature_dir / "contracts"
    if contracts.exists():
        for path in sorted(p for p in contracts.rglob("*") if p.is_file()):
            artifacts[rel(path, feature_dir)] = (path, read_text(path))
    return artifacts


def infer_phase(root: Path) -> str:
    resolution = find_feature_dir(root)
    feature_dir = feature_path(root, resolution)
    artifacts = load_artifacts(root, feature_dir)
    changed, _ = implementation_changed_files(root)

    if "spec.md" not in artifacts:
        return "specify"
    if "plan.md" not in artifacts:
        return "plan"
    if "tasks.md" not in artifacts:
        return "tasks"
    return "implement" if changed else "tasks"


def resolve_phase(root: Path, requested: str | None) -> str:
    if requested and requested in PHASES:
        return requested
    return infer_phase(root)


def extract_paths(text: str) -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in PATH_TOKEN.finditer(line):
            token = (match.group(1) or match.group(2) or "").strip()
            if not token or token.startswith(("http://", "https://")):
                continue
            if token.startswith("#"):
                continue
            token = token.strip().strip(".,:;)")
            found.append((token.replace("\\", "/"), lineno, line))
    return found


def nearby_new_marker(line: str) -> bool:
    lowered = line.lower()
    markers = ("new", "create", "created", "add", "generate", "planned", "new file", "new path")
    return any(marker in lowered for marker in markers)


def path_status(path_text: str, root: Path, artifact_dir: Path, source_line: str) -> tuple[str, str]:
    normalized = path_text.strip().strip(".,:;")
    candidates: list[Path] = []
    raw = Path(normalized)
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(root / normalized)
        candidates.append(artifact_dir / normalized)

    if any(candidate.exists() for candidate in candidates):
        return "exists", "Referenced path exists."
    if nearby_new_marker(source_line):
        return "planned-new", "Referenced path is explicitly marked as new/planned."
    return "missing", "Referenced path was not found from repository root or feature artifact directory."


def referenced_paths(
    root: Path,
    artifact_dir: Path,
    artifacts: dict[str, tuple[Path, str]],
    names: Iterable[str] | None = None,
) -> list[PathReference]:
    selected = set(names) if names is not None else None
    refs: list[PathReference] = []
    for artifact_name, (path, text) in artifacts.items():
        if selected is not None and artifact_name not in selected:
            continue
        for token, lineno, line in extract_paths(text):
            status, evidence = path_status(token, root, artifact_dir, line)
            refs.append(PathReference(token, status, f"{rel(path, root)}:{lineno}", evidence))
    return refs


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


def package_dependencies(root: Path) -> set[str]:
    package_json = root / "package.json"
    if not package_json.exists():
        return set()
    try:
        data = json.loads(read_text(package_json))
    except json.JSONDecodeError:
        return set()
    deps: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        values = data.get(key, {})
        if isinstance(values, dict):
            deps.update(values.keys())
    return deps


def python_dependency_text(root: Path) -> str:
    chunks: list[str] = []
    for name in ("pyproject.toml", "requirements.txt", "requirements-dev.txt", "uv.lock", "poetry.lock"):
        path = root / name
        if path.exists():
            chunks.append(read_text(path).lower())
    return "\n".join(chunks)


def detect_project_types(root: Path) -> list[str]:
    types: list[str] = []
    checks = [
        ("node", root / "package.json"),
        ("python", root / "pyproject.toml"),
        ("python", root / "requirements.txt"),
        ("rust", root / "Cargo.toml"),
        ("go", root / "go.mod"),
        ("java-maven", root / "pom.xml"),
        ("java-gradle", root / "build.gradle"),
    ]
    seen: set[str] = set()
    for label, path in checks:
        if path.exists() and label not in seen:
            seen.add(label)
            types.append(label)
    return types or ["unknown"]


def manifest_paths(root: Path) -> list[Path]:
    names = {
        "package.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "package-lock.json",
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "uv.lock",
        "poetry.lock",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "settings.gradle",
        "Makefile",
        "Dockerfile",
        "docker-compose.yml",
        "compose.yml",
    }
    paths = [root / name for name in sorted(names) if (root / name).exists()]
    github = root / ".github" / "workflows"
    if github.exists():
        paths.extend(sorted(p for p in github.rglob("*") if p.is_file()))
    return paths


def safe_commands(root: Path) -> list[SafeCommand]:
    commands: list[SafeCommand] = []
    scripts = package_scripts(root)

    test_script = scripts.get("test", "")
    if test_script and "no test specified" not in test_script.lower():
        if (root / "pnpm-lock.yaml").exists():
            commands.append(SafeCommand(["pnpm", "test"], "high", "package.json scripts.test + pnpm-lock.yaml"))
        elif (root / "yarn.lock").exists():
            commands.append(SafeCommand(["yarn", "test"], "high", "package.json scripts.test + yarn.lock"))
        else:
            commands.append(SafeCommand(["npm", "test"], "high", "package.json scripts.test"))

    if scripts.get("lint"):
        if (root / "pnpm-lock.yaml").exists():
            commands.append(SafeCommand(["pnpm", "lint"], "high", "package.json scripts.lint + pnpm-lock.yaml"))
        elif (root / "yarn.lock").exists():
            commands.append(SafeCommand(["yarn", "lint"], "high", "package.json scripts.lint + yarn.lock"))
        else:
            commands.append(SafeCommand(["npm", "run", "lint"], "high", "package.json scripts.lint"))

    py_deps = python_dependency_text(root)
    if "pytest" in py_deps:
        commands.append(SafeCommand(["pytest", "-q"], "medium", "Python dependency manifests mention pytest"))
    if "ruff" in py_deps:
        commands.append(SafeCommand(["ruff", "check", "."], "medium", "Python dependency manifests mention ruff"))

    makefile = root / "Makefile"
    if makefile.exists():
        make_text = read_text(makefile)
        for target, command in (("test", ["make", "test"]), ("lint", ["make", "lint"])):
            if re.search(rf"^{re.escape(target)}\s*:", make_text, re.MULTILINE):
                commands.append(SafeCommand(command, "medium", f"Makefile target {target}"))

    if (root / "go.mod").exists():
        commands.append(SafeCommand(["go", "test", "./..."], "high", "go.mod"))
    if (root / "Cargo.toml").exists():
        commands.append(SafeCommand(["cargo", "test"], "high", "Cargo.toml"))
    if (root / "pom.xml").exists():
        commands.append(SafeCommand(["mvn", "test"], "high", "pom.xml"))
    gradlew = root / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if gradlew.exists():
        commands.append(SafeCommand([str(gradlew), "test"], "high", gradlew.name))

    deduped: list[SafeCommand] = []
    seen: set[tuple[str, ...]] = set()
    for command in commands:
        key = tuple(command.command)
        if key not in seen:
            seen.add(key)
            deduped.append(command)
    return deduped


def runnable_command(command: list[str]) -> tuple[bool, str]:
    executable = Path(command[0]).name
    if Path(command[0]).exists() or command_exists(executable):
        return True, "executable found"
    return False, f"executable not found: {executable}"


def run_safe_commands(root: Path, timeout: int = 120) -> list[CommandResult]:
    commands = safe_commands(root)
    if not commands:
        return [CommandResult("N/A", "NOT_RUN", "No safe project check was detected from manifests or docs.")]

    results: list[CommandResult] = []
    for safe in commands:
        runnable, reason = runnable_command(safe.command)
        if not runnable:
            results.append(CommandResult(safe.label, "NOT_RUN", reason))
            continue
        code, output = run(safe.command, root, timeout=timeout)
        result = "PASS" if code == 0 else "FAIL"
        note = output.splitlines()[-1] if output.strip() else f"exit code {code}"
        results.append(CommandResult(safe.label, result, note))
    return results


def root_structure(root: Path) -> list[str]:
    entries = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if child.name in {".git", ".specify"}:
            continue
        suffix = "/" if child.is_dir() else ""
        entries.append(f"{child.name}{suffix}")
    return entries[:40]


def docs_and_instructions(root: Path) -> list[Path]:
    candidates: list[Path] = []
    direct_names = (
        "README.md",
        "AGENTS.md",
        "CLAUDE.md",
        "COPILOT.md",
        ".github/copilot-instructions.md",
    )
    for name in direct_names:
        path = root / name
        if path.exists():
            candidates.append(path)
    docs = root / "docs"
    if docs.exists():
        candidates.extend(sorted(p for p in docs.rglob("*.md") if p.is_file())[:20])
    return candidates


def source_layout(root: Path) -> list[Path]:
    likely = []
    for name in (
        "src",
        "app",
        "lib",
        "packages",
        "services",
        "cmd",
        "internal",
        "tests",
        "test",
        "spec",
        "scripts",
    ):
        path = root / name
        if path.exists():
            likely.append(path)
    return likely


def latest_git_log(root: Path, limit: int = 5) -> list[str]:
    output = git_output(root, ["log", f"-{limit}", "--oneline", "--decorate"])
    return [line.strip() for line in output.splitlines() if line.strip()]


def requirement_ids(text: str) -> list[str]:
    return sorted(set(match.upper() for match in FR_ID.findall(text)))


def scenario_headers(text: str) -> list[str]:
    return [line.strip().lstrip("# ").strip() for line in text.splitlines() if SCENARIO.match(line)]


def task_entries(tasks_text: str) -> list[tuple[int, str, str]]:
    entries: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(tasks_text.splitlines(), start=1):
        match = TASK_LINE.match(line)
        if match:
            entries.append((lineno, match.group("state"), match.group("body").strip()))
    return entries


def verdict_from_findings(findings: list[Finding]) -> str:
    if any(f.severity == "CRITICAL" for f in findings):
        return "FAIL"
    if any(f.severity == "HIGH" and f.category in BLOCKING_HIGH_CATEGORIES for f in findings):
        return "FAIL"
    if sum(1 for f in findings if f.severity == "HIGH") >= 2:
        return "FAIL"
    if findings:
        return "PASS_WITH_WARNINGS"
    return "PASS"


def finding_dicts(findings: list[Finding]) -> list[dict[str, str]]:
    ordered = sorted(findings, key=lambda finding: SEVERITY_ORDER[finding.severity], reverse=True)
    return [asdict(finding) for finding in ordered]
