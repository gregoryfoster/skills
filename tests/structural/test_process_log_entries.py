"""Every session-journal entry opens on the heading its own index prescribes.

`orchestrating-issue-backlog/references/process-log.md` says, under "Adding an
entry": write the entry file "opening with a `## Session <date>` heading". That
rule was enforced by nothing, and by 2026-09-16 it had drifted on **9 of the
50** entries then in the log — all nine on the heading level (`#` rather than
`##`), one of them dropping the word "Session" as well. The session that
normalised them drifted off it too, writing both of its own new entries on `#`
before conforming them, which is the argument for a gate rather than a rule.

Drift here is cheap individually and expensive in aggregate. The entries are one
Markdown corpus read through a single index; a file whose title outranks its own
sections renders as a different document shape from its 49 neighbours, and
`measure-context.sh` reports its `##` sections without the title among them. The
rule is also the only thing that makes an entry recognisable as an entry without
opening the index first.

This is the 2026-08-19 lesson from the log itself, applied to the log: a
convention with three advisory readers and no gate is ungated, and nobody
notices the drift until someone counts. So it is gated — cheaply, by its first
line.

Kept in its own file per AGENTS.md: a new structural rule goes in
`test_<rule>.py` rather than at the end of `test_context_surface.py`, so that
parallel worktrees adding rules do not collide on one file.

The check is deliberately generic over skills. Only `orchestrating-issue-backlog`
keeps a process log today, but the vendoring cohort copies this layout, and a
second skill that grows one should inherit the rule rather than rediscover it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "skills"

# `<year>/index.md` is the year's row table, not a session — it is bound by the
# per-doc token budget and by test_references.py's reachability rule instead.
ENTRIES = sorted(
    p
    for p in SKILLS_DIR.glob("*/references/process-log/*/*.md")
    if p.name != "index.md"
)

OPENING = re.compile(r"^## Session .+")


def test_the_corpus_is_not_empty() -> None:
    """Guard against a moved layout silently emptying the parametrization.

    A glob that matches nothing turns every assertion below into zero tests,
    which reports green. #152 is the precedent: a non-recursive glob let the
    whole journal out of another check without failing anything.
    """
    assert ENTRIES, (
        f"No process-log entries found under {SKILLS_DIR}/*/references/process-log/"
        "<year>/. If the layout moved, move this glob with it."
    )


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.name)
def test_entry_opens_on_the_prescribed_heading(entry: Path) -> None:
    first = entry.read_text().splitlines()[0] if entry.read_text() else ""
    assert OPENING.match(first), (
        f"{entry.relative_to(REPO_ROOT)} opens with {first!r}. "
        "process-log.md's 'Adding an entry' prescribes '## Session <date>' — "
        "level two, so the title is a sibling of the entry's own sections, and "
        "the literal word Session so an entry is recognisable as one."
    )
