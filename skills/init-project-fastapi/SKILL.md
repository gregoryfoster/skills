---
name: init-project-fastapi
description: Bootstraps a new FastAPI project with the full CannObserv agent tooling foundation — SSH deploy key, pyproject.toml, FastAPI skeleton, structured logging, TDD scaffold, vendor skill submodules and GitHub issue tracking. Use when starting a new service in the CannObserv org.
compatibility: Designed for Claude. Requires git, gh CLI, ssh-keygen, uv. Must run inside an initialized git repository.
metadata:
  author: gregoryfoster
  version: "2.0.0"
  triggers: init project, bootstrap project, new fastapi project, set up foundation
---

# Initialize FastAPI Project — CannObserv Foundation

Bootstraps a new CannObserv FastAPI service from an empty git repo to a fully wired foundation: SSH deploy key, Python tooling, FastAPI skeleton, agent skills, and a closed GitHub issue.

When the new service will consume a sibling service's REST API, follow the bootstrap with the [`vendoring-openapi-client`](../vendoring-openapi-client/) skill — client vendoring and its drift guards are deliberately out of scope here.

<HARD-GATE>
Do NOT create files in the bootstrapped project's working tree or run project-mutating commands until you have collected all required parameters from the user and confirmed them. (Phase 0 below clones this skill's source to a scratch dir under `/tmp`; that does not touch the project tree.) The project name drives file content, package names, and git remotes throughout — getting it wrong means manual cleanup.
</HARD-GATE>

## Parameters to collect

Ask the user (one at a time if not provided upfront).

### Core parameters (required)

| Parameter | Example | Used in |
|---|---|---|
| `PROJECT_NAME` | `watcher` | pyproject.toml, AGENTS.md, README.md, skill headers, GH issue |
| `PROJECT_DESCRIPTION` | `monitors cannabis industry activity: licenses, regulatory filings...` | pyproject.toml, AGENTS.md, README.md |
| `GITHUB_ORG` | `CannObserv` | git remote, deploy key host alias, GH issue |
| `API_PORT` | `8000` | AGENTS.md, README.md, docs/COMMANDS.md, the API unit |
| `DEPLOY_KEY_LABEL` | `watcher-deploy-key` | ssh-keygen comment |
| `GIT_USER_NAME` | `Ada Lovelace` | git local config, commits |
| `GIT_USER_EMAIL` | `ada@example.com` | git local config, commits |

Before confirming the core parameters, show the current global git identity and ask the user whether to use it or override per-project:

```
Current global git identity:
  user.name  = <git config --global user.name>
  user.email = <git config --global user.email>

Enter GIT_USER_NAME [press Enter to use global value]:
Enter GIT_USER_EMAIL [press Enter to use global value]:
```

If the user accepts both global values, skip Phase 2a.

### Branch-point parameters (defaults reflect CannObserv cohort majority)

Each has a default the user can accept silently. Defaults come from comparing 7 sibling services (`address-validator`, `wslcb-licensing-tracker`, `power-map`, `archiver`, `watcher`, `notifier`, `observo`). The "drives" column names the phase(s) the choice activates or modifies.

| Parameter | Default | Choices | Drives |
|---|---|---|---|
| `DB_BACKED` | `yes` | `yes` \| `no` | Phase 3 deps, Phase 5c (database + models + alembic + deps.py + db_safety), Phase 6 conftest savepoint fixture, Phase 12 alembic smoke check |
| `PROVISION_POSTGRES` | `yes` | `yes` \| `no` | Phase 5d (apt-install Postgres, create role + databases, write `DATABASE_URL`/`TEST_DATABASE_URL` to `.env`); gated on `DB_BACKED=yes`. Set to `no` when an external Postgres is already wired up. |
| `SETTINGS_STYLE` | `pydantic-settings` | `pydantic-settings` \| `os.environ` | Phase 3 deps, Phase 5b (`src/core/config.py` shape) |
| `MODELS_LAYOUT` | `monolithic` | `monolithic` \| `package` | Phase 5c (`src/core/models.py` vs `src/core/models/`) |
| `AUTH_STYLE` | `header-token` | `header-token` \| `none` | Phase 5 (`require_api_key` dep + authed `/api/v1` router), Phase 5b (token accessor), Phase 6 (`tests/api/test_auth.py`) |
| `ADMIN_UI` | `none` | `none` \| `htmx` | Phase 3 deps (jinja2 + python-multipart), Phase 5 (`/static` mount + admin router include), Phase 5b (admin accessors), Phase 5e (templates + vendored htmx + `src/api/admin/` + `require_admin`), Phase 6 (`tests/api/test_admin.py`) — all per [`references/admin-ui.md`](references/admin-ui.md) |
| `LINT_PROFILE` | `minimal` | `minimal` \| `strict` | Phase 3 (ruff `select` rules + per-file ignores) |
| `LAYOUT` | `single` | `single` \| `workspace` | uv workspace monorepo — Phase 3/5 shape per [`references/workspace-layout.md`](references/workspace-layout.md) (`single` is the fully-templated path) |
| `GITHUB_CI` | `no` | `no` \| `yes` | Phase 7c (`.github/workflows/ci.yml` from [`references/github-ci.md`](references/github-ci.md)) |
| `DEPLOY_TARGET` | `releases` | `releases` \| `none` | Phase 5c (`schema_state`), Phase 7b (`deploying-releases` fresh mode: the deploy core and hooks, units on `/srv/<PROJECT_NAME>/live`, `tests/deploy/`, `DEPLOYMENT.md`), README "Deploy" section |
| `PRIVATE_INDEX` | `no` | `no` \| `co-pypi` | Phase 3 (index, sources, the `co-pypi` group, ruff exclude), Phase 3b (the wrapper, installed by `deploying-releases`; the dev recipe), Phase 7b (`UV_WRAPPER`), Phase 7c (the WIF token step), Phase 12 (lock and sync through the wrapper), Phase 15 (grants) — all per [`references/private-index.md`](references/private-index.md) |

Under `releases` a unit runs a root-owned, read-only release as its own `<PROJECT_NAME>` system user, never the checkout ([#372](https://github.com/gregoryfoster/skills/issues/372); `deploying-releases` D2, D7), so there is no unit user or home to choose.

**Sub-parameter of `PRIVATE_INDEX=co-pypi`:** `PRIVATE_DEPS` (required), the private requirement lines with floors, **transitive cannobserv siblings included**: uv sources direct dependencies only, per [`references/private-index.md`](references/private-index.md).

Each default reflects the CannObserv cohort majority. When the user asks "why this default?", the per-parameter rationale (which sibling services chose what, and why) lives in [`references/cohort-context.md`](references/cohort-context.md) — informational only; it gates no phase.

Confirm all core parameters AND all branch-point parameters (or their defaults) before proceeding.

## Procedure

### Phase 0 — Acquire skill source

Phases 1, 2, and 5c reference scripts and assets that live in *this* skill, not in the bootstrapped project. The project has no `skills/init-project-fastapi/` directory until Phases 9–10 create the vendor submodule and symlinks, so an early `bash skills/init-project-fastapi/scripts/foo.sh` would resolve to "file not found." Clone this skill's repo to a scratch location once, and reference everything skill-internal through the captured path.

Run the block below as a **single Bash invocation** — `set -euo pipefail` only protects the sequence when it executes atomically; splitting line-by-line drops the safety net (and `$SKILL_TMP` would expand to empty in each fresh sub-shell):

```bash
set -euo pipefail
SKILL_TMP=$(mktemp -d "${TMPDIR:-/tmp}/init-project-fastapi.XXXXXX")
git clone --depth 1 https://github.com/gregoryfoster/skills.git "$SKILL_TMP/gregoryfoster-skills"
SKILL_DIR="$SKILL_TMP/gregoryfoster-skills/skills/init-project-fastapi"
test -d "$SKILL_DIR/scripts" || { echo "Phase 0 clone failed — $SKILL_DIR/scripts missing"; exit 1; }
SKILL_SHA=$(git -C "$SKILL_TMP/gregoryfoster-skills" rev-parse HEAD)
echo "SKILL_DIR=$SKILL_DIR"
echo "SKILL_SHA=$SKILL_SHA"
echo "SKILL_TMP=$SKILL_TMP"
```

**Scope of the variable names.** `$SKILL_TMP` / `$SKILL_DIR` / `$SKILL_SHA` are live bash variables only *inside* the single invocation above. Everywhere else the angle-bracketed forms are placeholders — see the first Key invariant.

Record the three printed values. `<SKILL_SHA>` lands in the Phase 15 GH issue body so the bootstrap is reproducible; `<SKILL_TMP>` is what Phase 16 cleans up.

> **Pinning.** The clone above tracks `main`. Once this repo starts tagging releases, pass `-b <tag>` (or `-b <sha>`) to `git clone` to lock the bootstrap to a specific version.

### Phase 1 — SSH deploy key

```bash
bash "<SKILL_DIR>/scripts/gen-deploy-key.sh" <PROJECT_NAME> <DEPLOY_KEY_LABEL>
```

Present the **public key** to the user:

> "Add this as a deploy key (with **write access**) on the `<GITHUB_ORG>/<PROJECT_NAME>` GitHub repo, then confirm when done."

**Wait for confirmation before continuing.**

### Phase 2 — Configure git remote

```bash
bash "<SKILL_DIR>/scripts/configure-remote.sh" <PROJECT_NAME> <GITHUB_ORG>
```

Verify connectivity:

```bash
ssh -o StrictHostKeyChecking=no -T git@github-<PROJECT_NAME> 2>&1
```

Expected: `Hi <GITHUB_ORG>/<PROJECT_NAME>! You've successfully authenticated...`

### Phase 2a — Configure git identity

> Skip this phase if the user accepted both global values in the parameter collection step.

```bash
git config user.name  "<GIT_USER_NAME>"
git config user.email "<GIT_USER_EMAIL>"
```

Verify:

```bash
git config user.name   # should echo GIT_USER_NAME
git config user.email  # should echo GIT_USER_EMAIL
```

### Phase 3 — Core config files

Create these files, substituting parameters throughout:

- **`.python-version`**, **`.gitignore`**, **`.pre-commit-config.yaml`**, **`CLAUDE.md`** (`@AGENTS.md`), **`README.md`** — literal contents in [`references/core-config-files.md`](references/core-config-files.md).
- **`pyproject.toml`** — assemble from [`references/pyproject-toml.md`](references/pyproject-toml.md): the `[project]` table (with `DB_BACKED` and `SETTINGS_STYLE` conditional deps spliced in via prose instructions), pytest + coverage + uv_build blocks (always present), and both ruff profiles (`minimal` default vs `strict` opt-in). When `LAYOUT=workspace`, apply the deltas in [`references/workspace-layout.md`](references/workspace-layout.md) instead of the single-package `[project]` shape.

When `PRIVATE_INDEX=co-pypi`: splice `<PRIVATE_DEPS>` into `dependencies`, then add the `co-pypi` dependency group, the explicit `[[tool.uv.index]]` and a `[tool.uv.sources]` line per private name, and append `scripts/co_pypi_token.py` to ruff's `extend-exclude`, per (a) in [`references/private-index.md`](references/private-index.md).

### Phase 3b — The co-pypi wrapper

> Skip this entire phase when `PRIVATE_INDEX=no` (the default).

Per (b) in [`references/private-index.md`](references/private-index.md): install the wrapper with `deploying-releases`' installer, `bash "<SKILL_DIR>/../deploying-releases/scripts/install.sh" --co-pypi`, never by copying it. That writes `scripts/co-pypi.sh`, `scripts/co_pypi_token.py` and `tests/test_co_pypi.py`. Emit the dev recipe (`scripts/co-pypi.sh uv sync --locked`, and `uv lock` the same way) into the README Setup block and AGENTS.md **regardless of `DEPLOY_TARGET`**.

### Phase 4 — AGENTS.md

Adapt the template in [`references/agents-md-template.md`](references/agents-md-template.md) for the project. Substitute `<PROJECT_NAME>`, `<PROJECT_DESCRIPTION>`, `<API_PORT>`, `<API_PORT_DEV>` (= `<API_PORT> + 1`), and `<PROJECT_UNDERSCORE_UPPER>` (= project name with hyphens → underscores, uppercased — e.g. `usa-wa` → `USA_WA`; same derivation as Phase 5c's `<PROJECT_UNDERSCORE>`) throughout.

**Conditional-block syntax.** The template (and several other references) uses a blockquote pattern to gate content on branch-point values:

```
> Include when <PARAM>=<value>:
... content ...
> end include
```

When the condition is satisfied, write the inner content with placeholders substituted but **drop the `> Include when …:` and `> end include` marker lines**. When the condition is not satisfied, drop the entire block (markers + content). These blockquote markers must never appear in the rendered project file.

**Keep the `<!-- BEGIN socraticode-policy -->` / `<!-- END socraticode-policy -->` comments** around the Code Exploration Policy section — they are literal content, not conditional-block syntax, and **must** survive into the rendered `AGENTS.md`. They are the shared dedupe contract with `init-socraticode`: without them a later `init-socraticode` run appends a second policy section (see #74).

Sections in the template: Project Overview, Development Methodology, Environment & Tooling, Code Exploration Policy, Project Layout, Infrastructure, Server Lifecycle, Environment Variables, Common Commands, Agent Skills, Conventions.

### Phase 5 — Source skeleton

Create the empty `__init__.py` files (`src/`, `src/api/`, `src/core/`), then copy the templates from [`references/source-skeleton.md`](references/source-skeleton.md):

- `src/api/main.py` — FastAPI app with lifespan (calls `assert_database_safety()` when `DB_BACKED=yes`), version from package metadata, `/health`, (when `DB_BACKED=yes`) `/ready`, (when `AUTH_STYLE=header-token`) the authed `/api/v1` router + `require_api_key` dep, and (when `ADMIN_UI=htmx`) the `/static` mount + admin router include. The reference's "Adjustments" subsection lists the edits for each non-default branch point.
- `src/core/logging.py` — verbatim JSON logging utility (`build_json_formatter` + `ColorMessageFilter` + `configure_logging` + `get_logger`).
- `src/core/log_config.json` — verbatim uvicorn `--log-config` file; routes uvicorn's own `uvicorn`/`uvicorn.access`/`uvicorn.error` loggers through the shared JSON formatter so journald doesn't get mixed plain+JSON lines (skills#81), and attaches `ColorMessageFilter` to all three so uvicorn's ANSI-duplicate `color_message` extra is dropped at the record source rather than in the formatter (skills#82). Wired into the API unit's `ExecStart` and the dev-server commands.

### Phase 5b — Settings (`src/core/config.py`)

Single source of env access. `src/core/database.py` (Phase 5c) and any future runtime config imports from here.

Copy the variant for the project's `SETTINGS_STYLE` from [`references/settings-scaffolding.md`](references/settings-scaffolding.md): `pydantic-settings` (default — typed `Settings(BaseSettings)` class with `get_settings()` and a `get_database_url()` shim) or `os.environ` (explicit `get_database_url()` / `get_log_level()` guard functions). Both open no env file, read secrets from systemd's `$CREDENTIALS_DIRECTORY` too (a unit's `LoadCredential=`), and take `get_build_id()` from the release's `REVISION` (`dev` in a checkout). When `DB_BACKED=no`, drop the `get_database_url()` block from whichever variant you use.

### Phase 5c — Database scaffolding

> Skip this entire phase when `DB_BACKED=no`.

**Derive `PROJECT_UNDERSCORE` first.** Postgres SQL identifiers (role and database names) must not contain hyphens unless double-quoted everywhere — `CREATE ROLE usa-wa` is a syntax error and `psql -U usa-wa` parses `-wa` as a flag. Compute the underscore form once and substitute `<PROJECT_UNDERSCORE>` literally into the `alembic.ini` offline-fallback DSN (this phase) and the Phase 5d provisioning SQL:

```bash
PROJECT_NAME="<PROJECT_NAME>"           # substitute literal, e.g. usa-wa
PROJECT_UNDERSCORE=${PROJECT_NAME//-/_}
echo "PROJECT_UNDERSCORE=$PROJECT_UNDERSCORE"
```

For hyphen-free project names `PROJECT_UNDERSCORE == PROJECT_NAME`.

Then follow [`references/database-scaffolding.md`](references/database-scaffolding.md), which covers five artifacts:

1. **`src/core/database.py`** — async engine + session factory (`get_engine`, `get_session_factory`, `reset_engine`). Reads via `get_database_url` from `src/core/config.py`.
2. **Models** — `src/core/models.py` (monolithic, default) or `src/core/models/` package (`__init__.py` re-exports + `base.py`), per `MODELS_LAYOUT`. Ships `UlidPkMixin` (ULID string PKs — 4/4 cohort convergence) + `TimestampMixin`.
3. **`src/core/db_safety.py`** — boot guard refusing production-looking databases without `<PROJECT_UNDERSCORE_UPPER>_ALLOW_PRODUCTION_DB=1` (incident-driven; called from lifespan and from `alembic/env.py`'s online run).
4. **Alembic** — run `uv run alembic init alembic`, then overwrite `alembic/env.py` with the asset: `cp "<SKILL_DIR>/assets/alembic-env.py" alembic/env.py`. Then edit `alembic.ini` (script_location, prepend_sys_path, offline-fallback DSN — substitute `<PROJECT_UNDERSCORE>` derived above).
5. **`src/api/deps.py`** — `get_db_session` async generator that yields an `AsyncSession`. This is the FastAPI dependency the conftest overrides for test isolation.
6. **`src/core/schema_state.py`** (when `DEPLOY_TARGET=releases`) — copied from the asset with its test: the database's revision against the code's head, which the deploy's `migrate` hook asks before upgrading (exit 0 current or ahead, 3 behind, 2 anything else).

### Phase 5d — Provision PostgreSQL

> Skip this entire phase when `DB_BACKED=no`.
>
> When `PROVISION_POSTGRES=no`, skip Phase 5d. The operator must run steps 2–6 of [`references/postgres-provisioning.md`](references/postgres-provisioning.md) themselves before Phase 12.

Follow [`references/postgres-provisioning.md`](references/postgres-provisioning.md): detect existing install, `apt-get install postgresql`, generate a random password, create the role + two databases (using `<PROJECT_UNDERSCORE>` from Phase 5c so SQL identifiers stay unquoted), append `DATABASE_URL` + `TEST_DATABASE_URL` to `./.env`, and verify TCP+password connectivity. Fix any verification failure before proceeding to Phase 12.

### Phase 5e — Admin UI (HTMX + Jinja2)

> Skip this entire phase when `ADMIN_UI=none` (default).

Follow [`references/admin-ui.md`](references/admin-ui.md), which covers the full set:

1. **Vendored htmx** — `mkdir -p src/static/vendor && cp "<SKILL_DIR>/assets/htmx.min.js" src/static/vendor/htmx.min.js` (pinned 2.x from this skill's assets; never a CDN reference).
2. **Templates** — `src/templates/` (`base.html`, `admin/index.html`, `admin/partials/status.html`).
3. **`src/api/admin/`** — same-app router package (`include_in_schema=False`): one full-page route + one HTMX partial route.
4. **Auth** — `is_htmx` helper + fail-closed `require_admin` (trusted-proxy header, redirect split browser-303 vs `HX-Redirect`) in `src/api/deps.py`; admin accessors in `src/core/config.py` (the `[ADMIN_UI=htmx]`-marked lines in [`references/settings-scaffolding.md`](references/settings-scaffolding.md)).
5. **`src/api/main.py` additions** — `/static` mount + `admin_router` include (also listed in the source-skeleton Adjustments).

### Phase 6 — Tests scaffold

Create empty `__init__.py` files (`tests/`, `tests/api/`, `tests/core/`), then copy the templates from [`references/tests-scaffolding.md`](references/tests-scaffolding.md):

- `tests/conftest.py` — default (DB_BACKED=yes) includes session-scoped event loop fixture, `_check_test_url_safety` guard (name-based `_test` check + inequality) with `DATABASE_URL` env pinning, `test_engine` (create_all/drop_all; migration-driven alternative documented for later), savepoint-isolated `db_session`, and `client` AsyncClient with `get_db_session` dependency override. The reference also ships a no-DB variant for `DB_BACKED=no`.
- `tests/test_health.py` — minimal smoke test that asserts `/health` returns 200 with `status` and `revision` (`dev` in a checkout), the field the deploy's verify reads. Always created.
- `tests/core/test_logging.py` — pins the JSON log field contract (`timestamp`, `level`, `logger`, `message`); a bare `JsonFormatter()` would drop all but `message` (skills#69). Also pins the uvicorn `--log-config` unification — that `log_config.json` stays valid and single-sources its formatter (skills#81) — and that `ColorMessageFilter` is placed on the three uvicorn loggers and strips the extra from the record itself (skills#82). Always created.
- `tests/core/test_config.py` — pins the settings contract (defaults + env-override for `log_level`, and `get_build_id()` read from `REVISION`: the branch-point-invariant fields). Always created; the `SETTINGS_STYLE` variant matches Phase 5b. Cheap, and it lifts a fresh scaffold well clear of the coverage floor (see Phase 12).
- `tests/api/test_auth.py` — auth-gate test. Only when `AUTH_STYLE=header-token`.
- `tests/api/test_admin.py` — admin gate + rendering tests (browser 303 vs htmx `HX-Redirect`, fail-closed 503, full page vs fragment). Only when `ADMIN_UI=htmx`; template in [`references/admin-ui.md`](references/admin-ui.md).

### Phase 7 — Docs

**`docs/COMMANDS.md`** — setup, dev server, test, lint, submodule commands. Substitute `<API_PORT>`.

**`docs/SKILLS.md`** — copy from this project's `docs/SKILLS.md` verbatim (skill names and vendor sources are the same across projects).

**`docs/plans/.gitkeep`** — empty file to track the directory. This is the default plans directory governed by the [`writing-plans`](../writing-plans/) skill; bootstrap creates it so the first plan can be written without ceremony. Projects that prefer a different path can drop a single-line `.skills/plans_dir` file under the repo root (see [`writing-plans/SKILL.md`](../writing-plans/SKILL.md) for the resolution order).

### Phase 7b — Deployment artifacts

> Skip this entire phase when `DEPLOY_TARGET=none`.

Delegate to [`deploying-releases`](../deploying-releases/SKILL.md) in **fresh mode**, following `<SKILL_DIR>/../deploying-releases/references/fresh.md` with its installer resolved there. Its inputs:

- `PROJECT=<PROJECT_NAME>`, `GITHUB_REPO=<GITHUB_ORG>/<PROJECT_NAME>`, and `CI_JOBS=(lint test)`, or `CI=none` when `GITHUB_CI=no`.
- One long-running unit, `<PROJECT_NAME>-api`, with `EXEC_START` `uvicorn src.api.main:app --host 127.0.0.1 --port <API_PORT> --log-config src/core/log_config.json`. `IMPORT_MODULES=(src.api.main)`, and its `verify` is `verify_http_health http://127.0.0.1:<API_PORT>/health "$2"`.
- No dev unit: the dev server stays a manual uvicorn on `<API_PORT_DEV>`.
- `DB=alembic` when `DB_BACKED=yes`. The deploy user can't read the DSN credential below, so `migrate` takes hook-contract's oneshot form: `deploy/<PROJECT_NAME>-migrate@.service` from `oneshot.tmpl`, in `/srv/<PROJECT_NAME>/releases/%i` with the API unit's `LoadCredential=` and opt-in, upgrading only when `src.core.schema_state` exits 3.
- `PRIVATE_INDEX` as chosen, which adds `UV_WRAPPER=scripts/co-pypi.sh`.

That gives the installed core and hooks, `deploy/<PROJECT_NAME>-api.service`, `tests/deploy/`, `DEPLOYMENT.md` and `.skills/deploy_command`. Then edit the rendered API unit. When `DB_BACKED=yes`, add `postgresql.service` to `After=` for a local Postgres, `LoadCredential=database_url:/etc/<PROJECT_NAME>/credentials/database_url`, and `Environment=<PROJECT_UNDERSCORE_UPPER>_ALLOW_PRODUCTION_DB=1`, never in the env file, which a dev shell loads too. Append a README "Deploy" section that links `DEPLOYMENT.md`. `tests/deploy/` must pass in Phase 12. Nothing here touches the host: the operator's one-time steps are in `DEPLOYMENT.md`.

### Phase 7c — CI workflow

> Skip this entire phase when `GITHUB_CI=no` (default).

Create `.github/workflows/ci.yml` from [`references/github-ci.md`](references/github-ci.md) — lint job (ruff check + format), test job with a Postgres 16 service, `alembic upgrade` + `alembic check` drift tripwire, pytest. The convergent archiver/observo shape.

When `PRIVATE_INDEX=co-pypi`: give **every** job that runs `uv sync` (lint and test) `id-token: write`, `prune-cache: true`, the `GCP_WIF_PROVIDER` assert, the WIF auth step minting `co-pypi-reader`'s access token, and the pair on the `uv sync` step alone, per (d) in [`references/private-index.md`](references/private-index.md).

### Phase 8 — `.claude/` settings and hooks

Copy `managing-skills`' `skills-submodule-update.sh` into `.claude/hooks/`, then write `.claude/settings.json` with its `SessionStart` wiring — commands and literal JSON in [`references/claude-settings.md`](references/claude-settings.md).

The hook ships as a **script file**, not an inline JSON one-liner: the script is lock-gated once per UTC day, log-bounded, auto-commits **only on `main`** (the old inline form happily committed submodule bumps onto feature branches), and opportunistically re-installs `.skills/doctor.sh` each session.

### Phase 9 — Vendor submodules

```bash
git submodule add https://github.com/gregoryfoster/skills.git skills-vendor/gregoryfoster-skills
git submodule add https://github.com/obra/superpowers.git skills-vendor/obra-superpowers
```

### Phase 10 — `skills/` directory

Symlink every vendor skill into `skills/` and install the symlink doctor; no local override — loops, and where former overrides' content goes, in [`references/skill-symlinks.md`](references/skill-symlinks.md).

Rules that reference cannot re-derive:

- Create every link **from the repo root** with **relative** paths, using `ln -sfn` — never bare `ln -s`, which recurses into an existing directory-symlink and deposits a dangling link inside the obra submodule on name collisions (`using-git-worktrees`, `writing-plans`). `-sfn` also makes the loop idempotent on re-runs, and lets the later vendor in the loop override the earlier one.
- Of the review workflows, a FastAPI project takes **only** the `-python-fastapi` variant, and it takes the one `shipping-work`, which detects the stack; the retired `shipping-work-*` variants are skipped ([#537](https://github.com/gregoryfoster/skills/issues/537)). The loop filters by pattern, so stack variants added upstream later are excluded without an edit here.
- `.skills/doctor.sh` must be installed in this phase. The `reviewing-*` / `shipping-*` skills preflight through it, and without the install that preflight is a silent no-op ([#65](https://github.com/gregoryfoster/skills/issues/65) found it missing in all four consumer repos).

### Phase 11 — `.claude/skills/` symlinks

Mirror every entry in `skills/` into `.claude/skills/` so Claude Code discovers them — loop in [`references/skill-symlinks.md`](references/skill-symlinks.md). Same rules as Phase 10: run from the repo root, paths relative from `.claude/skills/`, `ln -sfn`.

### Phase 12 — Verify

When `PRIVATE_INDEX=co-pypi`, **lock and sync through the wrapper before the block below**: no private name resolves without the token. Run (e) in [`references/private-index.md`](references/private-index.md): probe for a **readable** reader key; if there is one, `scripts/co-pypi.sh uv lock`, then `uv sync --locked` the same way; if not, skip every step that needs the lock and record the **mandatory** follow-up.

Always run:

```bash
uv sync
uv run pre-commit install
uv run ruff check .
```

Expected: ruff clean.

Also run the advisory type checker — non-gating, so report diagnostics but do not block the bootstrap. `skills-vendor/` is excluded via `[tool.ty.src]` in `pyproject.toml`, so output is project code only; a fresh scaffold may still surface one genuine `src`-import diagnostic (seen on the `CannObserv/replicator` bootstrap) — note anything real in the GH issue rather than fixing it here.

```bash
uv run ty check
```

When `DB_BACKED=yes`, also run:

```bash
# Confirm Alembic can introspect models and report current revision.
# Output should be empty (no revisions yet) or list the head revision.
uv run alembic current 2>&1 | grep -Ev "^(INFO|$)" || true
# Autogenerate-drift tripwire (needs a reachable DATABASE_URL; skip + note in
# the GH issue if the DB isn't provisioned yet). Clean on a fresh scaffold.
uv run alembic check
```

Run the full suite gated and **measure** — `uv run pytest` (when `DB_BACKED=yes`, only after `TEST_DATABASE_URL` is set via Phase 5d/out-of-band; the conftest raises at import without it — if unset, skip and note in the GH issue). The scaffolded suite (health + logging + config) clears `fail_under=80` on a typical bootstrap (replicator: 91%), so keep the gate on; **only if it reports under 80** for a given mix (`DB_BACKED=yes`/`ADMIN_UI=htmx` add thinly-covered modules; CI-vs-local skew — see [`references/github-ci.md`](references/github-ci.md)) fall back to a `--no-cov` subset run (`uv run pytest --no-cov tests/test_health.py tests/core/test_logging.py tests/core/test_config.py`) plus a GH note. Everything above must pass before proceeding — **except** that coverage shortfall, which takes the fallback, not filler tests (the gate activates naturally once feature tests land).

### Phase 13 — Commit

Stage everything and commit:

```bash
git add -A
git commit -m "#1 feat: set up project foundation"
```

Commit message body should list all key scaffold components (see AGENTS.md commit convention).

### Phase 14 — Push

```bash
bash skills/shipping-work/scripts/push.sh
```

**If the push is rejected with `! [rejected] main -> main (fetch first)`,** the GitHub repo was created via the UI with "Add LICENSE" or "Add README" checked, leaving an unrelated initial commit on `main`. Prevent it next time by creating the repo with no LICENSE/README; recover this time by rebasing onto the remote and re-pushing:

```bash
# Only run when the push above was rejected for divergent history.
git pull --rebase --allow-unrelated-histories origin main
bash skills/shipping-work/scripts/push.sh
```

### Phase 15 — GitHub issue

Create and immediately close issue #1:

```bash
gh issue create \
  --title "Set up project foundation" \
  --body "..."
```

Body must include: Summary (1–2 sentences), Design doc (N/A), Scope (bulleted list of all scaffold components), and a `## Bootstrap provenance` line citing the Phase 0 clone (`gregoryfoster/skills@<SKILL_SHA>`) so future bootstraps are reproducible against the same skill revision. When Phase 12's pytest smoke step was skipped because `TEST_DATABASE_URL` wasn't set on the fresh bootstrap, add a `## Follow-ups` section noting that the smoke test must run before the first feature PR lands.

When `PRIVATE_INDEX=co-pypi`, add (f)'s follow-ups from [`references/private-index.md`](references/private-index.md) to `## Follow-ups`: the skipped lock, the `GCP_WIF_PROVIDER` and WIF-provider grants when `GITHUB_CI=yes`, the reader key on each host, and Dependabot admission.

Post a completion comment referencing the commit SHA, then close:

```bash
gh issue comment 1 --body "..."
gh issue close 1
```

### Phase 16 — Report

First, clean up the Phase 0 scratch clone:

```bash
rm -rf "<SKILL_TMP>"
```

If the bootstrap aborted mid-phase, `<SKILL_TMP>` (under `/tmp`) is left behind and the OS reclaims it on the standard tmp-cleanup cadence; no manual intervention required.

Then present the completion table from [`references/completion-report.md`](references/completion-report.md). Branch-point rows show the choice made, or "skipped" when the branch was disabled.

## Key invariants

- `<SKILL_DIR>`, `<SKILL_SHA>`, and `<SKILL_TMP>` from Phase 0 are **placeholders** for literal absolute values captured once and substituted into every later phase that names them (same convention as `<PROJECT_NAME>`) — they are not inherited shell variables (each Bash invocation runs in a fresh shell). If the agent session restarts mid-bootstrap, re-run Phase 0 and use the new paths from there on.
- `shipping-work`'s `pre-ship.sh` keeps its pass stamp under the repo's own `git rev-parse --git-common-dir`, keyed on the tree — no per-project substitution required, and no risk of cross-project stamp collisions.
- All symlinks use **relative** paths — absolute paths break after cloning.
- `src/core/config.py` is the single source of env access. Both `os.environ` reads and `pydantic-settings` instantiation belong there; no other module should call `os.environ.get()` for runtime configuration.
- `configure_logging()` is called once inside the FastAPI `lifespan` context manager — never at module import time, and never in library modules.
- When `DEPLOY_TARGET=releases`: no unit runs the checkout, `uv` or the repo `.env`; a deploy is `scripts/deploy.sh`, the core `deploying-releases` installs, which is never edited. The build id is the release's `REVISION`.
- When `DB_BACKED=yes`: `tests/conftest.py` must reject `TEST_DATABASE_URL == DATABASE_URL` (production-URL safety check) — `Base.metadata.drop_all` runs on teardown and would destroy any production table mapped to the project's models.
- When `ADMIN_UI=htmx`: `require_admin` fails closed (unconfigured `ADMIN_AUTH_HEADER` → 503, never open); the admin router mounts with `include_in_schema=False`; `htmx.min.js` is copied from this skill's assets (provenance = `<SKILL_SHA>`) — never hot-linked from a CDN.
- `uv.lock` must be committed alongside `pyproject.toml`.
- When `PRIVATE_INDEX=co-pypi`: the token reaches one `uv` and nothing else. The key sits at `/etc/<PROJECT_NAME>/co-pypi-reader.json` (or `CO_PYPI_KEY`), never in `GOOGLE_APPLICATION_CREDENTIALS`, the repo or a `.env`, and CI is keyless WIF. The installed pair is never edited.

**Self-budget:** held to a **14,700-token ratchet (estimate and exact)** by
`tests/structural/test_skill_self_budget.py` — a named exception to the repo's
6,000-token standard, set at current size so this file cannot grow. The offline
estimate reads ~1,800 tokens *below* the exact count here, so a green
pre-commit run is necessary and not sufficient: measure exact before adding.
