"""CR 1910 — the reference says when a heal's taken file becomes the marker.

`references/auto-refresh-hook.md` said `.git/skills-update.staging.heal.<pid>.<epoch>`
"becomes the marker again once that PID is gone". `_taker_live` also gives
it up past MARKER_MAX_AGE (a reused PID), and since CR 1906 one is adopted
only with no marker there, every other being dropped with the marker that
supersedes it. The sentence naming the file must say both: the age, read
from the hook, and the drop.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = ROOT / "skills/managing-skills/scripts/skills-submodule-update.sh"
DOC = ROOT / "skills/managing-skills/references/auto-refresh-hook.md"


def _sentence() -> str:
    text = DOC.read_text()
    hits = [
        s for s in re.split(r"(?<=[.])\s", text) if "staging.heal.<pid>.<epoch>" in s
    ]
    assert len(hits) == 1, hits
    return hits[0]


def test_it_names_the_age_bound():
    age = re.search(r"^MARKER_MAX_AGE=(\d+)$", HOOK.read_text(), re.M)
    assert age, "the hook no longer sets MARKER_MAX_AGE"
    sentence = _sentence()
    assert f"{age.group(1)} s" in sentence, (
        "the taken file is adopted once its PID is gone OR past "
        f"MARKER_MAX_AGE ({age.group(1)} s): {sentence}"
    )


def test_it_says_the_others_are_dropped():
    sentence = _sentence()
    assert "dropped" in sentence and "no marker" in sentence, (
        "a taken file is adopted only with no marker there; every other is "
        "dropped with the marker that supersedes it (CR 1906): " + sentence
    )
