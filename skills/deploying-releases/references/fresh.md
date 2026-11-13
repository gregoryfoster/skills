# Fresh mode: a new repo on releases from its first commit

What `init-project-fastapi` delegates when `DEPLOY_TARGET=releases`, and what a new repo does by hand otherwise. Nothing here touches a host: the operator's one-time steps are in the `DEPLOYMENT.md` this writes, and run in the host's own session.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `PROJECT` | the repo's name | The unit prefix, the service user, `/srv/<PROJECT>`, `/etc/<PROJECT>` |
| `GITHUB_REPO` | `<org>/<PROJECT>` | For the CI gate; `CI=none` when the repo has no CI |
| The units | one API service | Each long-running unit: its name and `ExecStart` (the venv's entry point). Each oneshot: its name, module and interval |
| `DEV_TARGET` | none | A dev unit for each that should have one, named `<unit>-dev`, on `/srv/<PROJECT>/dev`; "none" means no dev unit at all |
| `DB` | none | Alembic: the `migrate` hook (as the deploy user, or through `<PROJECT>-migrate@.service` when it can't read the DSN) and a single-head `post_build_check` |
| `PRIVATE_INDEX` | no | co-pypi: `UV_WRAPPER=scripts/co-pypi.sh` ([#632](https://github.com/gregoryfoster/skills/issues/632)) |

## Steps

1. **Install the core and the hooks template:** `bash "<install.sh>"` (resolved as SKILL.md shows).
2. **Fill in `scripts/deploy_hooks.sh`.** `PROJECT`, `GITHUB_REPO`, `CI_JOBS` (the job names `ci.yml` runs on a push to `main`), `IMPORT_MODULES` (the app's entry modules), `UV_WRAPPER` when the index is private. Delete each hook the repo doesn't need. Write `verify` for each unit:
   - an HTTP service: `verify_http_health http://127.0.0.1:<port>/health "$2"`, where `/health` reports `revision` read from `REVISION` (`dev` when absent);
   - a oneshot on a timer: `verify_next_tick "$1" "$2" "<its summary message>"`, or `verify_forced_run` when a forced run is safe;
   - a worker with no port: return 2 for the core's restart check, or check the heartbeat another unit reports.
3. **Render the units** from `assets/units/` into `deploy/`: `service.tmpl` for each long-running unit, `oneshot.tmpl` and `timer.tmpl` for each scheduled one. Substitute `<PROJECT>`, `<NAME>`, `<EXEC_START>` (relative to the venv's `bin/`, such as `uvicorn src.api.main:app --host 127.0.0.1 --port 8000`), `<MODULE>` and `<INTERVAL>`. A dev unit is the same file with `-dev` in its name and `/srv/<PROJECT>/dev` in both paths.
4. **Copy the tests:** `assets/tests/test_deploy_contract.py` and `test_deploy_units.py` into `tests/deploy/`. They read the hooks file, so they need no editing, and they must pass before the first commit.
5. **Write `DEPLOYMENT.md`** from `assets/DEPLOYMENT.md.tmpl`, substituting `<PROJECT>`, and link it from the README.
6. **Set `.skills/deploy_command`** to `scripts/deploy.sh`.
7. **The app side,** which `init-project-fastapi`'s references own: `get_build_id()` reads `REVISION` from the release root and is `dev` without it; `Settings` reads only the env files it can open (a root-only `EnvironmentFile=` is exported by systemd before the user switch, and pydantic-settings raises on one it can't read: observo#695); under `DB`, `alembic/env.py` asserts the database is the one the settings name.

## What it does not do

- Run a deploy. The first deploy, and enabling each unit, is the operator's, after `DEPLOYMENT.md`'s one-time steps.
- Write a sudoers file, a user or anything under `/srv` or `/etc`.
- Add a drift check (a separate follow-up to #372).
