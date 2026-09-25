"""`--repo-commit` backfills every row a multi-file run appended (#324).

The backfill rewrote exactly one row, the newest in the whole ledger. A run
that records rows for two files — two `SKILL.md` surfaces, or a policy file and
a skill — appends both at one HEAD, so the other kept the parent hash: the #206
gap `--repo-commit` exists to close, left open with no warning.

What this file pins:

- **Every curation row sharing the newest row's stale commit is backfilled**,
  walking back from the newest, and each is named on stderr.
- **The walk stops at the first row with another commit**, so an earlier
  run's row is never rewritten.
- **A baseline row at the same HEAD is skipped, not rewritten** — exempt as
  before — and does not end the walk.
- **A null commit backfills the newest row alone**: it names no HEAD, so it
  cannot tell this run's rows from ones predating the field.
- **A row the default branch holds ends the walk** even at the same commit —
  rewritten, it is the line merge=union later keeps twice (CR 11) — and a walk
  past the newest row with no `origin/HEAD` to check against says so.
- **`--dry-run` previews every target** and writes nothing; **a re-run is a
  no-op**.
- **The prose names the multi-row rule** where the backfill is documented.

Keep this list current — it is the file's index.
"""

import json
import subprocess
from pathlib import Path

from .test_loss_warrants import _clean_env, _repo
from .test_telemetry_amend import (
    LEDGER,
    RECORD,
    TELEMETRY,
    _commit,
    _row,
    _rows,
    _seed,
    _with_origin,
)

STALE = "5ta1e00"
EARLIER = "ea41e00"


def _backfill(repo: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(RECORD), "--repo-commit", "HEAD", *flags],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=30,
    )


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        env=_clean_env(),
        check=True,
    ).stdout.strip()


def _two_file_run(tmp_path: Path) -> Path:
    """An earlier run's row, then this run's baseline and two curation rows,
    all three appended at one HEAD."""
    repo = _repo(tmp_path, "# P\n")
    _seed(
        repo,
        _row("2000-01-01", 500, ["demote:W"], repo_commit=EARLIER),
        _row("2000-01-05", 480, ["baseline:pre-curation"], repo_commit=STALE),
        _row("2000-01-05", 450, ["demote:X"], repo_commit=STALE),
        _row("2000-01-05", 90, ["demote:Z"], file="OTHER.md", repo_commit=STALE),
    )
    return repo


class TestEveryRowOfTheRunIsBackfilled:
    def test_both_curation_rows_name_the_shipping_commit(self, tmp_path: Path):
        repo = _two_file_run(tmp_path)
        r = _backfill(repo)
        assert r.returncode == 0, r.stderr
        head = _head(repo)
        rows = _rows(repo)
        assert [x["repo_commit"] for x in rows] == [EARLIER, STALE, head, head]

    def test_each_rewritten_row_is_named(self, tmp_path: Path):
        r = _backfill(_two_file_run(tmp_path))
        named = [ln for ln in r.stderr.splitlines() if ln.startswith("backfilled")]
        assert len(named) == 2, r.stderr
        assert "AGENTS.md" in named[0] and "OTHER.md" in named[1], r.stderr

    def test_an_earlier_runs_row_ends_the_walk(self, tmp_path: Path):
        """The row before this run's names an older HEAD, because every run
        commits its ledger — so it is history and stays as it is."""
        repo = _two_file_run(tmp_path)
        before = (repo / LEDGER).read_text().splitlines()[0]
        assert _backfill(repo).returncode == 0
        assert (repo / LEDGER).read_text().splitlines()[0] == before

    def test_a_baseline_at_the_same_head_is_skipped_not_a_stop(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n")
        _seed(
            repo,
            _row("2000-01-05", 450, ["demote:X"], repo_commit=STALE),
            _row("2000-01-05", 480, ["baseline:pre-curation"], repo_commit=STALE),
            _row("2000-01-05", 90, ["demote:Z"], file="OTHER.md", repo_commit=STALE),
        )
        assert _backfill(repo).returncode == 0
        head = _head(repo)
        assert [x["repo_commit"] for x in _rows(repo)] == [head, STALE, head]

    def test_a_null_commit_backfills_the_newest_row_alone(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n")
        _seed(
            repo,
            _row("2000-01-01", 500, ["demote:W"]),
            _row("2000-01-05", 450, ["demote:X"]),
        )
        assert _backfill(repo).returncode == 0
        assert [x.get("repo_commit") for x in _rows(repo)] == [None, _head(repo)]


class TestAHeldRowIsHistory:
    def test_a_row_the_default_branch_holds_ends_the_walk(self, tmp_path: Path):
        """A parallel branch cut from the same HEAD merged its row, never
        backfilled, so it shares this run's stale commit."""
        repo = _repo(tmp_path, "# P\n")
        merged = _row(
            "2000-01-05", 90, ["demote:Z"], file="OTHER.md", repo_commit=STALE
        )
        _seed(repo, merged)
        _commit(repo, "the other branch's curation")
        _with_origin(tmp_path, repo)
        _seed(repo, merged, _row("2000-01-06", 450, ["demote:X"], repo_commit=STALE))
        r = _backfill(repo)
        assert r.returncode == 0, r.stderr
        assert [x["repo_commit"] for x in _rows(repo)] == [STALE, _head(repo)]

    def test_a_walk_with_nothing_to_check_against_warns(self, tmp_path: Path):
        r = _backfill(_two_file_run(tmp_path))
        assert r.returncode == 0, r.stderr
        assert "no origin/HEAD" in r.stderr, r.stderr

    def test_a_single_row_backfill_stays_quiet(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n")
        _seed(repo, _row("2000-01-05", 450, ["demote:X"], repo_commit=STALE))
        r = _backfill(repo)
        assert r.returncode == 0, r.stderr
        assert "WARN" not in r.stderr, r.stderr


class TestPreviewAndRerun:
    def test_dry_run_prints_every_target_and_writes_nothing(self, tmp_path: Path):
        repo = _two_file_run(tmp_path)
        untouched = (repo / LEDGER).read_text()
        r = _backfill(repo, "--dry-run")
        assert r.returncode == 0, r.stderr
        preview = [json.loads(ln) for ln in r.stdout.splitlines()]
        assert [x["file"] for x in preview] == ["AGENTS.md", "OTHER.md"]
        assert {x["repo_commit"] for x in preview} == {_head(repo)}
        assert (repo / LEDGER).read_text() == untouched

    def test_a_rerun_is_a_no_op(self, tmp_path: Path):
        repo = _two_file_run(tmp_path)
        assert _backfill(repo).returncode == 0
        once = (repo / LEDGER).read_text()
        again = _backfill(repo)
        assert again.returncode == 0, again.stderr
        assert "nothing to backfill" in again.stderr
        assert (repo / LEDGER).read_text() == once


def test_the_prose_names_the_multi_row_rule():
    text = TELEMETRY.read_text()
    assert "#324" in text
    assert "shares its commit" in text
