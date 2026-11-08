"""#603 — a run killed inside its push twice in a row waits for the next UTC day.

#575 made the refresh hook back off a day after the second run in a row was
killed inside its `git commit`. Nothing counted a kill inside its `git push`.
A consumer whose pre-push hook runs a suite that does not fit the hook's 120 s
timeout has the push killed, and the push is retried at EVERY session:
- `direct`: `_reconcile_unpushed` pushes at every session start, ahead of the
  once-per-day lock, and the run whose push was killed had already stamped
  that lock. So stamping the lock, which is how #575 backs off, does not stop
  this push. The reconcile has to check the back-off itself.
- `pr`: the branch push in `_pr_publish` runs inside the refresh. A kill there
  never stamps the lock, so the next session refreshes and pushes again.

A kill inside the push is recorded in #575's own count file
(`.git/skills-update.commit-kills`). While a push is in flight, the file has a
second line, `push pid <PID> <epoch>`. A heal that finds a dead owner's line
counts it as #575 counts a commit-stage kill. The second in a row backs off to
the next UTC day, and the heal says why on stderr, once: the push runs the
repo's pre-push hooks, and `.skills/refresh-skip-hooks` (#572) can skip them
on this hook's own push. A push that returns, accepted or refused, removes the
file, which resets the count.

The kills are real SIGKILLs of the run's whole process group, from inside the
consumer's pre-push hook (tests/utils/refresh_hook_consumer.py's group).

Coverage:
- two consecutive kills inside the push, then a third session (the issue's
  case, verbatim)                       → no push the same UTC day; one stderr
                                          line; the next day pushes
- the same, in `pr` mode                → no branch push the same UTC day
- one kill                              → pushed at the next session
- a kill, a push that lands, a kill     → pushed: the push reset the count
- a kill, a push the pre-push hook refuses, a kill
                                        → pushed: a refused push returned too
- a second session while the first is still inside its push
                                        → the live push is not counted
"""

import time

import pytest

from tests.structural.test_refresh_hook_pr_mode import (
    PR_BRANCH,
    _commit_knob,
    _creates,
    _gh,
    _new_day,
)
from tests.utils.refresh_hook_consumer import (
    _vendor_commit,
    ahead,
    build,
    content,
    finish_hook,
    git,
    gitlink,
    lock,
    log_text,
    origin_gitlink,
    run_hook,
    start_hook,
    today,
)

# A phrase only the back-off line carries.
BACKOFF_LINE = "next UTC day"
COUNTER = ".git/skills-update.commit-kills"


def _install_pre_push(c) -> None:
    """A consumer pre-push hook that counts its runs in `c.pushes`. While
    `c.kill_flag` exists it SIGKILLs the run's whole process group, once;
    while `c.refuse_flag` exists it refuses the push, once; while
    `c.hold_flag` exists it parks there, once, until `c.release` exists."""
    c.pushes = c.path.parent / "pre-push-runs"
    c.refuse_flag = c.path.parent / "refuse-armed"
    c.hold_flag = c.path.parent / "hold-armed"
    hook = c.path / ".git" / "hooks" / "pre-push"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        "#!/bin/sh\n"
        f'echo x >>"{c.pushes}"\n'
        f'if [ -f "{c.kill_flag}" ]; then\n'
        f'  rm -f "{c.kill_flag}"\n'
        "  kill -KILL 0\n"
        "  sleep 5\n"
        "fi\n"
        f'if [ -f "{c.refuse_flag}" ]; then\n'
        f'  rm -f "{c.refuse_flag}"\n'
        "  echo 'pre-push: refused' >&2\n"
        "  exit 1\n"
        "fi\n"
        f'if [ -f "{c.hold_flag}" ]; then\n'
        f'  rm -f "{c.hold_flag}"\n'
        f'  : > "{c.held}"\n'
        f'  while [ ! -f "{c.release}" ]; do sleep 0.05; done\n'
        "fi\n"
        "exit 0\n"
    )
    hook.chmod(0o755)


@pytest.fixture
def consumer(tmp_path):
    c = build(tmp_path)
    _install_pre_push(c)
    return c


@pytest.fixture
def pr_consumer(tmp_path):
    """test_refresh_hook_pr_mode.py's consumer, with the pre-push hook
    installed after the fixture's own push of the knob."""
    c = build(tmp_path)
    _commit_knob(c, "pr\n")
    c.gh = _gh(c)
    _install_pre_push(c)
    return c


def _pushes(c) -> int:
    return c.pushes.read_text().count("x") if c.pushes.exists() else 0


def _stamp(c) -> str:
    return lock(c).read_text().strip() if lock(c).exists() else ""


def _kill_in_push(c):
    """One session start, SIGKILLed by the consumer's pre-push hook."""
    before = _pushes(c)
    c.kill_flag.write_text("")
    result = run_hook(c)
    assert result.returncode < 0, (
        f"fixture: the run was meant to be killed inside `git push`, and "
        f"exited {result.returncode}:\n{result.stderr}"
    )
    assert _pushes(c) == before + 1, "fixture: the kill was not inside the push"
    assert not c.kill_flag.exists()
    return result


def _assert_pushed(c, result, pointer):
    assert result.returncode == 0, result.stderr
    assert BACKOFF_LINE not in result.stderr, (
        "backed off where it should have pushed: " + result.stderr
    )
    assert ahead(c) == 0, "the session did not push"
    assert origin_gitlink(c) == pointer


def _assert_backoff_said(result):
    assert result.returncode == 0, result.stderr
    assert result.stderr.count(BACKOFF_LINE) == 1, result.stderr
    assert "pre-push" in result.stderr, result.stderr
    assert ".skills/refresh-skip-hooks" in result.stderr, result.stderr
    assert "120 s" in result.stderr, result.stderr


class TestTheIssuesCase:
    def test_two_kills_inside_the_push_then_a_third_session(self, consumer):
        """The issue's case, verbatim: two consecutive kills inside the push,
        then a third session, which must not push again the same UTC day."""
        c = consumer
        _kill_in_push(c)  # the refresh commits; its push is killed
        assert ahead(c) == 1, "fixture: the commit should have landed"
        assert _stamp(c) == today(), "fixture: the commit's run spends the day"
        _kill_in_push(c)  # the reconcile pushes it again, and is killed again

        third = run_hook(c)

        assert _pushes(c) == 2, (
            "the third session pushed again the same UTC day, after two "
            "consecutive kills inside `git push`"
        )
        _assert_backoff_said(third)
        assert ahead(c) == 1, "the back-off is not a rollback"
        assert origin_gitlink(c) == c.before
        assert _stamp(c) == today()
        assert "push" in log_text(c), log_text(c)

    def test_said_once_and_the_next_day_pushes(self, consumer):
        c = consumer
        _kill_in_push(c)
        _kill_in_push(c)
        _assert_backoff_said(run_hook(c))

        fourth = run_hook(c)

        assert fourth.returncode == 0, fourth.stderr
        assert BACKOFF_LINE not in fourth.stderr, (
            "said again at the next session: " + fourth.stderr
        )
        assert _pushes(c) == 2, "pushed again the same UTC day"

        _new_day(c)
        fifth = run_hook(c)

        _assert_pushed(c, fifth, c.after)
        assert not (c.path / COUNTER).exists(), "the push left the count behind"

    def test_one_kill_is_pushed_at_the_next_session(self, consumer):
        """#555's contract stands: the first kill is not a pattern."""
        c = consumer
        _kill_in_push(c)

        _assert_pushed(c, run_hook(c), c.after)


class TestAPushThatReturnsResetsTheCount:
    def _bump_tomorrow(self, c) -> str:
        newer = _vendor_commit(c.up, c.v2 + "# c3\n", "vendor c3")
        _new_day(c)
        return newer

    def test_a_push_that_lands(self, consumer):
        c = consumer
        _kill_in_push(c)
        _assert_pushed(c, run_hook(c), c.after)
        assert not (c.path / COUNTER).exists(), "the push left the count behind"

        newer = self._bump_tomorrow(c)
        _kill_in_push(c)

        _assert_pushed(c, run_hook(c), newer)

    def test_a_push_the_pre_push_hook_refuses(self, consumer):
        c = consumer
        _kill_in_push(c)
        c.refuse_flag.write_text("")

        refused = run_hook(c)

        assert refused.returncode == 0, refused.stderr
        assert "could not push" in refused.stderr, refused.stderr
        assert not c.refuse_flag.exists(), "fixture: the refusal never fired"
        assert not (c.path / COUNTER).exists(), (
            "a push that returned, refused, left the count behind"
        )

        _new_day(c)
        _kill_in_push(c)

        _assert_pushed(c, run_hook(c), c.after)


class TestALivePush:
    def test_a_second_session_does_not_count_a_push_in_flight(self, consumer):
        """Two sessions in one checkout: the second starts while the first
        is still inside its pre-push hook. The first's record is live, so
        the second's heal must leave it alone."""
        c = consumer
        c.hold_flag.write_text("")
        first = start_hook(c)
        try:
            for _ in range(600):
                if c.held.exists():
                    break
                assert first.poll() is None, "fixture: the first run ended unheld"
                time.sleep(0.05)
            assert c.held.exists(), "fixture: the first run never reached its push"

            second = run_hook(c)
        finally:
            c.release.write_text("")
            done = finish_hook(first)

        assert second.returncode == 0, second.stderr
        assert done.returncode == 0, done.stderr
        assert "killed inside its push" not in log_text(c), (
            "a push still in flight was counted as killed:\n" + log_text(c)
        )
        assert BACKOFF_LINE not in second.stderr + done.stderr
        assert ahead(c) == 0 and origin_gitlink(c) == c.after


class TestPrMode:
    def test_two_kills_inside_the_branch_push_then_a_third_session(self, pr_consumer):
        """`pr` mode's push is the branch push, inside the refresh. A kill
        there never stamps the lock, so each session refreshed and pushed
        again."""
        c = pr_consumer
        _kill_in_push(c)
        assert _stamp(c) != today(), "fixture: a killed refresh spends no day"
        _kill_in_push(c)

        third = run_hook(c)

        assert _pushes(c) == 2, (
            "the third session pushed the branch again the same UTC day"
        )
        _assert_backoff_said(third)
        assert _creates(c.gh) == [], "a pull request was opened"
        assert _stamp(c) == today()
        assert content(c) == gitlink(c) == c.before, (
            "the content was left ahead of its pointer"
        )
        r = git(c.origin, "rev-parse", "--verify", "-q", PR_BRANCH, check=False)
        assert r.returncode != 0, "fixture: the killed pushes never landed"
