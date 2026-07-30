# Database scaffolding

Detailed file contents for the `init-project-fastapi` skill's Phase 5c (database scaffolding). Skip this entire reference when `DB_BACKED=no`.

## `src/core/database.py`

Async engine + session factory. Imports `get_database_url` from `src/core/config.py` (see [`settings-scaffolding.md`](settings-scaffolding.md)).

```python
"""Async database engine and session factory."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.config import get_database_url
from src.core.logging import get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the shared async engine, creating it on first call."""
    global _engine
    if _engine is None:
        url = get_database_url()
        _engine = create_async_engine(url, echo=False)
        logger.info("database engine created", extra={"host": url.split("@")[-1]})
    return _engine


def reset_engine() -> None:
    """Reset the shared engine and session factory. For testing only."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the shared session factory, creating it on first call."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory
```

## Models — choose layout based on `MODELS_LAYOUT`

### `MODELS_LAYOUT=monolithic` (default; matches 6/7 of cohort)

Create `src/core/models.py`:

```python
"""SQLAlchemy declarative base, shared mixins, and table definitions."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from ulid import ULID


def generate_ulid() -> str:
    """Return a new ULID string — sortable, 26 chars, cohort-standard row id."""
    return str(ULID())


class Base(DeclarativeBase):
    """Declarative base for all models."""


class UlidPkMixin:
    """Mixin adding a ULID primary key (CHAR(26), lexicographically time-ordered)."""

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=generate_ulid)


class TimestampMixin:
    """Mixin adding created_at and updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )


# Add table classes below as the schema grows; default shape is
# `class Foo(UlidPkMixin, TimestampMixin, Base)`. Promote to a `models/`
# package (MODELS_LAYOUT=package) when crossing ~5 tables or natural
# domain boundaries.
```

ULID PKs are a 4/4 cohort convergence (archiver/power-map/observo via `python-ulid`, usa-wa via a custom column type) — time-ordered so B-tree inserts stay append-mostly, and safe to generate client-side.

### `MODELS_LAYOUT=package` (matches notifier)

Create directory `src/core/models/` with:

**`src/core/models/__init__.py`** (re-exports):

```python
"""SQLAlchemy models."""

from src.core.models.base import Base, TimestampMixin

__all__ = ["Base", "TimestampMixin"]
```

**`src/core/models/base.py`** — same `Base` + `TimestampMixin` definitions as the monolithic variant above (drop the trailing comment).

## Alembic

Initialize Alembic, then overwrite the generated `alembic/env.py` with the asset content:

```bash
uv run alembic init alembic
```

Overwrite `alembic/env.py` with the asset:

```bash
cp "<SKILL_DIR>/assets/alembic-env.py" alembic/env.py
```

`<SKILL_DIR>` is the placeholder for the path captured in [Phase 0 of SKILL.md](../SKILL.md#phase-0--acquire-skill-source). Substitute the literal value printed by Phase 0.

Edit `alembic.ini`:

- Set `script_location = %(here)s/alembic`
- Confirm `prepend_sys_path = .` is present (alembic init populates it by default)
- Set the offline-fallback DSN: `sqlalchemy.url = postgresql+asyncpg://<PROJECT_UNDERSCORE>:<PROJECT_UNDERSCORE>@localhost:5432/<PROJECT_UNDERSCORE>` (only used by `alembic --sql` offline tooling; runtime reads `DATABASE_URL`). `<PROJECT_UNDERSCORE>` is the project name with hyphens converted to underscores (derived in Phase 5c — see SKILL.md). For hyphen-free project names it equals `<PROJECT_NAME>`; for hyphenated names (e.g. `usa-wa` → `usa_wa`) the underscore form keeps SQL identifiers unquoted so the offline DSN and the real Postgres role/database (Phase 5d) agree.

> The asset [`alembic-env.py`](../assets/alembic-env.py) imports `Base` from `src.core.models`. The package re-export in `MODELS_LAYOUT=package` and the monolithic `models.py` both expose `Base` at that path, so no env.py edit is needed for either layout.

### Optional hardening (adopt as the schema grows)

- **Boot-time head guard.** Once real migrations exist, refuse to serve behind schema: observo's `assert_db_at_head` runs in `lifespan` and raises if `alembic_version` trails the script head (observo #192 — added after removing `create_all` from startup). Not scaffolded by default because a fresh project has no revisions to compare.
- **Autogenerate-drift tripwire.** `uv run alembic check` fails when models changed but no migration was generated. Phase 12 runs it once at bootstrap; wire it into CI (`GITHUB_CI=yes`) so the drift class from observo #202 can't land silently.

## `src/core/db_safety.py`

Startup guard against pointing a dev/test process at a production database. Positive assertion (name must look non-production), not just an inequality check — modeled on archiver's `db_safety.py`, added after a 2026-07 incident where a dev server on the dev port silently shared the production database. Called from `lifespan` before any resource is built (see [`source-skeleton.md`](source-skeleton.md)).

```python
"""Refuse to start against a production-looking database without explicit consent."""

import os

from src.core.config import get_database_url

_ALLOW_ENV = "<PROJECT_UNDERSCORE_UPPER>_ALLOW_PRODUCTION_DB"
_SAFE_SUFFIXES = ("_test", "_dev")


class ProductionDatabaseRefused(RuntimeError):
    """Raised when the configured database looks like production."""


def assert_database_safety() -> None:
    """Raise unless the DB name carries a safe suffix or production is opted into."""
    if os.environ.get(_ALLOW_ENV) == "1":
        return
    try:
        url = get_database_url()
    except RuntimeError:
        # DATABASE_URL unset — nothing to guard. The app still boots (liveness
        # /health works during DB-less bring-up); the first real DB use raises
        # get_database_url's helpful error.
        return
    db_name = url.rsplit("/", 1)[-1].split("?")[0]
    if not db_name.endswith(_SAFE_SUFFIXES):
        raise ProductionDatabaseRefused(
            f"database {db_name!r} looks like production; "
            f"set {_ALLOW_ENV}=1 (production deploys only) or point at a *_dev/*_test database"
        )
```

`<PROJECT_UNDERSCORE_UPPER>` = `<PROJECT_UNDERSCORE>` uppercased (e.g. `usa-wa` → `USA_WA`). The production systemd unit sets `Environment=<PROJECT_UNDERSCORE_UPPER>_ALLOW_PRODUCTION_DB=1` **after** its `EnvironmentFile` lines so env files can't override the opt-in (see [`systemd-deploy.md`](systemd-deploy.md)). Skip this module when `DB_BACKED=no`.

## `src/api/deps.py`

FastAPI dependency that yields a database session:

```python
"""FastAPI dependencies (database session, auth, etc.)."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    """Yield an async DB session, closing it after the request completes."""
    factory = get_session_factory()
    async with factory() as session:
        yield session
```

> **FastAPI ≥0.118 cleanup timing.** The code after `yield` in a dependency now runs **after the response is sent** — the session stays open during response serialization but any post-yield commit/rollback happens post-response. Don't rely on post-yield code to affect the response; commit inside the handler when the result must be durable before the client sees 200.

When `AUTH_STYLE=header-token`, this file also carries `require_api_key` — see [`source-skeleton.md`](source-skeleton.md) § AUTH_STYLE for the template.
