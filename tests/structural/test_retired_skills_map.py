"""The root `retired-skills` map is one consumers' doctors can act on (#537).

`.skills/doctor.sh` in every consuming repo reads this file and repoints
`skills/<old>` at `<new>`, so a bad line is a cohort-wide mistake: a `<new>`
that does not exist would point 13 repos' links at nothing. And a retired
skill that still ships must say so in its own SKILL.md, or an agent that
loads it from this repo — where nothing repoints — follows it unwarned.

No API calls.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAP = REPO_ROOT / "retired-skills"
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _pairs() -> list[tuple[str, str]]:
    pairs = []
    for raw in MAP.read_text().splitlines():
        line = raw.split("#", 1)[0].split()
        if line:
            assert len(line) == 2, f"not an '<old> <new>' pair: {raw!r}"
            pairs.append((line[0], line[1]))
    return pairs


def _frontmatter(text: str) -> str:
    assert text.startswith("---\n")
    return text.split("\n---\n", 1)[0]


def test_every_line_is_a_pair_of_skill_names():
    pairs = _pairs()
    assert pairs
    for old, new in pairs:
        assert NAME.match(old) and NAME.match(new), (old, new)
        assert old != new


def test_each_old_name_is_listed_once():
    olds = [old for old, _ in _pairs()]
    assert len(olds) == len(set(olds))


def test_every_replacement_ships():
    for _, new in _pairs():
        assert (REPO_ROOT / "skills" / new / "SKILL.md").is_file(), new
        assert new not in {old for old, _ in _pairs()}, f"{new} is itself retired"


def test_a_retired_skill_that_still_ships_says_so():
    """Its frontmatter names the replacement, and so does its first line."""
    for old, new in _pairs():
        skill = REPO_ROOT / "skills" / old / "SKILL.md"
        if not skill.is_file():
            continue
        text = skill.read_text()
        fm = _frontmatter(text)
        m = re.search(r"^  deprecated: \"?(.+?)\"?$", fm, re.M)
        assert m and re.search(rf"\b{re.escape(new)}\b", m.group(1)), (
            f"{old}: metadata.deprecated must name {new}"
        )
        body = text.split("\n---\n", 1)[1].lstrip("\n")
        banner = body.split("\n\n", 2)[1] if body.startswith("# ") else ""
        assert banner.startswith("> **Deprecated") and f"`{new}`" in banner, (
            f"{old}: the paragraph under its heading must be the deprecation "
            f"banner naming `{new}`"
        )
