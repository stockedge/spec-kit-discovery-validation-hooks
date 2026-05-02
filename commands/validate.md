---
description: Validate Spec Kit artifacts or implementation against repository evidence.
---

## User Input

```text
$ARGUMENTS
```

You MUST consider the user input before proceeding.

## Goal

Validate the current Spec Kit phase output against:

- Repository evidence
- Project constitution
- Generated discovery reports
- Actual files and dependencies
- Test and lint signals where safe

This command is primarily read-only. It MUST NOT apply fixes automatically.

It MAY write one compact validation report only under:

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
- Never silently fix files.
- Never mark tasks complete.
- Never rewrite `spec.md`, `plan.md`, or `tasks.md` unless the user explicitly asks in a separate follow-up.

## Phase Resolution

Determine the target phase in this order:

1. If the first argument is one of `specify`, `plan`, `tasks`, or `implement`, use it.
2. Otherwise infer from current artifacts:
   - `spec.md` exists but `plan.md` is missing: validate `specify`
   - `plan.md` exists but `tasks.md` is missing: validate `plan`
   - `tasks.md` exists and implementation has not started: validate `tasks`
   - `tasks.md` exists and source changes exist: validate `implement`
3. If ambiguous, ask the user to choose. Do not guess.

## Context Loading

Load only what is needed:

- `.specify/memory/constitution.md`
- `.specify/context-grounding/discovery-<phase>.md` if present
- Current feature artifacts:
  - `spec.md`
  - `plan.md`
  - `tasks.md`
  - `research.md`
  - `data-model.md`
  - `contracts/`
  - `quickstart.md`
- Relevant source files referenced by artifacts
- Relevant dependency manifests

## Validation Checks

### A. Validate `specify`

Check `spec.md` for:

- Requirements are testable and unambiguous
- Success criteria are measurable
- No implementation details leak into the spec
- User stories map to existing or plausible domain concepts
- No unresolved placeholders or excessive `[NEEDS CLARIFICATION]`
- Terminology aligns with repository docs and existing code
- Constitution requirements are respected

### B. Validate `plan`

Check `plan.md` for:

- Referenced existing file paths actually exist
- New file paths are clearly marked as new
- Proposed dependencies already exist or are explicitly justified
- Architecture matches existing project structure
- Test strategy matches detected test framework
- No unsupported framework, language, or runtime assumptions
- Constitution gates are satisfied

### C. Validate `tasks`

Check `tasks.md` for:

- Every functional requirement has at least one task
- Every acceptance scenario has implementation or test coverage
- Task order is feasible
- Parallel `[P]` tasks do not touch the same files
- File paths are real or explicitly planned as new
- Tests are scheduled before or alongside implementation where appropriate
- No vague tasks like "implement feature" without file-level detail

### D. Validate `implement`

Check implementation against `spec.md`, `plan.md`, and `tasks.md`:

- Completed tasks are actually reflected in changed files
- Referenced files exist
- Implementation covers functional requirements
- Tests or code paths cover key scenarios and edge cases
- Architecture matches `plan.md`
- Constitution constraints are respected
- No obvious drift from existing project conventions

If available, run the mechanical validator first:

```text
python .specify/extensions/discovery-validation-hooks/scripts/validate_implementation.py --phase implement
```

If that script exists and succeeds, use its generated report as the primary repository-grounded evidence. Then add any manual semantic findings the script cannot determine.

If the script is unavailable, perform the checks manually and then run safe project checks when available.

Allowed examples:

```text
pytest -q
ruff check .
npm test
npm run lint
pnpm test
pnpm lint
yarn test
yarn lint
go test ./...
cargo test
mvn test
./gradlew test
```

Rules for executable checks:

- Do not install packages.
- Do not run migrations against production.
- Do not run deploy, publish, release, or destructive commands.
- Prefer commands already defined in package scripts, Makefile, CI, or project docs.
- If a command is uncertain or potentially destructive, do not run it; report it as "manual validation required."
- If available, use a platform-appropriate timeout wrapper such as `timeout 120s <command>`.

## Severity

Use this severity model:

- `CRITICAL`: artifact or implementation is likely invalid; implementation should stop
- `HIGH`: likely to cause failed implementation, failed tests, or major rework
- `MEDIUM`: quality or maintainability problem
- `LOW`: minor issue or improvement

## Verdict

- `FAIL`: Any `CRITICAL` finding, or multiple `HIGH` findings that block the next phase.
- `PASS_WITH_WARNINGS`: No blocking issue, but at least one meaningful risk remains.
- `PASS`: No material repository compatibility or artifact quality issue found.

## Required Output

Produce a Markdown report:

```markdown
# Validation Report: <phase>

## Verdict
PASS | PASS_WITH_WARNINGS | FAIL

## Summary
<short explanation>

## Findings
| ID | Severity | Category | Location | Evidence | Recommendation |
|----|----------|----------|----------|----------|----------------|

## Coverage
| Requirement / Scenario | Covered? | Evidence | Notes |
|------------------------|----------|----------|-------|

## Repository Compatibility
| Check | Result | Evidence |
|-------|--------|----------|

## Executed Commands
| Command | Result | Notes |
|---------|--------|-------|

## Next Actions
<concrete next actions>
```

## Persistence

Write the report to:

```text
.specify/context-grounding/validation-<phase>.md
```

For `implement`, the mechanical validator writes this file automatically when it is run.

## Gate Behavior

- If verdict is `FAIL`, explicitly tell the user not to proceed to the next Spec Kit phase.
- If verdict is `PASS_WITH_WARNINGS`, list risks and let the user decide.
- If verdict is `PASS`, state the next recommended command.
