# AGENTS.md template

Full `AGENTS.md` template for the `init-project-fastapi` skill (Phase 4). Adapt for the project. Replace `<PROJECT_NAME>`, `<PROJECT_DESCRIPTION>`, `<API_PORT>`, `<API_PORT_DEV>` (= `<API_PORT> + 1`) throughout.

Conditional blocks are gated on branch-point parameters and marked `> Include when <PARAM>=<value>`. Drop the block when the condition is false; otherwise write the rendered contents (with placeholders substituted).

```markdown
# <PROJECT_NAME> — Agent Guidelines

Be terse. Prefer fragments over full sentences. Skip filler and preamble. Sacrifice grammar for density. Lead with the answer or action.

## Project Overview

<PROJECT_DESCRIPTION>

## Development Methodology

TDD required. Red → Green → Refactor. No production code without a failing test first.

## Environment & Tooling

Python ≥3.13, uv, pytest, ruff. `ty` is available as a **non-gating** type checker (`uv run ty check`) — advisory only; no pre-commit or CI gate.

<!-- BEGIN socraticode-policy -->
## Code Exploration Policy

SocratiCode is the preferred semantic-search tool for this repo (once indexed; the artifact manifest lives in `.socraticodecontextartifacts.json`, and the index itself lives in the local Qdrant store + on-disk graph once `codebase_index` has run). Its MCP tools are **deferred** — schemas load only after a `ToolSearch` prefetch.

**Negative rule.** For broad semantic questions ("where is X", "how does Y work", "what depends on Z"), use SocratiCode MCP tools first. Reach for `grep`/`ripgrep` only on exact strings (error messages, log lines, known symbols). Reserve the Explore subagent for path-pattern walks (e.g. "all `*.py` under `src/api/routes/`"), not semantic search.

| Goal | Tool |
|------|------|
| Where is X defined / how does Y work / what files touch Z | `codebase_search` |
| Exact string/regex match (errors, log lines, known symbols) | `grep` / `rg` |
| Blast radius of changing/deleting a file or function | `codebase_impact` |
| What does an entry point actually do? | `codebase_flow` |
| Callers and callees of a function | `codebase_symbol` |
| Imports/dependents of a file | `codebase_graph_query` |
| DB schemas, deployment topology, runbook context | `codebase_context` / `codebase_context_search` |

Prefetch query — run via `ToolSearch` at session start:

`select:mcp__plugin_socraticode_socraticode__codebase_search,mcp__plugin_socraticode_socraticode__codebase_symbol,mcp__plugin_socraticode_socraticode__codebase_symbols,mcp__plugin_socraticode_socraticode__codebase_flow,mcp__plugin_socraticode_socraticode__codebase_impact,mcp__plugin_socraticode_socraticode__codebase_graph_query,mcp__plugin_socraticode_socraticode__codebase_status,mcp__plugin_socraticode_socraticode__codebase_context,mcp__plugin_socraticode_socraticode__codebase_context_search`
<!-- END socraticode-policy -->

## Project Layout

​```
src/api/        — FastAPI app (ASGI, routes, schemas); /api/v1/ versioned; /health, /ready root-level
src/api/main.py — App factory, lifespan, router registration
src/api/deps.py — FastAPI dependencies (DB session, auth)
> Include when ADMIN_UI=htmx:
src/api/admin/  — Server-rendered admin surface (HTMX + Jinja2); /admin/ gated by trusted-proxy header
src/templates/  — Jinja2 templates (base.html + admin pages/partials)
src/static/     — Static assets; vendor/htmx.min.js is vendored (no CDN, no Node toolchain)
> end include
src/core/       — Shared domain logic, logging, config
src/core/logging.py  — configure_logging() + get_logger()
src/core/config.py   — Settings / env access (see Environment Variables)
> Include when DB_BACKED=yes:
src/core/database.py — Async engine + session factory
src/core/models.py   — SQLAlchemy declarative base + tables (or src/core/models/ package)
alembic/             — Database migrations
> end include
tests/          — Mirrors src/ structure; integration tests in `@pytest.mark.integration`
docs/           — Reference docs (COMMANDS, SKILLS); docs/plans/ holds implementation plans
> Include when DEPLOY_TARGET=systemd:
deploy/         — Systemd unit + deployment config
> end include
​```

## Infrastructure

**Single-VM setup.** Code committed to main is the deployed code.

| Service | Framework | Port | Managed by |
|---|---|---|---|
| API (live) | FastAPI | <API_PORT> | `systemctl` (`<PROJECT_NAME>.service`) [DEPLOY_TARGET=systemd] |
| API (dev) | FastAPI | <API_PORT_DEV> | manual uvicorn |

`<API_PORT_DEV>` = `<API_PORT> + 1`. The exe.dev proxy transparently forwards ports 3000–9999; the dev server is reachable at `https://<PROJECT_NAME>.exe.xyz:<API_PORT_DEV>/`.

## Server Lifecycle

> Include when DEPLOY_TARGET=systemd:
**Port <API_PORT> belongs to systemd.** Never start uvicorn manually on port <API_PORT>.

| Situation | Action |
|---|---|
| Code committed to main | `sudo systemctl restart <PROJECT_NAME>` |
| Testing a worktree/branch | `uv run uvicorn ... --port <API_PORT_DEV> --reload` |
| Debugging the live service | `sudo journalctl -u <PROJECT_NAME> -f` |
| After editing `deploy/<PROJECT_NAME>.service` | `sudo systemctl daemon-reload && sudo systemctl restart <PROJECT_NAME>` |
| After DB model changes [DB_BACKED=yes] | `uv run alembic upgrade head` then restart |

**Dev server workflow.** Run on port `<API_PORT_DEV>` so the live service stays up. Load env first:

​```bash
set -a; . /etc/<PROJECT_NAME>/.env 2>/dev/null; . .env 2>/dev/null; set +a
uv run uvicorn src.api.main:app --host 0.0.0.0 --port <API_PORT_DEV> --reload
​```

**After finishing work.** Always restart the systemd service to pick up changes merged to main:

​```bash
sudo systemctl restart <PROJECT_NAME>
​```
> end include

> Include when DEPLOY_TARGET=none:
No production deployment yet. Run dev server on port <API_PORT>:

​```bash
uv run uvicorn src.api.main:app --host 0.0.0.0 --port <API_PORT> --reload
​```
> end include

## Environment Variables

> Include when DEPLOY_TARGET=systemd:
Two env files, loaded in order (later values override):

1. **`/etc/<PROJECT_NAME>/.env`** — production secrets (`DATABASE_URL`, etc.). Survives repo resets and worktree switches. Managed manually on the VM.
2. **`.env`** (repo root, git-ignored) — dev/agent secrets (`GH_TOKEN`, `TEST_DATABASE_URL`). Never commit.

The systemd service loads both automatically. For shell commands:

​```bash
set -a; . /etc/<PROJECT_NAME>/.env 2>/dev/null; . .env 2>/dev/null; set +a
​```
> end include

> Include when DEPLOY_TARGET=none:
**`.env`** (repo root, git-ignored): all secrets. Never commit.

​```bash
set -a; . .env; set +a
​```
> end include

Currently defined:
- `GH_TOKEN` — GitHub personal access token (used by `gh` CLI)
> Include when DB_BACKED=yes:
- `DATABASE_URL` — PostgreSQL connection string
- `TEST_DATABASE_URL` — PostgreSQL connection string for the test database (name must end `_test`)
- `<PROJECT_UNDERSCORE_UPPER>_ALLOW_PRODUCTION_DB` — set to `1` only via `Environment=` in the production systemd unit, **never in an env file** (systemd env files override `Environment=`, which would defeat the guard); the app refuses to boot against a non-`_dev`/`_test` database without it
> end include
> Include when AUTH_STYLE=header-token:
- `API_AUTH_TOKEN` — shared secret for `X-API-Key` on `/api/v1/*`; unset = all authed routes return 503 (fail-closed)
> end include
> Include when ADMIN_UI=htmx:
- `ADMIN_AUTH_HEADER` — name of the trusted-proxy identity header gating `/admin/*` (exe.dev pattern); unset = admin routes return 503 (fail-closed)
- `ADMIN_LOGIN_URL` — redirect target for unauthenticated admin requests (303 for browsers, `HX-Redirect` for htmx); unset = plain 401
> end include
> Include when DEPLOY_TARGET=systemd:
- `BUILD_ID` — git SHA stamped by the systemd unit's `ExecStartPre`; defaults to `"dev"` outside systemd
> end include

## Common Commands

​```bash
# Install dependencies
uv sync

# Load environment (required before running server, migrations, or gh)
set -a; . /etc/<PROJECT_NAME>/.env 2>/dev/null; . .env 2>/dev/null; set +a   # DEPLOY_TARGET=systemd
# set -a; . .env; set +a                                       # DEPLOY_TARGET=none

# Run tests
uv run pytest

# Run a subset of tests (skip the coverage gate, which measures all of src/)
uv run pytest --no-cov tests/path/to/test.py

# Run integration tests (requires PostgreSQL) [DB_BACKED=yes]
uv run pytest -m integration

# Run linter
uv run ruff check .

# Type check (advisory, non-gating; skills-vendor/ excluded)
uv run ty check

# Database migrations [DB_BACKED=yes]
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"

# FastAPI dev server
uv run uvicorn src.api.main:app --host 0.0.0.0 --port <API_PORT_DEV> --reload   # DEPLOY_TARGET=systemd
# uv run uvicorn src.api.main:app --host 0.0.0.0 --port <API_PORT> --reload     # DEPLOY_TARGET=none
​```

Full reference: `docs/COMMANDS.md`

## Agent Skills

Skills in `skills/` (agentskills.io) and `.claude/skills/` (Claude Code). Reference: `docs/SKILLS.md`

## Conventions

**Commit Messages:**
​```
#<number> [type]: <description>      # with issue
[type]: <description>                # without issue
​```
Types: feat, fix, refactor, docs, test, chore

**Logging:**
​```python
from src.core.logging import get_logger
logger = get_logger(__name__)
​```
Entry points only: `configure_logging()` is called once inside the FastAPI `lifespan`. Never in library modules.

**Date & Time:**
- All UTC
- ISO 8601: `YYYY-MM-DDTHH:MM:SS.ffffffZ` (timestamps), `YYYY-MM-DD` (dates)

**General:**
- No inline module imports; all at file top
- Docstrings for public modules, classes, functions
- Test structure mirrors source (`src/foo.py` → `tests/test_foo.py`)
- Explicit imports only
- Small, focused functions
```
