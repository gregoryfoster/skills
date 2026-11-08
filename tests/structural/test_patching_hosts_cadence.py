"""patching-hosts' probe: a missed `scheduled` window is `cadence:overdue` (#592).

`posture scheduled` relies on a person to start every run, and before this
nothing reported a window that closed with no run: co-processor's weekly
window passed unattended (2026-11-03), and wslcb-licensing-tracker's four
Tuesday windows did, 2026-10-13 to 11-03, while 51 security packages piled
up. The probe now reads the last run from local facts only: a run
directory's bulk line or reboot chain, a directory its retention emptied by
its name, or the marker a run that left no bulk record writes. It counts
the weekday and `#N` windows that have closed since, each only once it opens
most of a period after the last run, and the periods missed.

What this file pins:

- wslcb's case: weekly by default, `window Tue 05:00-10:00`, the last run
  2026-10-06, now 2026-11-03T12:47Z: overdue, 4 weeks missed;
- co-processor's: the last run a week earlier, now just after this
  Tuesday's window closed: overdue, 1 missed;
- a window still open, or a dated one that closed, is no miss, and window
  lines are alternatives (CR 1957);
- no run on record is `cadence:no-run`, never "not overdue";
- every run directory is a run, dated by its bulk line, its reboot chain,
  or else its name, whatever else it holds or whether it can be read (CR
  1956, 1969, 1971, 1979-1983);
- a marker newer than the newest run is the last run; one that doesn't
  parse, or a stamp past the clock, is ignored and named in not_read, and
  one within the hour past it is taken as now (CR 1960, 1970);
- `monthly`'s floors; `automatic` has no window to miss;
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


def test_an_abandoned_recovery_point_is_an_attempt_the_next_window_counts_from(
    tmp_path,
):
    # CR 1979-1984: every run directory is an attempt, and the finding counts
    # from the last attempt. One whose bulk never ran is dated by its name,
    # and only windows after it count.
    h = ClockHost(tmp_path).knob(WEEKLY_TUE_PM)
    h.ran("20261027T150000Z", bulk="2026-10-27T15:30")
    h.recovery_point_only("20261103T140000Z")
    c = h.at("2026-11-03T21:05").run()["updates"]["cadence"]
    assert (c["last_run"], c["windows_missed"]) == ("2026-11-03T14:00:00Z", 0)
    h.cases["date"] = []
    out = h.at("2026-11-10T21:05").run()
    c = out["updates"]["cadence"]
    assert (c["windows_missed"], c["first_missed"]) == (1, "2026-11-10T15:00:00Z")
    assert "cadence:overdue" in _ids(out)


def test_an_attempt_after_four_missed_weeks_resets_the_count(tmp_path):
    # CR 1984, S1 on wslcb's history: a real run on 10-06, four Tuesdays
    # missed, then a recovery point at 04:00 on 11-03 whose bulk never ran.
    # The finding reads periods since that attempt: none yet, then one.
    h = ClockHost(tmp_path).knob(WEEKLY_TUE).ran("20261006T070000Z")
    h.recovery_point_only("20261103T040000Z")
    out = h.at("2026-11-03T12:47").run()
    c = out["updates"]["cadence"]
    assert (c["last_run"], c["periods_missed"]) == ("2026-11-03T04:00:00Z", 0)
    assert "cadence:overdue" not in _ids(out)
    h.cases["date"] = []
    c = h.at("2026-11-10T12:47").run()["updates"]["cadence"]
    assert (c["periods_missed"], c["first_missed"]) == (1, "2026-11-10T05:00:00Z")


def test_bulks_that_failed_before_their_holds_are_attempts(tmp_path):
    # CR 1984, S6: apply.sh makes the directory, then fails before holds and
    # steps (its apt-get update, say). A failed attempt's record is where the
    # failure shows; this finding reads it as attended.
    h = ClockHost(tmp_path).knob(WEEKLY_TUE).ran("20261006T070000Z")
    for day in ("13", "20", "27"):
        (h.run_dir(f"202610{day}T050500Z") / "apt-get-update.log").write_text("E\n")
    (h.run_dir("20261103T050500Z") / "apt-get-update.log").write_text("E\n")
    out = h.at("2026-11-03T12:47").run()
    c = out["updates"]["cadence"]
    assert (c["last_run"], c["periods_missed"]) == ("2026-11-03T05:05:00Z", 0)
    assert "cadence:overdue" not in _ids(out)


def test_a_recovery_point_alone_is_a_run_not_no_run_on_record(tmp_path):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE_PM).recovery_point_only("20261103T140000Z")
    out = h.at("2026-11-03T21:05").run()
    assert out["updates"]["cadence"]["last_run"] == "2026-11-03T14:00:00Z"
    assert "cadence:no-run" not in _ids(out)


def test_a_reboot_only_run_is_dated_by_its_chain(tmp_path):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE_PM)
    h.rebooted("20261103T153000Z", "2026-11-03T15:42:00Z")
    out = h.at("2026-11-03T21:05").run()
    c = out["updates"]["cadence"]
    assert c["last_run"] == "2026-11-03T15:42:00Z"
    assert c["windows_missed"] == 0


@pytest.mark.skipif(os.geteuid() == 0, reason="root enters any directory")
def test_a_run_directory_that_cant_be_read_is_dated_by_its_name(tmp_path):
    # It never stops the count: an old one no one can read would turn the
    # check off for good.
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
    assert (c["last_run"], c["windows_missed"]) == ("2026-11-03T14:00:00Z", 0)
    assert c["unchecked_why"] is None


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 file")
def test_a_listed_steps_no_one_can_read_falls_back_to_the_name(tmp_path):
    # CR 1982.
    h = ClockHost(tmp_path, sudo=False).knob(WEEKLY_TUE_PM)
    h.ran("20261027T150000Z")
    h.ran("20261103T140000Z", bulk="2026-11-03T15:30")
    steps = h.run_dir("20261103T140000Z") / "steps"
    steps.chmod(0o000)
    try:
        out = h.at("2026-11-03T21:05").run()
    finally:
        steps.chmod(0o600)
    c = out["updates"]["cadence"]
    assert (c["last_run"], c["windows_missed"]) == ("2026-11-03T14:00:00Z", 0)


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


# --- CR 1969: a directory its retention emptied ------------------------------


def test_a_directory_its_retention_emptied_still_dates_the_run(tmp_path):
    # recovery-point.sh says to delete every file in the run on its retention
    # date: the empty directory left is dated by its name, within the day
    # the bulk allows its recovery point.
    h = ClockHost(tmp_path).knob(WEEKLY_TUE)
    h.run_dir("20261006T070000Z")
    out = h.at("2026-11-03T12:47").run()
    c = out["updates"]["cadence"]
    assert c["last_run"] == "2026-10-06T07:00:00Z"
    assert (c["windows_missed"], c["periods_missed"]) == (4, 4)
    assert "cadence:overdue" in _ids(out)


def test_an_emptied_directory_newer_than_a_full_one_is_the_last_run(tmp_path):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE).ran("20260901T070000Z")
    h.run_dir("20261006T070000Z")
    out = h.at("2026-11-03T12:47").run()
    c = out["updates"]["cadence"]
    assert c["last_run_from"] == "/var/backups/patching-hosts-20261006T070000Z"
    assert (c["windows_missed"], c["first_missed"]) == (4, "2026-10-13T05:00:00Z")


# --- CR 1970: a stamp within the hour past the clock is now -------------------


def test_a_chain_firing_just_past_the_clock_is_taken_as_now(tmp_path):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE_PM).ran("20261006T150000Z")
    h.rebooted("20261103T203000Z", "2026-11-03T21:25:00Z")
    out = h.at("2026-11-03T21:05").run()
    c = out["updates"]["cadence"]
    assert c["last_run"] == "2026-11-03T21:05:00Z"
    assert c["last_run_from"] == "/var/backups/patching-hosts-20261103T203000Z"
    assert c["windows_missed"] == 0
    assert not [n for n in out["not_read"] if "patching-hosts-" in n]


def test_a_marker_just_past_the_clock_is_taken_as_now(tmp_path):
    h = ClockHost(tmp_path).knob(WEEKLY_TUE).ran("20261006T070000Z")
    h.marker("20261103T130700Z\n")
    out = h.at("2026-11-03T12:47").run()
    c = out["updates"]["cadence"]
    assert c["last_run"] == "2026-11-03T12:47:00Z"
    assert c["last_run_from"] == "/var/backups/patching-hosts-last-reading"
    assert c["windows_missed"] == 0
    assert not [n for n in out["not_read"] if "patching-hosts-" in n]


# --- CR 1971: a run's records are root's alone ---------------------------------


class RootRecordHost(ClockHost):
    """cat answers for a run's records as root would: on a host they're
    0600 in a 0700 directory. Its fallback is the system's cat, which the
    stubs' own case outputs reach too."""

    STUBBED = (*ClockHost.STUBBED, "cat")
    FALLBACKS = {
        **ClockHost.FALLBACKS,
        "cat": 'for d in /bin /usr/bin; do [ -x "$d/cat" ] && exec "$d/cat" "$@"; done; exit 127',
    }


@pytest.mark.parametrize(
    "name, text, last",
    [
        ("steps", "bulk\tok\t1793719800\t300\t2048\n", "2026-11-03T15:30:00Z"),
        (
            "reboot-chain.unit",
            "patching-hosts-reboot-x 2026-11-03T15:42:00Z\n",
            "2026-11-03T15:42:00Z",
        ),
    ],
    ids=["steps", "reboot-chain"],
)
def test_a_root_only_run_record_is_read_as_root(tmp_path, name, text, last):
    h = RootRecordHost(tmp_path).knob(WEEKLY_TUE_PM)
    rec = h.run_dir("20261103T140000Z") / name
    rec.write_text(text)
    rec.chmod(0o000)
    h.on("cat", f"-- */{name}", text)
    try:
        out = h.at("2026-11-03T21:05").run()
    finally:
        rec.chmod(0o600)
    assert out["updates"]["cadence"]["last_run"] == last
    assert out["updates"]["cadence"]["windows_missed"] == 0
    if os.geteuid() != 0:
        assert [c for c in h.calls("sudo") if c[1].endswith(f"/{name}")]


# --- CR 1979, 1980: what's left in an old directory never matters ------------


def test_an_old_cut_off_bulk_doesnt_stop_the_check(tmp_path):
    # run.md: a bulk killed after writing holds is retried in a new run
    # directory, so the old one stays, with no retention to sweep it.
    h = ClockHost(tmp_path).knob(WEEKLY_TUE_PM)
    d = h.run_dir("20260901T150000Z")
    (d / "holds").write_text("postgres postgresql-16\n")
    (d / "hold-versions").write_text("postgresql-16 16.10\n")
    h.ran("20261027T150000Z", bulk="2026-10-27T15:30")
    h.marker("20261027T200000Z\n")
    out = h.at("2026-11-03T21:05").run()
    c = out["updates"]["cadence"]
    assert c["last_run_from"] == "/var/backups/patching-hosts-last-reading"
    assert (c["windows_missed"], c["first_missed"]) == (1, "2026-11-03T15:00:00Z")
    assert "cadence:overdue" in _ids(out)


@pytest.mark.parametrize("left", ["journal", ".keep"])
def test_a_directory_its_retention_left_a_journal_or_a_keep_still_dates_the_run(
    tmp_path, left
):
    # Every rebooted run has journal/, which deleting the run's files leaves.
    h = ClockHost(tmp_path).knob(WEEKLY_TUE).ran("20260901T070000Z")
    d = h.run_dir("20261006T070000Z")
    if left == "journal":
        (d / "journal").mkdir()
    else:
        (d / ".keep").write_text("")
    out = h.at("2026-11-03T12:47").run()
    c = out["updates"]["cadence"]
    assert c["last_run"] == "2026-10-06T07:00:00Z"
    assert (c["windows_missed"], c["first_missed"]) == (4, "2026-10-13T05:00:00Z")


# --- CR 1973: periods, not windows --------------------------------------------


def test_daily_windows_miss_weeks_not_days(tmp_path):
    days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    h = ClockHost(tmp_path).knob(
        "posture scheduled\n" + "".join(f"window {d} 05:00-10:00\n" for d in days)
    )
    h.ran("20261006T070000Z")
    out = h.at("2026-11-03T12:47").run()
    c = out["updates"]["cadence"]
    assert (c["periods_missed"], c["windows_missed"]) == (4, 22)
    m = _finding(out, "cadence:overdue")["message"]
    assert "4 weeks" in m and "22 windows" in m


def test_a_missed_month_is_one_period(tmp_path):
    h = ClockHost(tmp_path).knob(
        "posture scheduled\ncadence monthly\nwindow Sun#2 08:00-12:00\n"
    )
    h.ran("20261011T090000Z")
    out = h.at("2026-11-08T13:00").run()
    assert out["updates"]["cadence"]["periods_missed"] == 1
    assert "1 month " in _finding(out, "cadence:overdue")["message"]


def test_a_monthly_period_is_a_month_not_a_week(tmp_path):
    # CR 1981: 18 Sundays close from 12 July, the first past 31 days, to 8
    # November; each month's first starts a period: 12 Jul, 9 Aug, 6 Sep,
    # 4 Oct, 1 Nov.
    h = ClockHost(tmp_path).knob(
        "posture scheduled\ncadence monthly\nwindow Sun 08:00-12:00\n"
    )
    h.ran("20260607T090000Z")
    c = h.at("2026-11-08T13:00").run()["updates"]["cadence"]
    assert (c["periods_missed"], c["windows_missed"]) == (5, 18)
