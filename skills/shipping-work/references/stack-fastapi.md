# Stack: FastAPI

Applies when `pre-ship.sh` reports `framework fastapi`: `fastapi` is a
declared dependency in `pyproject.toml`. The checks are the uv toolchain's,
the same in every uv repo (see [gate-topology.md](gate-topology.md)). This
file holds what is specific to a FastAPI service.

## What doc-check watches by default

`AGENTS.md`, `README.md`, `CHANGELOG.md`, `pyproject.toml`, `uv.lock`,
`schema.sql`, `alembic/versions/`, `deploy/`, `src/api/`, `src/models/`,
`src/core/` and `.env.example`. On a hit, check the AGENTS.md route table
along with its structure and conventions. `.skills/doc-sensitive-paths` and
`.skills/doc-sections` replace these defaults.

## Step 8 — next steps for a FastAPI service

A project's `.skills/next-steps`, when present, replaces this table
(SKILL.md Step 8).

| Category | Trigger | Example action |
|---|---|---|
| DB migration (alembic) | `alembic/versions/` changed | `uv run alembic upgrade head` (or the project's `migrate.sh`), then `systemctl restart <project>` |
| DB migration (raw SQL) | `schema.sql` changed | `apply_schema` or `systemctl restart <project>` |
| Service restart | Code change (no auto-reload in prod) | `systemctl restart <project>` |
| Integration tests | New `@pytest.mark.integration` tests | `uv run pytest -m integration` on a real env; the gate never runs them |
| Env var / secret | New config key | Add to the project's env file and restart |
| Dev-server cleanup | Worktree shutdown | `fuser -k <port>/tcp` for the project's port |

Each row here that restarts the service is offered only after `bash
"<run-pre-restart.sh>"` passes or finds no `.skills/pre_restart` (SKILL.md
Step 8). A unit that applies its schema in `ExecStartPre` doesn't fail on an
unreachable DB: it loops in start-pre, and applies the schema unwatched when
the DB returns (CannObserv/power-map#748).

With `.skills/deploy_command` set, the deploy command owns both DB migration
rows and the service restart row, so drop them. Don't run `alembic upgrade
head` from the checkout either: it migrates live outside the deploy's order.
The env var row's "and restart" becomes the deploy
([deploy-command.md](deploy-command.md)).

## Env files

A service whose tests read secrets wraps the gate rather than forking it:
the recipe at the top of `pre-ship.sh` loads `/etc/<project>/.env` and the
checkout's `.env` (the primary checkout's from a linked worktree), and
exports `PRE_SHIP_ENV_NAMES`. Those names join the stamp key, and an empty
list writes no stamp, so a run that loaded no env cannot bless the tree for
one that does ([#497](https://github.com/gregoryfoster/skills/issues/497)).
