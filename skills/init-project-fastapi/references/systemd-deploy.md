# systemd deployment artifacts

Detailed templates for the `init-project-fastapi` skill's Phase 7b (deployment artifacts). Skip this entire reference when `DEPLOY_TARGET=none`.

## `deploy/<PROJECT_NAME>.service`

Lifted from `notifier`'s canonical pattern (BUILD_ID stamping via `ExecStartPre`, two-tier `EnvironmentFile` chain). Substitute `<PROJECT_NAME>`, `<PROJECT_DESCRIPTION>`, `<API_PORT>`, `<DEPLOY_USER>`, `<DEPLOY_HOME>` throughout.

```ini
[Unit]
Description=<PROJECT_NAME> — <PROJECT_DESCRIPTION>
After=network.target postgresql.service

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

ExecStart=/usr/local/bin/uv run uvicorn src.api.main:app --host 0.0.0.0 --port <API_PORT>
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Per-host adjustments

- **PostgreSQL dependency.** The `After=network.target postgresql.service` line assumes a local Postgres. Remove `postgresql.service` from `After=` when the DB lives on another host, or drop the line entirely when `DB_BACKED=no`.
- **`uv` path.** `/usr/local/bin/uv` is the standard install location for the deploy host. If `uv` lives elsewhere on a given VM, edit before deploying or symlink it into `/usr/local/bin`.

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
