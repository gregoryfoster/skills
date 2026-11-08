"""patching-hosts' probe: a missed `scheduled` window is `cadence:overdue` (#592).

`posture scheduled` relies on a person to start every run, and before this
nothing reported a window that closed with no run: co-processor's weekly
window passed unattended (2026-11-03), and wslcb-licensing-tracker's four
Tuesday windows did, 2026-10-13 to 11-03, while 51 security packages piled
up. The probe now reads the last run from local facts only, the newest
`/var/backups/patching-hosts-<UTC>` directory and the marker a run with
nothing pending writes, and counts the weekday and `#N` windows that have
closed since.

What this file pins:

- wslcb's case: weekly by default, `window Tue 05:00-10:00`, the last run
  directory 2026-10-06, now 2026-11-03T12:47Z: overdue, 4 windows missed;
- co-processor's: the last run a week earlier, now just after this
  Tuesday's window closed: overdue, 1 missed;
- a window still open, or a dated one that closed, is no miss;
- no run directory and no marker is `cadence:no-run`, never "not overdue";
- a marker newer than the newest run directory is the last run, and one
  that doesn't parse is ignored and named in not_read;
- `monthly` counts a closed `#N` window, and a plain weekday window only
  once it opens more than 31 days after the last run;
- `automatic` has no window to miss;
- an exception covers `cadence:overdue`.

"Now" is the probe's clock, `date +%s`, which the stub answers: `--today`
holds a whole day, and can't tell a window that just closed from one that's
still open.
"""

import calendar
import os
import time
from pathlib import Path

import pytest

from tests.structural.patching_hosts_rig import dispatcher
from tests.structural.test_patching_hosts_probe import Host, _finding, _ids


@pytest.fixture(scope="module", autouse=True)
def _dispatcher(tmp_path_factory):
    with dispatcher(tmp_path_factory):
        yield


def _stamp_epoch(stamp: str) -> int:
    """20261006T070000Z as seconds since 1970, UTC."""
    return calendar.timegm(time.strptime(stamp, "%Y%m%dT%H%M%SZ"))


def _epoch(iso: str) -> int:
    """2026-11-03T12:47 as seconds since 1970, UTC."""
    return calendar.timegm(
        (
            int(iso[0:4]),
            int(iso[5:7]),
            int(iso[8:10]),
            int(iso[11:13]),
            int(iso[14:16]),
            0,
        )
    )


class ClockHost(Host):
    """A probe whose clock reads a set instant: `date +%s` answers it, and
    every other `date` call is the system's."""

    STUBBED = (*Host.STUBBED, "date")
    FALLBACKS = {
        **Host.FALLBACKS,
        "date": 'for d in /bin /usr/bin; do [ -x "$d/date" ] && exec "$d/date" "$@"; done; exit 127',
    }

    def at(self, iso: str) -> "ClockHost":
        self.on("date", "+%s", f"{_epoch(iso)}\n")
        return self

    def run_dir(self, stamp: str) -> Path:
        """A run directory, as apply.sh or recovery-point.sh names one: by
        when it was made."""
        d = self.root / "var" / "backups" / f"patching-hosts-{stamp}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def ran(self, stamp: str, bulk: str | None = None) -> "ClockHost":
        """A run whose directory is STAMP and whose bulk started at BULK
        (default: STAMP), as apply.sh records it in steps: the step, its
        result, its start, wall seconds and max RSS."""
        at = _epoch(bulk) if bulk else _stamp_epoch(stamp)
        (self.run_dir(stamp) / "steps").write_text(f"bulk\tok\t{at}\t300\t2048\n")
        return self

    def recovery_point_only(self, stamp: str) -> "ClockHost":
        """A recovery point whose bulk never started: no steps line."""
        (self.run_dir(stamp) / "recovery-point").write_text("began 0\n")
        return self

    def rebooted(self, stamp: str, fire: str) -> "ClockHost":
        """A reboot-only run: a directory made by hand, and the chain's
        record, its unit and when it fires, as reboot-chain.sh writes it."""
        (self.run_dir(stamp) / "reboot-chain.unit").write_text(
            f"patching-hosts-reboot-{stamp} {fire}\n"
        )
        return self

    def marker(self, text: str) -> "ClockHost":
        self.write("var/backups/patching-hosts-last-reading", text)
        return self


WEEKLY_TUE = "posture scheduled\nwindow Tue 05:00-10:00\n"


def test_wslcbs_four_missed_tuesdays_are_overdue(tmp_path):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE).ran("20261006T070000Z")
    out = h.at("2026-11-03T12:47").run()
    c = out["updates"]["cadence"]
    assert c["cadence"] == "weekly"
    assert c["last_run"] == "2026-10-06T07:00:00Z"
    assert c["last_run_from"] == "/var/backups/patching-hosts-20261006T070000Z"
    assert c["windows_missed"] == 4
    assert c["first_missed"] == "2026-10-13T05:00:00Z"
    f = _finding(out, "cadence:overdue")
    assert f["kind"] == "deviation"
    assert f["exception_what"] == "cadence:overdue"
    for word in ("2026-10-06", "4 windows", "2026-10-13T05:00:00Z", "weekly"):
        assert word in f["message"]


def test_co_processors_one_missed_window_is_overdue(tmp_path):
    h = ClockHost(tmp_path).knob("posture scheduled\nwindow Tue 15:00-21:00\n")
    h.ran("20261027T160000Z")
    out = h.at("2026-11-03T21:05").run()
    c = out["updates"]["cadence"]
    assert (c["windows_missed"], c["first_missed"]) == (1, "2026-11-03T15:00:00Z")
    assert "1 window " in _finding(out, "cadence:overdue")["message"]


def test_a_window_still_open_is_no_miss(tmp_path):
    h = ClockHost(tmp_path).knob("posture scheduled\nwindow Tue 15:00-21:00\n")
    h.ran("20261027T160000Z")
    out = h.at("2026-11-03T20:00").run()
    assert out["updates"]["cadence"]["windows_missed"] == 0
    assert out["updates"]["cadence"]["first_missed"] is None
    assert not [i for i in _ids(out) if i.startswith("cadence:")]


def test_a_missed_dated_window_is_no_miss(tmp_path):
    # A dated line is a one-off: missing it isn't overdue.
    h = ClockHost(tmp_path).knob(
        "posture scheduled\nwindow Tue 15:00-21:00\nwindow 2026-10-30 10:00-12:00 bulletin\n"
    )
    h.ran("20261027T160000Z")
    out = h.at("2026-11-02T12:00").run()
    assert out["updates"]["cadence"]["windows_missed"] == 0
    assert "cadence:overdue" not in _ids(out)


def test_no_run_directory_and_no_marker_is_no_run_on_record(tmp_path):
    # A retention sweep that deleted every run directory reads the same.
    h = ClockHost(tmp_path).knob(WEEKLY_TUE)
    (h.root / "var" / "backups" / "patching-hosts-prune-nginx").mkdir(parents=True)
    out = h.at("2026-11-03T12:47").run()
    c = out["updates"]["cadence"]
    assert (c["last_run"], c["last_run_from"], c["windows_missed"]) == (
        None,
        None,
        None,
    )
    f = _finding(out, "cadence:no-run")
    assert f["kind"] == "unknown"
    assert f["exception_what"] is None
    assert "patching-hosts-last-reading" in f["message"]
    assert "cadence:overdue" not in _ids(out)


def test_a_marker_newer_than_the_run_directory_is_the_last_run(tmp_path):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE).ran("20261006T070000Z")
    h.marker("20261102T090000Z\n")
    out = h.at("2026-11-03T08:00").run()
    c = out["updates"]["cadence"]
    assert c["last_run"] == "2026-11-02T09:00:00Z"
    assert c["last_run_from"] == "/var/backups/patching-hosts-last-reading"
    assert c["windows_missed"] == 0
    assert not [i for i in _ids(out) if i.startswith("cadence:")]


def test_an_older_marker_leaves_the_run_directory_the_last_run(tmp_path):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE).ran("20261027T070000Z")
    h.marker("20261006T090000Z\n")
    out = h.at("2026-11-03T12:47").run()
    c = out["updates"]["cadence"]
    assert c["last_run_from"] == "/var/backups/patching-hosts-20261027T070000Z"
    assert c["windows_missed"] == 1


def test_a_marker_that_doesnt_parse_is_ignored_and_said(tmp_path):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE).ran("20261027T070000Z")
    h.marker("yesterday\n")
    out = h.at("2026-11-03T08:00").run()
    assert out["updates"]["cadence"]["last_run_from"].endswith("20261027T070000Z")
    assert [n for n in out["not_read"] if "patching-hosts-last-reading" in n]


@pytest.mark.parametrize(
    "now, missed",
    [("2026-11-08T11:00", 0), ("2026-11-08T13:00", 1)],
    ids=["open", "closed"],
)
def test_monthly_counts_a_closed_week_of_the_month_window(tmp_path, now, missed):
    # 2026-10-11 and 2026-11-08 are each month's 2nd Sunday.
    h = ClockHost(tmp_path).knob(
        "posture scheduled\ncadence monthly\nwindow Sun#2 08:00-12:00\n"
    )
    h.ran("20261011T090000Z")
    out = h.at(now).run()
    c = out["updates"]["cadence"]
    assert c["windows_missed"] == missed
    assert ("cadence:overdue" in _ids(out)) is bool(missed)
    if missed:
        assert c["first_missed"] == "2026-11-08T08:00:00Z"
        assert "monthly" in _finding(out, "cadence:overdue")["message"]


@pytest.mark.parametrize(
    "now, missed",
    [("2026-11-03T12:47", 0), ("2026-11-10T12:00", 1)],
    ids=["within-a-month", "past-a-month"],
)
def test_monthly_counts_a_plain_weekday_window_only_past_a_month(tmp_path, now, missed):
    # 3 November opens 28 days after the run, inside the month; 10
    # November opens 35 days after, past it.
    h = ClockHost(tmp_path).knob(
        "posture scheduled\ncadence monthly\nwindow Tue 05:00-10:00\n"
    )
    h.ran("20261006T070000Z")
    out = h.at(now).run()
    c = out["updates"]["cadence"]
    assert c["windows_missed"] == missed
    assert ("cadence:overdue" in _ids(out)) is bool(missed)
    if missed:
        assert c["first_missed"] == "2026-11-10T05:00:00Z"


def test_automatic_has_no_window_to_miss(tmp_path):
    h = ClockHost(tmp_path).knob("posture automatic\nwindow Tue 05:00-10:00\n")
    out = h.at("2026-11-03T12:47").run()
    c = out["updates"]["cadence"]
    assert c["windows_missed"] is None
    assert "automatic" in c["unchecked_why"]
    assert not [i for i in _ids(out) if i.startswith("cadence:")]


def test_a_scheduled_host_with_no_recurring_window_says_so(tmp_path):
    h = ClockHost(tmp_path).knob(
        "posture scheduled\nwindow 2026-10-30 10:00-12:00 one-off\n"
    )
    h.ran("20261006T070000Z")
    out = h.at("2026-11-03T12:47").run()
    c = out["updates"]["cadence"]
    assert c["windows_missed"] is None
    assert "weekday" in c["unchecked_why"]
    assert not [i for i in _ids(out) if i.startswith("cadence:")]


def test_an_exception_covers_an_overdue_run(tmp_path):
    h = ClockHost(tmp_path).knob(
        WEEKLY_TUE + "exception cadence:overdue 2026-12-31 migration freeze\n"
    )
    h.ran("20261006T070000Z")
    out = h.at("2026-11-03T12:47").run()
    assert "cadence:overdue" not in _ids(out)
    assert "cadence:overdue" in _ids(out, "excepted")


def test_post_boot_reads_no_cadence(tmp_path):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE)
    out = h.at("2026-11-03T12:47").run("--post-boot")
    assert not [i for i in _ids(out) if i.startswith("cadence:")]


# --- CR 1956: a run is a bulk that started, or a reboot chain ----------------

WEEKLY_TUE_PM = "posture scheduled\nwindow Tue 15:00-21:00\n"


def test_a_run_is_dated_by_its_bulk_not_by_its_recovery_point(tmp_path):
    # A datastore host's recovery point makes the directory, before the
    # window opens; the bulk ran inside it.
    h = ClockHost(tmp_path).knob(WEEKLY_TUE_PM)
    h.ran("20261103T140000Z", bulk="2026-11-03T15:30")
    out = h.at("2026-11-03T21:05").run()
    c = out["updates"]["cadence"]
    assert c["last_run"] == "2026-11-03T15:30:00Z"
    assert c["windows_missed"] == 0
    assert "cadence:overdue" not in _ids(out)


def test_a_recovery_point_whose_bulk_never_started_is_no_run(tmp_path):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE_PM)
    h.ran("20261027T150000Z", bulk="2026-10-27T15:30")
    h.recovery_point_only("20261103T140000Z")
    out = h.at("2026-11-03T21:05").run()
    c = out["updates"]["cadence"]
    assert c["last_run_from"] == "/var/backups/patching-hosts-20261027T150000Z"
    assert (c["windows_missed"], c["first_missed"]) == (1, "2026-11-03T15:00:00Z")


def test_only_a_recovery_point_on_disk_is_no_run_on_record(tmp_path):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE_PM).recovery_point_only("20261103T140000Z")
    out = h.at("2026-11-03T21:05").run()
    assert out["updates"]["cadence"]["last_run"] is None
    assert "cadence:no-run" in _ids(out)


def test_a_reboot_only_run_is_dated_by_its_chain(tmp_path):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE_PM)
    h.rebooted("20261103T153000Z", "2026-11-03T15:42:00Z")
    out = h.at("2026-11-03T21:05").run()
    c = out["updates"]["cadence"]
    assert c["last_run"] == "2026-11-03T15:42:00Z"
    assert c["windows_missed"] == 0


@pytest.mark.skipif(os.geteuid() == 0, reason="root enters any directory")
def test_a_run_directory_that_cant_be_read_leaves_the_count_unread(tmp_path):
    h = ClockHost(tmp_path, sudo=False).knob(WEEKLY_TUE_PM)
    h.ran("20261006T150000Z")
    h.ran("20261103T140000Z", bulk="2026-11-03T15:30")
    d = h.run_dir("20261103T140000Z")
    d.chmod(0o000)
    try:
        out = h.at("2026-11-03T21:05").run()
    finally:
        d.chmod(0o700)
    c = out["updates"]["cadence"]
    assert c["windows_missed"] is None
    assert "couldn't be read" in c["unchecked_why"]
    assert not [i for i in _ids(out) if i.startswith("cadence:")]
    assert [n for n in out["not_read"] if "patching-hosts-20261103T140000Z" in n]


# --- CR 1957: windows are alternatives; a period's floor ----------------------


def test_a_second_weekly_window_after_a_run_is_no_miss(tmp_path):
    h = ClockHost(tmp_path).knob(
        "posture scheduled\nwindow Tue 15:00-21:00\nwindow Thu 15:00-21:00\n"
    )
    h.ran("20261103T160000Z")
    out = h.at("2026-11-05T22:00").run()
    assert out["updates"]["cadence"]["windows_missed"] == 0


def test_a_run_moved_a_day_early_is_no_miss(tmp_path):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE).ran("20261102T090000Z")
    out = h.at("2026-11-03T11:00").run()
    assert out["updates"]["cadence"]["windows_missed"] == 0
    assert "cadence:overdue" not in _ids(out)


def test_monthly_alternative_weeks_of_the_month_are_no_miss(tmp_path):
    # 2026-11-08 and 2026-11-22 are November's 2nd and 4th Sundays.
    h = ClockHost(tmp_path).knob(
        "posture scheduled\ncadence monthly\nwindow Sun#2 08:00-12:00\nwindow Sun#4 08:00-12:00\n"
    )
    h.ran("20261108T090000Z")
    out = h.at("2026-11-22T13:00").run()
    assert out["updates"]["cadence"]["windows_missed"] == 0


@pytest.mark.parametrize(
    "ran, missed",
    [("20261028T060000Z", 0), ("20261028T040000Z", 1)],
    ids=["5d23h-before-it-opens", "6d01h-before-it-opens"],
)
def test_weekly_counts_a_window_opening_more_than_6_days_after(tmp_path, ran, missed):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE).ran(ran)
    out = h.at("2026-11-03T11:00").run()
    assert out["updates"]["cadence"]["windows_missed"] == missed


@pytest.mark.parametrize(
    "ran, missed",
    [("20261101T090000Z", 0), ("20261101T070000Z", 1)],
    ids=["20d23h", "21d01h"],
)
def test_monthly_counts_a_week_of_the_month_window_past_21_days(tmp_path, ran, missed):
    # 2026-11-01 and 2026-11-22 are November's 1st and 4th Sundays.
    h = ClockHost(tmp_path).knob(
        "posture scheduled\ncadence monthly\nwindow Sun#1 08:00-12:00\nwindow Sun#4 08:00-12:00\n"
    )
    h.ran(ran)
    out = h.at("2026-11-22T13:00").run()
    assert out["updates"]["cadence"]["windows_missed"] == missed


def test_monthly_counts_a_plain_window_opening_29_days_after_as_within(tmp_path):
    # CR 1961: 3 November 05:00 opens 29 days 21 hours after the run, inside
    # 31 days, so a 28-day month would wrongly count it.
    h = ClockHost(tmp_path).knob(
        "posture scheduled\ncadence monthly\nwindow Tue 05:00-10:00\n"
    )
    h.ran("20261004T080000Z")
    out = h.at("2026-11-03T12:00").run()
    assert out["updates"]["cadence"]["windows_missed"] == 0


# --- CR 1960: a stamp past the clock -----------------------------------------


def test_a_run_record_past_the_clock_is_ignored_and_said(tmp_path):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE).ran("20261006T070000Z")
    h.ran("20261201T070000Z")
    out = h.at("2026-11-03T12:47").run()
    c = out["updates"]["cadence"]
    assert c["last_run"] == "2026-10-06T07:00:00Z"
    assert c["windows_missed"] == 4
    assert [n for n in out["not_read"] if "20261201T070000Z" in n and "clock" in n]


def test_a_marker_past_the_clock_is_ignored_and_said(tmp_path):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE).ran("20261006T070000Z")
    h.marker("20270101T000000Z\n")
    out = h.at("2026-11-03T12:47").run()
    c = out["updates"]["cadence"]
    assert c["last_run_from"].endswith("20261006T070000Z")
    assert c["windows_missed"] == 4
    assert [n for n in out["not_read"] if "patching-hosts-last-reading" in n]


# --- CR 1961: a marker only root can read -------------------------------------


class RootMarkerHost(ClockHost):
    """head answers for the marker as root would: the user can't read it."""

    STUBBED = (*ClockHost.STUBBED, "head")
    FALLBACKS = {
        **ClockHost.FALLBACKS,
        "head": 'for d in /usr/bin /bin; do [ -x "$d/head" ] && exec "$d/head" "$@"; done; exit 127',
    }


def test_a_root_only_marker_is_read_as_root(tmp_path):
    h = RootMarkerHost(tmp_path).knob(WEEKLY_TUE).ran("20261006T070000Z")
    m = h.write(
        "var/backups/patching-hosts-last-reading", "20261102T090000Z\n", mode=0o000
    )
    h.on("head", "-n 1 -- */patching-hosts-last-reading", "20261102T090000Z\n")
    try:
        out = h.at("2026-11-03T08:00").run()
    finally:
        m.chmod(0o644)
    c = out["updates"]["cadence"]
    assert c["last_run_from"] == "/var/backups/patching-hosts-last-reading"
    assert c["windows_missed"] == 0
    if os.geteuid() != 0:
        assert [c for c in h.calls("sudo") if "patching-hosts-last-reading" in c[1]]
