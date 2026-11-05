"""#572 — the refresh hook's own commit and pushes skip the hook ids
`.skills/refresh-skip-hooks` names, through pre-commit's SKIP.

The harness kills the refresh hook at 120 s, and the hook commits through the
consumer's pre-commit. CannObserv/power-map's suite runs about 550 s on a
pointer-only commit and CannObserv/cli's 112 s, so every refresh there was
killed, and since #555 killed again at every session start. Each consumer
answered with a gate in its own pre-commit that guessed the hook's commit from
its staged paths (power-map#752), a copy of COMMIT_PATHS that would drift with
it. Decided on #572: the hook marks its own commit instead, with the knob's ids
in SKIP, so a bump made by hand still runs every hook.

The consumer's hooks here are plain git hooks that record the SKIP they were
run with, which is what pre-commit reads; pre-commit itself is not needed to
show what the hook hands it.

Coverage:
- no knob                              → SKIP is not set for the commit or push
- a knob                               → its ids reach the commit and the push
- comments, blank lines, CRLF, several ids on a line
                                       → read as ids
- an SKIP the session already carries  → kept, the knob's ids appended
- a comma, a trailing `#`, no ids, a directory
                                       → unusable: SKIP not set, said on
                                         stderr once, and the bump still lands
- merge_mode pr                        → no commit hook runs; the branch push
                                         carries the ids
- each phase's time                    → in the log; a push only where one
                                         was attempted (CR 1817)
- a run past the warning line          → one stderr line naming the knob
"""

import subprocess
from pathlib import Path

import pytest

from tests.structural.test_refresh_hook_pr_mode import PR_BRANCH, _gh, _origin
from tests.utils.refresh_hook_consumer import (
    HOOK,
    VENDOR,
    build,
    clean_env,
    git,
    gitlink,
    log_text,
    origin_gitlink,
    run_hook,
)

KNOB = ".skills/refresh-skip-hooks"
UNSET = "<unset>"


@pytest.fixture
def consumer(tmp_path):
    c = build(tmp_path)
    for stage in ("pre-commit", "pre-push"):
        record = tmp_path / f"{stage}.skip"
        hook = c.path / ".git" / "hooks" / stage
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(
            f'#!/bin/sh\nprintf "%s\\n" "${{SKIP-{UNSET}}}" >> "{record}"\nexit 0\n'
        )
        hook.chmod(0o755)
    return c


def _seen(c, stage: str) -> list[str]:
    record = c.path.parent / f"{stage}.skip"
    return record.read_text().splitlines() if record.exists() else []


def _commit_knob(c, text: str | None = None, *, directory: bool = False) -> None:
    """The knob as a consumer ships it: committed and pushed with everything
    else, so the hook's run starts from a clean tree."""
    knob = c.path / KNOB
    knob.parent.mkdir(exist_ok=True)
    if directory:
        knob.mkdir()
        (knob / "keep").write_text("")
    else:
        knob.write_bytes(text.encode())
    git(c.path, "add", "-A")
    git(c.path, "commit", "-qm", "knob", "--no-verify")
    git(c.path, "push", "-q", "--no-verify", "origin", "main")


def _assert_bump_landed(c, result):
    assert result.returncode == 0, result.stderr
    assert gitlink(c) == c.after, f"the bump was not committed:\n{log_text(c)}"
    assert origin_gitlink(c) == c.after, f"the bump was not pushed:\n{log_text(c)}"


def test_no_knob_leaves_skip_unset(consumer):
    result = run_hook(consumer)
    _assert_bump_landed(consumer, result)
    assert _seen(consumer, "pre-commit") == [UNSET]
    assert _seen(consumer, "pre-push") == [UNSET]
    assert "skipping pre-commit hook" not in log_text(consumer)


def test_the_knobs_ids_reach_the_commit_and_the_push(consumer):
    _commit_knob(consumer, "pytest\nty\n")
    result = run_hook(consumer)
    _assert_bump_landed(consumer, result)
    assert _seen(consumer, "pre-commit") == ["pytest,ty"]
    assert _seen(consumer, "pre-push") == ["pytest,ty"]
    assert f"skipping pre-commit hook(s) pytest,ty ({KNOB})" in log_text(consumer)
    assert KNOB not in result.stderr


def test_a_commit_made_by_hand_runs_every_hook(consumer):
    """The knob shapes only the hook's own commands: nothing it does leaves
    SKIP behind for the operator's next commit."""
    _commit_knob(consumer, "pytest\n")
    _assert_bump_landed(consumer, run_hook(consumer))
    (consumer.path / "README.md").write_text("by hand\n")
    git(consumer.path, "commit", "-qam", "by hand")
    assert _seen(consumer, "pre-commit") == ["pytest", UNSET]


def test_comments_blank_lines_crlf_and_shared_lines(consumer):
    _commit_knob(consumer, "# slow stages\r\n\r\n  pytest   ty\r\n# end\r\nmypy")
    _assert_bump_landed(consumer, run_hook(consumer))
    assert _seen(consumer, "pre-commit") == ["pytest,ty,mypy"]


def test_a_skip_the_session_carries_is_kept(consumer):
    _commit_knob(consumer, "pytest\n")
    env = clean_env()
    env["SKIP"] = "shellcheck"
    env["PATH"] = f"{consumer.bindir}:{env.get('PATH', '/usr/bin:/bin')}"
    result = subprocess.run(
        ["bash", str(HOOK)],
        cwd=consumer.path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    _assert_bump_landed(consumer, result)
    assert _seen(consumer, "pre-commit") == ["shellcheck,pytest"]


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("pytest,ty\n", "has 'pytest,ty', which is not a hook id"),
        ("pytest # the slow one\n", "has '#', which is not a hook id"),
        ("# nothing here\n\n", "names no hook id"),
        (None, "is present but not a readable file"),
    ],
    ids=["comma", "trailing-comment", "no-ids", "directory"],
)
def test_an_unusable_knob_skips_nothing_and_says_so_once(consumer, text, said):
    _commit_knob(consumer, text, directory=text is None)
    result = run_hook(consumer)
    _assert_bump_landed(consumer, result)
    assert _seen(consumer, "pre-commit") == [UNSET]
    assert _seen(consumer, "pre-push") == [UNSET]
    lines = [line for line in result.stderr.splitlines() if KNOB in line]
    assert len(lines) == 1, f"said {len(lines)} times, not once:\n{result.stderr}"
    assert said in lines[0]
    assert "every pre-commit hook" in lines[0]


def test_each_phase_is_timed_in_the_log(consumer):
    _assert_bump_landed(consumer, run_hook(consumer))
    log = log_text(consumer)
    for phase in ("refresh", "commit", "push"):
        assert f"timing: {phase} done at " in log, f"no {phase} timing:\n{log}"
    assert log.index("timing: refresh") < log.index("timing: commit")
    assert log.index("timing: commit") < log.index("timing: push")


def test_a_slow_run_warns_once_naming_the_knob(consumer, tmp_path):
    """The 90 s line itself is not waited out: a copy of the hook with the line
    at 0 s shows what a run past it says."""
    source = HOOK.read_text()
    assert source.count("TIMING_WARN_AT=90\n") == 1
    copy = Path(tmp_path) / "hook-warn-at-0.sh"
    copy.write_text(source.replace("TIMING_WARN_AT=90\n", "TIMING_WARN_AT=0\n"))
    env = clean_env()
    env["PATH"] = f"{consumer.bindir}:{env.get('PATH', '/usr/bin:/bin')}"
    result = subprocess.run(
        ["bash", str(copy)],
        cwd=consumer.path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    _assert_bump_landed(consumer, result)
    lines = [line for line in result.stderr.splitlines() if "timeout" in line]
    assert len(lines) == 1, result.stderr
    assert "of the hook's 120 s default timeout" in lines[0]
    assert KNOB in lines[0]
    assert "past the 0s warning line" in log_text(consumer)


def test_a_run_inside_the_line_says_nothing(consumer):
    result = run_hook(consumer)
    _assert_bump_landed(consumer, result)
    assert "timeout" not in result.stderr


def test_pr_mode_skips_on_its_branch_push_and_runs_no_commit_hook(consumer):
    """`merge_mode` pr builds its commit with `git commit-tree`, which runs
    no hook; its push to the proposal branch goes through pre-push, and
    carries the knob as the direct push does."""
    (consumer.path / ".skills").mkdir(exist_ok=True)
    (consumer.path / ".skills" / "merge_mode").write_text("pr\n")
    _commit_knob(consumer, "pytest\n")
    _gh(consumer)
    result = run_hook(consumer)
    assert result.returncode == 0, result.stderr
    assert _origin(consumer, f"{PR_BRANCH}:{VENDOR}") == consumer.after
    assert _seen(consumer, "pre-commit") == []
    assert _seen(consumer, "pre-push") == ["pytest"]


def test_a_run_that_pushes_nothing_logs_no_push(consumer):
    """CR 1817: `timing: push done` was logged after the last reconcile call
    whether or not it pushed anything."""
    _assert_bump_landed(consumer, run_hook(consumer))
    log = consumer.path / ".git" / "skills-update.log"
    log.write_text("")
    (consumer.path / ".git" / "skills-update.lock").unlink()
    result = run_hook(consumer)
    assert result.returncode == 0, result.stderr
    text = log_text(consumer)
    assert "timing: refresh done at " in text, text
    assert "timing: push" not in text, text
