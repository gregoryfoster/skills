---
name: init-project-fastapi
description: Bootstraps a new FastAPI project with the full CannObserv agent tooling foundation — SSH deploy key, pyproject.toml, FastAPI skeleton, structured logging, TDD scaffold, vendor skill submodules, local skill overrides, and GitHub issue tracking. Use when starting a new service in the CannObserv org.
compatibility: Designed for Claude. Requires git, gh CLI, ssh-keygen, uv. Must run inside an initialized git repository.
metadata:
  author: gregoryfoster
  version: "1.0"
  triggers: init project, bootstrap project, new fastapi project, set up foundation
---

# Initialize FastAPI Project — CannObserv Foundation

Bootstraps a new CannObserv FastAPI service from an empty git repo to a fully wired foundation: SSH deploy key, Python tooling, FastAPI skeleton, agent skills, and a closed GitHub issue.

<HARD-GATE>
Do NOT create files or run commands until you have collected all required parameters from the user and confirmed them. The project name drives file content, package names, and git remotes throughout — getting it wrong means manual cleanup.
</HARD-GATE>

## Parameters to collect

Ask the user (one at a time if not provided upfront):

| Parameter | Example | Used in |
|---|---|---|
| `PROJECT_NAME` | `watcher` | pyproject.toml, AGENTS.md, README.md, skill headers, GH issue |
| `PROJECT_DESCRIPTION` | `monitors cannabis industry activity: licenses, regulatory filings...` | pyproject.toml, AGENTS.md, README.md |
| `GITHUB_ORG` | `CannObserv` | git remote, deploy key host alias, GH issue |
| `API_PORT` | `8000` | AGENTS.md, README.md, docs/COMMANDS.md |
| `DEPLOY_KEY_LABEL` | `watcher-deploy-key` | ssh-keygen comment |
| `GIT_USER_NAME` | `Ada Lovelace` | git local config, commits |
| `GIT_USER_EMAIL` | `ada@example.com` | git local config, commits |

Before confirming, show the current global git identity and ask the user whether to use it or override per-project:

```
Current global git identity:
  user.name  = <git config --global user.name>
  user.email = <git config --global user.email>

Enter GIT_USER_NAME [press Enter to use global value]:
Enter GIT_USER_EMAIL [press Enter to use global value]:
```

If the user accepts both global values, skip Phase 2a.

Confirm all seven before proceeding.

## Procedure

### Phase 1 — SSH deploy key

```bash
bash skills/init-project-fastapi/scripts/gen-deploy-key.sh <PROJECT_NAME> <DEPLOY_KEY_LABEL>
```

Present the **public key** to the user:

> "Add this as a deploy key (with **write access**) on the `<GITHUB_ORG>/<PROJECT_NAME>` GitHub repo, then confirm when done."

**Wait for confirmation before continuing.**

### Phase 2 — Configure git remote

```bash
bash skills/init-project-fastapi/scripts/configure-remote.sh <PROJECT_NAME> <GITHUB_ORG>
```

Verify connectivity:

```bash
ssh -o StrictHostKeyChecking=no -T git@github-<PROJECT_NAME> 2>&1
```

Expected: `Hi <GITHUB_ORG>/<PROJECT_NAME>! You've successfully authenticated...`

### Phase 2a — Configure git identity

> Skip this phase if the user accepted both global values in the parameter collection step.

```bash
git config user.name  "<GIT_USER_NAME>"
git config user.email "<GIT_USER_EMAIL>"
```

Verify:

```bash
git config user.name   # should echo GIT_USER_NAME
git config user.email  # should echo GIT_USER_EMAIL
```

### Phase 3 — Core config files

Create these files, substituting parameters throughout:

**`.python-version`**
```
3.12
```

**`.gitignore`** — standard Python + project ignores:
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

# Gunicorn
gunicorn.ctl

# Git worktrees
.worktrees/
```

**`pyproject.toml`**
- name = `<PROJECT_NAME>`
- description = `<PROJECT_DESCRIPTION>`
- dependencies: `fastapi>=0.115.0`, `python-json-logger>=4.0.0`, `uvicorn>=0.34.0`
- dev deps: `anyio`, `pre-commit`, `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`
- build backend: hatchling
- ruff: line-length=100, target=py312, exclude vendor/, select E/F/I/W/UP
- pytest: testpaths=tests, asyncio_mode=auto, integration marker
- coverage: source=src, fail_under=80

**`.pre-commit-config.yaml`**

Use the latest stable rev from `https://github.com/astral-sh/ruff-pre-commit/releases`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.6  # update to latest stable
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

**`CLAUDE.md`**
```
@AGENTS.md
```

**`README.md`** — setup, dev server, test commands; link to docs/COMMANDS.md

### Phase 4 — AGENTS.md

Adapt the template below for the project. Replace `<PROJECT_NAME>`, `<PROJECT_DESCRIPTION>`, `<API_PORT>` throughout.

```markdown
# <PROJECT_NAME> — Agent Guidelines

Be terse. Prefer fragments over full sentences. Skip filler and preamble. Sacrifice grammar for density. Lead with the answer or action.

## Project Overview

<PROJECT_DESCRIPTION>

## Development Methodology

TDD required. Red → Green → Refactor. No production code without a failing test first.

## Environment & Tooling

Python ≥3.12, uv, pytest, ruff

## Project Layout

​```
src/api/        — FastAPI app (ASGI, routes, schemas)
src/core/       — Shared domain logic
tests/          — Mirrors src/ structure
docs/           — Reference docs (COMMANDS, SKILLS)
​```

## Services

| Service | Framework | Port |
|---|---|---|
| API | FastAPI | <API_PORT> |

​```bash
# FastAPI dev server
uv run uvicorn src.api.main:app --host 0.0.0.0 --port <API_PORT> --reload
​```

## Secrets

`env` (git-ignored): API keys and tokens. Never commit secrets.

​```bash
export $(cat env | xargs)
​```

Currently defined:
- `GH_TOKEN` — GitHub personal access token (used by `gh` CLI)

## Common Commands

​```bash
uv sync
uv run pytest
uv run ruff check .
uv run uvicorn src.api.main:app --host 0.0.0.0 --port <API_PORT> --reload
​```

Full reference: `docs/COMMANDS.md`

## Agent Skills

Skills in `skills/` (agentskills.io) and `.claude/skills/` (Claude Code). Reference: `docs/SKILLS.md`

## Conventions

**Commit Messages:**
​```
#<number> [type]: <description>      # with issue
[type]: <description>                # without issue
​```
Types: feat, fix, refactor, docs, test, chore

**Logging:**
​```python
from src.core.logging import get_logger
logger = get_logger(__name__)
​```
Entry points only: call `configure_logging()` once.

**Date & Time:**
- All UTC
- ISO 8601: `YYYY-MM-DDTHH:MM:SS.ffffffZ` (timestamps), `YYYY-MM-DD` (dates)

**General:**
- No inline module imports; all at file top
- Docstrings for public modules, classes, functions
- Test structure mirrors source (`src/foo.py` → `tests/test_foo.py`)
- Explicit imports only
- Small, focused functions
```

### Phase 5 — Source skeleton

**`src/__init__.py`** — empty

**`src/api/__init__.py`** — empty

**`src/api/main.py`**
```python
"""FastAPI application entry point."""

from fastapi import FastAPI

from src.core.logging import configure_logging

configure_logging()

app = FastAPI(title="<PROJECT_NAME>", version="0.1.0")
```

**`src/core/__init__.py`** — empty

**`src/core/logging.py`** — copy verbatim from the reference implementation:
```python
"""Structured JSON logging utilities."""

import logging
import sys

from pythonjsonlogger.json import JsonFormatter


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logger with JSON formatting. Call once at entry points."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Use in modules as: logger = get_logger(__name__)"""
    return logging.getLogger(name)
```

### Phase 6 — Tests scaffold

Create empty `__init__.py` files:
- `tests/__init__.py`
- `tests/api/__init__.py`
- `tests/core/__init__.py`

### Phase 7 — Docs

**`docs/COMMANDS.md`** — setup, dev server, test, lint, submodule commands. Substitute `<API_PORT>`.

**`docs/SKILLS.md`** — copy from this project's `docs/SKILLS.md` verbatim (skill names and vendor sources are the same across projects).

**`docs/plans/.gitkeep`** — empty file to track the directory.

### Phase 8 — `.claude/settings.json`

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "LOCK=\"/tmp/<PROJECT_NAME>-submodule-update-$(date +%Y%m%d)\"; if [ ! -f \"$LOCK\" ]; then git submodule update --remote --merge vendor/gregoryfoster-skills vendor/obra-superpowers && touch \"$LOCK\" && if ! git diff --quiet HEAD vendor/gregoryfoster-skills vendor/obra-superpowers 2>/dev/null; then git add vendor/gregoryfoster-skills vendor/obra-superpowers && git commit -m 'chore: update skills submodules'; fi; fi"
          }
        ]
      }
    ]
  },
  "permissions": {
    "allow": [
      "Read(/home/exedev/.claude/projects/**)"
    ]
  }
}
```

### Phase 9 — Vendor submodules

```bash
git submodule add https://github.com/gregoryfoster/skills.git vendor/gregoryfoster-skills
git submodule add https://github.com/obra/superpowers.git vendor/obra-superpowers
```

### Phase 10 — `skills/` directory

**Vendor symlinks (9):** Create from within the repo root — paths must be relative from `skills/`:

```bash
# obra-superpowers
ln -s ../vendor/obra-superpowers/skills/dispatching-parallel-agents  skills/dispatching-parallel-agents
ln -s ../vendor/obra-superpowers/skills/subagent-driven-development   skills/subagent-driven-development
ln -s ../vendor/obra-superpowers/skills/systematic-debugging          skills/systematic-debugging
ln -s ../vendor/obra-superpowers/skills/test-driven-development       skills/test-driven-development
ln -s ../vendor/obra-superpowers/skills/using-git-worktrees           skills/using-git-worktrees
ln -s ../vendor/obra-superpowers/skills/verification-before-completion skills/verification-before-completion
ln -s ../vendor/obra-superpowers/skills/writing-skills                skills/writing-skills

# gregoryfoster-skills
ln -s ../vendor/gregoryfoster-skills/skills/managing-skills-claude    skills/managing-skills-claude
ln -s ../vendor/gregoryfoster-skills/skills/reviewing-architecture-claude skills/reviewing-architecture-claude
```

**Local overrides (4):** Copy the following from this project and substitute `<PROJECT_NAME>` in the frontmatter `name:` field and skill headers:

| Override | Files |
|---|---|
| `skills/brainstorming/` | `SKILL.md` |
| `skills/reviewing-code-claude/` | `SKILL.md`, `scripts/gather-context.sh` |
| `skills/shipping-work-claude/` | `SKILL.md`, `scripts/check-status.sh`, `scripts/close-issue.sh`, `scripts/comment-issue.sh`, `scripts/pre-ship.sh`, `scripts/push.sh` |
| `skills/writing-plans/` | `SKILL.md`, `plan-document-reviewer-prompt.md` |

Substitutions in local overrides:
- Skill headers: `— power-map` → `— <PROJECT_NAME>`
- `pre-ship.sh` stamp file prefix: `pm-tests-clean` → `<PROJECT_NAME>-tests-clean`
- All other content: verbatim

### Phase 11 — `.claude/skills/` symlinks (13)

Create from repo root — paths must be relative from `.claude/skills/`:

```bash
mkdir -p .claude/skills
for skill in \
  brainstorming reviewing-code-claude shipping-work-claude writing-plans \
  dispatching-parallel-agents managing-skills-claude reviewing-architecture-claude \
  subagent-driven-development systematic-debugging test-driven-development \
  using-git-worktrees verification-before-completion writing-skills; do
  ln -s "../../skills/$skill" ".claude/skills/$skill"
done
```

### Phase 12 — Verify

```bash
uv sync
uv run pre-commit install
uv run ruff check .
uv run pytest --no-cov
```

Expected: ruff clean, pytest exits 0 or 5 (no tests collected — acceptable on empty suite).

If either fails, fix before proceeding.

### Phase 13 — Commit

Stage everything and commit:

```bash
git add -A
git commit -m "#1 feat: set up project foundation"
```

Commit message body should list all key scaffold components (see AGENTS.md commit convention).

### Phase 14 — Push

```bash
bash skills/shipping-work-claude/scripts/push.sh
```

### Phase 15 — GitHub issue

Create and immediately close issue #1:

```bash
gh issue create \
  --title "Set up project foundation" \
  --body "..."
```

Body must include: Summary (1–2 sentences), Design doc (N/A), Scope (bulleted list of all scaffold components).

Post a completion comment referencing the commit SHA, then close:

```bash
gh issue comment 1 --body "..."
gh issue close 1
```

### Phase 16 — Report

Present a completion table:

| Component | Status |
|---|---|
| SSH deploy key | Configured |
| Git remote | `git@github-<PROJECT_NAME>:<GITHUB_ORG>/<PROJECT_NAME>.git` |
| Python tooling | uv, pytest, ruff, hatchling |
| FastAPI skeleton | `src/api/main.py`, `src/core/logging.py` |
| Tests scaffold | `tests/api/`, `tests/core/` |
| Vendor submodules | `gregoryfoster/skills`, `obra/superpowers` |
| Skills | 4 local overrides + 9 vendor symlinks + 13 Claude discovery symlinks |
| GH issue | #1 closed |

## Key invariants

- The stamp file prefix in `pre-ship.sh` must use `<PROJECT_NAME>` not `pm` — mixing stamp files across projects causes false test-pass skips.
- All symlinks use **relative** paths — absolute paths break after cloning.
- `configure_logging()` called once in `src/api/main.py` only — never in library modules.
- `uv.lock` must be committed alongside `pyproject.toml`.
