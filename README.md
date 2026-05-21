# Spec Kit Discovery and Validation Hooks

Repository-grounded discovery and validation commands for GitHub Spec Kit phases.

This extension adds phase-scoped discovery and validation hooks inspired by the Spec Kit Agents workflow described in [arXiv:2604.05278](https://arxiv.org/abs/2604.05278) ([PDF](https://arxiv.org/pdf/2604.05278)).
The implementation also uses [sbhavani/speckit-agents](https://github.com/sbhavani/speckit-agents) as a reference for the shape of pre-phase discovery, post-phase validation, JSON findings, and auditable hook records.

- `speckit.discovery-validation-hooks.discover`, aliased as `speckit.discover`
- `speckit.discovery-validation-hooks.validate`, aliased as `speckit.validate`
- Mandatory lifecycle hooks around `specify`, `plan`, `tasks`, and `implement`
- Stdlib-only discovery and validation scripts that write Markdown and JSON reports as artifacts

The goal is to keep Spec Kit artifacts grounded in the actual repository: existing files, dependencies, conventions, feature artifacts, and safe project checks.

## Requirements

- Spec Kit CLI installed as `specify`
- Python 3.11+
- Git
- A Spec Kit project initialized with an AI coding agent integration

Install the official Spec Kit CLI from GitHub:

```bash
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
specify version
```

On Windows terminals that default to CP932, use UTF-8 for `specify` commands:

```powershell
$env:PYTHONUTF8='1'; specify version
```

## Install

Clone this extension:

```bash
git clone https://github.com/stockedge/spec-kit-discovery-validation-hooks.git
```

Initialize Spec Kit in the target project:

```bash
cd /path/to/target-project
specify init --here --integration claude
```

Install the extension from the local clone:

```bash
specify extension add --dev /path/to/spec-kit-discovery-validation-hooks
specify extension list
```

Restart the AI coding agent so command files or skills are reloaded.

## Usage

Canonical command names:

```text
/speckit.discovery-validation-hooks.discover plan
/speckit.discovery-validation-hooks.validate plan
```

Aliases, when supported by the installed Spec Kit version and integration:

```text
/speckit.discover plan
/speckit.validate plan
```

Codex skills mode exposes skills instead of slash commands:

```text
$speckit-discover
$speckit-validate
```

The commands can infer the phase when enough artifacts exist:

```text
/speckit.discover
/speckit.validate
```

Reports are written under:

```text
.specify/context-grounding/
```

Each report is emitted as both Markdown and JSON:

```text
.specify/context-grounding/discovery-<phase>.md
.specify/context-grounding/discovery-<phase>.json
.specify/context-grounding/validation-<phase>.md
.specify/context-grounding/validation-<phase>.json
.specify/context-grounding/grounding-log.jsonl
```

## Lifecycle Hooks

The extension registers mandatory hooks:

- `before_specify` -> `speckit.discovery-validation-hooks.discover`
- `after_specify` -> `speckit.discovery-validation-hooks.validate`
- `before_plan` -> `speckit.discovery-validation-hooks.discover`
- `after_plan` -> `speckit.discovery-validation-hooks.validate`
- `before_tasks` -> `speckit.discovery-validation-hooks.discover`
- `after_tasks` -> `speckit.discovery-validation-hooks.validate`
- `before_implement` -> `speckit.discovery-validation-hooks.discover`
- `after_implement` -> `speckit.discovery-validation-hooks.validate`

Each hook is marked `optional: false`.

## Discovery

`discover` is a read-only repository probing command. It collects evidence for the next Spec Kit phase and writes:

```text
.specify/context-grounding/discovery-<phase>.md
.specify/context-grounding/discovery-<phase>.json
```

It looks for project structure, documentation, constitution rules, manifests, dependency files, test commands, lint commands, source layout, and phase-specific implementation context.

The mechanical entrypoint is:

```bash
python .specify/extensions/discovery-validation-hooks/scripts/discover_context.py --phase plan
```

## Validation

`validate` checks Spec Kit artifacts against repository evidence. It writes:

```text
.specify/context-grounding/validation-<phase>.md
.specify/context-grounding/validation-<phase>.json
```

The extension includes a stdlib-only mechanical validator for all Spec Kit phases:

```bash
python .specify/extensions/discovery-validation-hooks/scripts/validate_artifacts.py --phase plan
python .specify/extensions/discovery-validation-hooks/scripts/validate_artifacts.py --phase tasks
python .specify/extensions/discovery-validation-hooks/scripts/validate_artifacts.py --phase implement
```

The previous implementation-only command is still supported as a compatibility wrapper:

```bash
python .specify/extensions/discovery-validation-hooks/scripts/validate_implementation.py --phase implement
```

The validator returns a non-zero exit code when the verdict is `FAIL`; mandatory hooks should treat that as a phase gate. It checks:

- Required feature artifacts: `spec.md`, `plan.md`, `tasks.md`
- Referenced file paths exist or are explicitly planned as new
- Implementation changes are visible in `git status` or committed branch diffs
- Basic `FR-###` requirement coverage against `tasks.md`
- Basic scenario/task coverage heuristics
- Parallel `[P]` task file conflicts
- Constitution presence
- Safe project checks detected from manifests, such as `pytest -q`, `ruff check .`, `npm test`, `pnpm lint`, `make test`, `go test ./...`, `cargo test`, `mvn test`, and `gradlew test`

It does not install packages, run migrations, deploy, publish, release, or edit source files.

Feature directory resolution is intentionally conservative: when multiple `specs/<feature>/` directories match and the current branch or artifacts cannot identify one, validation fails instead of guessing by modification time.

## LLM Review Gate (v0.3.0+)

The mechanical validator alone cannot produce a `PASS` verdict. After each
`validate_artifacts.py` run you must attest LLM-side semantic review:

```bash
python .specify/extensions/discovery-validation-hooks/scripts/attest_llm_review.py \
  --phase plan --findings llm-review-plan.json

python .specify/extensions/discovery-validation-hooks/scripts/validate_artifacts.py --phase plan
```

The second `validate` checks `llm_findings` + `llm_attestation` inside
`validation-<phase>.json`, verifies the signature, and confirms the
`discovery_sha256` matches both the `discovery-<phase>.json` and the
`grounded-by` trailer in the phase artifact.

To use v0.2.x compatible behaviour (mechanical-only gate), pass:

```bash
python scripts/validate_artifacts.py --phase plan --no-require-llm-review --no-require-trailer
```

## Grounding Trailer (v0.3.0+)

`discover_context.py` now prints a `grounded-by` trailer line after the report.
Append it to the end of the phase artifact (`spec.md` / `plan.md` / `tasks.md`):

    <!-- grounded-by: .specify/context-grounding/discovery-<phase>.json sha256=<hex> -->

Without it, validation fails with category `Grounding trailer`. Re-running
discover regenerates a new sha256; replace the old trailer line each time.

## Reference Scope

This repository implements the context-grounding extension layer, not the full multi-agent system from the paper.

Borrowed design ideas from `sbhavani/speckit-agents`:

- Separate pre-phase discovery and post-phase validation hooks.
- Structured JSON findings in addition to human-readable summaries.
- Per-run audit records for hook output and timing.
- Explicit tool/check allowlists for validation.

Intentionally not included here:

- PM and developer agent orchestration.
- Mattermost or Redis worker infrastructure.
- Worktree lifecycle and PR creation automation.

Those responsibilities belong to a full orchestrator such as `sbhavani/speckit-agents`; this extension stays focused on portable Spec Kit hook artifacts.

## Safety Model

- Read-only except for report artifacts under `.specify/context-grounding/`
- No package installation
- No destructive commands
- No source edits
- No automatic task completion
- Safe commands only when already implied by manifests, scripts, or project files

The mechanical validator complements agent review. It catches repository compatibility failures, but it does not replace semantic code review.

## Development

Validate the extension manifest:

```bash
ruby -e "require 'yaml'; data=YAML.load_file('extension.yml'); abort('missing commands') unless data.dig('provides','commands')&.length==2; abort('missing hooks') unless data['hooks']&.length==8; puts 'extension.yml OK'"
```

Check the validator syntax:

```bash
python -m py_compile scripts/context_grounding.py scripts/discover_context.py scripts/validate_artifacts.py scripts/validate_implementation.py
```

Run unit tests:

```bash
python -m unittest discover -s tests
```

Smoke test in a temporary Spec Kit project:

```bash
specify init --here --integration codex --script ps --ignore-agent-tools
specify extension add --dev /path/to/spec-kit-discovery-validation-hooks
specify extension list
python .specify/extensions/discovery-validation-hooks/scripts/discover_context.py --phase implement
# In an empty project this should produce a FAIL report and exit non-zero until feature artifacts exist.
python .specify/extensions/discovery-validation-hooks/scripts/validate_artifacts.py --phase implement
```

## License

MIT
