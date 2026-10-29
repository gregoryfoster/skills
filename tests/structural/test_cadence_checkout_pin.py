"""A re-render of the cadence workflow never writes an older checkout pin (#373).

`install-cadence.sh` rendered its `actions/checkout@vN` as a literal, and
Dependabot's github-actions ecosystem bumps every `uses:` under
`.github/workflows/`, the generated file included. The next re-render wrote the
template's pin back over the bump, and nothing said so: a one-line diff in a
file whose header says not to hand-edit it. watcher had SHA-pinned every action
(CannObserv/watcher#360, 2026-10-10), so there it would also turn the pin
guard red.

The installed line now wins when it is a SHA pin (kept verbatim) or a `@vN` at
or above the template's major, and `--check` names what a re-render would
write. Three fixtures, as #373's thread asks: a SHA-pinned installed line, an
`@vN` above the template and an `@vN` below it, plus the form it can't read.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.utils.skill_loader import SKILLS_DIR

INSTALL_CADENCE = SKILLS_DIR / "curating-context" / "scripts" / "install-cadence.sh"
WF = Path(".github/workflows/context-cadence.yml")
CHECKOUT = re.compile(r"^ *- uses: actions/checkout@.*$", re.M)
SHA_LINE = "      - uses: actions/checkout@" + "3d3c42e5" * 5 + " # v99.0.1"


def _env() -> dict:
    """No inherited GIT_*, and no global or system config, as the other
    installer suites do: pre-commit exports GIT_INDEX_FILE and friends."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALL_CADENCE), "--cron", "0 15 * * 1", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_env(),
        timeout=60,
    )


def _installed(tmp_path: Path, line: str | None) -> Path:
    """A repo with the workflow installed, its checkout line then moved to `line`
    the way a Dependabot PR moves it: that one line, nothing else."""
    repo = tmp_path / "r"
    repo.mkdir(parents=True)
    r = subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo)],
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert r.returncode == 0, r.stderr
    r = _run(repo)
    assert r.returncode == 0, r.stderr
    if line is not None:
        wf = repo / WF
        text, n = CHECKOUT.subn(line, wf.read_text(), count=1)
        assert n == 1, "the rendered workflow has no checkout line to move"
        wf.write_text(text)
    return repo


def _checkout(repo: Path) -> str:
    return CHECKOUT.search((repo / WF).read_text()).group(0)


def _template_line(tmp_path: Path) -> str:
    return _checkout(_installed(tmp_path / "fresh", None))


def _template_major(tmp_path: Path) -> int:
    return int(re.search(r"@v(\d+)$", _template_line(tmp_path)).group(1))


def _check_line(repo: Path) -> str:
    r = _run(repo, "--check")
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("checkout pin:")]
    assert len(lines) == 1, r.stdout
    return lines[0]


@pytest.mark.parametrize(
    "line",
    [SHA_LINE, "      - uses: actions/checkout@v99"],
    ids=["sha-pin", "major-above-the-template"],
)
def test_a_rerender_keeps_an_installed_pin_newer_than_the_template(tmp_path, line):
    repo = _installed(tmp_path, line)
    before = (repo / WF).read_text()
    r = _run(repo)
    assert r.returncode == 0, r.stderr
    assert _checkout(repo) == line, "the re-render downgraded the installed pin"
    assert (repo / WF).read_text() == before, "the bump alone must read as current"
    assert "unchanged:" in r.stdout and "kept: actions/checkout@" in r.stdout


def test_print_renders_the_kept_pin(tmp_path):
    """What this repo's own parity test reads: `--print` against the installed
    file. A bare Dependabot bump of context-cadence.yml then still matches."""
    repo = _installed(tmp_path, SHA_LINE)
    r = _run(repo, "--print")
    assert r.returncode == 0, r.stderr
    assert r.stdout == (repo / WF).read_text()


def test_the_rest_of_the_file_is_still_rerendered(tmp_path):
    """Keeping the pin is not keeping the file: a hand edit elsewhere goes."""
    repo = _installed(tmp_path, SHA_LINE)
    wf = repo / WF
    wf.write_text(wf.read_text().replace("name: context-cadence", "name: edited"))
    r = _run(repo)
    assert r.returncode == 0, r.stderr
    assert "name: edited" not in wf.read_text()
    assert _checkout(repo) == SHA_LINE


def test_a_major_below_the_template_is_raised_to_it(tmp_path):
    major = _template_major(tmp_path)
    repo = _installed(tmp_path, "      - uses: actions/checkout@v5")
    assert major > 5, "the fixture needs a major below the template's"
    assert "behind (@v5;" in _check_line(repo)
    r = _run(repo)
    assert r.returncode == 0, r.stderr
    assert _checkout(repo) == _template_line(tmp_path / "again")


def test_a_pin_it_cannot_read_is_named_before_and_after(tmp_path):
    """A branch ref is neither form, so the template's line wins; that is the
    one downgrade left, and it is said out loud on both paths."""
    repo = _installed(tmp_path, "      - uses: actions/checkout@main")
    assert "DOWNGRADE" in _check_line(repo) and "@main" in _check_line(repo)
    r = _run(repo)
    assert r.returncode == 0, r.stderr
    assert "replaced: actions/checkout@main" in r.stderr
    assert _checkout(repo) == _template_line(tmp_path / "again")


def test_check_names_a_sha_pin_below_the_template(tmp_path):
    """Verbatim is the rule for a SHA pin, but one whose comment is below the
    floor (Node 20's v4, #163) is said out loud rather than read as current."""
    old = "      - uses: actions/checkout@" + "08eba0b2" * 5 + " # v4.3.0"
    repo = _installed(tmp_path, old)
    r = _run(repo, "--check")
    assert "kept (SHA-pinned" in r.stdout
    assert "Its comment says v4, below the template's" in r.stdout
    assert r.returncode == 0
    assert (
        "below the template's"
        not in _run(_installed(tmp_path / "x", SHA_LINE), "--check").stdout
    )


@pytest.mark.parametrize(
    ("line", "says"),
    [
        (None, "yes (@v"),
        (SHA_LINE, "kept (SHA-pinned"),
        ("      - uses: actions/checkout@v99", "kept (@v99 is at or above"),
        ("      - uses: actions/checkout@v7.0.1-rc", "DOWNGRADE"),
    ],
    ids=["template", "sha-pin", "major-above", "unread"],
)
def test_check_reports_the_pin_without_changing_the_exit(tmp_path, line, says):
    """Not a guarantee, so not rc=3: a full install reads 0 whatever the pin."""
    repo = _installed(tmp_path, line)
    assert says in _check_line(repo)
    assert _run(repo, "--check").returncode == 0
