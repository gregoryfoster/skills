---
name: init-project-fastapi
description: Bootstraps a new FastAPI project with the full CannObserv agent tooling foundation — SSH deploy key, pyproject.toml, FastAPI skeleton, structured logging, TDD scaffold, vendor skill submodules, local skill overrides, and GitHub issue tracking. Use when starting a new service in the CannObserv org.
compatibility: Designed for Claude. Requires git, gh CLI, ssh-keygen, uv. Must run inside an initialized git repository.
metadata:
  author: gregoryfoster
  version: "1.2"
  triggers: init project, bootstrap project, new fastapi project, set up foundation
---

# Initialize FastAPI Project — CannObserv Foundation

Bootstraps a new CannObserv FastAPI service from an empty git repo to a fully wired foundation: SSH deploy key, Python tooling, FastAPI skeleton, agent skills, and a closed GitHub issue.

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
| `API_PORT` | `8000` | AGENTS.md, README.md, docs/COMMANDS.md, systemd unit |
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
| `LINT_PROFILE` | `minimal` | `minimal` \| `strict` | Phase 3 (ruff `select` rules + per-file ignores) |
| `LAYOUT` | `single` | `single` \| `workspace` | uv workspace monorepo — Phase 3/5 shape per [`references/workspace-layout.md`](references/workspace-layout.md) (`single` is the fully-templated path) |
| `GITHUB_CI` | `no` | `no` \| `yes` | Phase 7c (`.github/workflows/ci.yml` from [`references/github-ci.md`](references/github-ci.md)) |
| `DEPLOY_TARGET` | `systemd` | `systemd` \| `none` | Phase 7b (`deploy/<PROJECT_NAME>.service`), Phase 3 `.gitignore`, README "Deploy" section |

**Sub-parameters of `DEPLOY_TARGET=systemd`** (skipped entirely when `DEPLOY_TARGET=none`):

| Sub-parameter | Default | Used in |
|---|---|---|
| `DEPLOY_USER` | `exedev` | systemd unit `User=` + `chown` in `ExecStartPre` |
| `DEPLOY_HOME` | `/home/<DEPLOY_USER>/<PROJECT_NAME>` | systemd unit `WorkingDirectory=` + repo-`.env` `EnvironmentFile` path |

### Cohort context (informational; show to the user when they ask "why this default?")

Stats refreshed 2026-07 from the 8-service cohort (address-validator, wslcb-licensing-tracker, power-map, archiver, watcher, notifier, observo, usa-wa), with deep analysis of the 4 mature services (archiver, power-map, observo, usa-wa — see [#65](https://github.com/gregoryfoster/skills/issues/65)).

- **`DB_BACKED=yes`**: 7/8 use SQLAlchemy[asyncio] + asyncpg. Power-map is the lone exception (raw asyncpg + hand-parsed `schema.sql`, no ORM/alembic).
- **`PROVISION_POSTGRES=yes`**: a fresh Ubuntu/Debian VM with no Postgres is the assumed CannObserv host (the canonical systemd unit's `After=postgresql.service` reflects this). Set to `no` when the host already has Postgres or when Postgres lives on a separate machine — Phase 5d then prints the manual provisioning checklist instead.
- **`SETTINGS_STYLE=pydantic-settings`**: observo, usa-wa, and address-validator use pydantic-settings; archiver/power-map/notifier/watcher read `os.environ` directly. Both work; the typed default remains recommended.
- **`MODELS_LAYOUT=monolithic`**: most start monolithic; archiver and notifier promoted to a `models/` package at ~5+ tables — the documented promotion path.
- **`AUTH_STYLE=header-token`**: all 4 mature services hand-rolled header auth (archiver `X-API-Key`, observo worker token, usa-wa `X-Operator-Token`, power-map API keys) — the scaffold now ships the shared fail-closed core.
- **`LINT_PROFILE=minimal`**: the historical `E,F,I,W,UP` core plus the rules the cohort added after being bitten (`B904`, `PLC0415` — archiver #97/observo) and the now-stable `FAST`/`ASYNC` groups. Address-validator alone runs strict.
- **`LAYOUT=single`**: usa-wa (full workspace) and observo (one member) adopted `[tool.uv.workspace]`; pick `workspace` only for genuinely multi-package architectures.
- **`GITHUB_CI=no`**: archiver and observo run CI (identical shape: Postgres service, ruff+format, alembic upgrade+check, pytest); power-map and usa-wa gate locally only. Off by default; recommended once PRs flow.
- **`DEPLOY_TARGET=systemd`**: power-map, usa-wa, archiver, observo all production-deploy via systemd; power-map/usa-wa grew oneshot+timer fleets (see [`references/systemd-deploy.md`](references/systemd-deploy.md)). 0/8 use Docker for the app itself.

**Async task queue (not a branch point yet).** Notifier/watcher use [procrastinate](https://procrastinate.readthedocs.io/); observo runs bespoke asyncio lifespan tasks + Redis Streams; usa-wa a custom outbox + sidecar. No convergent shape — promote deliberately when a worker is actually needed.

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

**Scope of the variable names.** Inside the block above, `$SKILL_TMP` / `$SKILL_DIR` / `$SKILL_SHA` are real bash variables — the block runs as a single shell invocation and they're live within it. *Outside* this block, the angle-bracketed forms `<SKILL_DIR>` / `<SKILL_SHA>` / `<SKILL_TMP>` are **placeholders** (same convention as `<PROJECT_NAME>`) — substitute the literal absolute path/SHA printed by Phase 0, do not paste them verbatim. Each later Bash invocation runs in a fresh shell, so Phase 0's variables are not inherited.

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

### Phase 4 — AGENTS.md

Adapt the template in [`references/agents-md-template.md`](references/agents-md-template.md) for the project. Substitute `<PROJECT_NAME>`, `<PROJECT_DESCRIPTION>`, `<API_PORT>`, `<API_PORT_DEV>` (= `<API_PORT> + 1`) throughout.

**Conditional-block syntax.** The template (and several other references) uses a blockquote pattern to gate content on branch-point values:

```
> Include when <PARAM>=<value>:
... content ...
> end include
```

When the condition is satisfied, write the inner content with placeholders substituted but **drop the `> Include when …:` and `> end include` marker lines**. When the condition is not satisfied, drop the entire block (markers + content). The markers must never appear in the rendered project file.

Sections in the template: Project Overview, Development Methodology, Environment & Tooling, Code Exploration Policy, Project Layout, Infrastructure, Server Lifecycle, Environment Variables, Common Commands, Agent Skills, Conventions.

### Phase 5 — Source skeleton

Create the empty `__init__.py` files (`src/`, `src/api/`, `src/core/`), then copy the templates from [`references/source-skeleton.md`](references/source-skeleton.md):

- `src/api/main.py` — FastAPI app with lifespan (calls `assert_database_safety()` when `DB_BACKED=yes`), version from package metadata, `/health`, (when `DB_BACKED=yes`) `/ready`, and (when `AUTH_STYLE=header-token`) the authed `/api/v1` router + `require_api_key` dep. The reference's "Adjustments" subsection lists the edits for each non-default branch point.
- `src/core/logging.py` — verbatim JSON logging utility (`configure_logging` + `get_logger`).

### Phase 5b — Settings (`src/core/config.py`)

Single source of env access. `src/core/database.py` (Phase 5c) and any future runtime config imports from here.

Copy the variant for the project's `SETTINGS_STYLE` from [`references/settings-scaffolding.md`](references/settings-scaffolding.md): `pydantic-settings` (default — typed `Settings(BaseSettings)` class with `get_settings()` and a `get_database_url()` shim) or `os.environ` (explicit `get_database_url()` / `get_log_level()` / `get_build_id()` guard functions). When `DB_BACKED=no`, drop the `get_database_url()` block from whichever variant you use.

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
3. **`src/core/db_safety.py`** — boot guard refusing production-looking databases without `<PROJECT_UNDERSCORE_UPPER>_ALLOW_PRODUCTION_DB=1` (incident-driven; called from lifespan).
4. **Alembic** — run `uv run alembic init alembic`, then overwrite `alembic/env.py` with the asset: `cp "<SKILL_DIR>/assets/alembic-env.py" alembic/env.py`. Then edit `alembic.ini` (script_location, prepend_sys_path, offline-fallback DSN — substitute `<PROJECT_UNDERSCORE>` derived above).
5. **`src/api/deps.py`** — `get_db_session` async generator that yields an `AsyncSession`. This is the FastAPI dependency the conftest overrides for test isolation.

### Phase 5d — Provision PostgreSQL

> Skip this entire phase when `DB_BACKED=no`.
>
> When `PROVISION_POSTGRES=no`, skip Phase 5d. The operator must run steps 2–6 of [`references/postgres-provisioning.md`](references/postgres-provisioning.md) themselves before Phase 12.

Follow [`references/postgres-provisioning.md`](references/postgres-provisioning.md): detect existing install, `apt-get install postgresql`, generate a random password, create the role + two databases (using `<PROJECT_UNDERSCORE>` from Phase 5c so SQL identifiers stay unquoted), append `DATABASE_URL` + `TEST_DATABASE_URL` to `./.env`, and verify TCP+password connectivity. Fix any verification failure before proceeding to Phase 12.

### Phase 6 — Tests scaffold

Create empty `__init__.py` files (`tests/`, `tests/api/`, `tests/core/`), then copy the templates from [`references/tests-scaffolding.md`](references/tests-scaffolding.md):

- `tests/conftest.py` — default (DB_BACKED=yes) includes session-scoped event loop fixture, `_check_test_url_safety` guard (name-based `_test` check + inequality) with `DATABASE_URL` env pinning, `test_engine` (create_all/drop_all; migration-driven alternative documented for later), savepoint-isolated `db_session`, and `client` AsyncClient with `get_db_session` dependency override. The reference also ships a no-DB variant for `DB_BACKED=no`.
- `tests/test_health.py` — minimal smoke test that asserts `/health` returns 200 with `status` and `build` keys. Always created.
- `tests/api/test_auth.py` — auth-gate test. Only when `AUTH_STYLE=header-token`.

### Phase 7 — Docs

**`docs/COMMANDS.md`** — setup, dev server, test, lint, submodule commands. Substitute `<API_PORT>`.

**`docs/SKILLS.md`** — copy from this project's `docs/SKILLS.md` verbatim (skill names and vendor sources are the same across projects).

**`docs/plans/.gitkeep`** — empty file to track the directory. This is the default plans directory governed by the [`writing-plans`](../writing-plans/) skill; bootstrap creates it so the first plan can be written without ceremony. Projects that prefer a different path can drop a single-line `.skills/plans_dir` file under the repo root (see [`writing-plans/SKILL.md`](../writing-plans/SKILL.md) for the resolution order).

### Phase 7b — Deployment artifacts

> Skip this entire phase when `DEPLOY_TARGET=none`.

Copy the templates from [`references/systemd-deploy.md`](references/systemd-deploy.md):

- `deploy/<PROJECT_NAME>.service` — systemd unit: BUILD_ID stamping via `ExecStartPre`, three-tier `EnvironmentFile` chain (`/run/<PROJECT_NAME>/build-id` → `/etc/<PROJECT_NAME>/.env` → repo `.env`), bounded restarts, `--frozen --no-sync` serve, and (when `DB_BACKED=yes`) the `ALLOW_PRODUCTION_DB` opt-in. Substitute `<PROJECT_NAME>`, `<PROJECT_DESCRIPTION>`, `<API_PORT>`, `<DEPLOY_USER>`, `<DEPLOY_HOME>`. The reference notes per-host adjustments and ships the fleet patterns (oneshot+timer pairs, `OnFailure=` notify template, main-checkout guard) to adopt as scheduled jobs appear.
- README **"Deploy"** section — append the `systemctl` install/restart/journalctl recipe to `README.md`.

### Phase 7c — CI workflow

> Skip this entire phase when `GITHUB_CI=no` (default).

Create `.github/workflows/ci.yml` from [`references/github-ci.md`](references/github-ci.md) — lint job (ruff check + format), test job with a Postgres 16 service, `alembic upgrade` + `alembic check` drift tripwire, pytest. The convergent archiver/observo shape.

### Phase 8 — `.claude/` settings and hooks

The submodule-refresh hook ships as a **script file**, not an inline JSON one-liner — the script (from `managing-skills`) is lock-gated once per UTC day, log-bounded, auto-commits **only on `main`** (the old inline form happily committed submodule bumps onto feature branches), and opportunistically re-installs `.skills/doctor.sh` each session:

```bash
mkdir -p .claude/hooks
cp "<SKILL_DIR>/../managing-skills/scripts/skills-submodule-update.sh" .claude/hooks/
chmod +x .claude/hooks/skills-submodule-update.sh
```

**`.claude/settings.json`**

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          { "type": "command", "command": "bash .claude/hooks/skills-submodule-update.sh" }
        ]
      }
    ]
  },
  "permissions": {
    "allow": [
      "Read(/home/exedev/.claude/projects/**)"
    ]
  }
}
```

### Phase 9 — Vendor submodules

```bash
git submodule add https://github.com/gregoryfoster/skills.git skills-vendor/gregoryfoster-skills
git submodule add https://github.com/obra/superpowers.git skills-vendor/obra-superpowers
```

### Phase 10 — `skills/` directory

**Vendor symlinks:** Symlink every skill from each submodule, except the cross-cutting review/ship workflows where only the `-python-fastapi` stack variant belongs in a FastAPI project. Create from within the repo root — paths must be relative from `skills/`:

```bash
mkdir -p skills
# ln -sfn: later vendor in loop overrides earlier (gregoryfoster overrides obra defaults).
# Bare `ln -s` would recurse into an existing directory-symlink and deposit a dangling
# link inside the obra submodule on name collisions (e.g. using-git-worktrees, writing-plans).
for repo in skills-vendor/obra-superpowers skills-vendor/gregoryfoster-skills; do
  for skill_dir in "$repo"/skills/*/; do
    skill_name=$(basename "$skill_dir")
    # Cross-cutting review/ship workflows ship as stack variants upstream.
    # A FastAPI project wants ONLY the -python-fastapi variant of each; skip
    # the stack-neutral name and any other stack variants. Pattern-based so
    # future stack variants added upstream get filtered automatically.
    case "$skill_name" in
      reviewing-code|reviewing-code-*|shipping-work|shipping-work-*)
        case "$skill_name" in
          reviewing-code-python-fastapi|shipping-work-python-fastapi) ;;
          *) continue ;;
        esac
        ;;
    esac
    ln -sfn "../$repo/skills/$skill_name" "skills/$skill_name"
  done
done
```

**Install the symlink doctor.** The `reviewing-*` / `shipping-*` skills preflight via `.skills/doctor.sh` (self-heals dangling vendor symlinks); without this step that preflight is a silent no-op ([#65](https://github.com/gregoryfoster/skills/issues/65) found it missing in all four consumer repos):

```bash
bash skills-vendor/gregoryfoster-skills/skills/managing-skills/scripts/install-doctor.sh
```

**Local overrides (1):** The cross-cutting review and ship workflows now ship as Python/FastAPI stack variants upstream (`reviewing-code-python-fastapi`, `shipping-work-python-fastapi`). Symlink those alongside the other vendor skills (Phase 10's vendor loop above selects only the `-python-fastapi` variants of these workflows) — no full-copy override needed for either workflow. The variant's `pre-ship.sh` auto-derives its per-SHA stamp prefix from the git toplevel basename, so no project-name substitution is required.

The remaining local override is the project-narrative skill that genuinely varies per-project:

| Override | Files |
|---|---|
| `skills/brainstorming/` | `SKILL.md` |

Substitutions in local overrides:
- Skill headers: `— power-map` → `— <PROJECT_NAME>`
- All other content: verbatim

> **Override frontmatter is required.** Every local override `SKILL.md` (both the row above and any thin overrides below) must declare `overrides: <vendor>/<upstream-skill-name>` and `override-reason: <one-line rationale>` in its frontmatter `metadata` block. The `<vendor>` token matches the submodule directory name under `skills-vendor/` (e.g. `gregoryfoster-skills`, `obra-superpowers`). See AGENTS.md § Required override frontmatter in the upstream `gregoryfoster/skills` repo for the canonical wording.

**Optional thin overrides** (only when the project genuinely needs them):
- `skills/writing-plans/` — fork only if the project ships project-specific narrative content (e.g., `plan-document-reviewer-prompt.md`). The plans directory itself is configurable via `.skills/plans_dir`; do not fork just to repoint it. The forked `SKILL.md` needs `overrides: gregoryfoster-skills/writing-plans` + `override-reason:`.
- `skills/shipping-work-python-fastapi/scripts/pre-ship.sh` — fork only if the project requires `/etc/<project>/.env` loading before tests (e.g., archiver, notifier, watcher). Keep the auto-derived stamp prefix. The forked `SKILL.md` needs `overrides: gregoryfoster-skills/shipping-work-python-fastapi` + `override-reason:` (e.g., `"Adds /etc/<project>/.env loading before pytest"`).
- Step 2.5 worktree-aware merge path — fork the relevant `shipping-work-python-fastapi/SKILL.md` step if the project deploys via a worktree layout that needs a specific `cd /home/.../<project>` step. Same frontmatter requirement.

### Phase 11 — `.claude/skills/` symlinks

Mirror every entry in `skills/` into `.claude/skills/` so Claude Code discovers them. Create from repo root — paths must be relative from `.claude/skills/`:

```bash
mkdir -p .claude/skills
# ln -sfn: same atomic-replace policy as Phase 10 — keeps the loop idempotent on re-runs.
for skill_dir in skills/*/; do
  skill_name=$(basename "$skill_dir")
  ln -sfn "../../skills/$skill_name" ".claude/skills/$skill_name"
done
```

### Phase 12 — Verify

Always run:

```bash
uv sync
uv run pre-commit install
uv run ruff check .
```

Expected: ruff clean.

When `DB_BACKED=yes`, also run:

```bash
# Confirm Alembic can introspect models and report current revision.
# Output should be empty (no revisions yet) or list the head revision.
uv run alembic current 2>&1 | grep -Ev "^(INFO|$)" || true
# Autogenerate-drift tripwire (needs a reachable DATABASE_URL; skip + note in
# the GH issue if the DB isn't provisioned yet). Clean on a fresh scaffold.
uv run alembic check
```

If `TEST_DATABASE_URL` is already set (i.e. the user has provisioned a test database via Phase 5d or out-of-band), also run the smoke test. Use `--no-cov` for subset runs — a fresh project has one test exercising one file (~63% coverage in practice), which trips the `fail_under=80` coverage gate from `pyproject.toml`. This matches the AGENTS.md template's "Common Commands" section, which already documents `--no-cov` for subset runs:

```bash
uv run pytest --no-cov tests/test_health.py
```

If `TEST_DATABASE_URL` is **not** set on a fresh bootstrap, skip the pytest smoke step — the conftest raises at import time without it. Note this clearly in the GH issue body (Phase 15) so the smoke test runs before the first feature PR lands.

When `DB_BACKED=no`, run:

```bash
uv run pytest --no-cov
```

Expected: pytest exits 0 or 5 (no tests collected — acceptable on empty suite). The conftest's `client` fixture binds to the app even without a database.

If any of the above fails, fix the underlying issue before proceeding.

### Phase 13 — Commit

Stage everything and commit:

```bash
git add -A
git commit -m "#1 feat: set up project foundation"
```

Commit message body should list all key scaffold components (see AGENTS.md commit convention).

### Phase 14 — Push

```bash
bash skills/shipping-work-python-fastapi/scripts/push.sh
```

**If the push is rejected with `! [rejected] main -> main (fetch first)`,** the GitHub repo was created via the UI with "Add LICENSE" or "Add README" checked, leaving an unrelated initial commit on `main`. Prevent it next time by creating the repo with no LICENSE/README; recover this time by rebasing onto the remote and re-pushing:

```bash
# Only run when the push above was rejected for divergent history.
git pull --rebase --allow-unrelated-histories origin main
bash skills/shipping-work-python-fastapi/scripts/push.sh
```

### Phase 15 — GitHub issue

Create and immediately close issue #1:

```bash
gh issue create \
  --title "Set up project foundation" \
  --body "..."
```

Body must include: Summary (1–2 sentences), Design doc (N/A), Scope (bulleted list of all scaffold components), and a `## Bootstrap provenance` line citing the Phase 0 clone (`gregoryfoster/skills@<SKILL_SHA>`) so future bootstraps are reproducible against the same skill revision. When Phase 12's pytest smoke step was skipped because `TEST_DATABASE_URL` wasn't set on the fresh bootstrap, add a `## Follow-ups` section noting that the smoke test must run before the first feature PR lands.

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

Then present a completion table. Branch-point rows show the choice made (or "skipped" when the branch was disabled):

| Component | Status |
|---|---|
| SSH deploy key | Configured |
| Git remote | `git@github-<PROJECT_NAME>:<GITHUB_ORG>/<PROJECT_NAME>.git` |
| Python tooling | uv, pytest (+timeout), ruff, ty (non-gating), uv_build |
| FastAPI skeleton | `src/api/main.py` (lifespan + /health[+/ready][+/api/v1 authed]), `src/core/logging.py` |
| Settings | `src/core/config.py` (`<SETTINGS_STYLE>`) |
| Auth | `<AUTH_STYLE>` — when header-token: `require_api_key` + `tests/api/test_auth.py` |
| Database | `<DB_BACKED>` — when yes: `src/core/database.py`, `src/core/db_safety.py`, `src/core/models[.py\|/]` (`<MODELS_LAYOUT>`, ULID PKs), `alembic/` |
| Lint profile | `<LINT_PROFILE>` |
| Layout | `<LAYOUT>` |
| CI | `<GITHUB_CI>` — when yes: `.github/workflows/ci.yml` |
| Tests scaffold | `tests/conftest.py`, `tests/test_health.py`, `tests/api/`, `tests/core/` |
| Deploy unit | `<DEPLOY_TARGET>` — when systemd: `deploy/<PROJECT_NAME>.service` (User=`<DEPLOY_USER>`, WorkingDirectory=`<DEPLOY_HOME>`) |
| Vendor submodules | `gregoryfoster/skills`, `obra/superpowers` |
| Skills | Local overrides + vendor skills symlinked (review/ship workflows: `-python-fastapi` variants only) + `.claude/skills/` discovery symlinks + `.skills/doctor.sh` |
| GH issue | #1 closed |
| Phase 0 scratch | Cleaned up (`<SKILL_TMP>` removed) |

## Key invariants

- `<SKILL_DIR>`, `<SKILL_SHA>`, and `<SKILL_TMP>` from Phase 0 are **placeholders** for literal absolute values captured once and substituted into every later phase that names them (same convention as `<PROJECT_NAME>`) — they are not inherited shell variables (each Bash invocation runs in a fresh shell). If the agent session restarts mid-bootstrap, re-run Phase 0 and use the new paths from there on.
- The `pre-ship.sh` per-SHA stamp prefix is auto-derived from `$(basename "$(git rev-parse --show-toplevel)")` in the `shipping-work-python-fastapi` variant — no per-project substitution required (and no risk of cross-project stamp collisions).
- All symlinks use **relative** paths — absolute paths break after cloning.
- `src/core/config.py` is the single source of env access. Both `os.environ` reads and `pydantic-settings` instantiation belong there; no other module should call `os.environ.get()` for runtime configuration.
- `configure_logging()` is called once inside the FastAPI `lifespan` context manager — never at module import time, and never in library modules.
- When `DEPLOY_TARGET=systemd`: the unit must declare its `ExecStartPre` BUILD_ID write **before** the `EnvironmentFile=-/run/<PROJECT_NAME>/build-id` line (the file must exist when systemd loads it). The `EnvironmentFile` order itself follows systemd convention — later entries override earlier ones — so BUILD_ID (read-only state from `ExecStartPre`) goes first as the lowest-precedence layer, then `/etc/<PROJECT_NAME>/.env`, then the repo `.env`.
- When `DB_BACKED=yes`: `tests/conftest.py` must reject `TEST_DATABASE_URL == DATABASE_URL` (production-URL safety check) — `Base.metadata.drop_all` runs on teardown and would destroy any production table mapped to the project's models.
- `uv.lock` must be committed alongside `pyproject.toml`.
