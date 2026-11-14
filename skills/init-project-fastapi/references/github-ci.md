# GitHub Actions CI (`GITHUB_CI=yes` or `pre-commit`)

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
      # Coverage gate is active. The scaffolded suite (health + logging +
      # config) clears fail_under=80 on a typical bootstrap (replicator: 91%).
      # If a given branch-point mix lands under 80 (DB_BACKED / ADMIN_UI add
      # thinly-covered modules), add `--no-cov` here until the first feature
      # tests land — and note the shortfall in the bootstrap issue.
      - run: uv run pytest
```

## `GITHUB_CI=pre-commit`: a `gate` job runs the hooks

The workflow above with `lint` replaced by `gate`, which runs the commit-time definition itself, `pre-commit run --all-files`, so CI checks what a commit checked and a hook added later reaches CI with no edit here (skills#598, from CannObserv/power-map#761). `test` stays: the scaffold's hooks are the two remote ruff hooks and don't run pytest, and the DB tier needs the Postgres service. The hooks don't change, so pytest stays out of commit time. Add the top-level `permissions:`, give `test` a `timeout-minutes: 20`, and replace `lint` with:

```yaml
permissions:
  contents: read

jobs:
  gate:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    env:
      # A stale uv.lock fails instead of re-resolving. On the job, not the
      # workflow: `test`'s `uv sync --frozen` refuses UV_LOCKED (exit 2).
      UV_LOCKED: "1"
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run pre-commit run --all-files --show-diff-on-failure
```

Phase 7b passes `CI_JOBS=(gate test)` in the same render. Under `PRIVATE_INDEX=co-pypi`, (d) applies to `gate` and `test`, and `gate`'s sync step stays `uv sync`, without `--frozen`.

**The guard.** Copy [`assets/test-gate-workflow.py`](../assets/test-gate-workflow.py) to `tests/ci/test_gate_workflow.py`, with an empty `tests/ci/__init__.py`. It reads `ci.yml`, `.pre-commit-config.yaml` and `scripts/deploy_hooks.sh`, and fails when:
- a local `system` hook's first entry word has no setup step in `gate` (`uv` → `astral-sh/setup-uv`, `npm`/`npx` → `actions/setup-node`). A remote hook is pre-commit's to install, so it's not checked;
- there's a second pre-commit command, a non-install step before it, or a `SKIP=`;
- `gate` has neither `UV_LOCKED: "1"` nor `uv sync --locked`;
- a job has no `timeout-minutes`, or permissions beyond `contents: read` and co-pypi's `id-token: write`;
- the job names (`name:`, else the id) differ from `CI_JOBS`. A missing name makes `deploy.sh` refuse every deploy with `<name> (not in the run)`. It's skipped without the hooks file or under `CI=none`.

A hook that needs another tool gets its setup step in `gate` and an entry in the test's `PROVIDERS`.

## Notes

- **`uv sync --frozen`** — CI installs exactly the committed `uv.lock`; a stale lockfile fails here instead of surfacing on the VM.
- **Coverage gate skew.** `pyproject.toml`'s `fail_under` measures all of `src/`; if CI installs a different extras set than dev machines, the percentages diverge (observo #214 lowered its gate to reconcile a 78.6% CI vs 80.2% local split). Keep the CI install set identical to the local one, or pin the gate to the CI number.
- **No deploy from CI.** The VM deploys with `scripts/deploy.sh`, which waits for this workflow to pass on the commit (`CI_JOBS`); CI is a gate, not a pipeline. Don't add deploy steps here without revisiting that model.
- **Submodules.** The checkout above skips `skills-vendor/` submodules deliberately — nothing in lint/test needs them, and cloning them costs time. Add `with: {submodules: recursive}` only if a test reads vendored skill content.
