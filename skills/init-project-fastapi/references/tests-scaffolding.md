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
        "Load env: set -a; . /etc/<PROJECT_NAME>/.env; . .env; set +a"
    )


def _check_test_url_safety(test_url: str) -> None:
    """Raise unless test_url names a *_test database distinct from DATABASE_URL.

    Two layers, both incident-driven across the cohort:
    1. Positive name check — the database name must end in `_test`. An
       inequality check alone still lets a mistyped production DSN through.
    2. Inequality check — TEST_DATABASE_URL must not equal DATABASE_URL,
       because teardown drops all model-mapped tables (Base.metadata.drop_all).
    """
    db_name = test_url.rsplit("/", 1)[-1].split("?")[0]
    if not db_name.endswith("_test"):
        raise RuntimeError(
            f"TEST_DATABASE_URL database {db_name!r} must end in '_test'. "
            "Test teardown drops all model-mapped tables; refusing a "
            "production-looking name."
        )
    prod_url = os.environ.get("DATABASE_URL")
    if prod_url and test_url == prod_url:
        raise RuntimeError(
            "TEST_DATABASE_URL must not equal DATABASE_URL. "
            "Test teardown drops all model-mapped tables (Base.metadata.drop_all) "
            "and would destroy matching production data."
        )


_check_test_url_safety(TEST_DATABASE_URL)

# Pin the environment: from here on, ANY code path that reads DATABASE_URL —
# including the app imported inside the client fixture, bypassing dependency
# overrides — resolves to the test database. Archiver adopted this defense
# after a dev process silently shared the production DB.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


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

## `tests/api/test_auth.py` — only when `AUTH_STYLE=header-token`

Exercises the `require_api_key` gate through the scaffolded `/api/v1/ping` route. The route must exist: router-level dependencies only run when a route matches, so an unmatched path would 404 before auth executes and prove nothing.

```python
"""Auth gate: /api/v1/* rejects missing/wrong keys, admits the configured key."""

import pytest

from src.core.config import get_settings

TOKEN = "test-token"


@pytest.fixture(autouse=True)
def _configure_token(monkeypatch):
    monkeypatch.setenv("API_AUTH_TOKEN", TOKEN)
    get_settings.cache_clear()  # SETTINGS_STYLE=os.environ: drop this line
    yield
    get_settings.cache_clear()  # SETTINGS_STYLE=os.environ: drop this line


async def test_missing_key_rejected(client):
    response = await client.get("/api/v1/ping")
    assert response.status_code == 401


async def test_wrong_key_rejected(client):
    response = await client.get("/api/v1/ping", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


async def test_valid_key_admitted(client):
    response = await client.get("/api/v1/ping", headers={"X-API-Key": TOKEN})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

For `SETTINGS_STYLE=os.environ` drop both `cache_clear()` lines and the `get_settings` import — `os.environ.get` reads live.

## Alternative: migration-driven test schema (adopt once real migrations exist)

The default `test_engine` uses `create_all`/`drop_all` — right for a fresh project with zero revisions. The mature cohort services flipped to **alembic as the only schema source**: archiver's conftest runs `alembic upgrade head` instead of `create_all`, and observo replays `DROP SCHEMA public CASCADE` + `alembic upgrade head` per session as a migration-ordering regression test. Adopt that shape once the first real migrations land:

```python
@pytest.fixture(scope="session")
async def test_engine():
    """Session-scoped engine; schema comes from migrations, not create_all."""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    # Alembic's env.py calls asyncio.run internally — run it in a worker
    # thread so it doesn't collide with the session-scoped event loop.
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: command.upgrade(Config("alembic.ini"), "head")
    )
    yield engine
    await engine.dispose()
```

(`from alembic import command`, `from alembic.config import Config`, `import asyncio`, `from sqlalchemy import text`. The savepoint `db_session` fixture is unchanged.) This also removes the `drop_all` teardown — the next session's `DROP SCHEMA` replay supersedes it.

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
