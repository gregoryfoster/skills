"""Every prescribed pin install records the version it pinned (#495).

`npm install --prefix ~/.socraticode/pin socraticode@<version>` without
`--save-exact` writes npm's default `save-prefix` into the pin's
`package.json`: `"socraticode": "^<version>"`. `node_modules` and the lockfile
are exact, so the driver's `pinVersion()` reads the right build today. But a
bare `npm install` or `npm update` in that directory — by hand, a script, or an
agent tidying it — then moves the pin to the newest release in range, and
nothing reports it. Observed on CannObserv/watcher's co-watcher (npm 11.19.0):
`"^1.14.0"` with 1.15.0, 1.16.0 and 1.16.1 all published. That undoes the
reason the skill pins at all, so every place the skill prescribes the install
— scripts and references alike — passes `--save-exact`.
"""

import re
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "skills" / "init-socraticode"

# [measured: 11 at 5c3e486e] — preflight.sh 3, host-memory.md 3,
# mcp-driver.mjs 4, parser-selftest.mjs 1. A floor, not an exact count: a new
# site is welcome, as long as it carries the flag.
MIN_SITES = 11

# `npm install` up to the end of its command: the next quote, backtick or
# line end. A doc's prose naming the line (host-memory.md's "the same
# `npm install … --prefix` line") is held to it too, since it is what an
# operator copies.
INSTALL = re.compile(r"npm install\b[^'\"`\n]*")


def _sites() -> list[tuple[str, str]]:
    found = []
    for path in sorted(SKILL.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".sh", ".mjs"}:
            continue
        for match in INSTALL.finditer(path.read_text(encoding="utf-8")):
            if "--prefix" in match.group(0):
                found.append((path.relative_to(SKILL).as_posix(), match.group(0)))
    return found


def test_the_sites_are_all_found() -> None:
    sites = _sites()
    assert len(sites) >= MIN_SITES, (
        f"found {len(sites)} pin installs, expected at least {MIN_SITES} — the "
        f"scan stopped seeing some, so the test below would pass vacuously:\n{sites}"
    )


@pytest.mark.parametrize("where", sorted({w for w, _ in _sites()}))
def test_every_pin_install_saves_exact(where: str) -> None:
    loose = [cmd for w, cmd in _sites() if w == where and "--save-exact" not in cmd]
    assert not loose, (
        f"{where} prescribes a pin install without --save-exact: npm then "
        "records a caret range in the pin's package.json, and a bare `npm "
        f"update` there moves the pin silently (#495)\n" + "\n".join(loose)
    )


def test_the_flag_comes_before_the_prefix() -> None:
    """One spelling, so a reader comparing two sites sees one command."""
    for where, cmd in _sites():
        assert cmd.startswith("npm install --save-exact --prefix"), (where, cmd)
