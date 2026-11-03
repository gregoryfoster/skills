"""#555 — a refresh killed part way is retried the same day, and its staging healed.

The VS Code extension starts a short-lived "config cache" CLI process on every
window (re)connect. It runs the SessionStart hooks and shuts down about 2-3 s
later, killing whatever is still running; the real session starts its own run
about 1 s after. Measured on CannObserv/address-validator (2026-11-01 and -02),
`skills-submodule-update.sh` was killed in that window twice:

- **11-01:** after `git add`, before `git commit` finished. The checkout was left
  with `.skills/doctor.sh` and the vendored gitlink staged, and nothing healed it.
- **11-02:** after `git submodule update`, before the commit block. The content
  moved, the pointer did not.

Both times the killed run had already written the day's lock ("Stamp the lock
BEFORE the update"), so the real session's run exited at the once-per-day guard
in under 200 ms, and the next try was a UTC day away, in the same window.

Decided (2026-11-03), options 1 and 2 together:
- the lock is written only once the update-and-commit block ends, so a killed
  run leaves it unspent; a run that completes but fails still spends it;
- a staged-but-uncommitted bump is healed at session start, ahead of the lock.
  The heal acts only on what the hook itself staged: an in-progress marker in
  `$gitdir` is written before the refresh and removed after its commit, and
  the heal unstages only when every staged path is one the marker names.

The kills are real: `kill -<SIG> 0` from inside the run's own process group
(see tests/utils/refresh_hook_consumer.py), reaching the hook and its git
children together, as the extension's shutdown does.

Coverage:
- killed between `git add` and `git commit` (the issue's 11-01 run, verbatim),
  then a second run                         → the bump is committed and pushed
- killed inside `git commit` by a consumer pre-commit hook (SIGTERM)
                                            → same
- killed after the update, before the commit block (11-02), then a second run
                                            → the bump is committed and pushed
- a killed run                              → the day's lock is unspent
- a completed run that fails (update, push) → the day's lock is spent
- a killed run, then a run that cannot redo the bump (main carries an
  operator's unpushed commit)               → the hook's staging is undone
- a human's staged path beside the hook's   → left staged, and not committed
- a manual bump a human staged by hand      → left staged (no marker)
- a kill that leaves git's index.lock       → the lock is never removed; the
                                              still-staged paths are named
- a clean run                               → leaves no marker behind
"""

import pytest

from tests.utils.refresh_hook_consumer import (
    DOCTOR_PATH,
    VENDOR,
    ahead,
    arm_pre_commit_kill,
    break_remote,
    build,
    content,
    git,
    gitlink,
    lock,
    log_text,
    origin_gitlink,
    run_hook,
    spend_todays_lock,
    staged,
    today,
    write_shim,
)

# The first `git diff --cached --quiet` a run makes is the commit block's own
# check, straight after its `git add` — the 11-01 window, entered with no git
# process holding .git/index.lock, which is the state the issue found.
AFTER_ADD = '[ "$1" = diff ] && [ "$2" = --cached ] && [ "$3" = --quiet ]'
# The commit block opens with `git status --porcelain`; the update is done.
BEFORE_COMMIT_BLOCK = '[ "$1" = status ] && [ "$2" = --porcelain ]'

MARKER = ".git/skills-update.staging"


@pytest.fixture
def consumer(tmp_path):
    return build(tmp_path)


def _kill_once(c, when: str, signal_name: str = "KILL"):
    write_shim(c, kill_when=when, signal_name=signal_name)
    c.kill_flag.write_text("")
    result = run_hook(c)
    write_shim(c)
    assert result.returncode < 0, (
        f"fixture: the first run was meant to be killed, and exited "
        f"{result.returncode}:\n{result.stderr}"
    )
    return result


def _assert_bump_landed(c, result):
    assert result.returncode == 0, result.stderr
    assert staged(c) == [], f"the second run left the index staged: {staged(c)}"
    assert gitlink(c) == c.after, (
        "the second run did not record the bump — the killed run had spent "
        "the day's lock, so this one exited at the once-per-day guard"
    )
    assert ahead(c) == 0 and origin_gitlink(c) == c.after, "the bump was not pushed"
    assert (c.path / DOCTOR_PATH).read_text() == c.v2
    assert git(c.path, "status", "--porcelain").stdout == ""


class TestTheIssuesReproduction:
    def test_killed_between_add_and_commit_then_a_second_run(self, consumer):
        """The 11-01 run, verbatim: `commit skills update:` is the last line
        in the log, both paths are staged, there is no index.lock — and the
        real session's run, a second later, has to finish the job."""
        _kill_once(consumer, AFTER_ADD)

        assert sorted(staged(consumer)) == sorted([DOCTOR_PATH, VENDOR]), (
            "fixture: the kill should leave the issue's staged state"
        )
        assert not (consumer.path / ".git" / "index.lock").exists()
        last = log_text(consumer).rstrip("\n").split("\n")[-1]
        assert last.endswith("commit skills update:"), last

        _assert_bump_landed(consumer, run_hook(consumer))

    def test_killed_inside_git_commit_then_a_second_run(self, consumer):
        """The same window, entered through the consumer's own pre-commit
        hook — where the 11-01 run spent its last second. SIGTERM, which git
        answers by removing its index.lock before it dies."""
        arm_pre_commit_kill(consumer, "TERM")
        first = run_hook(consumer)
        assert first.returncode < 0, first.stderr
        assert sorted(staged(consumer)) == sorted([DOCTOR_PATH, VENDOR])

        _assert_bump_landed(consumer, run_hook(consumer))

    def test_killed_after_the_update_then_a_second_run(self, consumer):
        """The 11-02 run: the content moved, nothing was staged, and the day
        was spent. The second run, the same day, must refresh."""
        _kill_once(consumer, BEFORE_COMMIT_BLOCK)

        assert content(consumer) == consumer.after
        assert gitlink(consumer) == consumer.before
        assert staged(consumer) == []

        _assert_bump_landed(consumer, run_hook(consumer))


class TestTheLock:
    def test_a_killed_run_leaves_the_day_unspent(self, consumer):
        _kill_once(consumer, AFTER_ADD)

        stamp = lock(consumer).read_text().strip() if lock(consumer).exists() else ""
        assert stamp != today(), "a run killed part way spent the day's lock"

    def test_a_failed_update_still_spends_the_day(self, consumer):
        """The damping the lock was stamped early for: a failure that runs to
        completion does not retry at every same-day session."""
        consumer.up.rename(consumer.up.parent / "up-gone")

        result = run_hook(consumer)

        assert result.returncode == 0, result.stderr
        assert "skills update failed" in result.stderr, result.stderr
        assert lock(consumer).read_text().strip() == today()

    def test_a_refused_push_still_spends_the_day(self, consumer):
        break_remote(consumer)

        result = run_hook(consumer)

        assert "could not push" in result.stderr, result.stderr
        assert lock(consumer).read_text().strip() == today()

    def test_a_clean_run_spends_the_day_and_leaves_no_marker(self, consumer):
        result = run_hook(consumer)

        assert result.returncode == 0, result.stderr
        assert lock(consumer).read_text().strip() == today()
        assert not (consumer.path / MARKER).exists()


class TestTheHeal:
    def test_a_run_that_cannot_redo_the_bump_still_undoes_the_staging(
        self, consumer
    ):
        """Main carries an operator's unpushed commit, so this run will not
        commit (#293) — the bump the killed run staged would otherwise sit in
        the index for the operator's next bare `git commit` to absorb."""
        _kill_once(consumer, AFTER_ADD)
        (consumer.path / "mine.txt").write_text("unshared\n")
        git(consumer.path, "add", "mine.txt")
        git(consumer.path, "commit", "-qm", "feat: my own work", "--", "mine.txt")

        result = run_hook(consumer)

        assert result.returncode == 0, result.stderr
        assert staged(consumer) == [], staged(consumer)
        assert git(consumer.path, "log", "-1", "--format=%s").stdout.strip() == (
            "feat: my own work"
        )
        assert not (consumer.path / MARKER).exists()

    def test_a_humans_staged_path_beside_the_hooks_is_left_alone(self, consumer):
        """The hazard: never unstage a human's own work. With anything but
        the hook's paths staged, the heal leaves the whole index alone."""
        (consumer.path / "README.md").write_text("operator work\n")
        git(consumer.path, "add", "README.md")
        _kill_once(consumer, AFTER_ADD)
        spend_todays_lock(consumer)  # isolate the heal from a redone refresh

        result = run_hook(consumer)

        assert result.returncode == 0, result.stderr
        assert sorted(staged(consumer)) == sorted(["README.md", DOCTOR_PATH, VENDOR])
        assert "leaving the index alone" in log_text(consumer), log_text(consumer)

    def test_a_humans_staged_path_survives_the_redone_refresh(self, consumer):
        """And when the same session redoes the bump, its commit is scoped to
        the hook's paths: the human's staged change stays staged, and out of
        the hook's commit."""
        (consumer.path / "README.md").write_text("operator work\n")
        git(consumer.path, "add", "README.md")
        _kill_once(consumer, AFTER_ADD)

        result = run_hook(consumer)

        assert result.returncode == 0, result.stderr
        assert staged(consumer) == ["README.md"]
        assert gitlink(consumer) == consumer.after
        assert git(consumer.path, "show", "HEAD:README.md").stdout == "consumer\n"

    def test_a_manual_bump_staged_by_hand_is_left_alone(self, consumer):
        """A human's `git add skills-vendor/<v>` stages exactly the hook's
        paths. With no in-progress marker it is not the hook's to undo."""
        git(consumer.path, "submodule", "update", "--remote", "--", VENDOR)
        git(consumer.path, "add", VENDOR)
        spend_todays_lock(consumer)

        result = run_hook(consumer)

        assert result.returncode == 0, result.stderr
        assert staged(consumer) == [VENDOR]
        assert content(consumer) == consumer.after
        assert "no in-progress marker" in log_text(consumer), log_text(consumer)

    def test_a_kill_that_leaves_index_lock_is_reported_not_forced(self, consumer):
        """SIGKILL inside `git commit` leaves git's own index.lock behind. The
        heal cannot tell that from a live git process's lock, so it never
        removes it: it says what is still staged, and how to clear it."""
        arm_pre_commit_kill(consumer, "KILL")
        first = run_hook(consumer)
        assert first.returncode < 0, first.stderr
        index_lock = consumer.path / ".git" / "index.lock"
        assert index_lock.exists(), "fixture: SIGKILL should strand index.lock"

        result = run_hook(consumer)

        assert result.returncode == 0, result.stderr
        assert index_lock.exists(), "the hook removed a git lock it did not hold"
        assert f"{VENDOR}" in result.stderr and "still staged" in result.stderr, (
            result.stderr
        )
