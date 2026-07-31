# Cohort context — why each default

Informational rationale for the branch-point defaults in `SKILL.md`. Surface this to the user when they ask "why this default?"; it does not gate any phase.

Stats refreshed 2026-07 from the 8-service cohort (address-validator, wslcb-licensing-tracker, power-map, archiver, watcher, notifier, observo, usa-wa), with deep analysis of the 4 mature services (archiver, power-map, observo, usa-wa — see [#65](https://github.com/gregoryfoster/skills/issues/65)).

- **`DB_BACKED=yes`**: 7/8 use SQLAlchemy[asyncio] + asyncpg. Power-map is the lone exception (raw asyncpg + hand-parsed `schema.sql`, no ORM/alembic).
- **`PROVISION_POSTGRES=yes`**: a fresh Ubuntu/Debian VM with no Postgres is the assumed CannObserv host (the canonical systemd unit's `After=postgresql.service` reflects this). Set to `no` when the host already has Postgres or when Postgres lives on a separate machine — Phase 5d then prints the manual provisioning checklist instead.
- **`SETTINGS_STYLE=pydantic-settings`**: observo, usa-wa, and address-validator use pydantic-settings; archiver/power-map/notifier/watcher read `os.environ` directly. Both work; the typed default remains recommended.
- **`MODELS_LAYOUT=monolithic`**: most start monolithic; archiver and notifier promoted to a `models/` package at ~5+ tables — the documented promotion path.
- **`AUTH_STYLE=header-token`**: all 4 mature services hand-rolled header auth (archiver `X-API-Key`, observo worker token, usa-wa `X-Operator-Token`, power-map API keys) — the scaffold now ships the shared fail-closed core.
- **`ADMIN_UI=none`**: 3/4 mature services grew a server-rendered HTMX + Jinja2 admin surface (archiver: sub-app `src/dashboard/`; power-map: `src/api/admin/` same-app router, ~80 modules; observo: Jinja routers + Vite frontend) — but none started with one, so the default stays off. Opting in scaffolds the convergent core (same-app router, vendored htmx, fail-closed trusted-proxy admin auth — [#67](https://github.com/gregoryfoster/skills/issues/67)); the JS toolchains are fully divergent across the three and deliberately **not** scaffolded — see the promotion paths in [`admin-ui.md`](admin-ui.md).
- **`LINT_PROFILE=minimal`**: the historical `E,F,I,W,UP` core plus the rules the cohort added after being bitten (`B904`, `PLC0415` — archiver #97/observo) and the now-stable `FAST`/`ASYNC` groups. Address-validator alone runs strict.
- **`LAYOUT=single`**: usa-wa (full workspace) and observo (one member) adopted `[tool.uv.workspace]`; pick `workspace` only for genuinely multi-package architectures.
- **`GITHUB_CI=no`**: archiver and observo run CI (identical shape: Postgres service, ruff+format, alembic upgrade+check, pytest); power-map and usa-wa gate locally only. Off by default; recommended once PRs flow.
- **`DEPLOY_TARGET=systemd`**: power-map, usa-wa, archiver, observo all production-deploy via systemd; power-map/usa-wa grew oneshot+timer fleets (see [`systemd-deploy.md`](systemd-deploy.md)). 0/8 use Docker for the app itself.

**Async task queue (not a branch point yet).** Notifier/watcher use [procrastinate](https://procrastinate.readthedocs.io/); observo runs bespoke asyncio lifespan tasks + Redis Streams; usa-wa a custom outbox + sidecar. No convergent shape — promote deliberately when a worker is actually needed.
