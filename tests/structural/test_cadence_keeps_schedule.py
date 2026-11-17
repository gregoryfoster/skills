"""A plain `install-cadence.sh` re-run keeps the installed schedule (#664).

The installer kept an installed workflow's checkout pin (#373) and ledger when
it re-rendered, but not its schedule. Without `--cron` it derived a slot from
the repo name and wrote that over the installed one, a custom `--cron`
included. `--check`'s `re-render:` line rendered with the installed schedule,
so it said `none` for a re-run that did change the file.

Now a re-run with no `--cron` keeps the installed schedule, and `--cron
derived` returns to the derived slot. With no workflow installed, the derived
slot applies as before. `--check`'s `re-render:` line and a plain re-run
therefore agree.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from tests.utils.skill_loader import SKILLS_DIR

INSTALL_CADENCE = SKILLS_DIR / "curating-context" / "scripts" / "install-cadence.sh"
WF = Path(".github/workflows/context-cadence.yml")
CRON_LINE = re.compile(r"^ *- cron: '(.*)'$", re.M)
CUSTOM = "0 9 * * 3"


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALL_CADENCE), *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_env(),
        timeout=60,
    )


def _repo(tmp_path: Path) -> Path:
    """The issue's fixture: a fresh repo whose origin is example/demo."""
    repo = tmp_path / "r"
    repo.mkdir(parents=True)
    for cmd in (
        ["git", "init", "-q", "-b", "main", str(repo)],
        [
            "git",
            "-C",
            str(repo),
            "remote",
            "add",
            "origin",
            "https://github.com/example/demo.git",
        ],
    ):
        r = subprocess.run(cmd, capture_output=True, text=True, env=_env())
        assert r.returncode == 0, r.stderr
    return repo


def _schedule(repo: Path) -> str:
    m = CRON_LINE.search((repo / WF).read_text())
    assert m, "the rendered workflow has no cron line"
    return m.group(1)


def _derived(tmp_path: Path) -> str:
    """Today's derived slot for example/demo, from a first install."""
    other = _repo(tmp_path / "derived")
    r = _run(other)
    assert r.returncode == 0, r.stdout + r.stderr
    return _schedule(other)


def test_the_issue_reproduction(tmp_path):
    """install --cron, --check, plain re-run: the re-run keeps the schedule,
    and --check's `none` was telling the truth."""
    repo = _repo(tmp_path)
    r = _run(repo, "--cron", CUSTOM)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"(schedule: {CUSTOM})" in r.stdout, r.stdout

    r = _run(repo, "--check")
    assert re.search(r"^re-render: +none\b", r.stdout, re.M), r.stdout
    before = (repo / WF).read_text()

    r = _run(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _schedule(repo) == CUSTOM, r.stdout
    assert (repo / WF).read_text() == before, (
        "a re-run --check called `none` changed the file"
    )
    assert "unchanged:" in r.stdout, r.stdout


def test_a_kept_custom_schedule_is_said_and_names_the_way_back(tmp_path):
    repo = _repo(tmp_path)
    derived = _derived(tmp_path)
    assert derived != CUSTOM
    _run(repo, "--cron", CUSTOM)
    r = _run(repo)
    assert re.search(rf"^kept: schedule '{re.escape(CUSTOM)}'", r.stdout, re.M), (
        r.stdout
    )
    assert f"'{derived}'" in r.stdout, r.stdout
    assert "--cron derived" in r.stdout, r.stdout


def test_a_kept_schedule_equal_to_the_derived_one_says_nothing_extra(tmp_path):
    repo = _repo(tmp_path)
    _run(repo)
    r = _run(repo)
    assert "unchanged:" in r.stdout, r.stdout
    assert "kept: schedule" not in r.stdout, r.stdout


def test_cron_derived_moves_to_the_derived_slot(tmp_path):
    repo = _repo(tmp_path)
    derived = _derived(tmp_path)
    _run(repo, "--cron", CUSTOM)
    r = _run(repo, "--cron", "derived")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _schedule(repo) == derived, r.stdout
    assert f"updated: {WF} (schedule: {derived})" in r.stdout, r.stdout


def test_a_first_install_still_derives(tmp_path):
    repo = _repo(tmp_path)
    derived = _derived(tmp_path)
    r = _run(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _schedule(repo) == derived
    assert "installed:" in r.stdout, r.stdout


def test_an_explicit_cron_still_wins(tmp_path):
    repo = _repo(tmp_path)
    _run(repo, "--cron", CUSTOM)
    r = _run(repo, "--cron", "5 14 * * 2")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _schedule(repo) == "5 14 * * 2"


def test_print_renders_what_a_plain_re_run_writes(tmp_path):
    repo = _repo(tmp_path)
    _run(repo, "--cron", CUSTOM)
    r = _run(repo, "--print")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout == (repo / WF).read_text()


def test_check_with_cron_derived_compares_against_the_derived_slot(tmp_path):
    """--check takes the same --cron a re-run would, `derived` included, and
    its advice names it."""
    repo = _repo(tmp_path)
    _run(repo, "--cron", CUSTOM)
    r = _run(repo, "--check", "--cron", "derived")
    assert re.search(r"^re-render: +behind\b", r.stdout, re.M), r.stdout
    assert "install-cadence.sh --cron derived" in r.stdout, r.stdout


def test_an_unreadable_installed_schedule_falls_back_to_derived_and_says_so(tmp_path):
    """A hand-edited schedule line this can't read is replaced by the derived
    slot, on stderr, as an unreadable checkout pin is (#373)."""
    repo = _repo(tmp_path)
    derived = _derived(tmp_path)
    _run(repo, "--cron", CUSTOM)
    wf = repo / WF
    wf.write_text(wf.read_text().replace(f"- cron: '{CUSTOM}'", "- cron: '0 9 * *'"))
    r = _run(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _schedule(repo) == derived
    assert "replaced: schedule '0 9 * *'" in r.stderr, r.stderr


def test_cron_derived_passes_the_shape_check(tmp_path):
    """`derived` is a word, not five fields; the shape check must not refuse it."""
    repo = _repo(tmp_path)
    r = _run(repo, "--print", "--cron", "derived")
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_help_documents_cron_derived():
    r = subprocess.run(
        ["bash", str(INSTALL_CADENCE), "--help"],
        capture_output=True,
        text=True,
        env=_env(),
        timeout=30,
    )
    assert r.returncode == 0
    text = " ".join(r.stdout.split())
    assert "--cron derived" in text, r.stdout
    assert "keeps the installed schedule" in text, r.stdout


def _set_cron_line(repo: Path, value: str) -> None:
    wf = repo / WF
    text, n = re.subn(
        r"^( *- cron: ).*$",
        lambda m: m.group(1) + value,
        wf.read_text(),
        count=1,
        flags=re.M,
    )
    assert n == 1, "the rendered workflow has no cron line"
    wf.write_text(text)


def test_a_trailing_yaml_comment_does_not_make_the_schedule_unreadable(tmp_path):
    """CR 2368: `- cron: '0 9 * * 3'  # set by ops` is a five-field schedule
    with a YAML comment after it. It read as unreadable, and a plain re-run
    wrote the derived slot over it."""
    repo = _repo(tmp_path)
    _run(repo)
    _set_cron_line(repo, f"'{CUSTOM}'  # set by ops")
    r = _run(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _schedule(repo) == CUSTOM, r.stdout + r.stderr
    assert "replaced: schedule" not in r.stderr, r.stderr


def test_the_replaced_message_quotes_the_schedule_once(tmp_path):
    """CR 2368: the message wrapped a still-quoted value in quotes again."""
    repo = _repo(tmp_path)
    _run(repo)
    _set_cron_line(repo, "'0 9 * *'  # four fields")
    r = _run(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "replaced: schedule '0 9 * *' " in r.stderr, r.stderr
    assert "''" not in r.stderr, r.stderr


def test_check_says_an_unreadable_schedule_would_be_replaced(tmp_path):
    """CR 2368: --check said only `behind … Run install-cadence.sh`, with no
    word that following it replaces the installed schedule."""
    repo = _repo(tmp_path)
    derived = _derived(tmp_path)
    _run(repo)
    _set_cron_line(repo, "'0 9 * *'")
    r = _run(repo, "--check")
    assert re.search(r"^ +schedule unread: ", r.stdout, re.M), r.stdout
    assert f"'{derived}'" in r.stdout, r.stdout
    assert r.returncode == 0, r.stdout + r.stderr


def test_check_says_nothing_extra_for_a_readable_schedule(tmp_path):
    repo = _repo(tmp_path)
    _run(repo, "--cron", CUSTOM)
    r = _run(repo, "--check")
    assert "schedule unread" not in r.stdout, r.stdout
