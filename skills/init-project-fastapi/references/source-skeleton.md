# Source skeleton

Detailed file contents for the `init-project-fastapi` skill's Phase 5 (source skeleton). Phase 5 creates these files; this reference holds the templates.

## `src/__init__.py`, `src/api/__init__.py`, `src/core/__init__.py`

Empty files (touch only).

## `src/api/main.py`

Default template assumes `DB_BACKED=yes` and `SETTINGS_STYLE=pydantic-settings`. Adjustments for other combinations are listed below.

```python
"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.core.config import get_settings
from src.core.database import get_session_factory
from src.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """One-time setup on startup, teardown on shutdown."""
    configure_logging()
    logger.info("application starting")
    yield
    logger.info("application stopping")


app = FastAPI(title="<PROJECT_NAME>", version="0.1.0", lifespan=lifespan)

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
- **`DB_BACKED=no`**: remove the three `sqlalchemy`/`src.core.database` imports and the entire `/ready` route. Keep `/health`.

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
