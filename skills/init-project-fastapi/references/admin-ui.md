# Admin UI scaffolding (`ADMIN_UI=htmx`)

Detailed templates for the `init-project-fastapi` skill's Phase 5e. Skip this file entirely when `ADMIN_UI=none` (default).

Design pass: [#67](https://github.com/gregoryfoster/skills/issues/67). The scaffolded shape is the convergent core of the three cohort services that grew an admin surface (archiver, power-map, observo): server-rendered Jinja2 + HTMX, same-app router, trusted-proxy auth. Everything the cohort diverges on (JS toolchains, sub-app registration, dashboard frameworks) is a documented promotion path, not scaffold — see the last section.

**Zero-Node invariant.** `ADMIN_UI=htmx` requires no `package.json`, no npm, no build step. htmx ships as a vendored file copied from this skill's assets.

## Dependencies (Phase 3 splice)

When `ADMIN_UI=htmx`, insert into the `dependencies` array in `pyproject.toml`:

```toml
    "jinja2>=3.1,<4",
    "python-multipart>=0.0.18,<0.1",
```

`python-multipart` is included up front because HTMX admin UIs post forms almost immediately. `aiofiles` is deliberately **not** a dependency — Starlette has served `StaticFiles`/`FileResponse` via anyio worker threads since 0.15 (2021); adding it would scaffold a dead dependency.

## Files created

```
src/api/admin/__init__.py            — empty (package marker)
src/api/admin/router.py              — same-app admin router (below)
src/templates/base.html              — page skeleton, loads vendored htmx
src/templates/admin/index.html       — full-page admin index
src/templates/admin/partials/status.html — example HTMX fragment
src/static/vendor/htmx.min.js        — vendored from skill assets (below)
tests/api/test_admin.py              — gate + rendering tests (below)
```

Plus additions to existing files: `src/api/deps.py` (`is_htmx` + `require_admin`), `src/core/config.py` (accessors — the `[ADMIN_UI=htmx]`-marked lines in [`settings-scaffolding.md`](settings-scaffolding.md)), and `src/api/main.py` (static mount + router include, below).

## Vendored htmx asset

```bash
mkdir -p src/static/vendor
cp "<SKILL_DIR>/assets/htmx.min.js" src/static/vendor/htmx.min.js
```

The asset is a pinned, reviewed copy of the htmx **2.x** minified dist (the version string is embedded in the file: `grep -oE '"2\.[0-9]+\.[0-9]+"' src/static/vendor/htmx.min.js`). Provenance rides the Phase 0 `SKILL_SHA` recorded in the bootstrap GH issue — the same reproducibility story as `alembic-env.py`. The copy is refreshed on skill releases; never replace it with a CDN `<script src>` — the admin surface must work air-gapped and under a strict CSP.

> **Refresh policy: latest *stable 2.x* only.** GitHub's `latest` release tag on bigskysoftware/htmx already points at 4.0 betas (not API-flagged as prereleases), so "grab the latest release" vendors a beta whose compatibility with the semantics this scaffold's code and tests assume (`HX-Request`, `HX-Redirect`) cannot be assumed. A major-version bump is a design change requiring its own review — pick the newest `v2.*` tag when refreshing.

## `src/api/admin/router.py`

`src/api/admin/__init__.py` is empty (touch only). The default template assumes `SETTINGS_STYLE=pydantic-settings`; for `os.environ`, import and call `get_build_id()` instead of `get_settings().build_id`.

```python
"""Server-rendered admin surface — HTMX + Jinja2, same-app router."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.api.deps import require_admin
from src.core.config import get_settings

# Anchored to the source tree, not CWD — systemd WorkingDirectory and the
# pytest rootdir differ, and a relative "src/templates" breaks under one
# of them.
_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"

templates = Jinja2Templates(directory=_TEMPLATES_DIR)

# include_in_schema=False: the admin surface is a browser surface, not part
# of the API contract — keep it out of /openapi.json.
admin_router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(require_admin)],
    include_in_schema=False,
)


@admin_router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Full-page render; htmx partials fill in dynamic regions."""
    return templates.TemplateResponse(request, "admin/index.html")


@admin_router.get("/partials/status", response_class=HTMLResponse)
async def status_partial(request: Request) -> HTMLResponse:
    """Example HTMX partial — returns a fragment, not a full page.

    Exists for the same reason as /api/v1/ping: it proves the auth gate,
    the template wiring, and the full-page/fragment split end-to-end.
    Replace with real partials as the admin surface grows.
    """
    return templates.TemplateResponse(
        request, "admin/partials/status.html", {"build": get_settings().build_id}
    )
```

## Auth — `is_htmx` + `require_admin` (add to `src/api/deps.py`)

`ADMIN_UI` is **orthogonal to `AUTH_STYLE`**: `AUTH_STYLE=header-token` protects the machine-facing `/api/v1` (browsers can't send `X-API-Key`); the admin surface authenticates via the power-map exe.dev pattern — a fronting proxy authenticates the browser session and stamps the identity into a trusted header. Without that proxy the admin surface is **intentionally unreachable** (fail-closed, like `require_api_key`).

**Security preconditions.** The header is only trustworthy when both hold: (1) the proxy **strips or overwrites** any client-supplied value of the `ADMIN_AUTH_HEADER` header before forwarding, and (2) the app port is **reachable only through the proxy** (firewall or bind rules) — the scaffold's systemd unit binds `0.0.0.0:<API_PORT>`, so anyone who can reach the port directly can forge the header and is fully authenticated. exe.dev's topology provides both; verify both before enabling `ADMIN_UI=htmx` on any other infrastructure.

When `DB_BACKED=no` and `AUTH_STYLE=none`, `src/api/deps.py` doesn't exist yet — create it containing only the block below, docstring included. When appending to an existing `deps.py`, drop the module docstring line (the file already has one).

```python
"""Admin-surface auth. Fail-closed: unconfigured proxy header means no access."""

from fastapi import HTTPException, Request

from src.core.config import get_admin_auth_header, get_admin_login_url


def is_htmx(request: Request) -> bool:
    """True when the request was issued by htmx (HX-Request header)."""
    return request.headers.get("HX-Request") == "true"


async def require_admin(request: Request) -> str:
    """Trusted-proxy admin auth (exe.dev pattern). Fail closed.

    Assumes a fronting proxy that authenticates the browser session and
    stamps the identity into the ADMIN_AUTH_HEADER header. Unconfigured
    header name means no access, not open access.
    """
    header_name = get_admin_auth_header()
    if not header_name:
        raise HTTPException(status_code=503, detail="Admin auth is not configured")
    user = request.headers.get(header_name)
    if user:
        return user
    login_url = get_admin_login_url()
    if is_htmx(request):
        # An HTTP redirect on an htmx request would swap the login page
        # INTO the hx-target element; HX-Redirect makes htmx do a
        # full-page navigation instead. This split is why is_htmx exists.
        headers = {"HX-Redirect": login_url} if login_url else None
        raise HTTPException(status_code=401, detail="Not authenticated", headers=headers)
    if login_url:
        # 303 See Other: an unauthenticated POST (expired session mid-form)
        # must become a GET at the login page, not replay as a POST there.
        raise HTTPException(
            status_code=303, detail="Redirecting to login", headers={"Location": login_url}
        )
    raise HTTPException(status_code=401, detail="Not authenticated")
```

**Import merging.** A second from-import of a module already imported trips ruff `I001` at Phase 12. With the default `AUTH_STYLE=header-token`, `deps.py` already imports from both modules — merge into single lines:

```python
from fastapi import HTTPException, Request, Security

from src.core.config import (
    get_admin_auth_header,
    get_admin_login_url,
    get_api_auth_token,
)
```

The `get_admin_auth_header()` / `get_admin_login_url()` accessors are the `[ADMIN_UI=htmx]`-marked lines in [`settings-scaffolding.md`](settings-scaffolding.md).

## `src/api/main.py` adjustments

Add to the base template from [`source-skeleton.md`](source-skeleton.md) — imports at the top (merged with existing lines where applicable), mount + include after `app.include_router(health_router)`:

```python
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from src.api.admin.router import admin_router

_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
app.include_router(admin_router)
```

## Templates

Substitute `<PROJECT_NAME>` in the templates below — in HTML it reads like a (bogus) tag, but it is the same placeholder convention as everywhere else in this skill.

### `src/templates/base.html`

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}<PROJECT_NAME> admin{% endblock %}</title>
  <script src="/static/vendor/htmx.min.js" defer></script>
</head>
<body>
  <main>{% block content %}{% endblock %}</main>
</body>
</html>
```

### `src/templates/admin/index.html`

```html
{% extends "base.html" %}
{% block content %}
<h1><PROJECT_NAME> admin</h1>
<div hx-get="/admin/partials/status" hx-trigger="load" hx-swap="innerHTML">
  Loading status…
</div>
{% endblock %}
```

### `src/templates/admin/partials/status.html`

```html
<p>build: <code>{{ build }}</code></p>
```

## `tests/api/test_admin.py`

Same conventions as `test_auth.py`: the example routes must exist for the gate to prove anything; `asyncio_mode = "auto"` means no decorators. For `SETTINGS_STYLE=os.environ` drop the three `cache_clear()` lines and the `get_settings` import — `os.environ.get` reads live.

Use the trailing-slash path `/admin/` in tests: `/admin` hits FastAPI's redirect-slashes 307 first, so the assertions would exercise the slash redirect instead of the auth gate.

```python
"""Admin gate + rendering: /admin rejects unauthenticated, renders page + fragment."""

import pytest

from src.core.config import get_settings

ADMIN_HEADER = "X-Auth-User"
ADMIN_USER = "ada"
LOGIN_URL = "https://login.example.test/"


@pytest.fixture(autouse=True)
def _configure_admin_auth(monkeypatch):
    monkeypatch.setenv("ADMIN_AUTH_HEADER", ADMIN_HEADER)
    monkeypatch.setenv("ADMIN_LOGIN_URL", LOGIN_URL)
    get_settings.cache_clear()  # SETTINGS_STYLE=os.environ: drop this line
    yield
    get_settings.cache_clear()  # SETTINGS_STYLE=os.environ: drop this line


async def test_unauthenticated_browser_redirected_to_login(client):
    response = await client.get("/admin/")
    assert response.status_code == 303
    assert response.headers["location"] == LOGIN_URL


async def test_unauthenticated_htmx_gets_hx_redirect(client):
    response = await client.get("/admin/", headers={"HX-Request": "true"})
    assert response.status_code == 401
    assert response.headers["hx-redirect"] == LOGIN_URL


async def test_unconfigured_auth_fails_closed(client, monkeypatch):
    monkeypatch.delenv("ADMIN_AUTH_HEADER")
    get_settings.cache_clear()  # SETTINGS_STYLE=os.environ: drop this line
    response = await client.get("/admin/", headers={ADMIN_HEADER: ADMIN_USER})
    assert response.status_code == 503


async def test_authenticated_page_renders(client):
    response = await client.get("/admin/", headers={ADMIN_HEADER: ADMIN_USER})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<html" in response.text


async def test_partial_is_a_fragment(client):
    response = await client.get(
        "/admin/partials/status",
        headers={ADMIN_HEADER: ADMIN_USER, "HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "<html" not in response.text
```

## Promotion paths (documented, not scaffolded)

**Sub-app registration (archiver's shape).** Archiver mounts its dashboard as a second FastAPI app (`register_dashboard(app)`) in the same process. That buys an isolated static mount, error handlers, and docs at the cost of a second app object threaded through lifespan and conftest. Promote when the admin surface genuinely needs its own middleware/error-handling stack — the same judgment call as the `MODELS_LAYOUT` monolithic → package promotion.

**JS toolchain.** Deliberately not a branch point: the cohort diverges completely (power-map: vitest + eslint 9 + prettier + happy-dom, with `package.json` version-synced to pyproject via a pre-commit hook; observo: Vite + Alpine + GridStack; archiver: npm lint/test wired into CI). Adopt a toolchain only when the admin surface accumulates real client-side logic — and note the version-sync pre-commit hook becomes relevant the moment a `package.json` exists. If the cohort converges on one shape, promote it to a branch point then.
