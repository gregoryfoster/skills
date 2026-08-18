# Completion table (Phase 16)

The report template for the `init-project-fastapi` skill's Phase 16. Present it after the Phase 0 scratch clone is cleaned up.

Then present a completion table. Branch-point rows show the choice made (or "skipped" when the branch was disabled):

| Component | Status |
|---|---|
| SSH deploy key | Configured |
| Git remote | `git@github-<PROJECT_NAME>:<GITHUB_ORG>/<PROJECT_NAME>.git` |
| Python tooling | uv, pytest (+timeout), ruff, ty (non-gating), uv_build |
| FastAPI skeleton | `src/api/main.py` (lifespan + /health[+/ready][+/api/v1 authed]), `src/core/logging.py`, `src/core/log_config.json` |
| Settings | `src/core/config.py` (`<SETTINGS_STYLE>`) |
| Auth | `<AUTH_STYLE>` — when header-token: `require_api_key` + `tests/api/test_auth.py` |
| Admin UI | `<ADMIN_UI>` — when htmx: `src/api/admin/`, `src/templates/`, `src/static/vendor/htmx.min.js` (vendored), `require_admin` + `tests/api/test_admin.py` |
| Database | `<DB_BACKED>` — when yes: `src/core/database.py`, `src/core/db_safety.py`, `src/core/models[.py\|/]` (`<MODELS_LAYOUT>`, ULID PKs), `alembic/` |
| Lint profile | `<LINT_PROFILE>` |
| Layout | `<LAYOUT>` |
| CI | `<GITHUB_CI>` — when yes: `.github/workflows/ci.yml` |
| Tests scaffold | `tests/conftest.py`, `tests/test_health.py`, `tests/core/test_logging.py`, `tests/core/test_config.py`, `tests/api/` |
| Deploy unit | `<DEPLOY_TARGET>` — when systemd: `deploy/<PROJECT_NAME>.service` (User=`<DEPLOY_USER>`, WorkingDirectory=`<DEPLOY_HOME>`) |
| Private wheelhouse | `<PRIVATE_WHEELHOUSE>` — when find-links: `scripts/sync_wheelhouse.py`, `[tool.uv] find-links`, `.wheelhouse/.gitkeep`, ExecStartPre/WIF sync (per `DEPLOY_TARGET`/`GITHUB_CI`) |
| Vendor submodules | `gregoryfoster/skills`, `obra/superpowers` |
| Skills | Local overrides + vendor skills symlinked (review/ship workflows: `-python-fastapi` variants only) + `.claude/skills/` discovery symlinks + `.skills/doctor.sh` |
| GH issue | #1 closed |
| Phase 0 scratch | Cleaned up (`<SKILL_TMP>` removed) |
