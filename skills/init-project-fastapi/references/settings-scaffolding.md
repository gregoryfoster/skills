# Settings scaffolding

Detailed `src/core/config.py` templates for the `init-project-fastapi` skill (Phase 5b). Settings is the single source of env access — `src/core/database.py` and any future runtime config imports from here. Create one of the two variants below based on `SETTINGS_STYLE`.

> **Both variants assume `DB_BACKED=yes`.** When `DB_BACKED=no`, drop **both** the `database_url` field **and** the `get_database_url()` shim function from the pydantic-settings variant; or omit the `get_database_url()` function entirely from the os.environ variant — those are the only DB-conditional lines in each template.
>
> **`AUTH_STYLE=header-token`** adds one field/function per variant, marked `[AUTH_STYLE=header-token]` below. Drop those lines when `AUTH_STYLE=none`.
>
> **`ADMIN_UI=htmx`** adds two fields/functions per variant, marked `[ADMIN_UI=htmx]` below. Drop those lines when `ADMIN_UI=none`. Consumed by `require_admin` in [`admin-ui.md`](admin-ui.md).

**Neither variant opens an env file**, so a root-only `/etc/<PROJECT_NAME>/` can't raise (observo#695). Secrets may also be files in `$CREDENTIALS_DIRECTORY`, a unit's `LoadCredential=`. `get_build_id()` reads the `REVISION` the deploy writes last into a release; a checkout has none, so `dev`.

## `SETTINGS_STYLE=pydantic-settings` (default)

```python
"""Application settings via pydantic-settings.

Env files are loaded before launch, never here. Secrets may also be files in
$CREDENTIALS_DIRECTORY (a unit's LoadCredential=).
"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

#: The release root's, written last by the deploy.
REVISION_FILE = Path(__file__).resolve().parents[2] / "REVISION"


class Settings(BaseSettings):
    """Runtime configuration."""

    model_config = SettingsConfigDict(
        extra="ignore", secrets_dir=os.environ.get("CREDENTIALS_DIRECTORY")
    )

    database_url: str | None = None
    log_level: str = "INFO"
    api_auth_token: str | None = None  # [AUTH_STYLE=header-token]
    admin_auth_header: str | None = None  # [ADMIN_UI=htmx]
    admin_login_url: str | None = None  # [ADMIN_UI=htmx]


@lru_cache
def get_settings() -> Settings:
    """Return the shared Settings instance."""
    return Settings()


def get_build_id() -> str:
    """The release's REVISION (its sha12), or 'dev' in a checkout."""
    try:
        return REVISION_FILE.read_text().strip() or "dev"
    except OSError:
        return "dev"


def get_api_auth_token() -> str | None:  # [AUTH_STYLE=header-token]
    """Return API_AUTH_TOKEN or None when auth is unconfigured (fail-closed)."""
    return get_settings().api_auth_token


def get_admin_auth_header() -> str | None:  # [ADMIN_UI=htmx]
    """Return ADMIN_AUTH_HEADER or None when admin auth is unconfigured (fail-closed)."""
    return get_settings().admin_auth_header


def get_admin_login_url() -> str | None:  # [ADMIN_UI=htmx]
    """Return ADMIN_LOGIN_URL or None (no redirect target — plain 401 instead)."""
    return get_settings().admin_login_url


def get_database_url() -> str:
    """Return DATABASE_URL or raise with a helpful error."""
    url = get_settings().database_url
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Load env with load_env (AGENTS.md § Environment Variables); "
            "never source the file."
        )
    return url
```

## `SETTINGS_STYLE=os.environ`

```python
"""Application settings via os.environ.

Env files are loaded before launch, never here. Secrets may also be files in
$CREDENTIALS_DIRECTORY (a unit's LoadCredential=).
"""

import os
from pathlib import Path

#: The release root's, written last by the deploy.
REVISION_FILE = Path(__file__).resolve().parents[2] / "REVISION"


def _secret(name: str) -> str | None:
    """NAME from the environment, else the unit's credential file `name`."""
    if value := os.environ.get(name):
        return value
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    try:
        return (Path(directory) / name.lower()).read_text().strip() if directory else None
    except OSError:
        return None


def get_database_url() -> str:
    """Return DATABASE_URL or raise with a helpful error."""
    url = _secret("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Load env with load_env (AGENTS.md § Environment Variables); "
            "never source the file."
        )
    return url


def get_log_level() -> str:
    """Return LOG_LEVEL or default to INFO."""
    return os.environ.get("LOG_LEVEL", "INFO")


def get_build_id() -> str:
    """The release's REVISION (its sha12), or 'dev' in a checkout."""
    try:
        return REVISION_FILE.read_text().strip() or "dev"
    except OSError:
        return "dev"


def get_api_auth_token() -> str | None:  # [AUTH_STYLE=header-token]
    """Return API_AUTH_TOKEN or None when auth is unconfigured (fail-closed)."""
    return _secret("API_AUTH_TOKEN")


def get_admin_auth_header() -> str | None:  # [ADMIN_UI=htmx]
    """Return ADMIN_AUTH_HEADER or None when admin auth is unconfigured (fail-closed)."""
    return os.environ.get("ADMIN_AUTH_HEADER")


def get_admin_login_url() -> str | None:  # [ADMIN_UI=htmx]
    """Return ADMIN_LOGIN_URL or None (no redirect target — plain 401 instead)."""
    return os.environ.get("ADMIN_LOGIN_URL")
```
