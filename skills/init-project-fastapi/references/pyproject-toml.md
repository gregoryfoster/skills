# pyproject.toml template

Detailed `pyproject.toml` structure for the `init-project-fastapi` skill (Phase 3). The agent assembles the file by combining the always-present blocks below with the optional blocks gated on branch-point parameters.

> **Conditional inclusion is described in prose above each block. No `# [CONDITIONAL: …]` markers appear in the templates themselves — when the agent writes the file, only real TOML lines should land in `pyproject.toml`.**

## Always-present blocks

### `[project]` table — base dependencies

Start from the block below. Then, before writing the file, splice in the optional dependency lines based on branch-point values:

- When `DB_BACKED=yes`: insert `"sqlalchemy[asyncio]>=2.0,<3"`, `"asyncpg>=0.30.0,<1"`, `"alembic>=1.15.0,<2"` into the `dependencies` array.
- When `SETTINGS_STYLE=pydantic-settings`: insert `"pydantic-settings>=2.5.0,<3"` into the `dependencies` array.

```toml
[project]
name = "<PROJECT_NAME>"
version = "0.1.0"
description = "<PROJECT_DESCRIPTION>"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0,<1",
    "python-json-logger>=4.0.0,<5",
    "uvicorn>=0.34.0,<1",
]

[dependency-groups]
dev = [
    "anyio>=4.0,<5",
    "pre-commit>=4.0,<5",
    "pytest>=8.0,<9",
    "pytest-asyncio>=1.0,<2",
    "pytest-cov>=6.0,<7",
    "ruff>=0.9,<1",
]
```

### Pytest config — session loop scope reflects the cohort majority

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short -m 'not integration' --cov=src --cov-report=term-missing"
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
markers = [
    "integration: marks tests that hit live external services or a real database; excluded by default (run with -m integration)",
]
filterwarnings = [
    "error::DeprecationWarning",
]
```

### Coverage config

```toml
[tool.coverage.run]
source = ["src"]

[tool.coverage.report]
show_missing = true
fail_under = 80
```

### Build system

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src"]
```

## Ruff config — choose based on `LINT_PROFILE`

When `DB_BACKED=yes`, append `"alembic/versions/"` to the `extend-exclude` array in whichever profile you pick.

### `LINT_PROFILE=minimal` (default; matches 5/7 of cohort)

```toml
[tool.ruff]
line-length = 100
target-version = "py312"
extend-exclude = ["skills-vendor/"]

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP"]

[tool.ruff.lint.isort]
known-first-party = ["src"]
```

### `LINT_PROFILE=strict` (matches `address-validator`; opt-in)

```toml
[tool.ruff]
line-length = 100
target-version = "py312"
extend-exclude = ["skills-vendor/"]

[tool.ruff.lint]
select = [
    "E", "W", "F", "I", "B", "C4", "UP", "S", "SIM",
    "ANN", "RUF", "PL", "SLF", "PTH", "TCH",
]
ignore = [
    "ANN401",  # Dynamically typed expressions (Any) allowed where needed
    "S101",    # Use of assert (needed in tests)
    "PLR0913", # Too many arguments — acceptable in FastAPI handlers
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["ANN", "S", "PLR2004", "SLF001"]

[tool.ruff.lint.flake8-bugbear]
extend-immutable-calls = ["fastapi.Depends"]

[tool.ruff.lint.isort]
known-first-party = ["src"]
```
