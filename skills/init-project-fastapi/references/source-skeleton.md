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
- **`ADMIN_UI=htmx`**: add the `/static` mount + `admin_router` include from [`admin-ui.md`](admin-ui.md) § main.py adjustments after the health router. Merge its `from fastapi.staticfiles import StaticFiles` / `from pathlib import Path` imports at the top.

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


def build_json_formatter() -> JsonFormatter:
    """The single JSON formatter definition for the whole process.

    Referenced by BOTH `configure_logging()` (non-uvicorn entry points) and
    `src/core/log_config.json` (uvicorn's `--log-config`, via the dictConfig
    `"()"` factory key), so app records and uvicorn's own access/error lines
    serialize with one identical schema — no drift, one place to change.

    Keys must be named in the fmt: a bare JsonFormatter() defaults to
    "%(message)s" and emits records with no level, logger, or timestamp
    (skills#69).
    """
    return JsonFormatter(
        "%(levelname)s %(name)s %(message)s",
        timestamp=True,
        rename_fields={"levelname": "level", "name": "logger"},
    )


class ColorMessageFilter(logging.Filter):
    """Drop uvicorn's `color_message` extra before anything serializes it.

    uvicorn logs its lifecycle lines with an ANSI-coloured duplicate of the
    message attached as `extra={"color_message": ...}`, for its own
    colour-aware default formatter. Every extra reaches the JSON payload, so
    without this the records carry a second copy of the message full of escape
    sequences — the one thing structured logging exists to avoid (skills#82).

    A *filter*, not the formatter's `reserved_attrs`, and on the *loggers*
    rather than the handler: both choices put the strip at the record's source,
    before any handler reads it. A handler that builds its payload from the
    record's `__dict__` instead of a `logging.Formatter` — which is exactly what
    OpenTelemetry's `LoggingHandler` does, against a reserved list that does not
    cover `color_message` — would otherwise resurrect the field the day the sink
    changes, silently and with no failing test.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Strip the extra if present. Never drops a record."""
        record.__dict__.pop("color_message", None)
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with JSON formatting. Call once at entry
    points that do NOT run under uvicorn (CLI scripts, alembic env, cron
    oneshots, tests). Under uvicorn, `--log-config src/core/log_config.json`
    configures the whole logging tree at boot instead; this call is then a
    harmless no-op-equivalent (it reinstalls an identical root handler), which
    keeps app logs JSON even if someone launches uvicorn without --log-config.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(build_json_formatter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Use in modules as: logger = get_logger(__name__)"""
    return logging.getLogger(name)
```

The key set (`timestamp`, `level`, `logger`, `message`) matches structlog's defaults, so a later structlog migration (#68) won't churn downstream log consumers. `timestamp=True` emits ISO-8601 UTC rather than `asctime`'s comma-millisecond local time. `tests/core/test_logging.py` (see [`tests-scaffolding.md`](tests-scaffolding.md)) pins this field set.

## `src/core/log_config.json`

Copy verbatim. This is uvicorn's logging config, passed via `--log-config src/core/log_config.json` in every uvicorn invocation (systemd `ExecStart` and the dev-server commands in [`agents-md-template.md`](agents-md-template.md)). Without it, uvicorn's own loggers (`uvicorn`, `uvicorn.access`, `uvicorn.error`) ship with `propagate=False` and their own plain-text handlers, so `configure_logging()` — which only touches the root logger — never reaches them, and the service emits **mixed-format** logs in journald: plain-text access/error lines interleaved with JSON app records (skills#81, surfaced in observo#395). This file routes all three uvicorn loggers through the same JSON formatter, from the first boot line onward.

```json
{
  "version": 1,
  "disable_existing_loggers": false,
  "formatters": {
    "json": { "()": "src.core.logging.build_json_formatter" }
  },
  "filters": {
    "strip_color_message": { "()": "src.core.logging.ColorMessageFilter" }
  },
  "handlers": {
    "stdout": {
      "class": "logging.StreamHandler",
      "formatter": "json",
      "stream": "ext://sys.stdout"
    }
  },
  "root": { "level": "INFO", "handlers": ["stdout"] },
  "loggers": {
    "uvicorn": {
      "level": "INFO",
      "handlers": ["stdout"],
      "filters": ["strip_color_message"],
      "propagate": false
    },
    "uvicorn.error": {
      "level": "INFO",
      "handlers": ["stdout"],
      "filters": ["strip_color_message"],
      "propagate": false
    },
    "uvicorn.access": {
      "level": "INFO",
      "handlers": ["stdout"],
      "filters": ["strip_color_message"],
      "propagate": false
    }
  }
}
```

The `"()"` factory key makes dictConfig call `build_json_formatter()`, so this file carries **no** duplicate copy of the fmt string or field renames — the formatter stays single-sourced in `logging.py`. uvicorn's `AccessFormatter` is deliberately not used: a standard `%(message)s` render of an access record already interpolates its `%s`-args into the request line (`127.0.0.1:0 - "GET /health HTTP/1.1" 200`), which lands in the JSON `message` field. Because the app's own loggers still propagate to `root`, and uvicorn's three loggers keep `propagate: false` with their own handler, every record is emitted exactly once. This dictConfig shape is also the seam a later structlog `ProcessorFormatter` migration (#68) would reuse. `tests/core/test_logging.py` pins that this file stays valid and keeps sharing the formatter.

`strip_color_message` is listed on **all three** loggers, not just the parent `uvicorn`, and that repetition is load-bearing: a logger's filters run only in `Logger.handle()` for records logged *through that logger*, and propagation walks ancestors' **handlers**, never their filters. A filter on `uvicorn` alone would therefore never see a `uvicorn.error` record — not even with `propagate: true`. Do not "simplify" it to one entry. Today only `uvicorn.error` carries the extra (uvicorn's `server.py`, `config.py`, and the `--reload` supervisors all log there; access records pass no `extra=` at all), but the other two cost nothing and hold if uvicorn moves a lifecycle line. The filter is a `"()"` factory reference like the formatter, so the existing dictConfig-validity test also catches a rename of `ColorMessageFilter` — dictConfig raises when it cannot resolve the callable.

> **`LAYOUT=workspace`:** adjust **both** `"()"` import paths (`build_json_formatter` and `ColorMessageFilter`) and the `--log-config` path to the package that owns `core/logging.py` (e.g. `packages/<name>/src/...`), matching the `src.*` → package rewrite applied elsewhere in this reference.
