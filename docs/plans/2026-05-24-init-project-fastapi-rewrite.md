---
title: Rewrite init-project-fastapi as core spine + opinionated branch points
date: 2026-05-24
status: draft
---

# Rewrite init-project-fastapi as core spine + opinionated branch points

## Problem

The current `init-project-fastapi` skill bootstraps a bare FastAPI skeleton (FastAPI app + JSON logger + tests scaffold + vendor skills wiring) that all 7 CannObserv sibling services (`address-validator`, `wslcb-licensing-tracker`, `power-map`, `archiver`, `watcher`, `notifier`, `observo`) have outgrown in convergent ways. After the first day of any new service, the agent and human re-add the same scaffolding: SQLAlchemy async + asyncpg + Alembic (6/7), session-scoped asyncio fixtures (5/7), AGENTS.md sections for Code Exploration Policy / Infrastructure / Server Lifecycle (5–6/7), and — for the most mature service (`notifier`) — a systemd unit with BUILD_ID stamping and two-tier `EnvironmentFile` loading. New services pay this tax every time, and the patterns drift slightly per project because there's no canonical source. The skill needs to absorb the convergence so future services start where today's mature ones already are.

## Approach

Restructure the skill into a **core spine** (applies to every bootstrap) plus **opinionated branch-point phases** (gated on six new parameters with majority-aligned defaults). The agent collects all 13 parameters upfront (7 existing + 6 new), confirms them, then runs phases conditionally. Branch defaults match the cohort majority: DB-backed = yes, deploy target = systemd, settings style = pydantic-settings, models layout = monolithic, lint profile = minimal, task queue = no. The core spine gains four new AGENTS.md sections, a session-scoped `tests/conftest.py`, health endpoints (`/health`, `/ready`) in `src/api/main.py`, and `/run/` in `.gitignore`. The DB branch scaffolds `src/core/database.py` (with the canonical `get_engine`/`get_session_factory`/`reset_engine` shape), a savepoint-isolation conftest fixture with a production-URL safety check (lifted from `archiver`), and an initialized `alembic/` directory. The deploy branch generates `deploy/<PROJECT_NAME>.service` directly from `notifier`'s template, including the `ExecStartPre` BUILD_ID write and `/run/<proj>/build-id` → `/etc/<proj>/.env` → repo `.env` EnvironmentFile chain. Existing Phases 1–2, 8–16 stay essentially unchanged; Phases 3–7 grow conditional sub-sections.

## Tradeoffs / alternatives

- **Keep skill bare; add a separate `init-project-fastapi-db` skill** — rejected because composition across init skills is awkward (vendor symlinks, GH issue creation, commit ordering all assume one orchestrator), and 6/7 repos would invoke both every time. Branch points inside one skill keep the surface coherent.
- **Make DB-backed opt-in (ask, no default)** — rejected because cohort signal is strong (6/7) and the friction of saying "yes" each time outweighs the rare bare-API case. The `no-DB` path is preserved as a one-word override at parameter-collection time.
- **Inline `notifier`'s entire shape as the canonical template** — rejected because `notifier`'s task-queue (procrastinate), Apprise dispatch, and tenant-aware auth are domain-specific; copying wholesale would force every new service to delete code. Branch points keep the inheritance selective.
- **Generate Dockerfile / docker-compose as deploy alternative** — rejected because 0/7 repos use Docker today. Adding a speculative branch point with no production exemplar to crib from would invent a pattern rather than codify one. Revisit when the first containerized service ships.
- **Adopt the address-validator strict ruff profile as default** — rejected because it's 1/7 and adds noise (ANN, S, PL) that the other 6 repos explicitly chose to omit. Offer as `LINT_PROFILE=strict` branch point with `minimal` default.

## Steps

1. **Update SKILL.md "Parameters to collect" table** — add 6 new parameter rows (`DB_BACKED`, `SETTINGS_STYLE`, `MODELS_LAYOUT`, `LINT_PROFILE`, `DEPLOY_TARGET`, `TASK_QUEUE`) with defaults and a one-line "drives" column. Update the confirmation prompt to show defaults inline.

2. **Expand AGENTS.md template (Phase 4) with four new sections** — Code Exploration Policy (SocratiCode tool precedence + prefetch query example), Infrastructure (port mappings, dev vs prod, systemd unit name), Server Lifecycle (systemctl restart, BUILD_ID retrieval, log inspection), Environment Files (two-tier `/etc/<proj>/.env` + repo `.env` documented load order). Lift verbatim from `notifier/AGENTS.md` where it's clearest.

3. **Add DB branch sub-section to Phase 3 (pyproject.toml)** — conditional deps block adds `sqlalchemy[asyncio]>=2.0`, `asyncpg>=0.30`, `alembic>=1.14`; ruff `exclude` gains `alembic/versions/`. Add `pydantic-settings>=2.0` when `SETTINGS_STYLE=pydantic-settings` (default).

4. **Add Phase 5b: Database scaffolding (conditional on `DB_BACKED=yes`)** — create `src/core/database.py` with `get_engine`/`get_session_factory`/`reset_engine`; create `src/core/models.py` (monolithic) or `src/core/models/__init__.py` + `base.py` (package) based on `MODELS_LAYOUT`; run `uv run alembic init alembic` and edit `alembic/env.py` to use the async engine + import the declarative base. Include a one-screen explanatory diff for the `env.py` edits.

5. **Add Phase 5c: Settings scaffolding (conditional on `SETTINGS_STYLE`)** — `pydantic-settings` path creates `src/core/config.py` with `Settings(BaseSettings)` reading `DATABASE_URL`, `LOG_LEVEL`, etc.; `os.environ` path creates `src/core/config.py` with explicit guard functions (`get_database_url()` raising a helpful `RuntimeError`).

6. **Expand Phase 5 (Source skeleton) `src/api/main.py`** — add `/health` and `/ready` route stubs to the core template (returns `{"status": "ok"}`); add a `lifespan` async context manager stub that calls `configure_logging()` and (if DB branch) initializes the engine. Move `configure_logging()` call into the lifespan instead of module-level.

7. **Replace Phase 6 (Tests scaffold) with a fleshed-out `tests/conftest.py`** — session-scoped event loop fixture with the explanatory comment from `observo/tests/conftest.py`; if `DB_BACKED=yes`, add the savepoint-isolation `db_session` fixture from `notifier/tests/conftest.py` + the `_check_test_url_safety` guard from `archiver/tests/conftest.py`. Include a minimal `tests/test_health.py` smoke test.

8. **Add Phase 7b: Deployment artifacts (conditional on `DEPLOY_TARGET=systemd`)** — create `deploy/<PROJECT_NAME>.service` from `notifier`'s template, parameterized on `PROJECT_NAME`, `API_PORT`, `DEPLOY_USER` (default `exedev`), and `DEPLOY_HOME` (default `/home/<DEPLOY_USER>/<PROJECT_NAME>`). `DEPLOY_USER` and `DEPLOY_HOME` are collected as sub-parameters of `DEPLOY_TARGET=systemd` during the parameter-collection phase (skipped entirely when `DEPLOY_TARGET=none`). README gains a "Deploy" section pointing at the unit. `.gitignore` gains `/run/` (BUILD_ID write target).

9. **Update Phase 12 (Verify)** — when `DB_BACKED=yes`, add a smoke check that `uv run alembic current` succeeds against a local DB or skips gracefully when no DB is reachable; add a note that `uv run pytest tests/test_health.py` should pass.

10. **Update Phase 16 (Report)** — completion table grows rows for Database, Settings, Deploy unit (each showing the branch-point value chosen or "skipped").

11. **Update "Key invariants" section** — add: `src/core/config.py` is the single source for env access; `lifespan` (not module-level) owns one-time setup; `deploy/<proj>.service` must declare `ExecStartPre` BUILD_ID write before `EnvironmentFile=-/run/<proj>/build-id`.

12. **Self-test by walking the rewritten skill against `notifier`** — read the rewritten SKILL.md end-to-end and confirm that running it with branch points (`DB_BACKED=yes`, `SETTINGS_STYLE=pydantic-settings`, `MODELS_LAYOUT=package`, `DEPLOY_TARGET=systemd`, `TASK_QUEUE=no`) would produce a tree structurally equivalent to today's `notifier`. Note any gaps and either close them or escalate as open questions.

## Open questions / risks

- **`notifier` uses `os.environ` for settings, not `pydantic-settings`** — the new default (`pydantic-settings`) reflects the *newer* converged choice (3/7 most recent), but Step 12's self-test against `notifier` will not be a perfect match on this dimension. Acceptable, but worth flagging in the rewrite that the most mature production service is on the older pattern.

- **Models package vs monolithic default** — chose monolithic (6/7) for the default, but `notifier`'s package layout becomes load-bearing past ~5 tables. The skill should include a one-line note: "Promote to `models/` package when you cross ~5 tables or domain boundaries become clear."

- **`pydantic-settings` adds a runtime dep to every new service** — even ones that don't immediately need typed config. ~2 MB install footprint, negligible startup cost. Calling out so the user can override the default if minimalism matters more than ergonomics.

- **Alembic `env.py` edits are non-trivial to template** — the async engine wiring + import-the-declarative-base pattern needs a working example, not just inline instructions. Plan to ship the edited `env.py` as an asset under `skills/init-project-fastapi/assets/alembic-env.py` and have the procedure copy + substitute.

- ~~**Systemd unit assumes `User=exedev` + `/home/exedev/<proj>` layout**~~ **Resolved:** added `DEPLOY_USER` (default `exedev`) and `DEPLOY_HOME` (default `/home/<DEPLOY_USER>/<PROJECT_NAME>`) as sub-parameters of `DEPLOY_TARGET=systemd`. See Step 8.

- **No CI/CD workflow in scope** — only 1/7 repos has a workflow today (notifier's SDK-staleness check, project-specific). Confirming we are *not* adding a generic `.github/workflows/ci.yml` in this rewrite; revisit when 2+ services need one.
