# Tests scaffolding

Detailed `tests/conftest.py` + `tests/test_health.py` templates for the `init-project-fastapi` skill (Phase 6). The default assumes `DB_BACKED=yes`; the no-DB variant is at the bottom.

## `tests/conftest.py` (DB_BACKED=yes — default)

```python
"""Shared test fixtures — async engine, savepoint-isolated session, and HTTP client.

Session-scoped event loop:
    Per-test loops would strand asyncpg connections (each connection is bound to
    the loop it was created in), forcing NullPool + per-test reconnect overhead
    (~50 ms per test, ~14x baseline). Session scope reuses one loop + pool for
    all tests in the run.
"""

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.api.deps import get_db_session
from src.core.models import Base

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    raise RuntimeError(
        "TEST_DATABASE_URL is not set. "
        "Load env: export $(cat /etc/<PROJECT_NAME>/.env .env 2>/dev/null | xargs)"
    )


def _check_test_url_safety(test_url: str) -> None:
    """Raise if test_url matches the production DATABASE_URL.

    Prevents Base.metadata.drop_all from destroying production data when
    TEST_DATABASE_URL is accidentally set to the production connection string.
    drop_all only drops model-mapped tables, not literally every table — but
    any production table mapped to Base.metadata is still at risk.
    """
    prod_url = os.environ.get("DATABASE_URL")
    if prod_url and test_url == prod_url:
        raise RuntimeError(
            "TEST_DATABASE_URL must not equal DATABASE_URL. "
            "Test teardown drops all model-mapped tables (Base.metadata.drop_all) "
            "and would destroy matching production data. "
            "Set TEST_DATABASE_URL to a dedicated test database "
            "(database name should include '_test')."
        )


_check_test_url_safety(TEST_DATABASE_URL)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
async def test_engine():
    """Session-scoped engine; creates schema once, drops it on teardown."""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession]:
    """Per-test session wrapped in a savepoint that rolls back on teardown."""
    async with test_engine.connect() as conn:
        txn = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        nested = await conn.begin_nested()

        @event.listens_for(session.sync_session, "after_transaction_end")
        def restart_savepoint(db_session, transaction):
            nonlocal nested
            if not nested.is_active:
                nested = conn.sync_connection.begin_nested()

        yield session

        await session.close()
        await txn.rollback()


@pytest.fixture
async def client(test_engine, db_session) -> AsyncGenerator[AsyncClient]:
    """AsyncClient wired to the FastAPI app with the savepointed db_session."""
    from src.api.main import app

    async def override_session() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

## `tests/test_health.py` — minimal smoke test (always created)

`pyproject.toml` sets `asyncio_mode = "auto"`, so coroutine tests are auto-marked — no `@pytest.mark.asyncio` decorator needed.

```python
"""Smoke test: /health responds 200 and includes a build id."""


async def test_health_returns_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "build" in body
```

## `tests/conftest.py` (DB_BACKED=no variant)

When `DB_BACKED=no`, replace the conftest above with this minimal version (no engine, no session fixture; `client` constructs the app directly):

```python
"""Shared test fixtures — HTTP client only (no database)."""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```
