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


def _discover() -> tuple[dict[str, dict[str, set[str]]], list[tuple[str, int, str]]]:
    """Every definition in every heredoc, and every heredoc that failed to parse.

    Nothing is asserted here. This runs at import, and an assertion at import
    fails COLLECTION: the module reports as an error with none of its tests
    run, which reads as broken tooling rather than as the finding it is, and
    takes the vacuity guard down with it (CR 17). The tests below assert.

    Keyed by SCRIPT rather than by heredoc, so a script with several blocks —
    score-cohort.sh has four — that defines a name twice internally is that
    script's own business unless the two copies differ, which is reported as
    its own failure below.
    """
    seen: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    unparsable: list[tuple[str, int, str]] = []
    for sh in sorted(SCRIPTS.glob("*.sh")):
        for n, block in enumerate(HEREDOC.findall(sh.read_text(encoding="utf-8"))):
            try:
                defs = _definitions(block)
            except SyntaxError as exc:
                unparsable.append((sh.name, n, f"line {exc.lineno}: {exc.msg}"))
                continue
            for name, dumped in defs.items():
                seen[name][sh.name].add(dumped)
    return seen, unparsable


SEEN, UNPARSABLE = _discover()
# name -> {script: dumped definition}, for names defined in 2+ scripts. A script
# holding two variants of one name contributes its FIRST here and is reported
# by test_no_script_defines_a_twin_two_ways; the cross-script comparison still
# runs on the rest rather than being withheld until that is fixed.
TWINS = {
    name: {s: sorted(v)[0] for s, v in per_script.items()}
    for name, per_script in SEEN.items()
    if len(per_script) >= 2
}


def test_every_heredoc_parses():
    """A heredoc that does not parse contributes nothing to discovery, so its
    definitions are outside the pin without anyone knowing."""
    assert not UNPARSABLE, "\n".join(
        f"{script} heredoc #{n}: {why}" for script, n, why in UNPARSABLE
    )


def test_no_script_defines_a_twin_two_ways():
    """A script with several heredocs defining one twin two ways has to pick
    one before the comparison across scripts can mean anything."""
    split = {
        (name, script): variants
        for name, per_script in SEEN.items()
        if len(per_script) >= 2
        for script, variants in per_script.items()
        if len(variants) > 1
    }
    assert not split, "\n".join(
        f"{script} defines `{name}` {len(variants)} ways in its own heredocs"
        for (name, script), variants in sorted(split.items())
    )


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
