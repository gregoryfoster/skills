"""The converse sweep: a runtime declaration nothing imports is stale.

Copied from the adopting-dependabot skill (gregoryfoster/skills#376), cut down
from CannObserv/watcher's tests/test_dependency_imports.py. Edit the block
marked ADAPT and nothing else.

Run it before turning on a package ecosystem. Each stale declaration would get
bump PRs for a package nobody chooses, and keeps a bound in force that means
nothing. Watcher had 8 of 26 runtime specifiers that nothing imported: an
extraction stack moved to a shared library, a deleted diff module, extracted
notification channels (watcher 93aa3f8).

**Resolution is by dotted prefix, not top-level name.** ``google`` is a
namespace several distributions ship into, so each import resolves to the
distributions shipping its longest dotted prefix, read from their installed
file lists.

**Precondition:** the environment is synced from the lockfile, so every
declared distribution is installed and its file list readable.
"""

import ast
import sys
import tomllib
from collections import defaultdict
from functools import cache
from importlib import metadata
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

# ---- ADAPT ------------------------------------------------------------------
# Where runtime code lives: every import under these counts.
SOURCE_DIRS: tuple[str, ...] = ("src",)
# Declared, but reached by name rather than by import:
# distribution -> (glob, witness text one match must contain, why).
# The witness is what keeps an entry honest: drop the last `Form(` and
# python-multipart stays declared for nothing, unless a test checks it.
NEEDED_WITHOUT_IMPORT: dict[str, tuple[str, str, str]] = {
    # "asyncpg": ("src/**/*.py", "postgresql+asyncpg", "SQLAlchemy loads the driver the URL names."),
    # "uvicorn": ("deploy/*.service", "uvicorn ", "The server the unit file runs."),
    # "python-multipart": ("src/**/*.py", "Form(", "FastAPI parses every Form(...) body with it."),
}
# -----------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
_RUNTIME = frozenset(
    canonicalize_name(Requirement(spec).name)
    for spec in _MANIFEST.get("project", {}).get("dependencies", [])
    if isinstance(spec, str)
)


def _first_party() -> frozenset[str]:
    """This repo's own top-level packages: at the root, in each source dir, and the dirs themselves."""
    names = {p.parent.name for p in REPO_ROOT.glob("*/__init__.py")}
    for directory in SOURCE_DIRS:
        base = REPO_ROOT / directory
        names |= {p.parent.name for p in base.glob("*/__init__.py")}
        names |= {p.stem for p in base.glob("*.py")}
        names.add(base.name)
    return frozenset(names)


def _module_name(file: metadata.PackagePath) -> str | None:
    """The dotted module a distribution's ``.py`` file defines; None for any other file."""
    if file.suffix != ".py":
        return None
    *directories, name = file.parts
    stem = name.removesuffix(".py")
    parts = directories if stem == "__init__" else [*directories, stem]
    if not parts or not all(part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


@cache
def _module_owners() -> dict[str, frozenset[str]]:
    """Each installed module path, and every package above it, to the distributions shipping it."""
    owners: dict[str, set[str]] = defaultdict(set)
    for dist in metadata.distributions():
        name = canonicalize_name(dist.metadata["Name"])
        for file in dist.files or ():
            module = _module_name(file)
            if module is None:
                continue
            parts = module.split(".")
            for end in range(1, len(parts) + 1):
                owners[".".join(parts[:end])].add(name)
    return {module: frozenset(names) for module, names in owners.items()}


def _owning_distributions(module: str) -> frozenset[str]:
    """The distributions shipping the longest dotted prefix of *module* that any ships."""
    owners = _module_owners()
    parts = module.split(".")
    for end in range(len(parts), 0, -1):
        found = owners.get(".".join(parts[:end]))
        if found:
            return found
    return frozenset()


def _imported_modules(path: Path) -> list[str]:
    """Each absolute import in *path*; ``from pkg import name`` yields ``pkg.name``."""
    found: list[str] = []
    for node in ast.walk(
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    ):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return found


@cache
def _imported_distributions() -> frozenset[str]:
    """Every distribution a third-party import under SOURCE_DIRS resolves to."""
    first_party = _first_party()
    found: set[str] = set()
    for directory in SOURCE_DIRS:
        for path in sorted((REPO_ROOT / directory).rglob("*.py")):
            for module in _imported_modules(path):
                top = module.partition(".")[0]
                if top in sys.stdlib_module_names or top in first_party:
                    continue
                found |= _owning_distributions(module)
    return frozenset(found)


@pytest.mark.parametrize("directory", SOURCE_DIRS)
def test_sweep_finds_imports(directory: str) -> None:
    """Guard the guard: a directory yielding no imports is vacuously clean."""
    assert any((REPO_ROOT / directory).rglob("*.py")), f"no Python under {directory}/"
    assert _imported_distributions(), "swept no third-party import: the sweep broke"


def test_every_runtime_dependency_is_imported() -> None:
    stale = sorted(_RUNTIME - _imported_distributions() - NEEDED_WITHOUT_IMPORT.keys())
    assert not stale, (
        f"declared in [project.dependencies] but imported nowhere under {', '.join(SOURCE_DIRS)}: "
        f"{stale}. Drop each, or, if it's reached by name rather than by import, add it to "
        "NEEDED_WITHOUT_IMPORT with its witness"
    )


@pytest.mark.parametrize("dist", list(NEEDED_WITHOUT_IMPORT))
def test_allowlist_entry_is_still_declared(dist: str) -> None:
    assert canonicalize_name(dist) in _RUNTIME, (
        f"{dist} is no longer declared; drop its entry"
    )


@pytest.mark.parametrize("dist", list(NEEDED_WITHOUT_IMPORT))
def test_allowlist_entry_is_still_unimported(dist: str) -> None:
    """An entry the sweep already satisfies hides nothing: drop it."""
    assert canonicalize_name(dist) not in _imported_distributions(), (
        f"{dist} is imported now; drop its entry"
    )


@pytest.mark.parametrize("dist", list(NEEDED_WITHOUT_IMPORT))
def test_allowlist_witness_still_holds(dist: str) -> None:
    pattern, witness, reason = NEEDED_WITHOUT_IMPORT[dist]
    assert any(
        witness in p.read_text(encoding="utf-8")
        for p in sorted(REPO_ROOT.glob(pattern))
        if p.is_file()
    ), (
        f"no {pattern} contains {witness!r}, so this no longer holds: {reason} "
        f"Drop {dist}, or its entry if something else needs it now"
    )
