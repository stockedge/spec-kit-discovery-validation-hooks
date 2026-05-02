# Changelog

## 0.1.0

- Add `speckit.discovery-validation-hooks.discover` with `speckit.discover` alias.
- Add `speckit.discovery-validation-hooks.validate` with `speckit.validate` alias.
- Register mandatory lifecycle hooks around `specify`, `plan`, `tasks`, and `implement`.
- Add a stdlib-only implementation validator that writes `.specify/context-grounding/validation-implement.md`.
- Add `.extensionignore` so local `.git` metadata and generated Python cache files are not copied during `--dev` installs.
