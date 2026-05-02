---
description: Discover repository context and produce phase-scoped evidence before a Spec Kit phase.
---

## User Input

```text
$ARGUMENTS
```

You MUST consider the user input before proceeding.

## Goal

Perform phase-scoped repository discovery before a Spec Kit phase.

This command is a read-only grounding command. It MUST NOT modify application source code, `spec.md`, `plan.md`, `tasks.md`, templates, or project configuration.

It MAY write one compact discovery report only under:

```text
.specify/context-grounding/
```

## Operating Rules

- Be evidence-first. Every non-obvious claim MUST cite a file path or command output.
- Do not invent APIs, files, dependencies, test commands, or architecture.
- Do not install packages.
- Do not run destructive commands.
- Do not edit source code.
- Keep the report compact. Prefer 10 strong findings over 50 weak ones.
- Use `rg` or `rg --files` for search when available. Fall back to platform tools only if needed.

## Phase Resolution

Determine the target phase in this order:

1. If the first argument is one of `specify`, `plan`, `tasks`, or `implement`, use it.
2. Otherwise infer from current artifacts:
   - No current feature or no `spec.md`: `specify`
   - `spec.md` exists but `plan.md` is missing: `plan`
   - `plan.md` exists but `tasks.md` is missing: `tasks`
   - `tasks.md` exists: `implement`
3. If multiple feature directories exist and the current feature cannot be determined from Spec Kit metadata or branch context, ask the user to choose. Do not guess.

## Discovery Scope

Collect only high-signal evidence relevant to the target phase.

Always inspect:

- Current branch and git status
- Root directory structure
- README, docs, AGENTS, CLAUDE, Copilot, or other agent instructions if present
- `.specify/memory/constitution.md` if present
- Build and dependency manifests when present:
  - `package.json`, `pnpm-lock.yaml`, `yarn.lock`, `package-lock.json`
  - `pyproject.toml`, `requirements.txt`, `uv.lock`, `poetry.lock`
  - `Cargo.toml`
  - `go.mod`
  - `pom.xml`, `build.gradle`, `settings.gradle`
  - `Makefile`
  - Docker, compose, and CI configuration
- Existing test commands and lint commands
- Existing source layout and naming conventions

## Phase-Specific Focus

### `specify`

Focus on:

- Existing domain concepts
- Existing user-facing flows
- Current public APIs or CLI commands
- Existing terminology used in docs and code
- Constraints from constitution and project docs

### `plan`

Focus on:

- Existing architecture patterns
- Existing modules likely to be touched
- Dependency versions already installed
- Similar implemented features
- Test framework and style
- File paths that exist and file paths that would be new

### `tasks`

Focus on:

- Files referenced by `plan.md`
- Test locations
- Setup dependencies
- Ordering constraints
- Which tasks can truly run in parallel

### `implement`

Focus on:

- Latest changed files
- Exact task file references
- Similar code paths
- Existing test and lint commands
- Integration boundaries and risky modules

## Required Output

Produce a concise Markdown report:

```markdown
# Discovery Report: <phase>

## Summary
<5-8 bullets of the most important repo facts>

## Relevant Files
| Path | Why it matters | Evidence |
|------|----------------|----------|

## Existing Patterns
| Pattern | Evidence | Implication |
|---------|----------|-------------|

## Dependencies and Tooling
| Tool/Dependency | Found where | Notes |
|-----------------|-------------|-------|

## Test and Validation Commands
| Command | Confidence | Source |
|---------|------------|--------|

## Risks / Constraints
| Risk | Severity | Evidence | Mitigation |
|------|----------|----------|------------|

## Guidance for Next Phase
<Specific guidance the next Spec Kit command must follow>
```

## Persistence

Write the same report to:

```text
.specify/context-grounding/discovery-<phase>.md
```

If a current feature directory is known, include its path in the report.

