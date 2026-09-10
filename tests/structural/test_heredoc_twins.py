"""Python shared by copying between heredocs must stay one definition (#275).

Every line of Python in `skills/curating-context/scripts/` lives inline in a
`python3 - <<'PY'` heredoc — twelve blocks across eight scripts — so there is no
module to import and a helper two scripts both need is copied between them.
The copies drift. `_erasable_prefixes` was copied under #272 and had diverged
textually before the day was out; `FENCE` existed three times in two spellings
with two behaviours; `HEADING` existed three times in three. Three of those
scripts gate one phase chain over the same file and put a count on the same
telemetry row, and two of them disagreed about where a fenced block ends.

The repo already pins ONE such twin by behaviour — `is_curation_row` and
`classify_run`, fed a single mixed ledger by `TestCurationRuleIsOneRule` — and
that is the stronger pin where a behaviour can be exercised end to end. This
file is the general one: it discovers every top-level function and `re.compile`
constant defined in more than one heredoc, and requires each set to be one
definition, compared as syntax rather than text so that a comment or a
docstring written for its own file does not count as drift, and a renamed
parameter or a respelled condition does.

A difference that is DELIBERATE is declared below with its reason, and the
declaration is itself checked: a listed exception that no longer differs fails,
so the table cannot go stale the way an acknowledgement file would.

Vacuity guard: the discovery must find the twins known to exist. A parser that
silently matched nothing would pass every assertion here, which is the failure
mode #272's own review met twice (CR 7, CR 10).
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "skills" / "curating-context" / "scripts"

# The heredoc body between the `<<'PY'` line and the terminator. Quoted `'PY'`
# only: an unquoted heredoc would carry shell interpolation, and none of these
# scripts uses one for Python.
HEREDOC = re.compile(r"<<'PY'[^\n]*\n(.*?)\nPY\n", re.S)

# name -> {script: reason}. A twin listed here must DIFFER from the others in
# that script, and the others must still agree among themselves.
DELIBERATE: dict[str, dict[str, str]] = {
    "HEADING": {
        "check-seams.sh": (
            "starts at `##`: a document title is not a section, and the "
            "moved-title class must not count an H1 leaving as a section "
            "leaving (#272)"
        ),
    },
}

# The twins that exist at the time of writing. The discovery below must find at
# least these, or it is not looking.
KNOWN_TWINS = {
    "FENCE",
    "HEADING",
    "LINK_DEPTH",
    "_erasable_prefixes",
    "is_curation_row",
}


def _strip_docstring(node: ast.AST) -> ast.AST:
    body = getattr(node, "body", None)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        node.body = body[1:] or [ast.Pass()]
    return node


def _definitions(block: str) -> dict[str, str]:
    """Top-level `def NAME(...)` and `NAME = re.compile(...)`, as syntax."""
    out = {}
    tree = ast.parse(block)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out[node.name] = ast.dump(_strip_docstring(node))
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "compile"
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "re"
        ):
            out[node.targets[0].id] = ast.dump(node.value)
    return out


def _twins() -> dict[str, dict[str, str]]:
    """name -> {script: dumped definition}, for names defined in 2+ scripts.

    Keyed by SCRIPT rather than by heredoc, so a script with several blocks —
    score-cohort.sh has four — that defines a name twice internally is that
    script's own business unless the two copies differ, which is reported as
    its own failure below.
    """
    seen: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for sh in sorted(SCRIPTS.glob("*.sh")):
        for block in HEREDOC.findall(sh.read_text(encoding="utf-8")):
            for name, dumped in _definitions(block).items():
                seen[name][sh.name].add(dumped)
    twins = {}
    for name, per_script in seen.items():
        if len(per_script) < 2:
            continue
        for script, variants in per_script.items():
            assert len(variants) == 1, (
                f"{script} defines `{name}` differently in two of its own "
                f"heredocs — pick one before the cross-script comparison can mean "
                "anything"
            )
        twins[name] = {s: next(iter(v)) for s, v in per_script.items()}
    return twins


TWINS = _twins()


def test_the_discovery_is_looking():
    """A parser that finds nothing passes every other test here."""
    missing = KNOWN_TWINS - TWINS.keys()
    assert not missing, (
        f"known twins not discovered: {sorted(missing)} — the heredoc or "
        "definition matcher has stopped matching, and every assertion below is "
        "vacuous until it is fixed"
    )


@pytest.mark.parametrize("name", sorted(TWINS))
def test_each_twin_is_one_definition(name: str):
    copies = TWINS[name]
    exceptions = DELIBERATE.get(name, {})
    canonical = {s: d for s, d in copies.items() if s not in exceptions}
    assert canonical, f"`{name}`: every copy is listed as an exception — to what?"
    distinct = set(canonical.values())
    assert len(distinct) == 1, (
        f"`{name}` is defined in {sorted(canonical)} and the copies differ. "
        "Make them one definition, or declare the difference in DELIBERATE with "
        "its reason. Comments and docstrings are not compared; everything else "
        "is."
    )


@pytest.mark.parametrize(
    "name,script",
    [(n, s) for n, per in sorted(DELIBERATE.items()) for s in sorted(per)],
)
def test_each_declared_exception_still_differs(name: str, script: str):
    """The table cannot go stale: an exception that no longer differs is a
    declaration about a difference that does not exist."""
    copies = TWINS.get(name, {})
    assert script in copies, (
        f"DELIBERATE lists `{name}` in {script}, which does not define it as a "
        "twin — drop the entry"
    )
    others = {d for s, d in copies.items() if s not in DELIBERATE[name]}
    assert copies[script] not in others, (
        f"DELIBERATE says `{name}` in {script} differs on purpose, and it no "
        "longer differs — drop the entry, or the reason it gives is describing "
        "nothing"
    )
