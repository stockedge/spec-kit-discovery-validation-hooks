# Changelog

## 0.2.0

- Add stdlib-only mechanical discovery via `scripts/discover_context.py`.
- Add all-phase validation via `scripts/validate_artifacts.py` for `specify`, `plan`, `tasks`, and `implement`.
- Emit JSON reports and append JSONL audit records under `.specify/context-grounding/`.
- Fail validation instead of guessing when multiple feature directories are ambiguous.
- Detect committed branch diffs as implementation evidence, not only dirty `git status` changes.
- Detect parallel `[P]` task conflicts on the same file and expand safe command detection.
- Keep `scripts/validate_implementation.py` as a compatibility wrapper for implementation validation.

## 0.1.2

- Treat blocking `HIGH` findings as `FAIL`, including missing referenced files, failed executable checks, missing implementation changes, and requirement coverage gaps.

## 0.1.1

- Resolve safe executable commands through `shutil.which()` before running them, fixing Windows `.cmd` launch failures such as `npm test`.

## 0.1.0

- Add `speckit.discovery-validation-hooks.discover` with `speckit.discover` alias.
- Add `speckit.discovery-validation-hooks.validate` with `speckit.validate` alias.
- Register mandatory lifecycle hooks around `specify`, `plan`, `tasks`, and `implement`.
- Add a stdlib-only implementation validator that writes `.specify/context-grounding/validation-implement.md`.
- Add `.extensionignore` so local `.git` metadata and generated Python cache files are not copied during `--dev` installs.
