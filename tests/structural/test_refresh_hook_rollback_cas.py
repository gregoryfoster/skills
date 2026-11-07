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

CR 1896 — a push refused because ANOTHER session's push of the same commit
landed first. Both sessions push one stranded bump; the remote takes one and
rejects the other ("incorrect old value provided"), and nothing has moved
local HEAD, so the loser's swap succeeded: main rolled back behind @{u} and
origin, and stderr claimed the checkout now "matches" its upstream. The hook
never pulls, so every later bump was refused until a human synced. Now a
failed push first asks whether the remote already has the commit — @{u}, then
one `git ls-remote` — and rolls back nothing if it does:
- the reviewer's race, a pre-push barrier → both pushes go together, one is
                                            refused; main stays on the bump
- the other session's push lands while this one waits, then this one's
  network fails                          → @{u} already holds it: no rollback
- @{u} stale, the remote's main moved to the commit after this push read it,
  so the remote refuses it               → ls-remote finds it: no rollback, and
                                            @{u} is brought up to it

CR 1907 — that `git ls-remote` is a second network wait. Asked only when the
push's own output shows the remote refused the ref:
- a push that never reaches the remote   → no ls-remote; rolled back
"""

import time

from tests.structural.test_refresh_hook_rollback_restores import (
    _origin_moves_ahead,
    _stranded_bump,
)
from tests.utils.refresh_hook_consumer import (
    break_remote,
    build,
    content,
    finish_hook,
    git,
    gitlink,
    log_text,
    run_hook,
    spend_todays_lock,
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


# CR 1896 ------------------------------------------------------------------


def _pushed_by_another(c, *results) -> None:
    """The bump is on the remote, so nothing may roll it back locally."""
    for r in results:
        assert r.returncode == 0, r.stderr
        assert "rolled" not in r.stderr, (
            "a session rolled back a commit the remote already holds: " + r.stderr
        )
    head = _rev(c, "HEAD")
    behind = git(c.path, "rev-list", "--count", "HEAD..@{u}").stdout.strip()
    assert head == c.bump, (
        f"main is at {head[:7]}, not the bump {c.bump[:7]} the remote holds — "
        f"{behind} behind @{{u}}, and the hook never pulls"
    )
    assert git(c.origin, "rev-parse", "main").stdout.strip() == c.bump
    assert _rev(c, "@{u}") == c.bump
    assert content(c) == gitlink(c) == c.after
    assert staged(c) == []
    log = log_text(c)
    assert RESTORED not in log, log
    assert "already has" in log, log


def _stranded(tmp_path):
    c = build(tmp_path)
    _stranded_bump(c)
    spend_todays_lock(c)  # each session only reconciles
    c.bump = _rev(c, "HEAD")
    return c


class TestAPushAnotherSessionLanded:
    def test_two_pushes_of_one_bump_race(self, tmp_path):
        """The reviewer's reproduction: a pre-push barrier holds both
        sessions until each has its advertisement, so both pushes go
        together and the remote refuses one."""
        c = _stranded(tmp_path)
        barrier = tmp_path / "barrier"
        barrier.mkdir()
        hook = c.path / ".git" / "hooks" / "pre-push"
        hook.write_text(
            "#!/bin/sh\n"
            f': > "{barrier}/$$"\n'
            f'while [ "$(ls "{barrier}" | wc -l)" -lt 2 ]; do sleep 0.02; done\n'
            "exit 0\n"
        )
        hook.chmod(0o755)

        a = start_hook(c)
        b = start_hook(c)
        a, b = finish_hook(a), finish_hook(b)

        log = log_text(c)
        assert log.count("unpushed: pushed 1 commit(s)") == 1, (
            "fixture: one push should land and the other be refused\n" + log
        )
        _pushed_by_another(c, a, b)

    def test_a_failed_push_after_the_other_sessions_landed(self, tmp_path):
        """One session parked at its push while another pushes the same
        bump; then the first's network fails. Its @{u} already holds it."""
        c = _stranded(tmp_path)
        write_shim(c, hold_when=AT_PUSH)
        c.kill_flag.write_text("")
        first = start_hook(c)
        deadline = time.monotonic() + 60
        while not c.held.exists():
            assert time.monotonic() < deadline, "the first run never reached the hold"
            time.sleep(0.05)
        second = run_hook(c)
        break_remote(c)
        c.release.write_text("")
        first = finish_hook(first)

        assert "could not push" not in second.stderr, second.stderr
        _pushed_by_another(c, first, second)

    def test_a_stale_upstream_is_checked_against_the_remote(self, tmp_path):
        """The remote already holds the bump and @{u} does not know it: the
        other session's push moved the remote's main after this one read its
        advertisement, and nothing has written this checkout's tracking ref.
        A pre-push hook moves it here, so the remote refuses this push for
        real ("incorrect old value provided"). Asked once, the remote has
        the commit."""
        c = _stranded(tmp_path)
        # The bump's objects on the remote, so its main can be moved to it.
        git(c.path, "push", "-q", "origin", f"{c.bump}:refs/heads/elsewhere")
        hook = c.path / ".git" / "hooks" / "pre-push"
        hook.write_text(
            "#!/bin/sh\n"
            f'git --git-dir="{c.origin}" update-ref refs/heads/main {c.bump}\n'
            "exit 0\n"
        )
        hook.chmod(0o755)

        result = run_hook(c)

        assert "incorrect old value" in log_text(c), (
            "fixture: the remote should refuse the push itself\n" + log_text(c)
        )
        _pushed_by_another(c, result)


# CR 1907 ------------------------------------------------------------------


class TestAPushThatNeverReachedTheRemote:
    def test_it_does_not_ask_the_remote_again(self, tmp_path):
        """A remote that drops packets costs the push its whole network wait;
        a `git ls-remote` after it costs a second one, and the 120 s kill
        then lands before the rollback, every session. Only a refusal by
        the remote itself — the two-session race always produces one —
        asks it again."""
        c = _stranded(tmp_path)
        asked = tmp_path / "ls-remote-calls"
        write_shim(c)
        shim = c.bindir / "git"
        first, rest = shim.read_text().split("\n", 1)
        shim.write_text(
            f'{first}\nif [ "$1" = ls-remote ]; then echo x >> "{asked}"; fi\n{rest}'
        )
        gone = str(c.path.parent / "gone.git")
        git(c.path, "config", "remote.origin.pushurl", gone)

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert not asked.exists(), (
            "a push that never reached the remote asked it again with ls-remote"
        )
        assert "rolled 1 commit(s) back" in result.stderr, result.stderr
        assert _rev(c, "HEAD") == _rev(c, "@{u}")
