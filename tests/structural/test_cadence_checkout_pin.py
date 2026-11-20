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

The template's own line is a SHA pin with its version in a comment (#675): the
job holds `contents: write` and `ANTHROPIC_API_KEY`, so a floating tag let
whoever could move it reach both. An installed tag at or below the template's
version is now pinned on a re-render; one above it is kept, and named as a tag
that can still move.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.utils.skill_loader import SKILLS_DIR

REPO_ROOT = Path(__file__).resolve().parents[2]
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
    return int(re.search(r" # v(\d+)\.", _template_line(tmp_path)).group(1))


def _template_vars() -> dict[str, str]:
    """The template's pin, read from the script as the render reads it."""
    text = INSTALL_CADENCE.read_text()
    found = dict(re.findall(r"^(TEMPLATE_CHECKOUT_(?:SHA|VERSION))=(\S+)$", text, re.M))
    assert set(found) == {"TEMPLATE_CHECKOUT_SHA", "TEMPLATE_CHECKOUT_VERSION"}, (
        "install-cadence.sh no longer sets TEMPLATE_CHECKOUT_SHA and "
        "TEMPLATE_CHECKOUT_VERSION as plain assignments"
    )
    return found


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
    assert "Its comment says v4.3.0, below the template's" in r.stdout
    assert r.returncode == 0
    assert (
        "below the template's"
        not in _run(_installed(tmp_path / "x", SHA_LINE), "--check").stdout
    )


@pytest.mark.parametrize(
    ("line", "says"),
    [
        (None, "yes (the template's SHA pin"),
        (SHA_LINE, "kept (SHA-pinned"),
        ("      - uses: actions/checkout@v99", "kept (@v99 is above"),
        ("      - uses: actions/checkout@v7.0.1-rc", "DOWNGRADE"),
    ],
    ids=["template", "sha-pin", "major-above", "unread"],
)
def test_check_reports_the_pin_without_changing_the_exit(tmp_path, line, says):
    """Not a guarantee, so not rc=3: a full install reads 0 whatever the pin."""
    repo = _installed(tmp_path, line)
    assert says in _check_line(repo)
    assert _run(repo, "--check").returncode == 0


def test_the_template_renders_a_sha_pin_with_its_version(tmp_path):
    """#675: never a floating tag. The SHA and its comment move together, in
    the shape Dependabot writes and test_dependabot.py's pin rule reads."""
    v = _template_vars()
    assert re.fullmatch(r"[0-9a-f]{40}", v["TEMPLATE_CHECKOUT_SHA"]), v
    assert re.fullmatch(r"\d+\.\d+\.\d+", v["TEMPLATE_CHECKOUT_VERSION"]), v
    assert _template_line(tmp_path) == (
        "      - uses: actions/checkout@"
        f"{v['TEMPLATE_CHECKOUT_SHA']} # v{v['TEMPLATE_CHECKOUT_VERSION']}"
    )


def test_the_template_pin_is_this_repos_installed_pin(tmp_path):
    """Who moves the template's pin (#675). This repo's Dependabot bumps its own
    installed context-cadence.yml, never the template inside the script, and a
    re-render keeps that bump (#373), so nothing else would notice the template
    falling behind. This test does: the push that lands the bump moves the
    template with it."""
    installed = CHECKOUT.search((REPO_ROOT / WF).read_text()).group(0)
    assert installed == _template_line(tmp_path), (
        f"this repo's {WF} pins\n  {installed.strip()}\nbut the template in "
        "install-cadence.sh renders\n  "
        f"{_template_line(tmp_path / 'again').strip()}\nA Dependabot bump of "
        "the installed file moved it. In the same push, set "
        "TEMPLATE_CHECKOUT_SHA and TEMPLATE_CHECKOUT_VERSION in "
        "skills/curating-context/scripts/install-cadence.sh to the installed "
        "pin (measure the SHA: git ls-remote https://github.com/actions/checkout "
        "refs/tags/v<version>), and the checkout line in "
        "skills/curating-context/references/cadence/workflow.md."
    )


@pytest.mark.parametrize(
    "tag",
    ["@v{major}", "@v{version}"],
    ids=["major-tag", "the-templates-own-version"],
)
def test_a_tag_at_the_template_version_is_pinned(tmp_path, tag):
    """An installed `@v7` was the template's own line before #675. It floats,
    so a re-render now writes the SHA pin over it, and both paths say so."""
    v = _template_vars()
    ref = tag.format(
        major=v["TEMPLATE_CHECKOUT_VERSION"].split(".")[0],
        version=v["TEMPLATE_CHECKOUT_VERSION"],
    )
    repo = _installed(tmp_path, f"      - uses: actions/checkout{ref}")
    line = _check_line(repo)
    assert line.startswith(f"checkout pin:       tag ({ref} can move"), line
    r = _run(repo, "--check")
    assert r.returncode == 0, r.stdout
    assert re.search(r"^re-render:\s+behind", r.stdout, re.M), r.stdout
    r = _run(repo)
    assert r.returncode == 0, r.stderr
    assert _checkout(repo) == _template_line(tmp_path / "again")
    assert f"pinned: actions/checkout{ref} to the template's SHA" in r.stdout


def test_a_tag_above_the_template_is_kept_and_named_as_a_tag(tmp_path):
    """Above the template, the pin would be a downgrade, so the tag stays; but
    `--check` says it can still move rather than reading it as current."""
    repo = _installed(tmp_path, "      - uses: actions/checkout@v7.9")
    r = _run(repo, "--check")
    assert r.returncode == 0
    assert "kept (@v7.9 is above the template's" in r.stdout
    assert "a tag, which can move" in r.stdout
    assert _run(repo).returncode == 0
    assert _checkout(repo) == "      - uses: actions/checkout@v7.9"


def test_check_names_a_sha_pin_that_is_not_the_templates_commit(tmp_path):
    """Same version comment, different SHA: kept verbatim, as every SHA pin is,
    but a comment that names the template's version over another commit is
    exactly what a reviewer can't see, so --check names it."""
    v = _template_vars()
    other = (
        "      - uses: actions/checkout@"
        + "ab" * 20
        + f" # v{v['TEMPLATE_CHECKOUT_VERSION']}"
    )
    repo = _installed(tmp_path, other)
    r = _run(repo, "--check")
    assert "kept (SHA-pinned" in r.stdout
    assert "is not the template's" in r.stdout, r.stdout
    assert r.returncode == 0
    assert (
        "is not the template's"
        not in _run(_installed(tmp_path / "x", SHA_LINE), "--check").stdout
    )


def test_pinning_a_bare_major_tag_says_it_may_step_back(tmp_path):
    """CR 2566. `@v7` follows the newest v7 release, so once checkout ships
    one past the template's pin, pinning it steps the job back to an older
    commit until Dependabot or the next skills bump moves the pin. The trade
    is kept (the moving tag is what #675 removes), but both paths say so,
    and a full `@vX.Y.Z` tag, which can't run anything newer, doesn't."""
    v = _template_vars()
    major = v["TEMPLATE_CHECKOUT_VERSION"].split(".")[0]
    repo = _installed(tmp_path, f"      - uses: actions/checkout@v{major}")
    says = "may be older than what it runs now"
    assert says in _run(repo, "--check").stdout
    r = _run(repo)
    assert r.returncode == 0, r.stderr
    assert says in r.stdout, r.stdout
    full = _installed(
        tmp_path / "full",
        f"      - uses: actions/checkout@v{v['TEMPLATE_CHECKOUT_VERSION']}",
    )
    assert says not in _run(full, "--check").stdout
    assert says not in _run(full).stdout


@pytest.mark.parametrize(
    "comment",
    ["v{major}", "v{major}.{minor}"],
    ids=["major-only", "major-minor"],
)
def test_a_short_comment_is_compared_only_as_far_as_it_goes(tmp_path, comment):
    """CR 2569. `# v7` read as 7.0.0 called the template's own SHA "below the
    template's v7.0.1: move the pin". A comment is compared only as far as it
    goes, and the template's SHA is never called below itself."""
    v = _template_vars()
    major, minor, _ = v["TEMPLATE_CHECKOUT_VERSION"].split(".")
    tag = comment.format(major=major, minor=minor)
    own = f"      - uses: actions/checkout@{v['TEMPLATE_CHECKOUT_SHA']} # {tag}"
    other = "      - uses: actions/checkout@" + "ab" * 20 + f" # {tag}"
    for repo in (_installed(tmp_path / "own", own), _installed(tmp_path / "x", other)):
        out = _run(repo, "--check").stdout
        assert "kept (SHA-pinned" in out, out
        assert "below the template's" not in out, out
        # Only an exact version claim is "the template's version".
        assert "is not the template's" not in out, out


def test_the_templates_sha_is_never_below_itself(tmp_path):
    """Whatever its comment says, the template's own commit isn't behind it."""
    v = _template_vars()
    line = f"      - uses: actions/checkout@{v['TEMPLATE_CHECKOUT_SHA']} # v4.0.0"
    out = _run(_installed(tmp_path, line), "--check").stdout
    assert "kept (SHA-pinned" in out and "below the template's" not in out, out
