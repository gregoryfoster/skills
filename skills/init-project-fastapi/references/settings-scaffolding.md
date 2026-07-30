# Settings scaffolding

Detailed `src/core/config.py` templates for the `init-project-fastapi` skill (Phase 5b). Settings is the single source of env access — `src/core/database.py` and any future runtime config imports from here. Create one of the two variants below based on `SETTINGS_STYLE`.

> **Both variants assume `DB_BACKED=yes`.** When `DB_BACKED=no`, drop **both** the `database_url` field **and** the `get_database_url()` shim function from the pydantic-settings variant; or omit the `get_database_url()` function entirely from the os.environ variant — those are the only DB-conditional lines in each template.
>
> **`AUTH_STYLE=header-token`** adds one field/function per variant, marked `[AUTH_STYLE=header-token]` below. Drop those lines when `AUTH_STYLE=none`.

## `SETTINGS_STYLE=pydantic-settings` (default)

```python
"""Application settings via pydantic-settings.

Env files (/etc/<PROJECT_NAME>/.env, repo .env) are loaded by systemd or the
developer before launch — never by this module.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str | None = None
    log_level: str = "INFO"
    build_id: str = "dev"
    api_auth_token: str | None = None  # [AUTH_STYLE=header-token]


@lru_cache
def get_settings() -> Settings:
    """Return the shared Settings instance."""
    return Settings()


def get_api_auth_token() -> str | None:  # [AUTH_STYLE=header-token]
    """Return API_AUTH_TOKEN or None when auth is unconfigured (fail-closed)."""
    return get_settings().api_auth_token


def get_database_url() -> str:
    """Return DATABASE_URL or raise with a helpful error."""
    url = get_settings().database_url
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Load env: set -a; . /etc/<PROJECT_NAME>/.env; . .env; set +a"
        )
    return url
```

## `SETTINGS_STYLE=os.environ`

```python
"""Application settings via os.environ.

Env files (/etc/<PROJECT_NAME>/.env, repo .env) are loaded by systemd or the
developer before launch — never by this module.
"""

import os


def get_database_url() -> str:
    """Return DATABASE_URL or raise with a helpful error."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Load env: set -a; . /etc/<PROJECT_NAME>/.env; . .env; set +a"
        )
    return url


def get_log_level() -> str:
    """Return LOG_LEVEL or default to INFO."""
    return os.environ.get("LOG_LEVEL", "INFO")


def get_build_id() -> str:
    """Return BUILD_ID (stamped by systemd ExecStartPre) or default to 'dev'."""
    return os.environ.get("BUILD_ID", "dev")


def get_api_auth_token() -> str | None:  # [AUTH_STYLE=header-token]
    """Return API_AUTH_TOKEN or None when auth is unconfigured (fail-closed)."""
    return os.environ.get("API_AUTH_TOKEN")
```
