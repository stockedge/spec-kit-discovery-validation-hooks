# Spec Kit Discovery and Validation Hooks

Repository-grounded discovery and validation commands for GitHub Spec Kit phases.

This extension adds phase-scoped discovery and validation hooks inspired by the Spec Kit Agents workflow described in [arXiv:2604.05278](https://arxiv.org/abs/2604.05278) ([PDF](https://arxiv.org/pdf/2604.05278)).

- `speckit.discovery-validation-hooks.discover`, aliased as `speckit.discover`
- `speckit.discovery-validation-hooks.validate`, aliased as `speckit.validate`
- Mandatory lifecycle hooks around `specify`, `plan`, `tasks`, and `implement`
- A stdlib-only implementation validator that writes validation reports as artifacts

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
```

It looks for project structure, documentation, constitution rules, manifests, dependency files, test commands, lint commands, source layout, and phase-specific implementation context.

## Validation

`validate` checks Spec Kit artifacts against repository evidence. It writes:

```text
.specify/context-grounding/validation-<phase>.md
```

For implementation validation, the extension includes a stdlib-only mechanical validator:

```bash
python .specify/extensions/discovery-validation-hooks/scripts/validate_implementation.py --phase implement
```

The validator checks:

- Required feature artifacts: `spec.md`, `plan.md`, `tasks.md`
- Referenced file paths exist or are explicitly planned as new
- Implementation changes are visible in `git status`
- Basic `FR-###` requirement coverage against `tasks.md`
- Constitution presence
- Safe project checks detected from manifests, such as `pytest -q`, `ruff check .`, `npm test`, `pnpm lint`, `go test ./...`, `cargo test`, `mvn test`, and `gradlew test`

It does not install packages, run migrations, deploy, publish, release, or edit source files.

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
python -m py_compile scripts/validate_implementation.py
```

Smoke test in a temporary Spec Kit project:

```bash
specify init --here --integration codex --script ps --ignore-agent-tools
specify extension add --dev /path/to/spec-kit-discovery-validation-hooks
specify extension list
python .specify/extensions/discovery-validation-hooks/scripts/validate_implementation.py --phase implement
```

## License

MIT
