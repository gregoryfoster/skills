# pyproject.toml template

Detailed `pyproject.toml` structure for the `init-project-fastapi` skill (Phase 3). The agent assembles the file by combining the always-present blocks below with the optional blocks gated on branch-point parameters.

> **Conditional inclusion is described in prose above each block. No `# [CONDITIONAL: …]` markers appear in the templates themselves — when the agent writes the file, only real TOML lines should land in `pyproject.toml`.**

## Always-present blocks

### `[project]` table — base dependencies

Start from the block below. Then, before writing the file, splice in the optional dependency lines based on branch-point values:

- When `DB_BACKED=yes`: insert `"sqlalchemy[asyncio]>=2.0,<3"`, `"asyncpg>=0.30.0,<1"`, `"alembic>=1.15.0,<2"` into the `dependencies` array.
- When `SETTINGS_STYLE=pydantic-settings`: insert `"pydantic-settings>=2.5.0,<3"` into the `dependencies` array.

Floors reflect hard ecosystem boundaries: FastAPI 0.126 dropped Pydantic v1 support entirely (and requires pydantic ≥2.9), so the explicit `pydantic` floor keeps the resolver from ever considering a v1-compatible range. `python-ulid` is a base dependency (not DB-gated) — all four mature cohort services use ULIDs as identifiers, DB-backed or not.

```toml
[project]
name = "<PROJECT_NAME>"
version = "0.1.0"
description = "<PROJECT_DESCRIPTION>"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    "fastapi>=0.126.0,<1",
    "pydantic>=2.9,<3",
    "python-json-logger>=4.0.0,<5",
    "python-ulid>=3.1.0,<4",
    "uvicorn[standard]>=0.34.0,<1",
]

[dependency-groups]
dev = [
    "anyio>=4.0,<5",
    "httpx>=0.27,<1",
    "pre-commit>=4.0,<5",
    "pytest>=9.0,<10",
    "pytest-asyncio>=1.0,<2",
    "pytest-cov>=7.0,<8",
    "pytest-timeout>=2.3,<3",
    "ruff>=0.16,<0.17",
    "ty",  # beta — deliberately unpinned; non-gating advisory checker
]
```

Notes on the dev group:

- **`pytest-timeout`** backstops silent hangs — observo lost a ~51-minute CI run to a leaked `idle in transaction` backend before adopting it (observo #377). The `timeout`/`timeout_method` keys in the pytest config below activate it.
- **`ty`** (astral's type checker, beta) is deliberately **non-gating**: run `uv run ty check` ad hoc; no pre-commit hook, no CI gate. None of the cohort services gate on a type checker — this keeps the option cheap without imposing one.
- **`pytest-xdist` is opt-in, not scaffolded.** Parallel runs against a shared test database require per-worker databases (`<db>_test_gw0`, …) and advisory-lock overlap guards (see observo `tests/db_bootstrap.py`). Add it only when suite duration hurts, together with that isolation machinery.
- **Pin-compat caveat.** The `pytest-asyncio>=1.0,<2` range is assumed to resolve alongside pytest 9 but has not been verified against a live index from this repo. If the first bootstrap's `uv sync` fails resolution on the pytest ceiling, widen or adjust the `pytest` pin and report back to the skill.

### Pytest config — session loop scope reflects the cohort majority

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short -m 'not integration' --cov=src --cov-report=term-missing"
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
timeout = 300
timeout_method = "thread"
markers = [
    "integration: marks tests that hit live external services or a real database; excluded by default (run with -m integration)",
]
filterwarnings = [
    "error::DeprecationWarning",
]
```

`timeout_method = "thread"` (not the default signal method) so the timeout fires even when a test is blocked inside an asyncpg connection that holds the event loop — the exact failure mode of observo's silent hang.

### Coverage config

```toml
[tool.coverage.run]
source = ["src"]

[tool.coverage.report]
show_missing = true
fail_under = 80
```

### Build system

`uv_build` is uv's own backend and the `uv init` default since mid-2025; it is pure-Python-only, which fits every service in the cohort. Fall back to hatchling (`requires = ["hatchling"]`, `build-backend = "hatchling.build"`, plus `[tool.hatch.build.targets.wheel] packages = ["src"]`) only if the project will ship extension modules.

```toml
[build-system]
requires = ["uv_build>=0.12.0,<0.13"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "src"
module-root = ""
```

## Ruff config — choose based on `LINT_PROFILE`

When `DB_BACKED=yes`, append `"alembic/versions/"` to the `extend-exclude` array in whichever profile you pick.

### `LINT_PROFILE=minimal` (default)

The historical minimal set was `E,F,I,W,UP`; the additions codify rules the cohort adopted independently after being bitten: `B904` (exception chaining) and `PLC0415` (no inline imports — enforces the AGENTS.md convention; archiver #97) plus the now-stable FastAPI-specific `FAST` rules and the `ASYNC` rules (blocking calls inside async handlers — the highest-value latent-bug class for these services). `PLC0415` is ignored in tests, where fixture-local imports are the established pattern (e.g. importing the app inside the `client` fixture).

```toml
[tool.ruff]
line-length = 100
target-version = "py314"
extend-exclude = ["skills-vendor/"]

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP", "B904", "PLC0415", "FAST", "ASYNC"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["PLC0415"]

[tool.ruff.lint.isort]
known-first-party = ["src"]
```

### `LINT_PROFILE=strict` (matches `address-validator`; opt-in)

```toml
[tool.ruff]
line-length = 100
target-version = "py314"
extend-exclude = ["skills-vendor/"]

[tool.ruff.lint]
select = [
    "E", "W", "F", "I", "B", "C4", "UP", "S", "SIM",
    "ANN", "RUF", "PL", "SLF", "PTH", "TCH",
    "FAST", "ASYNC",
]
ignore = [
    "ANN401",  # Dynamically typed expressions (Any) allowed where needed
    "S101",    # Use of assert (needed in tests)
    "PLR0913", # Too many arguments — acceptable in FastAPI handlers
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["ANN", "S", "PLR2004", "SLF001", "PLC0415"]

[tool.ruff.lint.flake8-bugbear]
extend-immutable-calls = ["fastapi.Depends"]

[tool.ruff.lint.isort]
known-first-party = ["src"]
```
