# Workspace layout (`LAYOUT=workspace`)

Adaptation checklist for bootstrapping a **uv workspace monorepo** instead of the default single package. `LAYOUT=single` remains the fully-templated path; this reference documents the deltas, with usa-wa (full workspace, 9 packages) and observo (one extractable member) as the working examples.

Choose `workspace` only when the architecture is genuinely multi-package from day one — e.g. a framework/domain/adapter/deployment split (usa-wa's "four-layer clearinghouse") or a deliberately extractable SDK (observo's `packages/exe_sdk`). A hunch that "we might split later" is not enough; promoting a module out of a single package later is cheap.

## Root `pyproject.toml` deltas

The root becomes a pure workspace/dev-tooling file — **no `[project]` table**:

```toml
[tool.uv.workspace]
members = ["packages/*"]

[tool.uv.sources]
# every member resolved from the workspace, e.g.:
# <PROJECT_NAME>-core = { workspace = true }
```

- `[dependency-groups] dev` stays at the root (single shared toolchain: pytest, ruff, pre-commit, ty, …). Runtime dependencies move into each member's own `pyproject.toml`.
- Members live at `packages/<member>/` with `src/<import_name>/` inside (usa-wa convention). Each member keeps its own `[project]` table and `uv_build` build-system block.
- One `uv.lock` at the root covers the whole workspace.

## Tool-config deltas (root pyproject)

- **pytest**: `testpaths = ["packages"]` (add `"scripts"` if operational scripts carry tests, per usa-wa).
- **coverage**: `source = ["packages"]`; `omit` any generated-client member.
- **ruff isort**: `known-first-party` lists every member import name, not `src`.
- **hatch/uv_build packaging** moves into each member — remove the root build-system block entirely (the root is not a package).

## Scaffold-phase deltas

- **Phase 5 skeleton** lands in the first member (e.g. `packages/<PROJECT_NAME>-api/src/<PROJECT_UNDERSCORE>_api/`), not a root `src/`. Shared config/logging/database modules belong in a `<PROJECT_NAME>-core` member the others depend on (usa-wa's `clearinghouse-core`).
- **Alembic** stays a single root install; its `env.py` imports `Base` from the core member and side-effect-imports every member that defines models (usa-wa pattern).
- **AGENTS.md Project Layout** section must map the member graph explicitly — which layer each package is, and the import-direction rule (deployments → domain → core, never the reverse).
- **Phase 12 verify** runs from the root; `uv sync` resolves all members.

## What does not change

Skills wiring (Phases 8–11), deploy units, `.claude/` setup, GH issue flow — all root-level and layout-independent.
