"""Private dependencies resolve from the co-pypi index, through the installed wrapper.

Copied in with deploying-releases' ``install.sh --co-pypi`` (gregoryfoster/skills#632);
the repo owns it after. Pure file reads: no network, no key.

* **The wrapper is the installed one, unedited.** ``scripts/co-pypi.sh`` and
  ``scripts/co_pypi_token.py`` match their own sha256 markers. A change belongs
  upstream, then ``install.sh --co-pypi``.
* **The URL is the org registry's byte for byte**, trailing slash included:
  Dependabot's updater matches it to the org's registry by string.
* **``explicit = true``, and a ``[tool.uv.sources]`` entry per private name.**
  An explicit index serves only the names pinned to it, so a private name never
  comes from PyPI, where it may be unclaimed, and nothing else comes from here.
* **Every private package is declared directly** (a dependency, an extra or a
  group, here or in a workspace member). uv binds a source to a direct
  dependency only, so one reached transitively would go to PyPI.
* **The lock carries each file's sha256**, and ``uv sync --locked`` refuses a
  file that misses it. A ``.wheelhouse`` lock is refused by the deploy.
* **The ``co-pypi`` group needs nothing from the index:** the wrapper syncs it
  before any token exists.
* **The repo's ruff excludes the minter,** which a ``--fix`` would otherwise edit.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO = Path(__file__).resolve().parents[1]
while not (REPO / "pyproject.toml").is_file() and REPO.parent != REPO:
    REPO = REPO.parent
PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text())
LOCK = tomllib.loads((REPO / "uv.lock").read_text())
WRAPPER = REPO / "scripts" / "co-pypi.sh"
MINTER = REPO / "scripts" / "co_pypi_token.py"
MARK_SHA = "# deploying-releases-co-pypi-sha256: "

INDEX = "co-pypi"
URL = "https://us-west1-python.pkg.dev/co-gcs/co-pypi/simple/"
HOST = "us-west1-python.pkg.dev"


def _uv() -> dict:
    return PYPROJECT.get("tool", {}).get("uv", {})


def _declared() -> set[str]:
    """Every name declared here or in a workspace member: what a source binds to."""
    paths = [REPO / "pyproject.toml"]
    for pattern in _uv().get("workspace", {}).get("members", []):
        paths += sorted(REPO.glob(f"{pattern}/pyproject.toml"))
    names = set()
    for path in paths:
        data = tomllib.loads(path.read_text())
        project = data.get("project", {})
        extras = project.get("optional-dependencies", {}).values()
        groups = data.get("dependency-groups", {}).values()
        lines = [
            *project.get("dependencies", []),
            *(r for extra in extras for r in extra),
            *(r for group in groups for r in group),
        ]
        requirements = [Requirement(r) for r in lines if isinstance(r, str)]
        names |= {canonicalize_name(req.name) for req in requirements}
    return names


def _private() -> list[dict]:
    return [p for p in LOCK["package"] if p.get("source", {}).get("registry") == URL]


@pytest.mark.parametrize("path", [WRAPPER, MINTER], ids=lambda p: p.name)
def test_the_wrapper_is_unedited(path: Path):
    text = path.read_text()
    match = re.search(rf"^{re.escape(MARK_SHA)}(\w+)$", text, flags=re.M)
    assert match, f"{path.name} has no co-pypi marker: run install.sh --co-pypi"
    zeroed = text.replace(match.group(0), MARK_SHA + "0" * 64, 1)
    assert hashlib.sha256(zeroed.encode()).hexdigest() == match.group(1), (
        f"{path.name} was edited by hand. Raise the change on gregoryfoster/skills, "
        "then reinstall with install.sh --co-pypi"
    )


def test_the_wrapper_is_executable():
    assert WRAPPER.stat().st_mode & 0o111


def test_the_repos_ruff_leaves_the_minter_alone():
    """A `ruff --fix` or `ruff format` pass would edit the installed minter and
    break its marker, so the repo's ruff excludes it."""
    ruff = PYPROJECT.get("tool", {}).get("ruff")
    if ruff is None:
        pytest.skip("no [tool.ruff] in pyproject.toml")
    excluded = [*ruff.get("exclude", []), *ruff.get("extend-exclude", [])]
    assert "scripts/co_pypi_token.py" in excluded, (
        'add "scripts/co_pypi_token.py" to [tool.ruff] extend-exclude'
    )


def test_one_explicit_co_pypi_index_at_the_org_registrys_url():
    indexes = [i for i in _uv().get("index", []) if i.get("name") == INDEX]
    assert len(indexes) == 1, f"want one [[tool.uv.index]] named {INDEX!r}"
    assert indexes[0]["url"] == URL, "byte for byte, trailing slash included"
    assert indexes[0].get("explicit") is True, (
        "an implicit index would serve every name, and a private one would be a"
        " lookup away from a PyPI namesake"
    )


def test_no_wheelhouse():
    assert "find-links" not in _uv(), "the co-pypi index replaced the wheelhouse"
    packages = LOCK["package"]
    assert not [p["name"] for p in packages if "wheelhouse" in str(p.get("source"))]


def test_the_sweep_finds_a_private_package():
    """Guard the guard: with nothing locked from the index, the tests below are vacuous."""
    assert _private(), f"nothing in uv.lock resolves from {URL}"


@pytest.mark.parametrize("package", _private(), ids=lambda p: p["name"])
def test_is_declared_directly_and_pinned_to_the_index(package: dict):
    assert canonicalize_name(package["name"]) in _declared(), (
        f"{package['name']} is locked but declared nowhere: uv binds sources to"
        " direct dependencies only, so a transitive one resolves from PyPI"
    )
    sources = {canonicalize_name(k): v for k, v in _uv().get("sources", {}).items()}
    assert sources.get(canonicalize_name(package["name"])) == {"index": INDEX}


@pytest.mark.parametrize("package", _private(), ids=lambda p: p["name"])
def test_locks_a_wheel_with_a_sha256_per_file(package: dict):
    """A wheel, not an sdist: CI's ``prune-cache`` keeps wheels built from
    source, so a private sdist would land in a cache a fork's PR can restore."""
    assert package.get("wheels"), f"{package['name']} would build from its sdist"
    for dist in [
        *([package["sdist"]] if "sdist" in package else []),
        *package["wheels"],
    ]:
        assert dist["url"].startswith(f"https://{HOST}/"), dist["url"]
        assert dist["hash"].startswith("sha256:") and len(dist["hash"]) == 7 + 64


def test_the_wrappers_group_needs_nothing_from_the_index():
    assert any(
        canonicalize_name(Requirement(r).name) == "google-auth"
        for r in PYPROJECT.get("dependency-groups", {}).get(INDEX, [])
        if isinstance(r, str)
    ), (
        f"declare [dependency-groups] {INDEX} = ['google-auth[requests]>=2,<3'], "
        "the minter's own dependency"
    )
    by_name: dict[str, list[dict]] = {}
    for package in LOCK["package"]:
        by_name.setdefault(package["name"], []).append(package)
    closure, todo = set(), ["google-auth"]
    while todo:
        name = todo.pop()
        if name in closure:
            continue
        closure.add(name)
        for package in by_name.get(name, []):
            todo += [d["name"] for d in package.get("dependencies", [])]
            for extra in package.get("optional-dependencies", {}).values():
                todo += [d["name"] for d in extra]
    assert "requests" in closure, "the extra the mint's transport needs"
    private = {p["name"] for p in _private()}
    assert not closure & private, f"the {INDEX} group would need a token to sync"
