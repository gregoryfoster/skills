---
name: init-project-fastapi
description: Bootstraps a new FastAPI project with the full CannObserv agent tooling foundation — SSH deploy key, pyproject.toml, FastAPI skeleton, structured logging, TDD scaffold, vendor skill submodules, local skill overrides, and GitHub issue tracking. Use when starting a new service in the CannObserv org.
compatibility: Designed for Claude. Requires git, gh CLI, ssh-keygen, uv. Must run inside an initialized git repository.
metadata:
  author: gregoryfoster
  version: "1.0"
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
| `DB_BACKED` | `yes` | `yes` \| `no` | Phase 3 deps, Phase 5c (database + models + alembic + deps.py), Phase 6 conftest savepoint fixture, Phase 12 alembic smoke check |
| `PROVISION_POSTGRES` | `yes` | `yes` \| `no` | Phase 5d (apt-install Postgres, create role + databases, write `DATABASE_URL`/`TEST_DATABASE_URL` to `.env`); gated on `DB_BACKED=yes`. Set to `no` when an external Postgres is already wired up. |
| `SETTINGS_STYLE` | `pydantic-settings` | `pydantic-settings` \| `os.environ` | Phase 3 deps, Phase 5b (`src/core/config.py` shape) |
| `MODELS_LAYOUT` | `monolithic` | `monolithic` \| `package` | Phase 5c (`src/core/models.py` vs `src/core/models/`) |
| `LINT_PROFILE` | `minimal` | `minimal` \| `strict` | Phase 3 (ruff `select` rules + per-file ignores) |
| `DEPLOY_TARGET` | `systemd` | `systemd` \| `none` | Phase 7b (`deploy/<PROJECT_NAME>.service`), Phase 3 `.gitignore`, README "Deploy" section |

**Sub-parameters of `DEPLOY_TARGET=systemd`** (skipped entirely when `DEPLOY_TARGET=none`):

| Sub-parameter | Default | Used in |
|---|---|---|
| `DEPLOY_USER` | `exedev` | systemd unit `User=` + `chown` in `ExecStartPre` |
| `DEPLOY_HOME` | `/home/<DEPLOY_USER>/<PROJECT_NAME>` | systemd unit `WorkingDirectory=` + repo-`.env` `EnvironmentFile` path |

### Cohort context (informational; show to the user when they ask "why this default?")

- **`DB_BACKED=yes`**: 6/7 use SQLAlchemy[asyncio] + asyncpg. Power-map is the lone exception (raw asyncpg, no ORM).
- **`PROVISION_POSTGRES=yes`**: a fresh Ubuntu/Debian VM with no Postgres is the assumed CannObserv host (the canonical systemd unit's `After=postgresql.service` reflects this). Set to `no` when the host already has Postgres or when Postgres lives on a separate machine — Phase 5d then prints the manual provisioning checklist instead.
- **`SETTINGS_STYLE=pydantic-settings`**: 3/7 newer services (power-map, address-validator, observo) converged here. Older services (notifier, archiver, watcher) still use explicit `os.environ` guard functions — both work, the newer pattern is the recommended default.
- **`MODELS_LAYOUT=monolithic`**: 6/7 use a single `models.py`. Promote to a `models/` package when crossing ~5 tables or natural domain boundaries (notifier did this).
- **`LINT_PROFILE=minimal`**: 5/7 stick to `E,F,I,W,UP`. Address-validator alone enabled the full strict profile (`ANN,S,SIM,RUF,PL,TCH,…`); offered as a branch point but not the default.
- **`DEPLOY_TARGET=systemd`**: notifier is the only production-deployed service today, and its systemd pattern (BUILD_ID via `ExecStartPre`, two-tier `EnvironmentFile`) is canonical. 0/7 use Docker.

**Async task queue (not a branch point yet).** Only notifier and watcher use [procrastinate](https://procrastinate.readthedocs.io/) for background work, and each wires its workers project-specifically (notifier's Apprise dispatcher, watcher's domain rate-limit poller). Until a third project converges on a shared shape, the skill does not scaffold procrastinate — promote it deliberately when you actually need a worker, following notifier's wiring as the reference.

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

**`.python-version`**
```
3.12
```

**`.gitignore`** — standard Python + project ignores:
```
# Python
__pycache__/
*.py[oc]
build/
dist/
wheels/
*.egg-info

# Virtual environments
.venv

# Environment / secrets
.env
env

# Coverage
htmlcov/
.coverage
coverage.xml

# IDE
.idea/
.vscode/
*.swp
*.swo

# Git worktrees
.worktrees/

# Runtime (BUILD_ID stamp target — DEPLOY_TARGET=systemd writes /run/<PROJECT_NAME>/build-id)
/run/
```

**`pyproject.toml`** — assemble from the templates in [`references/pyproject-toml.md`](references/pyproject-toml.md). The reference covers the `[project]` table (with `DB_BACKED` and `SETTINGS_STYLE` conditional deps spliced in via prose instructions), the pytest + coverage + build-system blocks (always present), and both ruff profiles (`minimal` default vs `strict` opt-in).

**`.pre-commit-config.yaml`**

Use the latest stable rev from `https://github.com/astral-sh/ruff-pre-commit/releases`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.6  # update to latest stable
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

**`CLAUDE.md`**
```
@AGENTS.md
```

**`README.md`** — setup, dev server, test commands; link to docs/COMMANDS.md

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

- `src/api/main.py` — FastAPI app with lifespan, `/health`, and (when `DB_BACKED=yes`) `/ready`. The reference's "Adjustments for non-default branch points" subsection lists the edits to make for `SETTINGS_STYLE=os.environ` and `DB_BACKED=no`.
- `src/core/logging.py` — verbatim JSON logging utility (`configure_logging` + `get_logger`).

### Phase 5b — Settings (`src/core/config.py`)

Single source of env access. `src/core/database.py` (Phase 5c) and any future runtime config imports from here.

Copy the variant for the project's `SETTINGS_STYLE` from [`references/settings-scaffolding.md`](references/settings-scaffolding.md): `pydantic-settings` (default — typed `Settings(BaseSettings)` class with `get_settings()` and a `get_database_url()` shim) or `os.environ` (explicit `get_database_url()` / `get_log_level()` / `get_build_id()` guard functions). When `DB_BACKED=no`, drop the `get_database_url()` block from whichever variant you use.

### Phase 5c — Database scaffolding

> Skip this entire phase when `DB_BACKED=no`.

**Derive `PROJECT_UNDERSCORE` first.** Postgres SQL identifiers (role names, database names) must not contain hyphens unless double-quoted everywhere — `CREATE ROLE usa-wa` is a syntax error, `psql -U usa-wa` parses `-wa` as a flag, etc. Compute the underscore form once and use it in the `alembic.ini` offline-fallback DSN (this phase) and in the Phase 5d Postgres provisioning SQL:

```bash
PROJECT_UNDERSCORE=${PROJECT_NAME//-/_}
echo "PROJECT_UNDERSCORE=$PROJECT_UNDERSCORE"
```

For hyphen-free project names `PROJECT_UNDERSCORE == PROJECT_NAME` and the substitution is a no-op.

Then follow [`references/database-scaffolding.md`](references/database-scaffolding.md), which covers four artifacts:

1. **`src/core/database.py`** — async engine + session factory (`get_engine`, `get_session_factory`, `reset_engine`). Reads via `get_database_url` from `src/core/config.py`.
2. **Models** — `src/core/models.py` (monolithic, default) or `src/core/models/` package (`__init__.py` re-exports + `base.py`), per `MODELS_LAYOUT`.
3. **Alembic** — run `uv run alembic init alembic`, then overwrite `alembic/env.py` with the asset: `cp "<SKILL_DIR>/assets/alembic-env.py" alembic/env.py`. Then edit `alembic.ini` (script_location, prepend_sys_path, offline-fallback DSN — substitute `<PROJECT_UNDERSCORE>` derived above).
4. **`src/api/deps.py`** — `get_db_session` async generator that yields an `AsyncSession`. This is the FastAPI dependency the conftest overrides for test isolation.

### Phase 5d — Provision PostgreSQL

> Skip this entire phase when `DB_BACKED=no`.
> When `PROVISION_POSTGRES=no`, skip the install/`CREATE ROLE`/`.env`-append steps and instead print the manual provisioning checklist (steps 2–6 in the reference) so the operator can run it themselves before re-running Phase 12.

Phase 5c scaffolds the code that *talks* to Postgres; this phase actually stands Postgres up so Phase 12's alembic + pytest smoke can exercise the DB path on a fresh VM.

Follow [`references/postgres-provisioning.md`](references/postgres-provisioning.md). The six steps cover: detect existing install, `apt-get install postgresql`, generate random password, create role + two databases (using `<PROJECT_UNDERSCORE>` from Phase 5c so SQL identifiers stay unquoted), append `DATABASE_URL` + `TEST_DATABASE_URL` to `./.env`, and verify TCP+password connectivity from both databases. If either verification query fails, fix the underlying issue before proceeding to Phase 12.

### Phase 6 — Tests scaffold

Create empty `__init__.py` files (`tests/`, `tests/api/`, `tests/core/`), then copy the templates from [`references/tests-scaffolding.md`](references/tests-scaffolding.md):

- `tests/conftest.py` — default (DB_BACKED=yes) includes session-scoped event loop fixture, `_check_test_url_safety` guard, `test_engine` (create_all/drop_all), savepoint-isolated `db_session`, and `client` AsyncClient with `get_db_session` dependency override. The reference also ships a no-DB variant for `DB_BACKED=no`.
- `tests/test_health.py` — minimal smoke test that asserts `/health` returns 200 with `status` and `build` keys. Always created.

### Phase 7 — Docs

**`docs/COMMANDS.md`** — setup, dev server, test, lint, submodule commands. Substitute `<API_PORT>`.

**`docs/SKILLS.md`** — copy from this project's `docs/SKILLS.md` verbatim (skill names and vendor sources are the same across projects).

**`docs/plans/.gitkeep`** — empty file to track the directory. This is the default plans directory governed by the [`writing-plans`](../writing-plans/) skill; bootstrap creates it so the first plan can be written without ceremony. Projects that prefer a different path can drop a single-line `.skills/plans_dir` file under the repo root (see [`writing-plans/SKILL.md`](../writing-plans/SKILL.md) for the resolution order).

### Phase 7b — Deployment artifacts

> Skip this entire phase when `DEPLOY_TARGET=none`.

Copy the templates from [`references/systemd-deploy.md`](references/systemd-deploy.md):

- `deploy/<PROJECT_NAME>.service` — systemd unit lifted from `notifier`'s canonical pattern: BUILD_ID stamping via `ExecStartPre`, three-tier `EnvironmentFile` chain (`/run/<PROJECT_NAME>/build-id` → `/etc/<PROJECT_NAME>/.env` → repo `.env`). Substitute `<PROJECT_NAME>`, `<PROJECT_DESCRIPTION>`, `<API_PORT>`, `<DEPLOY_USER>`, `<DEPLOY_HOME>`. The reference notes per-host adjustments (PostgreSQL `After=`, `uv` install path).
- README **"Deploy"** section — append the `systemctl` install/restart/journalctl recipe to `README.md`.

### Phase 8 — `.claude/settings.json`

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "LOCK=\"/tmp/<PROJECT_NAME>-submodule-update-$(date +%Y%m%d)\"; if [ ! -f \"$LOCK\" ]; then git submodule update --remote --merge skills-vendor/gregoryfoster-skills skills-vendor/obra-superpowers && touch \"$LOCK\" && if ! git diff --quiet HEAD skills-vendor/gregoryfoster-skills skills-vendor/obra-superpowers 2>/dev/null; then git add skills-vendor/gregoryfoster-skills skills-vendor/obra-superpowers && git commit -m 'chore: update skills submodules'; fi; fi"
          }
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

**Vendor symlinks:** Symlink every skill from each submodule. Create from within the repo root — paths must be relative from `skills/`:

```bash
mkdir -p skills
for repo in skills-vendor/obra-superpowers skills-vendor/gregoryfoster-skills; do
  for skill_dir in "$repo"/skills/*/; do
    skill_name=$(basename "$skill_dir")
    ln -s "../$repo/skills/$skill_name" "skills/$skill_name"
  done
done
```

**Local overrides (1):** The cross-cutting review and ship workflows now ship as Python/FastAPI stack variants upstream (`reviewing-code-python-fastapi`, `shipping-work-python-fastapi`). Symlink those alongside the other vendor skills (Phase 10 vendor loop above already does this) — no full-copy override needed for either workflow. The variant's `pre-ship.sh` auto-derives its per-SHA stamp prefix from the git toplevel basename, so no project-name substitution is required.

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
for skill_dir in skills/*/; do
  skill_name=$(basename "$skill_dir")
  ln -s "../../skills/$skill_name" ".claude/skills/$skill_name"
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
bash skills/shipping-work/scripts/push.sh
```

**If the push is rejected with `! [rejected] main -> main (fetch first)`,** the GitHub repo was created via the UI with the "Add LICENSE" or "Add README" checkbox, so the remote already has an initial commit on `main` that the local branch doesn't share history with. Detect this and rebase before re-pushing:

```bash
# Only run when the push above was rejected for divergent history.
git pull --rebase --allow-unrelated-histories origin main
bash skills/shipping-work/scripts/push.sh
```

The preferred long-term fix is to create the GitHub repo with **no LICENSE, no README** (the empty-repo state) so the first push has nothing to reconcile against; the rebase recipe is the recovery path when that didn't happen.

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
| Python tooling | uv, pytest, ruff, hatchling |
| FastAPI skeleton | `src/api/main.py` (lifespan + /health[+/ready]), `src/core/logging.py` |
| Settings | `src/core/config.py` (`<SETTINGS_STYLE>`) |
| Database | `<DB_BACKED>` — when yes: `src/core/database.py`, `src/core/models[.py\|/]` (`<MODELS_LAYOUT>`), `alembic/` |
| Lint profile | `<LINT_PROFILE>` |
| Tests scaffold | `tests/conftest.py`, `tests/test_health.py`, `tests/api/`, `tests/core/` |
| Deploy unit | `<DEPLOY_TARGET>` — when systemd: `deploy/<PROJECT_NAME>.service` (User=`<DEPLOY_USER>`, WorkingDirectory=`<DEPLOY_HOME>`) |
| Vendor submodules | `gregoryfoster/skills`, `obra/superpowers` |
| Skills | Local overrides + all vendor skills symlinked + matching `.claude/skills/` discovery symlinks |
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
