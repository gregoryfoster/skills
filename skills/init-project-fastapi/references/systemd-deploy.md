# systemd deployment artifacts

Detailed templates for the `init-project-fastapi` skill's Phase 7b (deployment artifacts). Skip this entire reference when `DEPLOY_TARGET=none`.

## `deploy/<PROJECT_NAME>.service`

Lifted from `notifier`'s canonical pattern (BUILD_ID stamping via `ExecStartPre`, two-tier `EnvironmentFile` chain). Substitute `<PROJECT_NAME>`, `<PROJECT_DESCRIPTION>`, `<API_PORT>`, `<DEPLOY_USER>`, `<DEPLOY_HOME>` throughout.

```ini
[Unit]
Description=<PROJECT_NAME> — <PROJECT_DESCRIPTION>
After=network.target postgresql.service
# Bound crash-restart loops: at most 10 restarts per 5 minutes, then stay
# failed (visible in systemctl status + OnFailure=) instead of flapping
# forever. Adopted after usa-wa #87.
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Type=simple
User=<DEPLOY_USER>
WorkingDirectory=<DEPLOY_HOME>

# Create runtime dir (runs as root before User= takes effect with + prefix)
ExecStartPre=+/bin/bash -c 'mkdir -p /run/<PROJECT_NAME> && chown <DEPLOY_USER>:<DEPLOY_USER> /run/<PROJECT_NAME>'

# Write current git SHA to a runtime env file before starting
ExecStartPre=/bin/bash -c 'echo BUILD_ID=$(git rev-parse --short HEAD) > /run/<PROJECT_NAME>/build-id'

# Load BUILD_ID, then system secrets, then optional repo-local overrides.
# Order matters: later EnvironmentFiles override earlier ones.
EnvironmentFile=-/run/<PROJECT_NAME>/build-id
EnvironmentFile=/etc/<PROJECT_NAME>/.env
EnvironmentFile=-<DEPLOY_HOME>/.env

# Production opt-in for the db_safety boot guard (DB_BACKED=yes only — drop
# otherwise). NOTE: systemd gives EnvironmentFile= precedence over
# Environment= regardless of textual order (systemd.exec: "Settings from
# these files override settings made with Environment="), so the guard
# holds only because the env files never define this variable — keep it
# out of /etc/<PROJECT_NAME>/.env and the repo .env.
Environment=<PROJECT_UNDERSCORE_UPPER>_ALLOW_PRODUCTION_DB=1

# --frozen --no-sync: serve exactly the committed lockfile; dependency sync
# is a deploy step, not a service-start side effect.
ExecStart=/usr/local/bin/uv run --frozen --no-sync uvicorn src.api.main:app --host 0.0.0.0 --port <API_PORT>
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Per-host adjustments

- **Private wheelhouse.** When `PRIVATE_WHEELHOUSE=find-links`, Phase 7b inserts a non-fatal wheelhouse-sync `ExecStartPre` (`-` prefix) just **above** the `ExecStart` line above — see call site (c) in [`private-wheelhouse.md`](private-wheelhouse.md). `ExecStart` stays on `--frozen --no-sync`.
- **PostgreSQL dependency.** The `After=network.target postgresql.service` line assumes a local Postgres. Remove `postgresql.service` from `After=` when the DB lives on another host, or drop the line entirely when `DB_BACKED=no`.
- **`uv` path.** `/usr/local/bin/uv` is the standard install location for the deploy host. If `uv` lives elsewhere on a given VM, edit before deploying or symlink it into `/usr/local/bin`.
- **Deploy step.** Because `ExecStart` runs `--frozen --no-sync`, run `uv sync --frozen` as part of the deploy (before `systemctl restart`) — the service no longer installs dependencies for you.

## Fleet patterns (adopt as scheduled jobs appear)

The mature cohort services converged on a systemd "fleet" beyond the single API unit — power-map ×4 and usa-wa ×8 timer pairs. Templates below are drop-in; substitute `<JOB>` per job.

**Oneshot + timer pair** — `deploy/<PROJECT_NAME>-<JOB>.service` + `.timer`:

```ini
# <PROJECT_NAME>-<JOB>.service
[Unit]
Description=<PROJECT_NAME> — <JOB>
After=network.target postgresql.service
OnFailure=<PROJECT_NAME>-notify-failure@%n.service

[Service]
Type=oneshot
User=<DEPLOY_USER>
WorkingDirectory=<DEPLOY_HOME>
# Refuse to run scheduled work from a non-main / detached-HEAD checkout —
# usa-wa #84 shipped a feature branch via a timer before adding this guard.
ExecStartPre=/bin/bash -c 'b=$(git symbolic-ref --short HEAD 2>/dev/null); [ "$b" = main ] || { echo "refusing: checkout on ${b:-detached HEAD}, not main" >&2; exit 1; }'
EnvironmentFile=/etc/<PROJECT_NAME>/.env
Environment=<PROJECT_UNDERSCORE_UPPER>_ALLOW_PRODUCTION_DB=1
ExecStart=/usr/local/bin/uv run --frozen --no-sync python -m src.jobs.<JOB>

# <PROJECT_NAME>-<JOB>.timer
[Unit]
Description=<PROJECT_NAME> — <JOB> schedule

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=15m

[Install]
WantedBy=timers.target
```

**Failure notification template** — `deploy/<PROJECT_NAME>-notify-failure@.service` (usa-wa #49). One templated unit serves every job via `OnFailure=…@%n.service`; `%i` carries the failing unit's name into the script:

```ini
[Unit]
Description=<PROJECT_NAME> — failure notification for %i

[Service]
Type=oneshot
User=<DEPLOY_USER>
WorkingDirectory=<DEPLOY_HOME>
EnvironmentFile=/etc/<PROJECT_NAME>/.env
ExecStart=/bin/bash <DEPLOY_HOME>/scripts/notify-failure.sh %i
```

`scripts/notify-failure.sh` is project-supplied (email gateway, webhook, …). Keep it fail-closed on missing config (error, don't silently skip) and never wire `OnFailure=` onto the notify unit itself (self-recursion).

## README "Deploy" section

Append the following block to `README.md`:

```markdown
## Deploy

The systemd unit lives at [`deploy/<PROJECT_NAME>.service`](deploy/<PROJECT_NAME>.service). To install on a fresh host:

​```bash
# Copy into systemd's path
sudo cp deploy/<PROJECT_NAME>.service /etc/systemd/system/<PROJECT_NAME>.service
sudo systemctl daemon-reload
sudo systemctl enable --now <PROJECT_NAME>

# Tail logs
sudo journalctl -u <PROJECT_NAME> -f
​```

Production secrets live in `/etc/<PROJECT_NAME>/.env` (managed manually on the VM, not in the repo). The unit's `ExecStartPre` writes the current git SHA to `/run/<PROJECT_NAME>/build-id` and exposes it as `BUILD_ID`.
```
