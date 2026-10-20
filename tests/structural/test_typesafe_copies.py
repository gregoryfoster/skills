"""#448 — every skill's `_typesafe.py` is a byte-equal copy of `scripts/_typesafe.py`.

A skill is vendored on its own, so it can't import another skill's scripts, and
each consuming skill carries its own copy of the client. Copies drift. The
precedent, `TestPythonClickHelperByteEquality`, compares two fixed paths. This
one globs, so a copy a later child adds is held from the commit that adds it,
with nobody remembering to list it.

Three rules:

- **Every copy is byte-equal to the canonical one, and a real file.** A symlink
  would break the moment the skill is vendored without this repo's root.
- **A skill script that imports `_typesafe` has a copy beside it.** Without one,
  the import works here, where `scripts/` might be on a path by accident, and
  fails in every consuming repo.
- **The client imports only the standard library.** Every skill script does
  [measured 2026-10-19], and the operator decided against `typesafe-sdk`.

Until #438 lands the first copy, the first rule has nothing to compare, and
pytest reports it as one skip ("got empty parameter set"), not as a pass. That
is the expected state. The skip goes away on the day a copy arrives.

No API calls. Pure file comparison and AST reads.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL = REPO_ROOT / "scripts" / "_typesafe.py"
# `**` so a copy or importer in a subdirectory of scripts/ is held too (CR 405).
SCRIPTS_GLOB = "skills/*/scripts/**/*.py"
COPIES = sorted(REPO_ROOT.glob("skills/*/scripts/**/_typesafe.py"))


def _imports(path: Path) -> set[str]:
    """Top-level module names a file imports, from its AST."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_canonical_client_exists():
    assert CANONICAL.is_file() and not CANONICAL.is_symlink()


@pytest.mark.parametrize(
    "copy", COPIES, ids=lambda p: p.relative_to(REPO_ROOT / "skills").as_posix()
)
def test_every_skill_copy_is_a_byte_equal_real_file(copy):
    assert not copy.is_symlink(), (
        f"{copy.relative_to(REPO_ROOT)} is a symlink. A skill is vendored on its "
        "own, so replace it with a real copy of scripts/_typesafe.py"
    )
    assert copy.read_bytes() == CANONICAL.read_bytes(), (
        f"{copy.relative_to(REPO_ROOT)} differs from scripts/_typesafe.py. Edit "
        "the canonical copy and re-copy it; never edit a skill's copy in place"
    )


def test_the_glob_reaches_where_copies_live():
    """The glob is the whole rule; if skills stopped living at skills/*/scripts it would match nothing."""
    assert any(REPO_ROOT.glob(SCRIPTS_GLOB)), (
        "no Python under skills/*/scripts/, so the copy glob can no longer see a copy"
    )


def test_every_importer_has_a_sibling_copy():
    missing = [
        script.relative_to(REPO_ROOT).as_posix()
        for script in sorted(REPO_ROOT.glob(SCRIPTS_GLOB))
        if script.name != "_typesafe.py"
        and "_typesafe" in _imports(script)
        and not (script.parent / "_typesafe.py").is_file()
    ]
    assert not missing, (
        f"{missing} import _typesafe with no _typesafe.py beside them. Copy "
        "scripts/_typesafe.py into that skill's scripts/; a skill can't import another's"
    )


def test_the_client_imports_only_the_standard_library():
    outside = sorted(_imports(CANONICAL) - set(sys.stdlib_module_names))
    assert not outside, (
        f"scripts/_typesafe.py imports {outside}, which aren't in the standard "
        "library. Skill scripts run in consuming repos with no install step (#448)"
    )
