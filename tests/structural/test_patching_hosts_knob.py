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
- the example in knob.md parses clean, and every directive in its table parses.

Runs under whatever `bash` is on PATH, which is 3.2 on macOS: the library is
written for it. No API calls; each test writes its knob under tmp_path.
"""

import json
import os
import re
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
        "quiet 25:00-01:00",  # bad hour
        "class prod",
        "posture sometimes",
        "hold",  # no step (bash 3.2 must not index tok[-1])
        "hold postgres",  # a step and no glob
        "hold postgresql-* Postgres",  # step name case
        "datastore postgres pg@16-main",  # no database
        "datastore redis",
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
        {"engine": "redis", "unit": "redis-server.service", "databases": [], "line": 4},
    ]


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


# One valid line per directive. The test below holds this to knob.md's table,
# so a directive documented there and missing here (or the reverse) fails.
EVERY_DIRECTIVE = {
    "class": "class production",
    "posture": "posture scheduled",
    "window": "window Tue 15:00-21:00",
    "quiet": "quiet 07:25-08:15 Sun",
    "inflight": "inflight systemctl list-units 'app-task@*' --state=active --no-legend | wc -l",
    "restarter": "restarter app-healthcheck.timer",
    "service": "service app-web.service",
    "health": "health curl -sf http://localhost:8000/health",
    "datastore": "datastore postgres postgresql@16-main app",
    "backup": "backup app-backup.service",
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
        "health",
        "datastore",
        "backup",
        "caller",
        "owner",
        "origin",
        "exception",
    ):
        assert out[key], f"{key} parsed to nothing"
    assert out["records"]["value"] == "example-org/host-records"


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
