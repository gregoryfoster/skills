# Stack: Click

Applies when `pre-ship.sh` reports `framework click`: `click` or `typer` is a
declared dependency in `pyproject.toml`, and `fastapi` is not. The checks are
the uv toolchain's, the same in every uv repo (see
[gate-topology.md](gate-topology.md)). This file holds what is specific to a
CLI or a shared library.

| Thought | Reality |
|---|---|
| "No tests/ directory means nothing to verify" | Ruff and the import check still apply. Skipping pytest is not skipping pre-ship. |

## Tests and the import check

pytest finds the suite by its own rules. A project that nests tests
elsewhere (e.g. `src/<pkg>/tests/`) sets `testpaths` in `pyproject.toml`; a
library with no suite at all is pytest's exit 5, which the gate counts as a
pass and says so.

The import check imports the `[project] name` with `-` read as `_`, when
`<name>/` or `src/<name>/` is in the tree; a guess that names nothing there is
skipped with a note. A project with several top-level packages, or whose
distribution name is not its import name, lists them in
`.skills/import-targets`, which always runs. `reviewing-code-python-click`
resolves the same targets, so review and ship agree.

## What doc-check watches by default

`AGENTS.md`, `README.md`, `pyproject.toml`, `uv.lock`, `src/` and
`.env.example`. On a hit, check the AGENTS.md command inventory along with its
structure and conventions.

## Commits

Some Click projects use a `#<number>: <topic> - <description>` commit
convention instead of the default; the project's AGENTS.md decides.

## Step 8 — next steps for a CLI or library

| Category | Trigger | Example action |
|---|---|---|
| Dep update | `pyproject.toml` changed | `uv sync` on consumers |
| Cross-package consumer | Public API change in a shared lib | Notify downstream consumers; bump version |
| Pydantic pin | Pydantic version-sensitive code | Verify pin compatibility (e.g., `pydantic==2.5.x`) |
| New command | New Click command registered | Document in README/AGENTS; check `--help` output |
