# Core config files (Phase 3)

Literal file contents for the `init-project-fastapi` skill's Phase 3. Create each file at the repo root, substituting parameters. `pyproject.toml` has its own reference — [`pyproject-toml.md`](pyproject-toml.md).

## `.python-version`

```
3.14
```

## `.gitignore`

Standard Python + project ignores:

```
# Python
__pycache__/
*.py[oc]
build/
dist/
wheels/
*.egg-info

# Virtual environments
.venv

# Environment / secrets
.env
env

# Coverage
htmlcov/
.coverage
coverage.xml

# IDE
.idea/
.vscode/
*.swp
*.swo

# Git worktrees
.worktrees/

# Runtime (BUILD_ID stamp target — DEPLOY_TARGET=systemd writes /run/<PROJECT_NAME>/build-id)
/run/
```

## `.pre-commit-config.yaml`

Use the latest stable rev from `https://github.com/astral-sh/ruff-pre-commit/releases`, kept in step with the pyproject ruff pin:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.0  # update to latest stable
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

## `CLAUDE.md`

```
@AGENTS.md
```

## `README.md`

Setup, dev server, test commands; link to `docs/COMMANDS.md`. (Phase 7b appends a "Deploy" section when `DEPLOY_TARGET=systemd`.)
