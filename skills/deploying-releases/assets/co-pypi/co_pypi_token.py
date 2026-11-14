# scripts/co_pypi_token.py — the co-pypi wrapper's minter (deploying-releases).
# deploying-releases-co-pypi: version 1
# deploying-releases-co-pypi-sha256: 0dff20874b37a955b58776c120b739164cb376aa318bede716cdd3c2cfe40e50
"""Run one ``uv`` command with a co-pypi access token in its environment.

    bash scripts/co-pypi.sh uv sync --locked --group dev
    bash scripts/co-pypi.sh uv lock --upgrade-package co-core

Installed by deploying-releases' ``install.sh --co-pypi`` with
``scripts/co-pypi.sh`` (gregoryfoster/skills#632), and never edited here: an
upgrade is a reviewable diff. Extracted from CannObserv/broker at ``bbf1c72f``,
which ported processor#121's locked group and replicator#183's allowlist.

cannobserv's packages resolve from its co-pypi Artifact Registry index
(``pyproject.toml``'s ``[[tool.uv.index]]``). It takes HTTP basic auth: the
username ``oauth2accesstoken`` and an OAuth2 access token as the password, which
uv reads from ``UV_INDEX_CO_PYPI_USERNAME`` / ``UV_INDEX_CO_PYPI_PASSWORD``. A
host has no gcloud, so this mints the token from the read-only
``co-pypi-reader`` key (``roles/artifactregistry.reader`` on co-pypi alone) and
``exec``s the command with the pair in that child's environment alone.

**The key:** ``CO_PYPI_KEY`` when set, else ``/etc/<name>/co-pypi-reader.json``,
``<name>`` being ``[project].name`` in the ``pyproject.toml`` beside this
script's directory. Never ``GOOGLE_APPLICATION_CREDENTIALS``: set shell-wide,
that names an identity to every Google client in the shell. The key path is
explicit, so google-auth's ADC search never runs.

**The caller's environment never reaches uv:** ``scripts/co-pypi.sh`` starts
the outer ``uv run`` from an allowlist and :func:`child_environment` cuts the
wrapped command's again, so the PATs a loaded ``.env`` carries reach neither.

**The token is never printed, logged, put in argv or written anywhere.** It
lives in this process and the wrapped ``uv``'s environment, an hour at most.
Anything but ``uv`` is refused before a token is minted. **Accepted limit:**
whatever that ``uv`` spawns inherits the pair (the build backend, building the
editable project). uv has no per-index credential scoping short of a keyring or
netrc file; the bound is the identity's read-only role and the token's hour.

Its own dependency is uv.lock's ``co-pypi`` group, run ``--frozen`` in this
script's checkout, so nothing in the process that holds the key is resolved at
run time.

Only a command that downloads from the index needs this: ``uv lock``, and a
``uv sync`` that needs a private file neither installed nor cached.
``uv lock --locked`` and ``uv audit --frozen`` don't.

Exit codes: the wrapped command's own - ``2`` usage or a refused command -
``1`` the mint failed (the key and its path included) - ``127`` the command
could not be run.
"""

from __future__ import annotations

import os
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

USERNAME_VAR = "UV_INDEX_CO_PYPI_USERNAME"
PASSWORD_VAR = "UV_INDEX_CO_PYPI_PASSWORD"
USERNAME = "oauth2accesstoken"
KEY_VAR = "CO_PYPI_KEY"
# The host's key: root:<deploy user> 640, beside the project's settings.
KEY_PATH = "/etc/{name}/co-pypi-reader.json"
PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
# Artifact Registry's documented scope for a token-as-password read; the
# identity's IAM role, artifactregistry.reader on co-pypi, is what bounds it.
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
# What uv may see. scripts/co-pypi.sh carries the same two lists, plus KEY_VAR.
# VIRTUAL_ENV is left out: the outer `uv run` sets it to the checkout's venv,
# and a wrapped `uv sync` in a release would warn about it.
ALLOWED = frozenset(
    {
        "PATH", "HOME", "USER", "LOGNAME", "LANG", "TERM", "TMPDIR",
        "http_proxy", "https_proxy", "no_proxy", "all_proxy",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
    }
)  # fmt: skip
ALLOWED_PREFIXES = ("LC_", "XDG_", "SSL_CERT_", "UV_")
USAGE = "usage: bash scripts/co-pypi.sh uv <command> [args...]"


def child_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """*environ* cut to the allowlist."""
    return {
        k: v
        for k, v in environ.items()
        if k in ALLOWED or k.startswith(ALLOWED_PREFIXES)
    }


def key_path(environ: Mapping[str, str], pyproject: Path = PYPROJECT) -> str:
    """``CO_PYPI_KEY``, else the project's default; raises when neither is known."""
    explicit = environ.get(KEY_VAR, "").strip()
    if explicit:
        return explicit
    try:
        name = tomllib.loads(pyproject.read_text())["project"]["name"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise LookupError(
            f"{KEY_VAR} is unset and {pyproject} names no [project].name"
        ) from exc
    if not isinstance(name, str) or not name or "/" in name or name.startswith("."):
        raise LookupError(
            f"{KEY_VAR} is unset and [project].name {name!r} is no directory name"
        )
    return KEY_PATH.format(name=name)


def mint_token(path: str) -> str:
    """An access token for the service account whose key is at *path*."""
    # Imported here, so the rest of this module runs without the co-pypi group.
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_file(
        path, scopes=SCOPES
    )
    credentials.refresh(Request())
    if not credentials.token:
        raise RuntimeError("the token endpoint returned no access token")
    return credentials.token


def main(
    argv: Sequence[str],
    environ: Mapping[str, str],
    *,
    mint: Callable[[str], str] = mint_token,
    execvpe: Callable[[str, list[str], dict[str, str]], object] = os.execvpe,
    pyproject: Path = PYPROJECT,
) -> int | None:
    """Exec *argv* (a ``uv`` command) with the co-pypi pair in its environment.

    Returns an exit code on failure; on success *execvpe* replaces the process,
    so in production nothing returns.
    """
    if not argv or Path(argv[0]).name != "uv":
        print(f"error: co-pypi wraps uv alone. {USAGE}", file=sys.stderr)
        return 2

    try:
        path = key_path(environ, pyproject)
    except LookupError as exc:
        print(f"error: no co-pypi-reader key: {exc}. Set {KEY_VAR}.", file=sys.stderr)
        return 1
    try:
        token = mint(path)
    except Exception as exc:  # broad by design: any failure here runs nothing
        # The exception is the token endpoint's or the key file's, never the token.
        print(
            f"error: could not mint a co-pypi access token from {path}:"
            f" {type(exc).__name__}: {exc}. Set {KEY_VAR}, or install the reader key there.",
            file=sys.stderr,
        )
        return 1

    env = child_environment(environ)
    env[USERNAME_VAR] = USERNAME
    env[PASSWORD_VAR] = token
    try:
        execvpe(argv[0], list(argv), env)
    except OSError as exc:
        # Names the command and errno, never `env`.
        print(f"error: could not run {argv[0]}: {exc.strerror or exc}", file=sys.stderr)
        return 127
    return None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], os.environ))
