"""patching-hosts' knob reader: `read-knob.sh` over `_knob-lib.sh` (#313, plan step 2).

The knob tells the skill what only a host's owner knows: its class, posture,
window, quiet ranges, and the commands and units a run must respect. A reader
that silently drops a line lets an apply run into a quiet range, or leaves a
database out of the recovery point, so every line either parses or becomes a
finding, and a malformed line makes the host report-only.

What this file pins, against references/knob.md:

- comments: `#` opens one only at a line's start or after whitespace;
- a malformed line, an unknown directive and a control character are findings,
  by line number, and never echo the line;
- sections layer global, then globs from least to most specific, then an exact
  name; equally specific globs tie, and neither applies;
- scalars take the most specific value, lists are replaced whole, keyed
  directives accumulate per key;
- an exception expires the day after its review-by date;
- a window may name a week of the month (`Sun#2`) or a date, with a reason; a
  dated line is never replaced by a more specific scope's windows, and one
  whose close has passed is a finding, not a reason to go report-only (#421);
- the example in knob.md parses clean, and every directive in its table parses;
- the example's inflight line counts a running oneshot, which is activating
  (#359);
- the reader calls the library outside any condition, so errexit stays on
  inside it, and it needs no tool beyond bash to order the sections;
- the library ignores its caller's IFS, leaves the caller's own `--help` alone,
  and refuses a date or a host it can't use;
- a backup line names the datastore units it covers, and one naming none is
  malformed (CR 194);
- nothing the reader prints carries an unescaped control character.

Runs under whatever `bash` is on PATH, which is 3.2 on macOS: the library is
written for it. No API calls; each test writes its knob under tmp_path.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL = REPO_ROOT / "skills" / "patching-hosts"
READ_KNOB = SKILL / "scripts" / "read-knob.sh"
KNOB_MD = SKILL / "references" / "knob.md"
TODAY = "2026-09-30"


def _clean_env() -> dict:
    """No inherited GIT_* vars (docs/STYLE.md: a fixture repo must not write to
    this one), and a predictable locale."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["LC_ALL"] = "C"
    return env


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(READ_KNOB), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=_clean_env(),
    )


def _read(tmp_path: Path, text: str, host: str = "web-1", today: str = TODAY) -> dict:
    knob = tmp_path / "patching-hosts"
    knob.write_bytes(text.encode())
    r = _run("--config", str(knob), "--host", host, "--today", today)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _kinds(out: dict) -> list[str]:
    return [f["kind"] for f in out["findings"]]


# --- absence and defaults -----------------------------------------------------


def test_no_knob_is_production_automatic_and_report_only(tmp_path):
    r = _run("--config", str(tmp_path / "absent"), "--host", "h", "--today", TODAY)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["knob"]["present"] is False
    assert out["class"] == {"value": "production", "line": None}
    assert out["posture"] == {"value": "automatic", "line": None}
    assert out["report_only"] is True
    assert any("no knob" in why for why in out["report_only_reasons"])
    assert [h["step"] for h in out["hold"]] == ["postgres", "redis", "docker"]
    assert out["findings"] == []


def test_no_posture_line_is_report_only(tmp_path):
    out = _read(tmp_path, "class production\n")
    assert out["posture"]["value"] == "automatic"
    assert out["report_only"] is True
    assert any("no posture line" in why for why in out["report_only_reasons"])


def test_an_ephemeral_host_is_report_only(tmp_path):
    out = _read(tmp_path, "class ephemeral\nposture scheduled\n")
    assert out["report_only"] is True
    assert any("ephemeral" in why for why in out["report_only_reasons"])


# --- comments and lines -------------------------------------------------------


def test_a_hash_opens_a_comment_only_at_line_start_or_after_whitespace(tmp_path):
    out = _read(
        tmp_path,
        "# a comment line\n"
        "posture scheduled   # after spaces\n"
        "class production\t# after a tab\n"
        "health curl -sf http://localhost/health#frag\n",
    )
    assert out["findings"] == []
    assert out["posture"]["value"] == "scheduled"
    assert out["class"]["value"] == "production"
    assert out["health"] == [
        {"command": "curl -sf http://localhost/health#frag", "line": 4}
    ]


def test_a_command_round_trips_through_json_exactly(tmp_path):
    cmd = "sh -c 'echo \"quoted\" back\\slash' | awk '{print $1}'\tx"
    out = _read(tmp_path, f"posture scheduled\ninflight {cmd}\n")
    assert out["inflight"] == [{"command": cmd, "line": 2}]


def test_crlf_line_endings_parse(tmp_path):
    out = _read(tmp_path, "posture scheduled\r\nwindow Tue 15:00-21:00\r\n")
    assert out["findings"] == []
    assert out["window"][0]["end"] == "21:00"


def test_a_last_line_without_a_newline_is_read(tmp_path):
    out = _read(tmp_path, "posture scheduled")
    assert out["posture"] == {"value": "scheduled", "line": 1}


# --- findings -----------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "window Tue",  # missing range
        "window Tuesday 15:00-21:00",  # weekday spelling
        "window Tue 15:00-15:00",  # zero-length: empty or a whole day
        # #421: a week of the month is 1 to 5, and only a dated line takes a
        # reason; a date must be one on the calendar.
        "window Sun#0 17:00-19:00",
        "window Sun#6 17:00-19:00",
        "window Sun# 17:00-19:00",
        "window Sunday#2 17:00-19:00",
        "window Sun#2 17:00-19:00 the second Sunday",
        "window Tue 15:00-21:00 a reason on a weekday line",
        "window 2026-02-29 13:55-15:55",  # 2026 isn't a leap year
        "window 2026-04-31 13:55-15:55",
        "window 2026-10-23",  # no range
        "window 2026-10-23 13:55-13:55 TS-2026-013",
        "window 26-10-23 13:55-15:55",
        "quiet 25:00-01:00",  # bad hour
        "class prod",
        "posture sometimes",
        "hold",  # no step (bash 3.2 must not index tok[-1])
        "hold postgres",  # a step and no glob
        "hold postgresql-* Postgres",  # step name case
        "datastore postgres pg@16-main",  # no database
        "datastore redis",
        "depends redis-server",  # #384: no unit it needs
        "depends redis-server tailscaled extra",
        "quiet *:00-*:00",  # an hour's range ending where it starts
        "quiet *:60-*:07",
        "quiet *:00-07:00",  # the hour on one end only
        "datastore redis redis-server ops",  # #379: a user and no key file
        "datastore redis redis-server ops etc/ops.key",  # relative
        "datastore redis redis-server 'ops' /etc/ops.key",  # user's quoting
        "datastore redis redis-server ops /etc/ops.key extra",
        "datastore qdrant qdrant.service qdrant https://q:6333",  # no key file
        "datastore qdrant qdrant.service qdrant q:6333 -",  # no scheme
        "datastore qdrant qdrant.service qdrant https://q:6333 key",  # relative
        "datastore qdrant qdrant.service -bad https://q:6333 -",  # container
        # CR 217: a key goes over plain http only to this host.
        "datastore qdrant qdrant.service qdrant http://index.example:6333 /etc/q.key",
        # CR 225: a name that starts 127. isn't this host.
        "datastore qdrant qdrant.service qdrant http://127.example.net:6333 /etc/q.key",
        "owner /usr/local/bin/* someone",
        "image-owner not-a-repo",
        "caller notarepo",
        "origin tailscale pin",
        "exception keep:x 2026-13-01 bad month",
        "exception keep:x 2026-12-31",  # no reason
        "restarter a.timer b.timer",
        "records",
        "frobnicate on",
    ],
)
def test_a_malformed_line_is_a_finding_and_makes_the_host_report_only(tmp_path, line):
    out = _read(tmp_path, f"posture scheduled\n{line}\n")
    malformed = [f for f in out["findings"] if f["kind"] == "malformed"]
    assert [f["line"] for f in malformed] == [2], out["findings"]
    assert out["report_only"] is True
    assert any("malformed" in why for why in out["report_only_reasons"])


def test_a_malformed_line_is_never_echoed(tmp_path):
    secret = "tskey-auth-kSECRETSECRET"
    knob = tmp_path / "patching-hosts"
    knob.write_text(f"posture scheduled\nclass {secret}\nhealth x\x07{secret}\n")
    r = _run("--config", str(knob), "--host", "h", "--today", TODAY)
    assert r.returncode == 0, r.stderr
    assert secret not in r.stdout and secret not in r.stderr
    out = json.loads(r.stdout)
    assert [f["line"] for f in out["findings"]] == [2, 3]


def test_a_malformed_section_header_drops_the_lines_under_it(tmp_path):
    out = _read(
        tmp_path,
        "posture scheduled\n[hostweb-*]\nclass ephemeral\n",
        host="web-1",
    )
    assert out["class"]["value"] == "production"
    assert [f["line"] for f in out["findings"]] == [2, 3]


def test_an_exception_expires_the_day_after_its_review_by_date(tmp_path):
    text = "posture scheduled\nexception keep:nginx 2026-09-30 kept until the image drops it\n"
    on_the_day = _read(tmp_path, text, today="2026-09-30")
    assert on_the_day["exception"][0]["expired"] is False
    assert on_the_day["findings"] == []
    after = _read(tmp_path, text, today="2026-10-01")
    assert after["exception"][0]["expired"] is True
    assert _kinds(after) == ["expired-exception"]
    # An expired exception is a deviation to report, not a reason to distrust
    # the knob.
    assert after["report_only"] is False


def test_a_repeat_at_the_same_precedence_is_a_finding_and_the_later_line_wins(tmp_path):
    out = _read(tmp_path, "posture automatic\nposture scheduled\n")
    assert out["posture"] == {"value": "scheduled", "line": 2}
    assert _kinds(out) == ["repeated"]
    assert out["findings"][0]["line"] == 1


def test_a_duplicate_section_header_is_merged_and_reported(tmp_path):
    out = _read(
        tmp_path,
        "posture scheduled\n[host web-1]\nclass staging\n[host web-1]\nrecords ops/records\n",
    )
    assert out["class"]["value"] == "staging"
    assert out["records"]["value"] == "ops/records"
    assert _kinds(out) == ["duplicate-section"]


# --- sections -----------------------------------------------------------------

LAYERED = """\
posture scheduled
class production
window Tue 15:00-21:00
quiet 07:25-08:15
exception keep:nginx 2026-12-31 global

[host co-*]
window Wed 01:00-02:00
exception keep:docker 2026-12-31 from co-*

[host co-worker-*]
class ephemeral
exception keep:nginx 2026-11-30 narrower

[host co-worker-7]
class staging
"""


def test_globs_layer_from_least_to_most_specific_and_an_exact_name_wins(tmp_path):
    out = _read(tmp_path, LAYERED, host="co-worker-7")
    assert out["sections"] == ["co-*", "co-worker-*", "co-worker-7"]
    assert out["class"] == {"value": "staging", "line": 16}
    # A list is replaced whole by the most specific scope that declares it.
    assert [w["weekday"] for w in out["window"]] == ["Wed"]
    # A list no section declares stays global.
    assert [q["start"] for q in out["quiet"]] == ["07:25"]
    # Keyed entries accumulate; the most specific wins per key.
    by_what = {e["what"]: e["reason"] for e in out["exception"]}
    assert by_what == {"keep:nginx": "narrower", "keep:docker": "from co-*"}
    assert out["findings"] == []


def test_a_host_matching_no_section_gets_the_global_lines(tmp_path):
    out = _read(tmp_path, LAYERED, host="standalone")
    assert out["sections"] == []
    assert out["class"]["value"] == "production"
    assert [w["weekday"] for w in out["window"]] == ["Tue"]
    assert out["report_only"] is False


def test_a_sectioned_file_with_no_global_posture_leaves_an_unmatched_host_report_only(
    tmp_path,
):
    out = _read(tmp_path, "[host co-*]\nposture scheduled\n", host="standalone")
    assert out["posture"] == {"value": "automatic", "line": None}
    assert out["report_only"] is True


def test_equally_specific_globs_tie_and_neither_applies(tmp_path):
    out = _read(
        tmp_path,
        "posture scheduled\nclass production\n[host co-*]\nclass staging\n[host *-db]\nclass dev\n",
        host="co-db",
    )
    assert out["class"]["value"] == "production"
    assert out["sections"] == []
    assert _kinds(out) == ["ambiguous-sections"]
    assert out["report_only"] is True
    assert any("equally specific" in why for why in out["report_only_reasons"])
    message = out["findings"][0]["message"]
    assert "[host co-*]" in message and "[host *-db]" in message


# --- keyed directives -----------------------------------------------------------


def test_a_hold_line_replaces_its_default_step_and_the_others_stay(tmp_path):
    out = _read(
        tmp_path, "posture scheduled\nhold postgresql-16 postgres\nhold tailscale ts\n"
    )
    # A list, not a dict: a default left beside its replacement would collapse
    # into one key and pass.
    assert out["hold"] == [
        {"step": "redis", "globs": ["redis-server", "redis-tools"], "line": None},
        {"step": "docker", "globs": ["docker.io", "containerd"], "line": None},
        {"step": "postgres", "globs": ["postgresql-16"], "line": 2},
        {"step": "ts", "globs": ["tailscale"], "line": 3},
    ]


def test_datastore_lines_naming_one_cluster_add_up(tmp_path):
    out = _read(
        tmp_path,
        "posture scheduled\n"
        "datastore postgres pg@16-main app\n"
        "datastore postgres pg@16-main audit reports\n"
        "datastore redis redis-server.service\n",
    )
    assert out["datastore"] == [
        {
            "engine": "postgres",
            "unit": "pg@16-main",
            "databases": ["app", "audit", "reports"],
            "line": 2,
        },
        {
            "engine": "redis",
            "unit": "redis-server.service",
            "databases": [],
            "user": None,
            "key_file": None,
            "line": 4,
        },
    ]


def test_a_redis_datastore_may_name_the_user_it_logs_in_as(tmp_path):
    # #379: broker's Redis runs an aclfile with default off, so a command
    # that needs a login needs a user, and a key file only root reads.
    out = _read(
        tmp_path,
        "posture scheduled\n"
        "datastore redis redis-server ops /etc/credstore.encrypted/redis-ops\n",
    )
    assert out["datastore"] == [
        {
            "engine": "redis",
            "unit": "redis-server",
            "databases": [],
            "user": "ops",
            "key_file": "/etc/credstore.encrypted/redis-ops",
            "line": 2,
        }
    ]
    assert out["findings"] == []


def test_a_qdrant_datastore_names_its_container_url_and_key_file(tmp_path):
    # #367: co-index's Qdrant runs as docker run --rm under a systemd unit.
    out = _read(
        tmp_path,
        "posture scheduled\n"
        "datastore qdrant qdrant.service qdrant https://index.example.ts.net:6333"
        " /etc/socraticode/qdrant.key\n"
        "datastore qdrant search.service search http://127.0.0.1:6333 -\n",
    )
    assert out["findings"] == []
    assert out["datastore"] == [
        {
            "engine": "qdrant",
            "unit": "qdrant.service",
            "databases": [],
            "container": "qdrant",
            "url": "https://index.example.ts.net:6333",
            "key_file": "/etc/socraticode/qdrant.key",
            "line": 2,
        },
        {
            "engine": "qdrant",
            "unit": "search.service",
            "databases": [],
            "container": "search",
            "url": "http://127.0.0.1:6333",
            "key_file": None,
            "line": 3,
        },
    ]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:6333",
        "http://127.0.1.1:6333",
        "http://localhost:6333",
        "http://[::1]:6333",
    ],
)
def test_a_qdrant_key_may_go_over_plain_http_on_this_host(tmp_path, url):
    out = _read(
        tmp_path,
        f"posture scheduled\ndatastore qdrant qdrant.service qdrant {url} /etc/q.key\n",
    )
    assert out["findings"] == []
    assert out["datastore"][0]["url"] == url


def test_a_qdrant_urls_trailing_slash_is_dropped(tmp_path):
    # CR 220: the scripts append /collections and /snapshots to it.
    out = _read(
        tmp_path,
        "posture scheduled\ndatastore qdrant qdrant.service qdrant https://q:6333/ -\n",
    )
    assert out["datastore"][0]["url"] == "https://q:6333"


def test_a_wrapping_range_is_marked(tmp_path):
    out = _read(
        tmp_path, "posture scheduled\nwindow Tue 14:15-07:25\nquiet 23:30-00:30 Sun\n"
    )
    assert out["window"][0]["wraps"] is True
    assert out["quiet"][0] == {
        "weekday": "Sun",
        "start": "23:30",
        "end": "00:30",
        "wraps": True,
        "line": 3,
    }


# --- #421: a week of the month, and a dated window -------------------------------


def test_a_week_of_the_month_is_read_beside_its_weekday(tmp_path):
    out = _read(tmp_path, "posture scheduled\nwindow Sun#2 17:00-19:00\n")
    assert out["findings"] == []
    assert out["window"] == [
        {
            "weekday": "Sun",
            "week": 2,
            "date": None,
            "start": "17:00",
            "end": "19:00",
            "wraps": False,
            "reason": None,
            "expired": False,
            "line": 2,
        }
    ]


def test_a_weekday_line_carries_no_week_date_or_reason(tmp_path):
    out = _read(tmp_path, "posture scheduled\nwindow Tue 15:00-21:00\n")
    [w] = out["window"]
    assert (w["weekday"], w["week"], w["date"], w["reason"]) == ("Tue", None, None, None)
    assert w["expired"] is False


def test_a_dated_window_names_its_date_its_weekday_and_its_reason(tmp_path):
    out = _read(
        tmp_path,
        "posture scheduled\nwindow 2026-10-23 13:55-15:55 TS-2026-013 kernel fix\n",
    )
    assert out["findings"] == []
    # The weekday is the one its date falls on, so a reader that only knows
    # weekday still reads a string; date says it opens once.
    assert out["window"] == [
        {
            "weekday": "Fri",
            "week": None,
            "date": "2026-10-23",
            "start": "13:55",
            "end": "15:55",
            "wraps": False,
            "reason": "TS-2026-013 kernel fix",
            "expired": False,
            "line": 2,
        }
    ]


def test_a_dated_windows_reason_is_optional(tmp_path):
    out = _read(tmp_path, "posture scheduled\nwindow 2028-02-29 13:55-15:55\n")
    assert out["findings"] == []
    [w] = out["window"]
    assert (w["date"], w["weekday"], w["reason"]) == ("2028-02-29", "Tue", None)


def test_a_past_dated_window_is_a_finding_but_not_report_only(tmp_path):
    text = "posture scheduled\nwindow Tue 15:00-21:00\nwindow 2026-09-29 13:55-15:55 TS-1\n"
    on_the_day = _read(tmp_path, text, today="2026-09-29")
    assert on_the_day["findings"] == []
    assert on_the_day["window"][1]["expired"] is False
    after = _read(tmp_path, text, today="2026-09-30")
    assert _kinds(after) == ["past-window"]
    assert after["findings"][0]["line"] == 3
    assert "2026-09-29" in after["findings"][0]["message"]
    assert after["window"][1]["expired"] is True
    # A deviation to clean up, not a reason to distrust the knob.
    assert after["report_only"] is False
    assert after["report_only_reasons"] == []


def test_a_dated_window_that_wraps_has_passed_only_once_its_close_has(tmp_path):
    text = "posture scheduled\nwindow 2026-09-29 23:00-02:00\n"
    assert _read(tmp_path, text, today="2026-09-30")["findings"] == []
    assert _kinds(_read(tmp_path, text, today="2026-10-01")) == ["past-window"]


def _window_lines(out: dict) -> list[int]:
    return [w["line"] for w in out["window"]]


def test_a_global_dated_window_adds_to_a_sections_weekday_windows(tmp_path):
    out = _read(
        tmp_path,
        "posture scheduled\n"
        "window Tue 15:00-21:00\n"
        "window 2026-10-23 13:55-15:55 TS-2026-013\n"
        "[host web-*]\n"
        "window Wed 01:00-02:00\n",
        today="2026-10-01",
    )
    # The section's weekday line replaces the global weekday line, and the
    # dated line is kept beside it.
    assert _window_lines(out) == [3, 5]
    assert out["findings"] == []


def test_a_sections_dated_window_adds_to_the_global_weekday_windows(tmp_path):
    out = _read(
        tmp_path,
        "posture scheduled\n"
        "window Tue 15:00-21:00\n"
        "[host web-*]\n"
        "window 2026-10-23 13:55-15:55 TS-2026-013\n",
        today="2026-10-01",
    )
    # A dated line alone in a section declares no list to replace the global
    # one with: the host keeps Tuesday and gains the 23rd.
    assert _window_lines(out) == [2, 4]


def test_dated_windows_accumulate_across_scopes_and_skip_an_unmatched_section(tmp_path):
    out = _read(
        tmp_path,
        "posture scheduled\n"
        "window 2026-10-23 13:55-15:55 global\n"
        "[host web-*]\n"
        "window Sun#2 17:00-19:00\n"
        "window 2026-10-24 13:55-15:55 glob\n"
        "[host web-1]\n"
        "window Mon 01:00-02:00\n"
        "window 2026-10-25 13:55-15:55 exact\n"
        "[host db-*]\n"
        "window 2026-10-26 13:55-15:55 another host's\n",
        today="2026-10-01",
    )
    # The exact section's weekday line replaces the glob's Sun#2; every dated
    # line that applies to the host stays.
    assert _window_lines(out) == [2, 5, 7, 8]
    assert [w["reason"] for w in out["window"] if w["date"]] == [
        "global",
        "glob",
        "exact",
    ]


# --- the doc and the parser agree ------------------------------------------------


def _knob_md_example() -> str:
    body = KNOB_MD.read_text()
    section = body[body.index("## An example") :]
    return re.search(r"```\n(.*?)```", section, re.S).group(1)


def test_the_example_in_knob_md_parses_clean(tmp_path):
    out = _read(tmp_path, _knob_md_example(), today="2026-09-30")
    assert out["findings"] == []
    assert out["report_only"] is False
    assert out["posture"]["value"] == "scheduled"
    assert out["image_owner"]["value"] == "example-org/base-image"
    assert out["datastore"][0]["databases"] == ["app"]


def test_the_examples_inflight_counts_a_running_oneshot():
    # #359: a Type=oneshot unit is activating while it runs, so a copy of
    # --state=active printed 0 mid-ingest and let the gate pass.
    [line] = [x for x in _knob_md_example().splitlines() if x.startswith("inflight ")]
    assert "--state=activating,active,deactivating" in line


# One valid line per directive. The test below holds this to knob.md's table,
# so a directive documented there and missing here (or the reverse) fails.
EVERY_DIRECTIVE = {
    "class": "class production",
    "posture": "posture scheduled",
    "window": "window Tue 15:00-21:00",
    "quiet": "quiet 07:25-08:15 Sun",
    "inflight": "inflight systemctl list-units 'app-task@*' --state=activating,active,deactivating --no-legend | wc -l",
    "restarter": "restarter app-healthcheck.timer",
    "service": "service app-web.service",
    "depends": "depends postgresql@16-main tailscaled.service",
    "health": "health curl -sf http://localhost:8000/health",
    "recovery": "recovery /usr/local/bin/app-recovery-check",
    "datastore": "datastore postgres postgresql@16-main app",
    "backup": "backup app-backup.service postgresql@16-main",
    "hold": "hold postgresql-* libpq5 postgres",
    "caller": "caller example-org/caller",
    "owner": "owner /usr/local/bin/* image",
    "image-owner": "image-owner example-org/base-image",
    "origin": "origin tailscale follow",
    "exception": "exception keep:nginx 2026-12-31 ships with the image",
    "records": "records example-org/host-records",
}


def test_every_directive_in_knob_md_is_one_the_parser_reads(tmp_path):
    table = KNOB_MD.read_text().split("## Directives", 1)[1].split("\n## ", 1)[0]
    documented = set(re.findall(r"^\| `([a-z-]+)", table, re.M))
    assert documented == set(EVERY_DIRECTIVE), (
        f"knob.md's table documents {sorted(documented)}; "
        f"this test covers {sorted(EVERY_DIRECTIVE)}"
    )
    out = _read(tmp_path, "\n".join(EVERY_DIRECTIVE.values()) + "\n")
    assert out["findings"] == [], out["findings"]
    for key in (
        "window",
        "quiet",
        "inflight",
        "restarter",
        "service",
        "depends",
        "health",
        "recovery",
        "datastore",
        "backup",
        "caller",
        "owner",
        "origin",
        "exception",
    ):
        assert out[key], f"{key} parsed to nothing"
    assert out["records"]["value"] == "example-org/host-records"


def test_a_recovery_line_is_a_command_list_apart_from_health(tmp_path):
    # #423: a check with side effects, run only around data-store steps and
    # after a boot, never at every probe as a health line is.
    out = _read(
        tmp_path,
        "posture scheduled\nhealth curl -sf http://localhost/health\n"
        "recovery curl -sf -X POST http://localhost/v2/validate | grep -q hit\n"
        "[host web-*]\nrecovery /usr/local/bin/check-rows\nrecovery\n",
    )
    assert out["recovery"] == [{"command": "/usr/local/bin/check-rows", "line": 5}]
    assert out["health"] == [{"command": "curl -sf http://localhost/health", "line": 2}]
    [f] = out["findings"]
    assert (f["line"], f["kind"]) == (6, "malformed")
    assert "recovery takes a command" in f["message"]


def test_an_hourly_quiet_range_is_one_for_every_hour(tmp_path):
    # #384: broker's hourly backup took 24 quiet lines.
    out = _read(tmp_path, "posture scheduled\nquiet *:55-*:07 Mon\nquiet *:00-*:07\n")
    late = [q for q in out["quiet"] if q["line"] == 2]
    assert len(late) == 24
    assert late[0] == {
        "weekday": "Mon",
        "start": "00:55",
        "end": "01:07",
        "wraps": False,
        "line": 2,
    }
    # 23:55 runs past midnight.
    assert late[-1] == {
        "weekday": "Mon",
        "start": "23:55",
        "end": "00:07",
        "wraps": True,
        "line": 2,
    }
    every = [(q["start"], q["end"]) for q in out["quiet"] if q["line"] == 3]
    assert every == [(f"{h:02d}:00", f"{h:02d}:07") for h in range(24)]
    assert out["findings"] == []


def test_a_depends_line_names_a_datastore_and_the_unit_it_needs(tmp_path):
    out = _read(
        tmp_path,
        "posture scheduled\ndatastore redis redis-server\ndepends redis-server tailscaled\n",
    )
    assert out["depends"] == [
        {"datastore": "redis-server", "unit": "tailscaled", "line": 3}
    ]


def test_a_backup_line_names_the_datastores_it_covers(tmp_path):
    # CR 194: a backup line with no datastore would stand in for them all.
    out = _read(
        tmp_path,
        "posture scheduled\n"
        "datastore postgres postgresql@16-main app\n"
        "datastore redis redis-server\n"
        "backup app-backup.timer postgresql@16-main redis-server\n",
    )
    assert out["backup"] == [
        {
            "unit": "app-backup.timer",
            "datastores": ["postgresql@16-main", "redis-server"],
            "line": 4,
        }
    ]
    # #480: a Postgres unit's databases it takes, after a colon.
    out = _read(
        tmp_path,
        "posture scheduled\n"
        "datastore postgres postgresql@16-main app app_test\n"
        "backup app-backup.timer postgresql@16-main:app\n",
    )
    assert out["report_only"] is False
    assert out["backup"][0]["datastores"] == ["postgresql@16-main:app"]
    out = _read(tmp_path, "posture scheduled\nbackup app-backup.timer\n")
    assert out["report_only"] is True
    assert any(
        f["line"] == 2 and "backup takes <unit> and each datastore unit" in f["message"]
        for f in out["findings"]
    ), out["findings"]


@pytest.mark.parametrize(
    "token", ["postgresql@16-main:", "postgresql@16-main:app,,b", ":app", "pg:a:b"]
)
def test_a_backup_lines_database_list_that_doesnt_parse_is_malformed(tmp_path, token):
    out = _read(tmp_path, f"posture scheduled\nbackup app-backup.timer {token}\n")
    assert out["report_only"] is True
    assert any(
        f["line"] == 2 and "<datastore unit>:<database>,..." in f["message"]
        for f in out["findings"]
    ), out["findings"]


# --- invocation -------------------------------------------------------------------


def test_help_and_argument_errors():
    assert _run("--help").returncode == 0
    assert _run("--bogus").returncode == 2
    assert _run("--today", "30/09/2026", "--config", "/nonexistent").returncode == 2
    assert _run("--config").returncode == 2


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 file")
def test_an_unreadable_knob_exits_2(tmp_path):
    knob = tmp_path / "patching-hosts"
    knob.write_text("posture scheduled\n")
    knob.chmod(0)
    try:
        r = _run("--config", str(knob), "--host", "h", "--today", TODAY)
    finally:
        knob.chmod(0o600)
    assert r.returncode == 2
    assert r.stdout == ""


def test_the_default_config_is_the_knob_at_the_repo_root(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".skills").mkdir(parents=True)
    (repo / "sub").mkdir()
    (repo / ".skills" / "patching-hosts").write_text("posture scheduled\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=_clean_env())
    r = _run("--host", "h", "--today", TODAY, cwd=repo / "sub")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["knob"]["present"] is True
    assert out["posture"]["value"] == "scheduled"


def test_a_symlinked_reader_finds_its_library(tmp_path):
    link = tmp_path / "read-knob.sh"
    link.symlink_to(READ_KNOB)
    r = subprocess.run(
        [
            "bash",
            str(link),
            "--config",
            str(tmp_path / "absent"),
            "--host",
            "h",
            "--today",
            TODAY,
        ],
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["knob"]["present"] is False


def test_the_reader_calls_the_library_outside_any_condition():
    """Inside `if`, `&&` or `||`, bash turns errexit off for the whole call,
    so a failure in the library would print a partial answer with exit 0."""
    calls = [
        line.strip()
        for line in READ_KNOB.read_text().splitlines()
        if "knob_load " in line and not line.lstrip().startswith("#")
    ]
    assert calls == ['knob_load "$config" "$host" "$today"'], calls


def test_the_applied_sections_need_no_tool_beyond_bash(tmp_path):
    """The reader runs on the host being patched. With no `sort` on PATH, the
    sections still layer and are still listed, rather than reading as none."""
    tools = tmp_path / "bin"
    tools.mkdir()
    for tool in ("dirname", "readlink"):
        (tools / tool).symlink_to(shutil.which(tool))
    knob = tmp_path / "patching-hosts"
    knob.write_text(LAYERED)
    env = _clean_env()
    env["PATH"] = str(tools)
    r = subprocess.run(
        [shutil.which("bash"), str(READ_KNOB), "--config", str(knob)]
        + ["--host", "co-worker-7", "--today", TODAY],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["sections"] == ["co-*", "co-worker-*", "co-worker-7"]


def _source(tmp_path: Path, knob_text: str, before: str, after: str, *args: str):
    """Runs a caller that sources the library the way the probe will:
    `before` runs ahead of knob_load, `after` reads its results."""
    knob = tmp_path / "patching-hosts"
    knob.write_text(knob_text)
    caller = tmp_path / "caller.sh"
    lib = READ_KNOB.parent / "_knob-lib.sh"
    caller.write_text(
        f'set -euo pipefail\n{before}. "{lib}"\n'
        f'knob_load "{knob}" web-1 {TODAY}\n{after}'
    )
    return subprocess.run(
        ["bash", str(caller), *args], capture_output=True, text=True, env=_clean_env()
    )


def test_the_library_ignores_a_callers_strict_ifs(tmp_path):
    knob = (
        "posture scheduled\n"
        "hold postgresql-16 libpq5 postgres\n"
        "exception keep:x 2026-12-31 two words\n"
    )
    after = (
        'for r in "${KNOB_HOLD[@]}" "${KNOB_EXCEPTION[@]}"; do\n'
        '  printf "%s\\n" "${r//$KNOB_US/|}"\n'
        "done\n"
        'printf "findings=%s\\n" "${#KNOB_FINDING[@]}"\n'
    )
    r = _source(tmp_path, knob, "IFS=$'\\n\\t'\n", after)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert "postgres|postgresql-16 libpq5|2" in lines, lines
    assert "keep:x|2026-12-31|two words|0|3" in lines, lines
    assert "findings=0" in lines, lines


def test_a_caller_keeps_its_own_help_and_reads_the_knob_variables(tmp_path):
    """Sourced, the library must not answer the caller's `--help`: $0 and $1
    are the caller's then. And knob_load leaves its results in KNOB_*."""
    after = (
        'printf "%s %s %s\\n" "$KNOB_POSTURE" "$KNOB_POSTURE_LINE" "$KNOB_PRESENT"\n'
        'printf "%s\\n" "${KNOB_WINDOW[0]//$KNOB_US/|}"\n'
    )
    knob = "posture scheduled\nwindow Tue 15:00-21:00\n"
    r = _source(tmp_path, knob, "", after, "--help")
    assert r.returncode == 0, r.stderr
    assert "This file is a library" not in r.stdout
    assert r.stdout.splitlines() == ["scheduled 1 1", "Tue|15:00|21:00|0|2"]


def test_knob_load_refuses_a_date_or_host_it_cant_use(tmp_path):
    """An empty date sorts before every review-by date, so no exception would
    ever expire; a host holding a newline would break the JSON."""
    knob = tmp_path / "patching-hosts"
    knob.write_text("posture scheduled\nexception keep:x 2026-01-01 old\n")
    lib = READ_KNOB.parent / "_knob-lib.sh"
    caller = (
        f'set -euo pipefail\n. "{lib}"\nknob_load "{knob}" "$1" "$2"\necho loaded\n'
    )
    bad = [("web-1", ""), ("web-1", "30/09/2026"), ("", TODAY), ("a\nb", TODAY)]
    for host, today in bad:
        r = subprocess.run(
            ["bash", "-c", caller, "caller", host, today],
            capture_output=True,
            text=True,
            env=_clean_env(),
        )
        assert r.returncode == 2, (host, today, r.stdout, r.stderr)
        assert "loaded" not in r.stdout
    r = _run("--config", str(knob), "--host", "a\nb", "--today", TODAY)
    assert r.returncode == 2
    assert r.stdout == ""


def test_a_config_path_with_a_control_character_is_refused(tmp_path):
    r = _run("--config", str(tmp_path / "a\nb"), "--host", "h", "--today", TODAY)
    assert r.returncode == 2
    assert r.stdout == ""
