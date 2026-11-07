"""#566 — two sessions rolling back one refused push roll it back once.

`_reconcile_unpushed` runs at every session start, ahead of the once-per-day
lock and of #555's in-progress marker, so nothing stops two sessions sharing a
checkout from entering it together. In `direct` mode, with `main` N commits
ahead of `@{u}` and every one the hook's, both pushed, both were refused, and
both ran `git reset --soft HEAD~N`. The second reset was relative to a HEAD
the first had already moved, so it rolled back N commits that were not the
hook's, and `main` ended up behind its upstream.

Now HEAD moves by compare-and-swap, as `pr` mode's pass already did (#560):
`git update-ref HEAD <target> <head>`, with `<head>` read once, before the
guards, and every guard, the push and the rollback reading that commit rather
than HEAD again. A second swap fails, is logged and said, and is never
reported as a rollback; the unstage and #550's restore run only after a swap
that succeeded.

Coverage, each with one session parked by the `git` shim while a second runs
to its end:
- parked at the push              → main ends at @{u}, rolled back once
- parked after the guards read the range, before the push
                                  → the same; a HEAD captured after the
                                    guards would be one they never read
- a swap git refuses, HEAD unmoved → "neither pushed nor rolled back", and no
                                    unstage or restore runs
"""

import time

from tests.structural.test_refresh_hook_rollback_restores import (
    _origin_moves_ahead,
    _stranded_bump,
)
from tests.utils.refresh_hook_consumer import (
    build,
    content,
    finish_hook,
    git,
    gitlink,
    log_text,
    run_hook,
    staged,
    start_hook,
    write_shim,
)

AT_PUSH = '[ "$1" = push ]'
# The merge-commit guard: the last read of the range ahead of the push.
AFTER_THE_GUARDS = '[ "$1" = rev-list ] && [ "$2" = --count ] && [ "$3" = --merges ]'
# The restore's header line, once per restore: the per-path line after it
# reads "restored <path> after a rolled-back push: …".
RESTORED = "to the pointer the index records, after a rolled-back push:"


def _rev(c, rev: str) -> str:
    return git(c.path, "rev-parse", rev).stdout.strip()


def _two_sessions(c, hold_when: str):
    """The first session parked at `hold_when`, the second run to its end,
    then the first released and run to its end."""
    write_shim(c, hold_when=hold_when)
    c.kill_flag.write_text("")
    first = start_hook(c)
    deadline = time.monotonic() + 60
    while not c.held.exists():
        assert time.monotonic() < deadline, "the first run never reached the hold"
        time.sleep(0.05)
    second = run_hook(c)
    c.release.write_text("")
    return finish_hook(first), second


def _refused_bump(tmp_path):
    c = build(tmp_path)
    _stranded_bump(c)
    _origin_moves_ahead(c)
    c.base = _rev(c, "@{u}")
    c.bump = _rev(c, "HEAD")
    assert _rev(c, "HEAD~1") == c.base
    return c


def _rolled_back_once(c, parked, ran) -> None:
    assert parked.returncode == 0, parked.stderr
    assert ran.returncode == 0, ran.stderr
    head = _rev(c, "HEAD")
    assert head == c.base, f"main is at {head[:7]}, not @{{u}} ({c.base[:7]}) — " + (
        "rolled back past its upstream: a commit that is not the hook's"
        if head != c.bump
        else "nothing rolled back"
    )
    assert content(c) == gitlink(c) == c.before
    assert staged(c) == []
    log = log_text(c)
    assert log.count("unpushed: push failed — rolled 1 commit(s) back") == 1, log
    assert log.count(RESTORED) == 1, (
        "the unstage and restore ran for a rollback that was not this run's\n" + log
    )
    assert "rolled 1 commit(s) back" in ran.stderr, ran.stderr
    assert "rolled 1" not in parked.stderr, (
        "a swap that failed was reported as a rollback: " + parked.stderr
    )
    assert "HEAD moved" in log, log
    assert "moved under this run" in parked.stderr, parked.stderr


class TestTwoSessionsRollBackOnce:
    def test_parked_at_the_push(self, tmp_path):
        """The issue's race, verbatim: both pushes refused, both roll back."""
        c = _refused_bump(tmp_path)

        parked, ran = _two_sessions(c, AT_PUSH)

        _rolled_back_once(c, parked, ran)

    def test_parked_after_the_guards_read_the_range(self, tmp_path):
        """The guards vetted the range ending at one HEAD. A rollback whose
        HEAD was read again after them moves a range nobody vetted."""
        c = _refused_bump(tmp_path)

        parked, ran = _two_sessions(c, AFTER_THE_GUARDS)

        _rolled_back_once(c, parked, ran)


class TestASwapGitRefuses:
    def test_it_is_said_and_nothing_is_restored(self, tmp_path):
        """HEAD has not moved, so it is still ahead: the old message stands,
        and the bump's content stays with the pointer HEAD still records."""
        c = _refused_bump(tmp_path)
        write_shim(c)
        shim = c.bindir / "git"
        text = shim.read_text().split("\n", 1)
        shim.write_text(
            text[0] + "\n"
            'if [ "$1" = update-ref ]; then '
            'echo "fatal: simulated refusal" >&2; exit 1; fi\n' + text[1]
        )

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert _rev(c, "HEAD") == c.bump
        assert "could be neither pushed nor rolled back" in result.stderr, result.stderr
        assert "rolled 1" not in result.stderr, result.stderr
        assert content(c) == gitlink(c) == c.after
        assert RESTORED not in log_text(c), log_text(c)
        assert "simulated refusal" in log_text(c)
