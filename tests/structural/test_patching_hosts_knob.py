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
- an exception expires the day after its review-by date; a `disabled:` or
  `removed:` stage's expiry is `soak-ended`, every other one's
  `expired-exception` (#636);
- `cadence weekly|monthly` is one value, weekly by default (#529);
- `bulk-factor <n>` is one value, 3 by default: a number from 1 to 99.99 with
  at most two decimals, and anything else is malformed (#556);
- a window may name a week of the month (`Sun#2`) or a date, with a reason; a
  dated line is never replaced by a more specific scope's windows, and one
  whose close has passed is a finding, not a reason to go report-only (#421);
- a dated line's reason cut by a `#` that starts a word is a finding,
  `window-reason-cut`; `# text` and `<repo>#N` aren't (#656);
- the example in knob.md parses clean, and every directive in its table parses;
- the example's inflight line counts a running oneshot, which is activating
  (#359);
- the reader calls the library outside any condition, so errexit stays on
  inside it, and it needs no tool beyond bash to order the sections;
- the library ignores its caller's IFS, leaves the caller's own `--help` alone,
  and refuses a date or a host it can't use;
- a backup line names the datastore units it covers, and one naming none is
  malformed (CR 194);
- nothing the reader prints carries an unescaped control character;
- `rebuild-*` lines describe how a host is rebuilt onto a new VM, and how a
  dependent steps around it, each step with its undo; a secret is a path the
  reader never opens; a knob without them prints `rebuild: null` (#673);
- a `standing` line pre-approves one lane within its limits until its
  review-by date, and is per lane; past the date it's `expired-standing`
  and isn't honoured (#673).

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
        # #529: one of weekly or monthly.
        "cadence",
        "cadence daily",
        "cadence weekly monthly",
        # #556: a number from 1 to 99.99, at most two decimals.
        "bulk-factor",
        "bulk-factor 0",
        "bulk-factor 0.9",  # below the dry run itself
        "bulk-factor 0.35",  # 3.5 mistyped
        "bulk-factor -3",
        "bulk-factor 3x",
        "bulk-factor 3.",
        "bulk-factor .5",
        "bulk-factor 3.555",  # a third decimal
        "bulk-factor 100",
        "bulk-factor 03",
        "bulk-factor 1e1",
        "bulk-factor 3,5",
        "bulk-factor 3 4",
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
    # CR 2524: since CR 2519 a live broader glob can still cover what an
    # expired line did, so the message claims no more than the line itself.
    [f] = after["findings"]
    assert "no longer covers" in f["message"]
    assert "unless another line covers it" in f["message"]
    # An expired exception is a deviation to report, not a reason to distrust
    # the knob.
    assert after["report_only"] is False


@pytest.mark.parametrize(
    "what, kind",
    [
        ("disabled:nginx", "soak-ended"),
        ("removed:nginx", "soak-ended"),
        ("disabled:fwupd", "soak-ended"),
        ("purged:nginx", "expired-exception"),
        ("keep:nginx", "expired-exception"),
    ],
    ids=["disabled", "removed", "disabled-apt-package", "purged", "keep"],
)
def test_a_prune_stage_past_its_date_is_a_soak_ending_not_a_lapse(tmp_path, what, kind):
    # #636: a disable or remove stage's review-by date is its soak, so its
    # passing is the prompt for the next stage, a kind of its own that a repo's
    # knob test can allow. A purge has no next stage, so its date is a recheck
    # and stays expired-exception, as does every other exception.
    text = f"posture scheduled\nexception {what} 2026-09-30 soaking\n"
    on_the_day = _read(tmp_path, text, today="2026-09-30")
    assert on_the_day["exception"][0]["expired"] is False
    assert on_the_day["findings"] == []
    after = _read(tmp_path, text, today="2026-10-01")
    assert after["exception"][0]["expired"] is True
    assert _kinds(after) == [kind]
    [f] = after["findings"]
    assert f["line"] == 2
    assert what in f["message"] and "2026-09-30" in f["message"]
    if kind == "soak-ended":
        assert "soak ended" in f["message"]
        # fwupd is an apt package the probe doesn't read, so its stage is
        # planned as apt:fwupd and nothing else prompts it (pruning.md).
        component = what.split(":", 1)[1]
        if component == "fwupd":
            component = "apt:fwupd"
        assert f"prune-plan.sh --component {component} " in f["message"]
        assert ("probe reports" in f["message"]) is (component == "nginx")
    assert after["report_only"] is False


def test_a_soak_ending_names_each_component_the_probe_reads():
    # The library's list of the six is the prune library's (#636): a seventh
    # added there alone would be told the probe doesn't read it.
    prune_lib = (SKILL / "scripts" / "_prune-lib.sh").read_text()
    knob_lib = (SKILL / "scripts" / "_knob-lib.sh").read_text()
    six = re.search(r'^PRUNE_COMPONENTS="([^"]+)"', prune_lib, re.M).group(1).split()
    case = re.search(r"^\s*([a-z|\s]+)\)\s*# the six \(#636\)", knob_lib, re.M)
    assert case, "the soak-ended case on the six is gone from _knob-lib.sh"
    assert sorted(w.strip() for w in case.group(1).split("|")) == sorted(six)


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
    assert (w["weekday"], w["week"], w["date"], w["reason"]) == (
        "Tue",
        None,
        None,
        None,
    )
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


@pytest.mark.parametrize(
    "tail, reason",
    [
        # co-processor 2026-11-10 (#620) and co-index 2026-11-03 (#569): an
        # issue named as #N right after the range opened a comment, and the
        # reason read null with nothing to say so (#656).
        ("#113-out-of-window", None),
        ("#31, a bulletin's kernel", None),
        # The same cut part-way through: the rest of the reason is lost.
        ("out of window, per #113", "out of window, per"),
    ],
)
def test_a_dated_windows_reason_cut_by_a_hash_is_a_finding(tmp_path, tail, reason):
    out = _read(tmp_path, f"posture scheduled\nwindow 2026-11-10 14:10-18:10 {tail}\n")
    assert out["window"][0]["reason"] == reason
    assert _kinds(out) == ["window-reason-cut"]
    f = out["findings"][0]
    assert f["line"] == 2
    assert "window 2026-11-10 14:10-18:10" in f["message"]
    assert "<repo>#N" in f["message"]
    # The comment isn't echoed, as no line's text is.
    assert "113" not in f["message"] and "31," not in f["message"]
    # The run's record is short, not the knob untrustworthy.
    assert out["report_only"] is False


@pytest.mark.parametrize(
    "line",
    [
        # A comment written as one: '#' and a space.
        "window 2026-11-10 14:10-18:10 # the owner's one-off\n",
        "window 2026-11-10 14:10-18:10 TS-2026-013 # kernel fix\n",
        # A doubled '#' is a comment written as one too (CR 2517).
        "window 2026-11-10 14:10-18:10 TS-2026-013 ## the owner's note\n",
        "window 2026-11-10 14:10-18:10 ##one-off\n",
        # <repo>#N holds its '#' inside a word, so nothing is cut.
        "window 2026-11-10 14:10-18:10 app#113-out-of-window\n",
        # A weekday line takes no reason, so a comment there loses nothing.
        "window Mon 14:10-18:10 #113\n",
    ],
)
def test_a_dated_windows_comment_or_repo_ref_is_no_finding(tmp_path, line):
    out = _read(tmp_path, f"posture scheduled\n{line}", today="2026-11-10")
    assert out["findings"] == []


def test_a_cut_reason_is_reported_only_for_a_host_its_window_applies_to(tmp_path):
    # CR 2518: as past-window, so a repo whose knob test reads every host
    # goes red only for the host the line is for.
    text = (
        "posture scheduled\n[host co-worker-*]\n"
        "window 2026-11-10 14:10-18:10 #113-out-of-window\n"
    )
    assert _kinds(_read(tmp_path, text, host="co-worker-1")) == ["window-reason-cut"]
    assert _read(tmp_path, text, host="web-1")["findings"] == []


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


# --- #529: the host's cadence -------------------------------------------------------


def test_cadence_defaults_to_weekly(tmp_path):
    out = _read(tmp_path, "posture scheduled\n")
    assert out["cadence"] == {"value": "weekly", "line": None}
    assert _read(tmp_path, "")["cadence"] == {"value": "weekly", "line": None}


def test_a_cadence_line_is_one_value_the_most_specific_scope_sets(tmp_path):
    text = "posture scheduled\ncadence monthly\n[host web-*]\ncadence weekly\n"
    assert _read(tmp_path, text, host="db-1")["cadence"] == {
        "value": "monthly",
        "line": 2,
    }
    assert _read(tmp_path, text, host="web-1")["cadence"] == {
        "value": "weekly",
        "line": 4,
    }


def test_a_cadence_set_twice_at_one_precedence_is_a_repeat(tmp_path):
    out = _read(tmp_path, "posture scheduled\ncadence weekly\ncadence monthly\n")
    assert out["cadence"] == {"value": "monthly", "line": 3}
    assert _kinds(out) == ["repeated"]
    # No overdue-run check in v1: a cadence is read and printed, never a
    # reason to go report-only.
    assert out["report_only"] is False


# --- #556: the bulk's factor -------------------------------------------------------


def test_bulk_factor_defaults_to_3(tmp_path):
    out = _read(tmp_path, "posture scheduled\n")
    assert out["bulk_factor"] == {"value": 3, "line": None}
    r = _run("--config", str(tmp_path / "absent"), "--host", "h", "--today", TODAY)
    assert json.loads(r.stdout)["bulk_factor"] == {"value": 3, "line": None}


@pytest.mark.parametrize("value", ["1", "4", "3.5", "2.25", "99.99", "10"])
def test_a_bulk_factor_line_is_a_number_from_1_to_99_99(tmp_path, value):
    out = _read(tmp_path, f"posture scheduled\nbulk-factor {value}\n")
    assert out["bulk_factor"] == {"value": float(value), "line": 2}
    assert out["findings"] == []
    assert out["report_only"] is False


def test_a_bad_bulk_factor_and_knob_md_name_the_range_the_parser_takes(tmp_path):
    # CR 1944: the parser takes 99.99, so "1 to 99" understated the range.
    [f] = _read(tmp_path, "posture scheduled\nbulk-factor 100\n")["findings"]
    assert "from 1 to 99.99" in f["message"], f
    table = KNOB_MD.read_text().split("## Directives", 1)[1]
    [row] = [r for r in table.splitlines() if r.startswith("| `bulk-factor")]
    assert "from 1 to 99.99" in row


def test_a_bulk_factor_line_is_one_value_the_most_specific_scope_sets(tmp_path):
    text = "posture scheduled\nbulk-factor 3.5\n[host web-*]\nbulk-factor 4\n"
    assert _read(tmp_path, text, host="db-1")["bulk_factor"] == {
        "value": 3.5,
        "line": 2,
    }
    assert _read(tmp_path, text, host="web-1")["bulk_factor"] == {
        "value": 4,
        "line": 4,
    }


def test_a_bulk_factor_set_twice_at_one_precedence_is_a_repeat(tmp_path):
    out = _read(tmp_path, "posture scheduled\nbulk-factor 4\nbulk-factor 3.5\n")
    assert out["bulk_factor"] == {"value": 3.5, "line": 3}
    assert _kinds(out) == ["repeated"]


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
    "cadence": "cadence monthly",
    "bulk-factor": "bulk-factor 4",
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
    # #673: one row in knob.md documents the whole rebuild-* family.
    "rebuild-image": "rebuild-image example-org/base-image\n"
    "rebuild-install bash scripts/install.sh\n"
    "rebuild-restore bash scripts/restore.sh --latest\n"
    "rebuild-check curl -sf http://localhost:8000/health\n"
    "rebuild-secret /etc/app/secret.env\n"
    "rebuild-step app-db stop-ingest systemctl stop app-ingest.timer\n"
    "rebuild-undo app-db stop-ingest systemctl start app-ingest.timer",
    "standing": "standing security no-reboot no-datastore 2026-12-31 security fixes between runs",
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
        "standing",
    ):
        assert out[key], f"{key} parsed to nothing"
    assert out["rebuild"]["image"]["value"] == "example-org/base-image"
    assert out["records"]["value"] == "example-org/host-records"
    assert out["bulk_factor"]["value"] == 4


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
    # #421 appends week, date, reason and expired after the line, so the
    # first five fields read as they always did.
    assert r.stdout.splitlines() == ["scheduled 1 1", "Tue|15:00|21:00|0|2||||0"]


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


# --- rebuild-* (#673 item 3) ---------------------------------------------------

REBUILD = (
    "posture scheduled\n"
    "rebuild-image example-org/base-image\n"
    "rebuild-install bash scripts/install.sh --host-env prod # from the checkout\n"
    "rebuild-restore bash scripts/restore.sh --latest\n"
    "rebuild-check curl -sf http://localhost:8000/health\n"
    "rebuild-check bash scripts/go-no-go.sh\n"
    "rebuild-secret /etc/app/secret.env\n"
    "rebuild-secret /etc/app/gcs-key.json\n"
)


def test_a_rebuild_section_reads_as_one_object_with_its_lines(tmp_path):
    out = _read(tmp_path, REBUILD)
    assert out["findings"] == []
    assert out["report_only"] is False
    assert out["rebuild"] == {
        "image": {"value": "example-org/base-image", "line": 2},
        "install": {"value": "bash scripts/install.sh --host-env prod", "line": 3},
        "restore": {"value": "bash scripts/restore.sh --latest", "line": 4},
        "check": [
            {"command": "curl -sf http://localhost:8000/health", "line": 5},
            {"command": "bash scripts/go-no-go.sh", "line": 6},
        ],
        "secret": [
            {"path": "/etc/app/secret.env", "line": 7},
            {"path": "/etc/app/gcs-key.json", "line": 8},
        ],
        "step": [],
    }


def test_a_knob_without_rebuild_or_standing_lines_reads_as_it_did(tmp_path):
    # Additive: every knob that read clean still does, with rebuild null and
    # standing empty, and nothing else changed.
    out = _read(tmp_path, "posture scheduled\nwindow Tue 15:00-21:00\n")
    assert out["findings"] == []
    assert out["rebuild"] is None
    assert out["standing"] == []


def test_a_rebuild_secret_is_a_path_the_reader_never_opens(tmp_path):
    # A FIFO blocks whoever opens it: a reader that read the secret would
    # hang here. One that doesn't exist is no finding either: the reader
    # checks the path's form, never the file.
    fifo = tmp_path / "secret.fifo"
    os.mkfifo(fifo)
    text = REBUILD + f"rebuild-secret {fifo}\nrebuild-secret /nonexistent/key\n"
    knob = tmp_path / "patching-hosts"
    knob.write_text(text)
    r = subprocess.run(
        [
            "bash",
            str(READ_KNOB),
            "--config",
            str(knob),
            "--host",
            "web-1",
            "--today",
            TODAY,
        ],
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["findings"] == []
    assert [s["path"] for s in out["rebuild"]["secret"]][-2:] == [
        str(fifo),
        "/nonexistent/key",
    ]


def test_a_relative_rebuild_secret_is_a_finding_not_report_only(tmp_path):
    out = _read(tmp_path, REBUILD + "rebuild-secret etc/app/secret.env\n")
    assert _kinds(out) == ["rebuild-secret-path"]
    [f] = out["findings"]
    assert f["line"] == 9
    assert "absolute" in f["message"]
    # A rebuild line never stops a patch run.
    assert out["report_only"] is False


def test_a_rebuild_section_missing_a_part_is_incomplete(tmp_path):
    text = "posture scheduled\nrebuild-image example-org/base-image\nrebuild-secret /etc/a\n"
    out = _read(tmp_path, text)
    assert _kinds(out) == ["rebuild-incomplete"]
    [f] = out["findings"]
    assert "rebuild-install" in f["message"]
    assert "rebuild-restore" in f["message"]
    assert "rebuild-check" in f["message"]
    assert out["report_only"] is False


def test_a_dependents_steps_pair_with_their_undo_by_host_and_name(tmp_path):
    # The dependent's own knob declares what it runs when app-db moves: its
    # steps alone are no rebuild section of its own, so nothing is incomplete.
    text = (
        "posture scheduled\n"
        "rebuild-step app-db stop-ingest systemctl stop app-ingest.timer\n"
        "rebuild-undo app-db stop-ingest systemctl start app-ingest.timer\n"
        "rebuild-step app-db repoint sed -i s/old/new/ /etc/app/db.env\n"
        "rebuild-undo app-cache flush systemctl restart app-cache\n"
    )
    out = _read(tmp_path, text)
    assert out["rebuild"]["image"] == {"value": None, "line": None}
    assert out["rebuild"]["step"] == [
        {
            "host": "app-db",
            "name": "stop-ingest",
            "run": "systemctl stop app-ingest.timer",
            "line": 2,
            "undo": "systemctl start app-ingest.timer",
            "undo_line": 3,
        },
        {
            "host": "app-db",
            "name": "repoint",
            "run": "sed -i s/old/new/ /etc/app/db.env",
            "line": 4,
            "undo": None,
            "undo_line": None,
        },
    ]
    assert sorted(_kinds(out)) == ["rebuild-no-step", "rebuild-no-undo"]
    by_kind = {f["kind"]: f for f in out["findings"]}
    assert by_kind["rebuild-no-undo"]["line"] == 4
    assert "app-db repoint" in by_kind["rebuild-no-undo"]["message"]
    assert by_kind["rebuild-no-step"]["line"] == 5
    assert out["report_only"] is False


def test_rebuild_lines_are_scoped_by_section(tmp_path):
    text = "posture scheduled\n[host co-db]\n" + REBUILD.split("\n", 1)[1]
    assert _read(tmp_path, text, host="web-1")["rebuild"] is None
    out = _read(tmp_path, text, host="co-db")
    assert out["rebuild"]["image"]["value"] == "example-org/base-image"
    assert out["findings"] == []
    # A more specific section replaces a one-value line and a list.
    text = (
        REBUILD + "[host web-1]\nrebuild-image example-org/other\nrebuild-check true\n"
    )
    out = _read(tmp_path, text)
    assert out["rebuild"]["image"] == {"value": "example-org/other", "line": 10}
    assert out["rebuild"]["check"] == [{"command": "true", "line": 11}]


@pytest.mark.parametrize(
    "line",
    [
        "rebuild-image",
        "rebuild-image two words",
        "rebuild-install",
        "rebuild-restore",
        "rebuild-check",
        "rebuild-secret",
        "rebuild-secret /a /b",
        "rebuild-step app-db",
        "rebuild-step app-db stop",
        "rebuild-step app/db stop true",
        "rebuild-step app-db Stop_It true",
        "rebuild-undo app-db stop",
    ],
)
def test_a_rebuild_line_that_doesnt_parse_is_malformed(tmp_path, line):
    out = _read(tmp_path, f"posture scheduled\n{line}\n")
    assert _kinds(out) == ["malformed"]
    assert out["findings"][0]["line"] == 2
    assert out["report_only"] is True


@pytest.mark.parametrize(
    "line, fault",
    [
        ("rebuild-step db-* stop systemctl stop x", "one host's name"),
        ("rebuild-undo app/db stop systemctl start x", "one host's name"),
        ("rebuild-step app-db Stop_It true", "lowercase letters"),
        ("rebuild-step app-db", "<host> <name> <command>"),
    ],
)
def test_a_malformed_rebuild_step_names_its_fault(tmp_path, line, fault):
    # CR 2540: a host glob was blamed on the step's name.
    out = _read(tmp_path, f"posture scheduled\n{line}\n")
    [f] = out["findings"]
    assert f["kind"] == "malformed"
    assert fault in f["message"], f["message"]
    if fault == "one host's name":
        assert "lowercase" not in f["message"]


# --- standing (#673 item 4) ----------------------------------------------------


def test_a_standing_line_reads_its_lane_limits_and_review_by(tmp_path):
    text = (
        "posture scheduled\n"
        "origin tailscale follow\n"
        "standing security no-reboot no-datastore 2026-12-31 between attended runs\n"
        "standing origin:tailscale no-held 2026-12-31 the client and daemon\n"
        "standing maintenance 2026-12-31 everything the run takes\n"
    )
    out = _read(tmp_path, text)
    assert out["findings"] == []
    assert out["standing"] == [
        {
            "lane": "security",
            "no_reboot": True,
            "no_datastore": True,
            "no_held": False,
            "review_by": "2026-12-31",
            "reason": "between attended runs",
            "expired": False,
            "line": 3,
        },
        {
            "lane": "origin:tailscale",
            "no_reboot": False,
            "no_datastore": False,
            "no_held": True,
            "review_by": "2026-12-31",
            "reason": "the client and daemon",
            "expired": False,
            "line": 4,
        },
        {
            "lane": "maintenance",
            "no_reboot": False,
            "no_datastore": False,
            "no_held": False,
            "review_by": "2026-12-31",
            "reason": "everything the run takes",
            "expired": False,
            "line": 5,
        },
    ]


def test_a_standing_line_expires_the_day_after_its_review_by_date(tmp_path):
    text = "posture scheduled\nstanding security no-reboot 2026-09-30 between runs\n"
    assert _read(tmp_path, text, today="2026-09-30")["findings"] == []
    out = _read(tmp_path, text, today="2026-10-01")
    assert out["standing"][0]["expired"] is True
    assert _kinds(out) == ["expired-standing"]
    [f] = out["findings"]
    assert f["line"] == 2
    assert "security" in f["message"] and "2026-09-30" in f["message"]
    assert out["report_only"] is False


def test_a_standing_line_is_keyed_by_lane_and_scoped_by_section(tmp_path):
    text = (
        "posture scheduled\n"
        "standing security 2026-12-31 every host\n"
        "[host web-*]\n"
        "standing security no-reboot 2026-12-31 the web hosts never reboot unattended\n"
        "[host db-*]\n"
        "standing maintenance 2026-12-31 not for web\n"
    )
    out = _read(tmp_path, text, host="web-1")
    assert [(s["lane"], s["no_reboot"], s["line"]) for s in out["standing"]] == [
        ("security", True, 4)
    ]
    out = _read(tmp_path, text, host="db-1")
    assert [(s["lane"], s["line"]) for s in out["standing"]] == [
        ("security", 2),
        ("maintenance", 6),
    ]


def test_a_standing_origin_the_knob_doesnt_follow_is_a_finding(tmp_path):
    # apply.sh refuses --lane origin:<origin> for one the knob doesn't
    # follow, so such a line could never approve anything.
    text = (
        "posture scheduled\n"
        "origin nodesource pin 22.11.0-1nodesource1\n"
        "standing origin:nodesource 2026-12-31 node\n"
        "standing origin:docker 2026-12-31 docker\n"
    )
    out = _read(tmp_path, text)
    assert _kinds(out) == ["standing-origin", "standing-origin"]
    assert [f["line"] for f in out["findings"]] == [3, 4]
    assert out["report_only"] is False


@pytest.mark.parametrize(
    "line",
    [
        "standing",
        "standing security",
        "standing security 2026-12-31",
        "standing nightly 2026-12-31 a lane apply.sh has no name for",
        "standing origin: 2026-12-31 no origin",
        "standing security no-restart 2026-12-31 an unknown limit",
        "standing security no-reboot 2026-13-01 a date that isn't one",
        "standing security no-reboot no-reboot-please 2026-12-31 typo",
        # CR 2534: a limit after the date would read as reason, so the line
        # would approve more than the owner wrote.
        "standing security 2026-12-01 no-reboot no-held nightly fixes",
        "standing maintenance no-held 2026-12-31 then no-datastore too",
    ],
)
def test_a_standing_line_that_doesnt_parse_is_malformed(tmp_path, line):
    out = _read(tmp_path, f"posture scheduled\n{line}\n")
    assert _kinds(out) == ["malformed"]
    assert out["report_only"] is True


def test_knob_standing_and_rebuild_records_keep_their_documented_fields(tmp_path):
    # The scripts read these records (the --standing gate, an executor's
    # rebuild): the field order documented at knob_reset is the contract.
    knob = (
        "posture scheduled\n"
        "standing security no-reboot no-held 2026-12-31 two words\n"
        + REBUILD.split("\n", 1)[1]
        + "rebuild-step app-db stop systemctl stop x\n"
        "rebuild-undo app-db stop systemctl start x\n"
    )
    after = (
        'printf "S %s\\n" "${KNOB_STANDING[0]//$KNOB_US/|}"\n'
        'printf "I %s %s\\n" "$KNOB_REBUILD_IMAGE" "$KNOB_REBUILD_IMAGE_LINE"\n'
        'printf "C %s\\n" "${KNOB_REBUILD_CHECK[0]//$KNOB_US/|}"\n'
        'printf "X %s\\n" "${KNOB_REBUILD_SECRET[1]//$KNOB_US/|}"\n'
        'printf "P %s\\n" "${KNOB_REBUILD_STEP[0]//$KNOB_US/|}"\n'
        'printf "A %s\\n" "$KNOB_REBUILD"\n'
    )
    r = _source(tmp_path, knob, "", after)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "S security|1|0|1|2026-12-31|two words|0|2",
        "I example-org/base-image 3",
        "C curl -sf http://localhost:8000/health|6",
        "X /etc/app/gcs-key.json|9",
        "P app-db|stop|systemctl stop x|10|systemctl start x|11",
        "A 1",
    ]
