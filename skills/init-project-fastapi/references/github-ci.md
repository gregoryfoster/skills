# GitHub Actions CI (`GITHUB_CI=yes`)

Workflow template for the `init-project-fastapi` skill's CI branch point. The shape is the convergent form archiver and observo independently arrived at: one lint job, one test job with a Postgres service, and the alembic drift tripwire.

Default is `GITHUB_CI=no` — the org's single-VM model gates locally (pre-commit + `pre-ship.sh`) and treats main-on-the-VM as the deployed truth. Choose `yes` when the repo will take PRs from more than one working copy, or when you want the `alembic check` tripwire to run somewhere a developer can't skip.

## `.github/workflows/ci.yml`

Splice per the branch points: drop the `services:`/migration/`alembic check` pieces when `DB_BACKED=no`; the pytest env vars come from the service container.

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run ruff format --check .

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: ci
          POSTGRES_PASSWORD: ci
          POSTGRES_DB: <PROJECT_UNDERSCORE>_test
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U ci"
          --health-interval 5s --health-timeout 5s --health-retries 10
    env:
      TEST_DATABASE_URL: postgresql+asyncpg://ci:ci@localhost:5432/<PROJECT_UNDERSCORE>_test
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen
      # Migration replay + autogenerate-drift tripwire (observo #202): upgrade
      # must apply cleanly from empty, and `alembic check` fails if models
      # changed without a generated migration.
      - run: uv run alembic upgrade head
        env: { DATABASE_URL: "${{ env.TEST_DATABASE_URL }}" }
      - run: uv run alembic check
        env: { DATABASE_URL: "${{ env.TEST_DATABASE_URL }}" }
      # --no-cov on a fresh scaffold: the pyproject fail_under=80 gate can't
      # be met by the bootstrap suite (~63% — see Phase 12). Once the first
      # real feature + tests land, drop --no-cov to activate the gate.
      - run: uv run pytest --no-cov
```

## Notes

- **`uv sync --frozen`** — CI installs exactly the committed `uv.lock`; a stale lockfile fails here instead of surfacing on the VM.
- **Coverage gate skew.** `pyproject.toml`'s `fail_under` measures all of `src/`; if CI installs a different extras set than dev machines, the percentages diverge (observo #214 lowered its gate to reconcile a 78.6% CI vs 80.2% local split). Keep the CI install set identical to the local one, or pin the gate to the CI number.
- **No deploy from CI.** The org deploys via systemd on the VM (`main` is the deployed code); CI is a tripwire, not a pipeline. Don't add deploy steps here without revisiting that model.
- **Submodules.** The checkout above skips `skills-vendor/` submodules deliberately — nothing in lint/test needs them, and cloning them costs time. Add `with: {submodules: recursive}` only if a test reads vendored skill content.
