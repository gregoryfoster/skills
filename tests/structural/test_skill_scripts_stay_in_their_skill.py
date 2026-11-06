"""A skill's scripts read only their own skill's directory (#537).

Pre-commit's test selection maps a test that runs `skills/<name>/scripts/x`
to `skills/<name>`. A script that reaches into a *different* skill through
its own location (`$HERE/../../<other>/...`) gives that test a dependency the
map cannot see: a change to the other skill would not select it.

This test fails on any such climb, so each one becomes a decision: allowlist
it here, with the reason the map still sees what it reads. Scripts that act
on the *caller's* repo (from the working directory) are not affected.

No API calls.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# path -> why the map still sees what the climb reads
ALLOWED = {
    "skills/managing-skills/scripts/install-hook.sh": (
        "the copy fallback reads another skill's hook; every test that runs "
        "it also opens that hook itself, which the tracer records"
    ),
}

# A variable set from the script's own location, e.g. HERE=$(dirname "$0").
_SELF = re.compile(
    r"^\s*(?:local\s+|readonly\s+|export\s+)?([A-Za-z_]\w*)="
    r".*(?:BASH_SOURCE|dirname[^#]*\$0\b)"
)
_PY_CLIMB = re.compile(
    r"__file__.*(?:parents\[[2-9]\]|parent\.parent\.parent|\.\./\.\.)"
)


def _climbs(path: Path) -> list[str]:
    try:
        lines = path.read_text().splitlines()
    except UnicodeDecodeError:
        return []
    if path.suffix == ".py" or (lines and "python" in lines[0]):
        pattern = _PY_CLIMB
    else:
        names = sorted({m.group(1) for line in lines if (m := _SELF.match(line))})
        if not names:
            return []
        pattern = re.compile(r"\$\{?(?:%s)\}?/\.\./\.\." % "|".join(names))
    return [
        f"{path.relative_to(REPO)}:{n}: {line.strip()}"
        for n, line in enumerate(lines, 1)
        if not line.lstrip().startswith("#") and pattern.search(line)
    ]


def test_no_skill_script_climbs_into_another_skill():
    hits = [
        hit
        for path in sorted(REPO.glob("skills/*/scripts/**/*"))
        if path.is_file() and str(path.relative_to(REPO)) not in ALLOWED
        for hit in _climbs(path)
    ]
    assert not hits, (
        "a skill script reads outside its skill via its own location, which "
        "the test-selection map cannot see; allowlist it with a reason:\n"
        + "\n".join(hits)
    )


def test_every_allowlisted_script_still_climbs():
    """An entry whose climb is gone is a stale exception."""
    stale = [p for p in ALLOWED if not _climbs(REPO / p)]
    assert not stale, f"allowlisted but no longer climbing: {stale}"
