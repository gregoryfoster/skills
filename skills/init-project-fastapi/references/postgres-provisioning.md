# PostgreSQL provisioning (Phase 5d)

Provisioning recipe used by [Phase 5d of SKILL.md](../SKILL.md#phase-5d--provision-postgresql) when `DB_BACKED=yes` and `PROVISION_POSTGRES=yes`. When `PROVISION_POSTGRES=no`, the phase prints steps 2–6 below as a manual checklist so the operator can run them themselves before re-running Phase 12.

Every SQL identifier below uses `<PROJECT_UNDERSCORE>` (derived in Phase 5c — `${PROJECT_NAME//-/_}`) so role and database names stay unquoted. For hyphen-free project names `PROJECT_UNDERSCORE == PROJECT_NAME` and the substitutions are no-ops.

## 1. Detect existing install

Skip any sub-step that's already done:

```bash
systemctl is-active postgresql 2>/dev/null || echo "postgresql not active"
which psql || echo "psql not on PATH"
```

## 2. Install (Ubuntu/Debian)

Matches the canonical systemd unit's `After=postgresql.service`:

```bash
sudo apt-get update
sudo apt-get install -y postgresql postgresql-contrib
```

## 3. Generate a random role password

24 bytes ≈ 48 hex characters:

```bash
PG_PW=$(openssl rand -hex 24)
echo "PG_PW=$PG_PW   # save this — also written to ./.env in step 5"
```

## 4. Create the role and two databases

As the `postgres` superuser:

```bash
sudo -u postgres psql <<SQL
CREATE ROLE <PROJECT_UNDERSCORE> LOGIN PASSWORD '$PG_PW';
CREATE DATABASE <PROJECT_UNDERSCORE>      OWNER <PROJECT_UNDERSCORE>;
CREATE DATABASE <PROJECT_UNDERSCORE>_test OWNER <PROJECT_UNDERSCORE>;
SQL
```

## 5. Append `DATABASE_URL` and `TEST_DATABASE_URL` to `./.env`

Use the `postgresql+asyncpg://` driver to match the runtime engine (Phase 5c's `database.py`):

```bash
cat >> ./.env <<ENV
DATABASE_URL=postgresql+asyncpg://<PROJECT_UNDERSCORE>:$PG_PW@localhost:5432/<PROJECT_UNDERSCORE>
TEST_DATABASE_URL=postgresql+asyncpg://<PROJECT_UNDERSCORE>:$PG_PW@localhost:5432/<PROJECT_UNDERSCORE>_test
ENV
```

## 6. Verify TCP + password connectivity from both databases

This proves the role can authenticate over TCP (not just `peer` auth on the local socket) and that both databases are reachable:

```bash
PGPASSWORD="$PG_PW" psql -h localhost -U <PROJECT_UNDERSCORE> -d <PROJECT_UNDERSCORE>      -c "SELECT 1;"
PGPASSWORD="$PG_PW" psql -h localhost -U <PROJECT_UNDERSCORE> -d <PROJECT_UNDERSCORE>_test -c "SELECT 1;"
```

Both `SELECT 1;` queries must return `1`. If either fails, fix the underlying issue (typical causes: `pg_hba.conf` `local` vs `host` rules, role password mismatch, Postgres not listening on `localhost`) before proceeding to Phase 12.
