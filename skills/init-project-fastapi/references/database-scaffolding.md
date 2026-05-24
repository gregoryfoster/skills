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

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all models."""


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


# Add table classes below as the schema grows.
# Promote to a `models/` package (MODELS_LAYOUT=package) when crossing ~5 tables
# or natural domain boundaries.
```

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

Now use the Write tool to replace `alembic/env.py` with the content of the asset [`alembic-env.py`](../assets/alembic-env.py). Do **not** use `cp` — Phase 5c runs before the vendor submodules and `skills/` symlinks are created (Phases 9–10), so the asset path doesn't exist as a real file in the bootstrapped project's tree. The asset is the agent's loaded source-of-truth; write its content directly.

Edit `alembic.ini`:

- Set `script_location = %(here)s/alembic`
- Confirm `prepend_sys_path = .` is present (alembic init populates it by default)
- Set the offline-fallback DSN: `sqlalchemy.url = postgresql+asyncpg://<PROJECT_NAME>:<PROJECT_NAME>@localhost:5432/<PROJECT_NAME>` (only used by `alembic --sql` offline tooling; runtime reads `DATABASE_URL`).

> The asset [`alembic-env.py`](../assets/alembic-env.py) imports `Base` from `src.core.models`. The package re-export in `MODELS_LAYOUT=package` and the monolithic `models.py` both expose `Base` at that path, so no env.py edit is needed for either layout.

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
