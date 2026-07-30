# Source skeleton

Detailed file contents for the `init-project-fastapi` skill's Phase 5 (source skeleton). Phase 5 creates these files; this reference holds the templates.

## `src/__init__.py`, `src/api/__init__.py`, `src/core/__init__.py`

Empty files (touch only).

## `src/api/main.py`

Default template assumes `DB_BACKED=yes` and `SETTINGS_STYLE=pydantic-settings`. Adjustments for other combinations are listed below.

```python
"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from importlib.metadata import version as pkg_version

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.core.config import get_settings
from src.core.database import get_session_factory
from src.core.db_safety import assert_database_safety
from src.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """One-time setup on startup, teardown on shutdown."""
    configure_logging()
    assert_database_safety()
    logger.info("application starting")
    yield
    logger.info("application stopping")


# version from package metadata — a hardcoded literal here drifts from
# pyproject.toml (power-map's /openapi.json reported 0.1.0 at project v0.15.0).
app = FastAPI(
    title="<PROJECT_NAME>", version=pkg_version("<PROJECT_NAME>"), lifespan=lifespan
)

health_router = APIRouter(tags=["health"])


@health_router.get("/health")
async def health() -> dict:
    """Liveness probe — confirms the app process is running. No external calls."""
    return {"status": "ok", "build": get_settings().build_id}


@health_router.get("/ready")
async def ready() -> JSONResponse:
    """Readiness probe — checks DB connectivity. Returns 503 on failure."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            await session.execute(text("SELECT 1"))
            return JSONResponse(status_code=200, content={"status": "ready", "db": True})
        except SQLAlchemyError:
            return JSONResponse(
                status_code=503, content={"status": "not_ready", "db": False}
            )


app.include_router(health_router)
```

### Adjustments for non-default branch points

- **`SETTINGS_STYLE=os.environ`**: replace `from src.core.config import get_settings` with `from src.core.config import get_build_id`; in `/health`, replace `get_settings().build_id` with `get_build_id()`.
- **`DB_BACKED=no`**: remove the three `sqlalchemy`/`src.core.database` imports, the `db_safety` import + `assert_database_safety()` call, and the entire `/ready` route. Keep `/health`.
- **`AUTH_STYLE=header-token`**: add the versioned, authenticated API router (below) after the health router. Health probes stay unauthenticated at root level.

### `AUTH_STYLE=header-token` — versioned router

Every mature cohort service hand-rolled header auth (archiver `require_api_key`, observo `require_worker_token`, usa-wa `require_operator`, power-map API keys); this scaffolds the shared core. Add to `src/api/main.py` — extend the base template's existing `from fastapi import …` line with `Depends` (a second separate `from fastapi import` line trips ruff `I001` at Phase 12):

```python
from fastapi import APIRouter, Depends, FastAPI  # merged with the base template's import

from src.api.deps import require_api_key

v1_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


@v1_router.get("/ping")
async def ping() -> dict:
    """Authed smoke route — proves the auth gate end-to-end.

    Router-level dependencies only run when a route matches, so an empty
    router would 404 before auth executes; this route keeps the gate (and
    tests/api/test_auth.py) exercising real behavior. Replace with feature
    routers as they are added.
    """
    return {"status": "ok"}


app.include_router(v1_router)
```

`require_api_key` lives in `src/api/deps.py` (see [`database-scaffolding.md`](database-scaffolding.md) § deps.py for the DB-backed file; for `DB_BACKED=no`, create `src/api/deps.py` containing only the auth dependency):

```python
"""Header-token auth. Fail-closed: unset token means no access, not open access."""

import secrets
from typing import Annotated

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from src.core.config import get_api_auth_token

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    api_key: Annotated[str | None, Security(_api_key_header)],
) -> None:
    """Reject the request unless X-API-Key matches API_AUTH_TOKEN."""
    expected = get_api_auth_token()
    if not expected:
        raise HTTPException(status_code=503, detail="API auth is not configured")
    if not api_key or not secrets.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
```

The matching `get_api_auth_token()` accessor is defined in [`settings-scaffolding.md`](settings-scaffolding.md). A DB-backed key table with per-key `last_used_at` (archiver's pattern) remains a project-level upgrade, not scaffold.

## `src/core/logging.py`

Copy verbatim:

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
