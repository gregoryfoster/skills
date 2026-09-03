"""Structural assertions for references/ and assets/ directories.

These tests enforce two cheap invariants that catch the kind of drift surfaced
during #29 round-1 review (broken asset path, parameter-row pointing at a
nonexistent Phase header):

1. Every `references/...` or `assets/...` link in a SKILL.md body resolves to
   a real file under the skill directory.
2. Every file under a skill's references/ directory is linked from its sibling
   SKILL.md (by filename appearing in the body).

Out of scope per #30: length cap on references, frontmatter-on-references
check, parameter-row -> Phase-header check.

## Nested references, and why the orphan rule grew a second half (#152)

`references/` was flat until the `orchestrating-issue-backlog` process log
became an *indexed journal*: `process-log.md` is the index, and one file per
session lives under `references/process-log/<year>/`. Nothing in the suite ever
forbade a subdirectory — the globs were simply non-recursive, so a nested file
was not caught by any rule here, it was invisible to all of them.

Making the orphan glob recursive on its own is worse than leaving it. It
compares `ref.name` (`2026-08-13-usa-wa.md`) against the raw link target
(`process-log/2026/2026-08-13-usa-wa.md`), so every entry fails; and once that
is fixed the rule *demands* SKILL.md link all 28 entries, which is the opposite
of what an index is for and would blow that skill's token ratchet on the spot.

So the rule is split by depth, and the top level keeps exactly the strictness it
had:

- `references/*.md` — linked **directly** from the sibling SKILL.md. Unchanged.
- `references/**/*.md` below the top level — linked from a reference doc that is
  itself reachable, i.e. reachable from SKILL.md through a chain of reference
  links. That is the index pattern stated as an invariant, and it is what makes
  "every entry has a row in the index" checkable without hand-keeping a list.

Reachability is computed with the SAME link extractor `test_relative_links.py`
gates dead links with, so "a link that counts here" and "a link that must
resolve there" cannot drift apart: a fenced or code-span link is not a link in
either, and only a real `[label](target)` reaches the graph.

No API calls required.
"""

import os
import re
from pathlib import Path

import pytest

from tests.structural.test_relative_links import _ABSOLUTE_RE, _mask_code
from tests.structural.test_relative_links import _LINK_RE as _RENDERED_LINK_RE
from tests.utils.skill_loader import Skill, all_skills, load_skill

# Match Markdown link targets of the form `(references/<path>)` or
# `(assets/<path>)`. `[^) ]+` captures everything up to the closing paren OR
# the first whitespace — which excludes a CommonMark link title such as
# `[label](references/foo.md "Title")`. The captured path may still include
# a `#fragment` or `?query` suffix; callers must strip those before
# resolving against the filesystem.
_LINK_RE = re.compile(r"\((references|assets)/([^) ]+)")


# Conditional-block markers in reference templates. A block opens with
# `> Include when <COND>:` and closes with `> end include`; the renderer drops
# the whole block when the condition is false, so an unterminated open has no
# boundary and silently swallows whatever follows (skills#82/#83 CR round 1).
_INCLUDE_OPEN = "> Include when"
_INCLUDE_CLOSE = "> end include"


def _rendered_targets(text: str, base: Path) -> set[Path]:
    """Every relative link in `text`, resolved against `base`.

    Code fences and code spans are masked first: a link nobody can click is not
    a link, which is the rule `test_relative_links.py` already settled on. The
    result is resolved but not required to exist — existence is that module's
    assertion, and duplicating it here would report the same defect twice.
    """
    targets: set[Path] = set()
    for match in _RENDERED_LINK_RE.finditer(_mask_code(text)):
        target = match["target"]
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        if not target or target.startswith("#") or _ABSOLUTE_RE.match(target):
            continue
        path = target.split("#", 1)[0].split("?", 1)[0]
        if not path:
            continue
        targets.add(Path(os.path.normpath(base / path)))
    return targets


def reachable_references(skill: Skill) -> set[Path]:
    """References reachable from SKILL.md, following links through references.

    Breadth-first from SKILL.md. A doc joins the frontier only once, so a cycle
    (two references linking each other) terminates instead of spinning — and a
    cycle among references is exactly the orphan shape this must not accept: an
    island of docs that link each other and are linked from nowhere never enters
    the frontier at all, because the frontier starts at SKILL.md.
    """
    ref_dir = skill.directory / "references"
    frontier = [
        target
        for target in _rendered_targets(skill.body, skill.directory)
        if target.is_relative_to(ref_dir) and target.is_file()
    ]
    seen: set[Path] = set()
    while frontier:
        doc = frontier.pop()
        if doc in seen:
            continue
        seen.add(doc)
        for target in _rendered_targets(doc.read_text(), doc.parent):
            if target.is_relative_to(ref_dir) and target.is_file():
                frontier.append(target)
    return seen


@pytest.fixture(params=all_skills(), ids=lambda s: s.dir_name)
def skill(request) -> Skill:
    return request.param


class TestReferences:
    """Linked-file-exists and no-orphan assertions for references/ and assets/."""

    def test_referenced_files_exist(self, skill: Skill) -> None:
        """Every (references|assets)/<path> link in SKILL.md must resolve."""
        for kind, raw in _LINK_RE.findall(skill.body):
            # Strip `#fragment` and `?query` suffixes so links like
            # `references/foo.md#L42` resolve against `references/foo.md`.
            name = raw.split("#", 1)[0].split("?", 1)[0]
            target = skill.directory / kind / name
            assert target.exists(), (
                f"{skill.dir_name}: {kind}/{name} linked from SKILL.md but missing"
            )

    def test_no_orphan_references(self, skill: Skill) -> None:
        """Every top-level references/*.md must be linked from sibling SKILL.md.

        Enforces the AGENTS.md "References convention" rule that references files
        must appear as a markdown link `[label](references/<name>.md)`, not merely
        as a backtick mention or comment. Uses the same regex as the linked-file
        check so the two assertions stay in lockstep.

        Top level only, and directly: a doc one directory down is covered by
        `test_no_orphan_nested_references`, which allows the extra hop an index
        exists to provide. Nothing here is relaxed by that — a file sitting
        beside SKILL.md's own reference set still has to be named by SKILL.md.
        """
        ref_dir = skill.directory / "references"
        if not ref_dir.is_dir():
            pytest.skip("no references/ directory")
        linked_names = {
            raw.split("#", 1)[0].split("?", 1)[0]
            for kind, raw in _LINK_RE.findall(skill.body)
            if kind == "references"
        }
        for ref in sorted(ref_dir.glob("*.md")):
            assert ref.name in linked_names, (
                f"{skill.dir_name}: references/{ref.name} exists but is not linked "
                f"as a markdown link `[label](references/{ref.name})` from SKILL.md"
            )

    def test_no_orphan_nested_references(self, skill: Skill) -> None:
        """Every references/**/*.md below the top level must be reachable.

        Reachable means: linked from a reference doc that is itself reachable
        from SKILL.md. One index linking its entries satisfies it; so does a
        deeper chain. What it refuses is the failure the non-recursive globs
        made silent — a subdirectory of files no document points at, measured by
        the per-doc budget and inspected by nothing else (#152).

        Requiring SKILL.md to link them directly instead would defeat the index:
        `orchestrating-issue-backlog` would have to name 28 session entries in a
        body already 7 tokens under its ratchet.
        """
        ref_dir = skill.directory / "references"
        if not ref_dir.is_dir():
            pytest.skip("no references/ directory")
        nested = sorted(p for p in ref_dir.rglob("*.md") if p.parent != ref_dir)
        if not nested:
            pytest.skip("no nested references")
        reachable = reachable_references(skill)
        orphans = [
            p.relative_to(ref_dir).as_posix() for p in nested if p not in reachable
        ]
        assert not orphans, (
            f"{skill.dir_name}: references/ holds nested files nothing links to: "
            f"{orphans}. A nested reference must be linked from a reference doc "
            "that SKILL.md links — an index and its entries. Unlinked, it is "
            "carried by the repo, measured by the per-doc budget, and reachable "
            "by no reader."
        )


class TestConditionalBlockMarkers:
    """Every `> Include when …:` block in a reference must be terminated.

    These markers gate branch-point content that an agent renders mechanically.
    An unterminated open leaves the block's extent undefined, so dropping it on
    a false condition takes an arbitrary amount of following prose with it —
    a silent deletion, with nothing failing to report it. That is exactly how
    an unterminated `PRIVATE_WHEELHOUSE` block reached main (skills#82/#83).
    """

    def test_include_markers_are_balanced(self, skill: Skill) -> None:
        ref_dir = skill.directory / "references"
        if not ref_dir.is_dir():
            pytest.skip("no references/ directory")
        # Recursive: a nested entry carries prose like any other reference, and
        # an unterminated block in one silently swallows the rest of its file.
        for ref in sorted(ref_dir.rglob("*.md")):
            name = ref.relative_to(ref_dir).as_posix()
            open_line = None
            for lineno, raw in enumerate(ref.read_text().splitlines(), 1):
                line = raw.strip()
                # startswith, not `in`: prose documenting the convention quotes
                # the marker mid-sentence and must not count as an occurrence.
                if line.startswith(_INCLUDE_OPEN):
                    assert open_line is None, (
                        f"{skill.dir_name}: references/{name} line {lineno} opens a "
                        f"'{_INCLUDE_OPEN}' block while line {open_line} is still open — "
                        f"add '{_INCLUDE_CLOSE}' to close the earlier one"
                    )
                    open_line = lineno
                elif line == _INCLUDE_CLOSE:
                    assert open_line is not None, (
                        f"{skill.dir_name}: references/{name} line {lineno} has a stray "
                        f"'{_INCLUDE_CLOSE}' with no matching '{_INCLUDE_OPEN}'"
                    )
                    open_line = None
            assert open_line is None, (
                f"{skill.dir_name}: references/{name} line {open_line} opens a "
                f"'{_INCLUDE_OPEN}' block that is never closed with '{_INCLUDE_CLOSE}' — "
                f"the renderer has no boundary for what to drop when the condition is false"
            )


class TestNestedReachabilityGate:
    """`reachable_references` proven against fixtures, not only a passing tree.

    The whole risk in #152 was a check that appears to cover a layout it cannot
    see. Asserting the new rule only against the real tree — where it passes —
    would reproduce that risk one level up: a reachability function that always
    returned every file would look identical from here.
    """

    @staticmethod
    def _tree(root, skill_body: str, index_body: str) -> Skill:
        directory = root / "journalling-skill"
        (directory / "references" / "log" / "2026").mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            "---\nname: journalling-skill\ndescription: fixture\n---\n\n" + skill_body
        )
        (directory / "references" / "log.md").write_text(index_body)
        (directory / "references" / "log" / "2026" / "entry.md").write_text(
            "## Session\n"
        )
        return load_skill(directory)

    def test_an_entry_reached_through_the_index_counts(self, tmp_path) -> None:
        skill = self._tree(
            tmp_path,
            "See [the log](references/log.md).\n",
            "| [2026-01-01](log/2026/entry.md) | project | headline |\n",
        )
        entry = skill.directory / "references" / "log" / "2026" / "entry.md"
        assert entry in reachable_references(skill)

    def test_an_entry_the_index_forgot_is_unreachable(self, tmp_path) -> None:
        """The failure the non-recursive glob made silent: a file nothing links."""
        skill = self._tree(
            tmp_path,
            "See [the log](references/log.md).\n",
            "| 2026-01-01 | project | headline |\n",
        )
        entry = skill.directory / "references" / "log" / "2026" / "entry.md"
        assert entry not in reachable_references(skill)

    def test_an_index_SKILL_md_does_not_link_carries_nothing(self, tmp_path) -> None:
        """Reachability starts at SKILL.md, so an unlinked index cannot confer it.

        Two orphans linking each other is the shape a naive "is anything
        pointing at it" check accepts and this one must not.
        """
        skill = self._tree(
            tmp_path,
            "No references linked here.\n",
            "| [2026-01-01](log/2026/entry.md) | project | headline |\n",
        )
        assert reachable_references(skill) == set()

    def test_a_link_inside_a_code_fence_does_not_confer_reachability(
        self, tmp_path
    ) -> None:
        """A link nobody can click cannot be how a reader found the entry."""
        skill = self._tree(
            tmp_path,
            "See [the log](references/log.md).\n",
            "```\n[2026-01-01](log/2026/entry.md)\n```\n",
        )
        entry = skill.directory / "references" / "log" / "2026" / "entry.md"
        assert entry not in reachable_references(skill)
