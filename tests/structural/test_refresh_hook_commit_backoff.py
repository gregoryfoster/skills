"""#575 — a refresh killed inside its commit twice in a row waits for the next UTC day.

#555 moved the day's lock to the end of a refresh, so a run killed part way is
retried at the next session instead of the next UTC day. That is right for the
VS Code extension's 2-3 s kill, which the real session a second later outruns.
It is wrong for a consumer whose pre-commit suite does not fit the hook's 120 s
timeout: the commit is killed at EVERY session start, where before it was
killed once a day (CannObserv/power-map measured ~550 s; CannObserv/cli 112 s).
And the operator sees almost nothing: the heal undoes the staging, and the log
ends mid-`pytest`.

So the heal counts a kill that fell between `git add` and the end of `git
commit` — one that left the hook's own paths staged — in a counter under the
git dir. On the second consecutive one it stamps the day's lock, and says why
on stderr, once: the commit did not fit the 120 s budget, and
`.skills/refresh-skip-hooks` (#572) is the fix. A run whose commit lands
resets the counter. A kill before `git add` neither counts nor resets: the
extension's ~2 s kill nearly always lands there, and if it reset the count, a
slow suite interleaved with it would never back off.

The kills are real, from inside the run's own process group, through a
consumer pre-commit hook (tests/utils/refresh_hook_consumer.py), with SIGTERM:
git answers it by removing its index.lock, so the heal can unstage.

Coverage:
- two consecutive kills inside `git commit`, then a third session (the issue's
  case, verbatim)                         → no retry the same day; staging and
                                            content undone; one stderr line
- one kill                                → retried at the next session (#555)
- the second kill, then later sessions the same day
                                          → the line is said once, not at every
                                            session
- the second kill with a human's path staged beside the hook's (the marker is
  kept, so every session heals it again) → counted once, said once
- a commit-stage kill, then a kill before `git add`
                                          → the next session retries
- a commit-stage kill, a kill before `git add`, a commit-stage kill
                                          → backs off: the pre-add kill did not
                                            reset the count
- a commit-stage kill, a run that commits, a commit-stage kill
                                          → retried: the commit reset the count
- a commit-stage kill, a heal killed at its restore, a commit-stage kill
  (CR 1899: the count was taken last, so a killed heal lost it)
                                          → backs off
"""

import pytest

from tests.utils.refresh_hook_consumer import (
    VENDOR,
    ahead,
    arm_pre_commit_kill,
    build,
    content,
    git,
    gitlink,
    lock,
    log_text,
    origin_gitlink,
    run_hook,
    staged,
    today,
    write_shim,
)

# The commit block opens with `git status --porcelain`; the update is done and
# nothing is staged yet — a kill here falls before `git add`.
BEFORE_COMMIT_BLOCK = '[ "$1" = status ] && [ "$2" = --porcelain ]'
# A phrase only the back-off line carries.
BACKOFF_LINE = "next UTC day"
COUNTER = ".git/skills-update.commit-kills"


@pytest.fixture
def consumer(tmp_path):
    return build(tmp_path)


def _stamp(c) -> str:
    return lock(c).read_text().strip() if lock(c).exists() else ""


def _kill_in_commit(c):
    """One session start, killed by the consumer's pre-commit hook."""
    arm_pre_commit_kill(c, "TERM")
    result = run_hook(c)
    assert result.returncode < 0, (
        f"fixture: the run was meant to be killed inside `git commit`, and "
        f"exited {result.returncode}:\n{result.stderr}"
    )
    # The doctor rides along only when the bump changes it.
    assert VENDOR in staged(c), (
        f"fixture: the kill should leave the hook's paths staged: {staged(c)}"
    )
    return result


def _kill_before_add(c):
    """One session start, killed after the update and before `git add`."""
    write_shim(c, kill_when=BEFORE_COMMIT_BLOCK, signal_name="TERM")
    c.kill_flag.write_text("")
    result = run_hook(c)
    write_shim(c)
    assert result.returncode < 0, (
        f"fixture: the run was meant to be killed before `git add`, and "
        f"exited {result.returncode}:\n{result.stderr}"
    )
    assert content(c) == c.after and staged(c) == []
    return result


def _assert_landed(c, result, pointer):
    assert result.returncode == 0, result.stderr
    assert BACKOFF_LINE not in result.stderr, (
        "backed off where it should have retried: " + result.stderr
    )
    assert staged(c) == [], staged(c)
    assert gitlink(c) == pointer, "the session did not retry the refresh"
    assert ahead(c) == 0 and origin_gitlink(c) == pointer


def _assert_backed_off(c, result):
    assert result.returncode == 0, result.stderr
    assert gitlink(c) == c.before, (
        "the session retried the refresh the same day, after two consecutive "
        "kills inside `git commit`"
    )
    assert _stamp(c) == today(), "the back-off did not spend the day's lock"
    assert result.stderr.count(BACKOFF_LINE) == 1, result.stderr
    assert ".skills/refresh-skip-hooks" in result.stderr, result.stderr
    assert "120 s" in result.stderr, result.stderr


class TestTheIssuesCase:
    def test_two_kills_inside_git_commit_then_a_third_session(self, consumer):
        """The issue's case, verbatim: two consecutive kills inside `git
        commit`, then a third session, which must not retry the same day.
        Its heal still undoes the second kill's bump, staging and content."""
        c = consumer
        _kill_in_commit(c)
        _kill_in_commit(c)  # the second session's heal, then its own kill

        third = run_hook(c)

        _assert_backed_off(c, third)
        assert staged(c) == [], "the back-off left the hook's staging in place"
        assert content(c) == c.before, "the content was left ahead of its pointer"
        assert ahead(c) == 0
        assert "back" in log_text(c), log_text(c)

    def test_one_kill_is_retried_at_the_next_session(self, consumer):
        """#555's contract stands: the first kill is not a pattern."""
        c = consumer
        _kill_in_commit(c)

        _assert_landed(c, run_hook(c), c.after)


class TestSaidOnce:
    def test_the_line_is_not_repeated_at_later_sessions(self, consumer):
        c = consumer
        _kill_in_commit(c)
        _kill_in_commit(c)
        third = run_hook(c)
        _assert_backed_off(c, third)

        fourth = run_hook(c)

        assert fourth.returncode == 0, fourth.stderr
        assert BACKOFF_LINE not in fourth.stderr, (
            "said again at the next session: " + fourth.stderr
        )
        assert gitlink(c) == c.before

    def test_a_kept_marker_is_counted_once(self, consumer):
        """With a human's path staged beside the hook's, the heal leaves the
        index alone and keeps the marker, so every later session heals the
        same killed run again. That is one kill, counted and said once."""
        c = consumer
        (c.path / "README.md").write_text("operator work\n")
        git(c.path, "add", "README.md")
        _kill_in_commit(c)
        _kill_in_commit(c)

        third = run_hook(c)

        _assert_backed_off(c, third)
        assert "README.md" in staged(c)

        fourth = run_hook(c)

        assert fourth.returncode == 0, fourth.stderr
        assert BACKOFF_LINE not in fourth.stderr, fourth.stderr

        lock(c).unlink()  # the next UTC day
        fifth = run_hook(c)

        assert fifth.returncode == 0, fifth.stderr
        assert BACKOFF_LINE not in fifth.stderr, (
            "the kept marker's kill was counted again: " + fifth.stderr
        )
        assert gitlink(c) == c.after, "the next day did not retry"
        assert staged(c) == ["README.md"]


class TestWhatCounts:
    def test_a_kill_before_git_add_does_not_count(self, consumer):
        c = consumer
        _kill_in_commit(c)
        _kill_before_add(c)  # heals the first kill, then dies before `git add`

        _assert_landed(c, run_hook(c), c.after)

    def test_a_kill_before_git_add_does_not_reset_the_count(self, consumer):
        """The extension's ~2 s kill nearly always lands before `git add`.
        Were it to reset the count, a suite too slow for 120 s interleaved
        with it would be retried at every session, as before."""
        c = consumer
        _kill_in_commit(c)
        _kill_before_add(c)
        _kill_in_commit(c)

        _assert_backed_off(c, run_hook(c))

    def test_a_run_that_commits_resets_the_count(self, consumer):
        c = consumer
        _kill_in_commit(c)
        _assert_landed(c, run_hook(c), c.after)
        assert not (c.path / COUNTER).exists(), "the commit left the count behind"

        git(c.up, "commit", "-q", "--allow-empty", "-m", "vendor c3")
        newer = git(c.up, "rev-parse", "HEAD").stdout.strip()
        lock(c).unlink()  # the next UTC day
        _kill_in_commit(c)

        _assert_landed(c, run_hook(c), newer)


# CR 1899 ------------------------------------------------------------------

# The heal's restore, after its unstage: the last git it runs before the
# count used to be taken.
HEAL_RESTORE = '[ "$1" = submodule ] && [ "$2" = update ] && [ "$3" = --checkout ]'


class TestAKilledHealStillCounts:
    def test_a_heal_killed_at_its_restore_counts_the_kill(self, consumer):
        """The count came last, after the restore and the marker's removal.
        A heal killed at its restore lost it, and the next heal found the
        staging already undone and counted nothing — so two commit-stage
        kills with a killed heal between them read as one, and a suite too
        slow for the budget was retried at every session again."""
        c = consumer
        _kill_in_commit(c)
        write_shim(c, kill_when=HEAL_RESTORE, signal_name="TERM")
        c.kill_flag.write_text("")
        healer = run_hook(c)
        write_shim(c)
        assert healer.returncode < 0, (
            f"fixture: the heal was meant to be killed at its restore:\n{healer.stderr}"
        )
        assert staged(c) == [], "fixture: the kill should fall after the unstage"
        _kill_in_commit(c)  # heals what the killed heal left, then its own kill

        _assert_backed_off(c, run_hook(c))
