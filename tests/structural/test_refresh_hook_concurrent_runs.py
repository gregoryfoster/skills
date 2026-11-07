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
- a second run while the first's claim is mid-write (CR 1808)
                                         → exactly one refresh
- a marker with no `pid` line, under 2 s old by mtime
                                         → left alone; older, healed

CR 1897 — two heals of one dead marker. Both sessions passed the liveness
check on the killed run's marker; the slower one's heal ended with `rm -f` of
the marker, by then the faster session's LIVE claim, and then claimed and ran
a second refresh beside the first. The heal now takes the dead marker by
rename, so exactly one session gets it, and claims it under its own PID for
the length of the heal:
- one session parked in its heal, a second starting meanwhile
                                         → the second leaves; one refresh
- a heal killed part way                 → the next session heals what it left
- a heal killed between taking the marker and claiming it, leaving only the
  renamed file                           → the next session heals that
"""

import os
import subprocess
import time

import pytest

from tests.utils.refresh_hook_consumer import (
    DOCTOR_PATH,
    VENDOR,
    ahead,
    arm_pre_commit_kill,
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


class TestTheClaimIsWrittenWhole:
    """CR 1808: `noclobber` creates the marker, then the claim used to fork
    `date +%s` for the first line's epoch. A second session reaching the
    marker in that window read a zero-byte file — no `pid` line, so not
    live — and both refreshed. The epoch is computed before the file is
    opened now, so the write has no fork inside it; and a marker with no
    parseable `pid` line is believed live for its first ~2 s by mtime."""

    def test_a_slow_date_inside_the_claim_lets_no_second_run_in(self, consumer):
        """The reviewer's reproduction: `date +%s` slowed once, for the first
        run's claim; the second session starts the moment the marker exists."""
        flag = consumer.path.parent / "slow-date"
        shim = consumer.bindir / "date"
        shim.write_text(
            "#!/bin/bash\n"
            f'if [ "$1" = "+%s" ] && [ -f "{flag}" ]; then rm -f "{flag}"; sleep 3; fi\n'
            'exec /bin/date "$@"\n'
        )
        shim.chmod(0o755)
        flag.write_text("")
        marker = consumer.path / MARKER

        first = start_hook(consumer)
        _wait_for(marker)
        second = finish_hook(start_hook(consumer))
        first_done = finish_hook(first)

        assert first_done.returncode == 0, first_done.stderr
        assert second.returncode == 0, second.stderr
        log = log_text(consumer)
        assert log.count("submodule update (") == 1, "both sessions refreshed:\n" + log
        assert "in flight" in log, log
        assert gitlink(consumer) == consumer.after
        assert ahead(consumer) == 0

    def test_a_fresh_marker_with_no_pid_line_is_left_alone(self, consumer):
        """A marker still being written: no `pid` line yet, mtime now."""
        (consumer.path / MARKER).write_text("")

        result = run_hook(consumer)

        assert result.returncode == 0, result.stderr
        assert (consumer.path / MARKER).exists()
        assert gitlink(consumer) == consumer.before
        assert _stamp(consumer) != today(), "a run that left it spent the day"
        assert "in flight" in log_text(consumer), log_text(consumer)

    def test_an_old_marker_with_no_pid_line_is_dead(self, consumer):
        """Past the window it is a killed claim's leftover: healed, and the
        refresh runs."""
        marker = consumer.path / MARKER
        marker.write_text("")
        old = time.time() - 60
        os.utime(marker, (old, old))

        result = run_hook(consumer)

        assert result.returncode == 0, result.stderr
        assert not marker.exists()
        assert gitlink(consumer) == consumer.after
        assert ahead(consumer) == 0


# CR 1897 ------------------------------------------------------------------

# The heal's last read of the index, ahead of the marker's removal.
HEAL_LAST_READ = (
    '[ "$1" = diff ] && [ "$2" = --cached ] && [ "$3" = --quiet ] '
    '&& [ "$4" = --ignore-submodules=none ]'
)
HEAL_RESTORE = '[ "$1" = submodule ] && [ "$2" = update ] && [ "$3" = --checkout ]'
REFRESH_UPDATE = '[ "$1" = submodule ] && [ "$2" = update ] && [ "$3" = --init ]'


def _killed_in_commit(c) -> None:
    """A dead marker, the hook's paths staged: a run killed in `git commit`."""
    arm_pre_commit_kill(c, "TERM")
    result = run_hook(c)
    assert result.returncode < 0, result.stderr
    assert VENDOR in staged(c), staged(c)
    write_shim(c)


def _no_heal_leftovers(c) -> None:
    left = sorted(p.name for p in (c.path / ".git").glob("skills-update.staging.*"))
    assert left == [], f"a heal left its renamed marker behind: {left}"


def _refreshed_once_more(c) -> None:
    assert gitlink(c) == c.after
    assert ahead(c) == 0 and origin_gitlink(c) == c.after
    assert content(c) == c.after
    assert staged(c) == []
    assert not (c.path / MARKER).exists()
    _no_heal_leftovers(c)


class TestTwoHealsOfOneDeadMarker:
    def test_a_session_starting_mid_heal_leaves_it_alone(self, consumer):
        """The reviewer's reproduction: Y parks in its heal, X starts. X used
        to heal the same dead marker, remove it and start a refresh; Y's
        `rm -f` then deleted X's live marker and Y refreshed beside it."""
        c = consumer
        _killed_in_commit(c)
        in_update = c.path.parent / "in-update"
        write_shim(c, hold_when=HEAL_LAST_READ)
        shim = c.bindir / "git"
        first, rest = shim.read_text().split("\n", 1)
        # Every refresh's update says so and is slowed, so that a second
        # refresh, if one starts, overlaps the first.
        shim.write_text(
            f'{first}\nif {REFRESH_UPDATE}; then : > "{in_update}"; sleep 3; fi\n{rest}'
        )
        log_before = len(log_text(c))
        c.kill_flag.write_text("")

        y = start_hook(c)
        try:
            _wait_for(c.held)
            x = start_hook(c)
            deadline = time.monotonic() + 60
            while x.poll() is None and not in_update.exists():
                assert time.monotonic() < deadline, "X neither left nor refreshed"
                time.sleep(0.05)
        finally:
            c.release.write_text("")
        y, x = finish_hook(y), finish_hook(x)

        assert y.returncode == 0, y.stderr
        assert x.returncode == 0, x.stderr
        log = log_text(c)[log_before:]
        assert log.count("] submodule update (") == 1, (
            "two refreshes ran in one checkout at once:\n" + log
        )
        assert "commit failed" not in log, log
        _refreshed_once_more(c)

    def test_a_heal_killed_part_way_is_healed_next(self, consumer):
        """Killed at its restore, after it took the marker: what it took is
        still a marker, under the dead heal's PID, with the killed run's
        paths. The next session heals it and refreshes."""
        c = consumer
        _killed_in_commit(c)
        write_shim(c, kill_when=HEAL_RESTORE, signal_name="TERM")
        c.kill_flag.write_text("")
        killed = run_hook(c)
        write_shim(c)
        assert killed.returncode < 0, killed.stderr

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        _refreshed_once_more(c)

    def test_a_marker_left_renamed_by_a_killed_heal_is_healed(self, consumer):
        """Killed between the rename and its own claim, a heal leaves only the
        renamed file. Nothing may strand the paths it names."""
        c = consumer
        _manual_stage(c)
        spend_todays_lock(c)  # isolate the heal from a redone refresh
        now = int(time.time())
        (
            c.path / ".git" / f"skills-update.staging.heal.{_dead_pid()}.{now}"
        ).write_text(f"pid {_dead_pid()} {now}\n{VENDOR}\n{DOCTOR_PATH}\n")

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert staged(c) == [], "the renamed marker's staging was stranded"
        assert content(c) == gitlink(c) == c.before
        assert not (c.path / MARKER).exists()
        _no_heal_leftovers(c)
