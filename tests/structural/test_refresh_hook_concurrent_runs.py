"""CR 1789 — a refresh in flight is left alone by a second session.

Before #555 the day's lock was stamped ahead of the refresh, and it doubled as
the hook's mutual exclusion: a session that started while another was
refreshing exited at the once-per-day guard. #555 moved the stamp to the end
of the refresh, so two sessions starting together in one checkout — several
agent sessions sharing a checkout, or two VS Code windows reconnecting — both
ran the whole refresh. Worse, the second run's heal read the first run's live
in-progress marker as a killed run's leftover, and unstaged and restored the
content under a run that was between `git add` and `git commit`.

The marker now names its owner (`pid <PID> <epoch seconds>`, then the paths).
A run that finds it owned by a live process exits at once, before touching the
working tree or the index, and without spending the day. The heal acts only on
a marker whose owner is gone — or one older than the hook's ceiling plus a
margin, which a PID reused by an unrelated process (or one from another PID
namespace) would otherwise hold forever.

Coverage:
- a second run while the first is held between `git add` and `git commit`
                                         → the first run's commit lands intact
- a fresh marker owned by a live process → the run leaves everything alone
- a marker owned by a live process, past the age bound
                                         → stale: healed
- a fresh marker whose owner is dead     → healed
"""

import subprocess
import time

import pytest

from tests.utils.refresh_hook_consumer import (
    DOCTOR_PATH,
    VENDOR,
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
    spend_todays_lock,
    staged,
    start_hook,
    today,
    write_shim,
)

AFTER_ADD = '[ "$1" = diff ] && [ "$2" = --cached ] && [ "$3" = --quiet ]'
MARKER = ".git/skills-update.staging"
# Past the hook's 120 s ceiling and any margin a fix might choose.
LONG_AGO = 3600


@pytest.fixture
def consumer(tmp_path):
    return build(tmp_path)


def _stamp(c) -> str:
    return lock(c).read_text().strip() if lock(c).exists() else ""


def _wait_for(path, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert time.monotonic() < deadline, f"fixture: {path.name} never appeared"
        time.sleep(0.05)


def _write_marker(c, pid: int, started: int) -> None:
    (c.path / MARKER).write_text(f"pid {pid} {started}\n{VENDOR}\n{DOCTOR_PATH}\n")


def _manual_stage(c) -> None:
    """The state a killed refresh leaves: the content moved and staged."""
    git(c.path, "submodule", "update", "--remote", "--merge", "--", VENDOR)
    git(c.path, "add", VENDOR)
    assert staged(c) == [VENDOR]


def _dead_pid() -> int:
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


class TestARefreshInFlight:
    def test_a_second_run_leaves_a_run_mid_commit_alone(self, consumer):
        c = consumer
        write_shim(c, hold_when=AFTER_ADD)
        c.kill_flag.write_text("")
        first = start_hook(c)
        try:
            _wait_for(c.held)

            second = run_hook(c)

            assert second.returncode == 0, second.stderr
            assert sorted(staged(c)) == sorted([DOCTOR_PATH, VENDOR]), (
                "the second run touched the index under a run between "
                f"`git add` and `git commit`: {staged(c)}"
            )
            assert content(c) == c.after, "the second run moved the content"
            assert gitlink(c) == c.before
            assert _stamp(c) != today(), "the second run spent the day"
            assert "in flight" in log_text(c), log_text(c)
        finally:
            c.release.write_text("")
            result = finish_hook(first)

        assert result.returncode == 0, result.stderr
        assert gitlink(c) == c.after, "the first run's commit did not land"
        assert ahead(c) == 0 and origin_gitlink(c) == c.after
        assert content(c) == c.after
        assert staged(c) == []
        assert not (c.path / MARKER).exists()

    def test_a_fresh_live_owner_stops_the_run_untouched(self, consumer):
        c = consumer
        _manual_stage(c)
        owner = subprocess.Popen(["sleep", "60"])
        try:
            _write_marker(c, owner.pid, int(time.time()))

            result = run_hook(c)
        finally:
            owner.kill()
            owner.wait()

        assert result.returncode == 0, result.stderr
        assert staged(c) == [VENDOR]
        assert content(c) == c.after
        assert _stamp(c) != today()
        assert "in flight" in log_text(c), log_text(c)


class TestAStaleMarkerIsHealed:
    def test_a_live_owner_past_the_age_bound_is_stale(self, consumer):
        """A PID reused by an unrelated long-lived process must not hold the
        checkout forever."""
        c = consumer
        _manual_stage(c)
        spend_todays_lock(c)  # isolate the heal from a redone refresh
        owner = subprocess.Popen(["sleep", "60"])
        try:
            _write_marker(c, owner.pid, int(time.time()) - LONG_AGO)

            result = run_hook(c)
        finally:
            owner.kill()
            owner.wait()

        assert result.returncode == 0, result.stderr
        assert staged(c) == []
        assert content(c) == gitlink(c) == c.before
        assert not (c.path / MARKER).exists()

    def test_a_fresh_marker_with_a_dead_owner_is_healed(self, consumer):
        c = consumer
        _manual_stage(c)
        spend_todays_lock(c)
        _write_marker(c, _dead_pid(), int(time.time()))

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert staged(c) == []
        assert content(c) == gitlink(c) == c.before
        assert not (c.path / MARKER).exists()
