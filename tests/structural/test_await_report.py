"""#479 — await-report.sh, the orchestrator's wait for a cloud worker's report.

A cloud session can't message the local orchestrator, so the orchestrator
polls the tracking issue's comments for the worker's hidden report marker.
What this file pins is what makes that wait trustworthy rather than merely
convenient:

- only the expected author's marker counts, since a public issue takes
  anyone's comment, and only this session's;
- every status ends the wait, so a blocked worker wakes the orchestrator as
  surely as a finished one;
- silence ends it too, rather than running forever;
- gh failing is retried, then reported with gh's own stderr, and is never
  read as "no report yet" indefinitely.

A fake `gh` on PATH serves the comments and the branch SHA, and applies the
script's real `--jq` filter with jq, so the filter is under test too.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT / "skills" / "orchestrating-issue-backlog" / "scripts" / "await-report.sh"
)
SESSION = "cse_016cbbv9tDawyfSFk6xgv8NJ"
URL = "https://github.com/o/r/issues/1#issuecomment-"

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None, reason="the fake gh applies --jq with jq"
)

FAKE_GH = r"""#!/usr/bin/env bash
set -euo pipefail
path=$2 filter=""
if [ "${3:-}" = --jq ]; then filter=$4; fi
echo "$path" >>"$FAKE_DIR/calls"
case $path in
  */comments*)
    if [ -f "$FAKE_DIR/fail" ]; then echo "HTTP 502: Bad Gateway (fake)" >&2; exit 1; fi
    jq -r "$filter" "$FAKE_DIR/comments.json" ;;
  */branches/*)
    # Each call takes the next line; an empty line or none is a 404.
    sha=$(head -n 1 "$FAKE_DIR/shas" 2>/dev/null || true)
    if [ -f "$FAKE_DIR/shas" ]; then sed -i.bak 1d "$FAKE_DIR/shas"; fi
    if [ -z "$sha" ]; then echo "HTTP 404: Not Found" >&2; exit 1; fi
    echo "$sha" ;;
esac
"""


def _marker(status: str, session: str = SESSION, sha: str = "611a2477") -> str:
    return (
        f"<!-- worker-report session={session} branch=pilot/x sha={sha} "
        f"status={status} -->\n## Cloud pilot worker\n..."
    )


def _comment(n: int, login: str, body: str) -> dict:
    return {"user": {"login": login}, "body": body, "html_url": f"{URL}{n}"}


@pytest.fixture
def fake(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    (tmp_path / "comments.json").write_text("[]")
    return tmp_path


def _run(
    fake: Path, *extra: str, comments: list | None = None
) -> subprocess.CompletedProcess:
    if comments is not None:
        (fake / "comments.json").write_text(json.dumps(comments))
    env = {
        **os.environ,
        "PATH": f"{fake / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
    }
    args = ["--repo", "o/r", "--issue", "1", "--session", SESSION, "--author", "me"]
    return subprocess.run(
        ["bash", str(SCRIPT), *args, "--interval", "0", *extra],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


@pytest.mark.parametrize("status", ["done", "blocked", "question"])
def test_every_status_ends_the_wait(fake, status):
    r = _run(fake, comments=[_comment(7, "me", _marker(status))])
    assert r.returncode == 0, r.stderr
    assert r.stdout == f"report\t{status}\t{URL}7\t611a2477\n"


def test_another_authors_marker_is_ignored(fake):
    # The repo is public: anyone can post a marker, and only the worker's counts.
    r = _run(
        fake, "--silence", "0", comments=[_comment(7, "stranger", _marker("done"))]
    )
    assert r.returncode == 3, r.stderr
    assert r.stdout.startswith("silent\t")


def test_another_sessions_marker_is_ignored(fake):
    other = _marker("done", session="cse_SOMEONEELSE")
    prefix = _marker("done", session=SESSION + "X")
    r = _run(
        fake,
        "--silence",
        "0",
        comments=[_comment(7, "me", other), _comment(8, "me", prefix)],
    )
    assert r.returncode == 3, r.stderr


def test_the_first_matching_report_wins_over_later_ones(fake):
    r = _run(
        fake,
        comments=[
            _comment(7, "stranger", _marker("done")),
            _comment(8, "me", _marker("blocked", sha="aaaa")),
            _comment(9, "me", _marker("done", sha="bbbb")),
        ],
    )
    assert r.stdout == f"report\tblocked\t{URL}8\taaaa\n"


def test_a_comment_without_a_marker_is_not_a_report(fake):
    r = _run(
        fake,
        "--silence",
        "0",
        comments=[_comment(7, "me", "## Cloud pilot worker\nstatus=done")],
    )
    assert r.returncode == 3


def test_a_push_counts_as_activity_and_is_printed_with_progress(fake):
    # Not pushed at the start (404), then one push; with --silence 0 the wait
    # ends right after it, carrying the SHA it last saw.
    (fake / "shas").write_text("\nabc123\n")
    r = _run(fake, "--branch", "pilot/x", "--progress", "--silence", "0")
    assert r.returncode == 3, r.stderr
    assert r.stdout == "push\tabc123\nsilent\t\t\tabc123\n"


def test_gh_failing_is_retried_then_reported_with_its_own_stderr(fake):
    (fake / "fail").write_text("")
    r = _run(fake, "--silence", "999")
    assert r.returncode == 2
    assert r.stdout == ""
    assert "gh failed on 5 polls in a row" in r.stderr
    assert "HTTP 502: Bad Gateway (fake)" in r.stderr
    polls = [c for c in (fake / "calls").read_text().splitlines() if "/comments" in c]
    assert len(polls) == 5


def test_since_is_passed_through(fake):
    r = _run(
        fake,
        "--since",
        "2026-10-25T00:00:00Z",
        comments=[_comment(7, "me", _marker("done"))],
    )
    assert r.returncode == 0
    assert (
        "comments?since=2026-10-25T00:00:00Z&per_page=100"
        in (fake / "calls").read_text()
    )


@pytest.mark.parametrize(
    "args",
    [
        ["--issue", "1", "--session", SESSION, "--author", "me"],
        ["--repo", "o/r", "--issue", "x", "--session", SESSION, "--author", "me"],
        [
            "--repo",
            "o/r",
            "--issue",
            "1",
            "--session",
            "cse_1; rm -rf /",
            "--author",
            "me",
        ],
        [
            "--repo",
            "o/r",
            "--issue",
            "1",
            "--session",
            SESSION,
            "--author",
            "me",
            "--bogus",
        ],
    ],
    ids=["missing-repo", "non-numeric-issue", "session-not-an-id", "unknown-flag"],
)
def test_a_bad_argument_is_exit_2(args):
    r = subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=30
    )
    assert r.returncode == 2
    assert r.stdout == ""
