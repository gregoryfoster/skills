"""A ledger a hand-edit already damaged can be repaired (#319).

`--amend` stops new damage; this file pins `record-telemetry.sh --repair`,
which fixes what is already there. `delta_tokens` / `delta_days` are derived
from the previous row at append time, and a row rewritten by hand — this repo's
own ledger held two — keeps deltas describing a neighbour or a count that no
longer exists.

What this file pins:

- **It corrects exactly what `--print-trend` warns about** — through the same
  function, so after a repair the trend is quiet.
- **Nothing else**: no observed field, no null filled in, no other line
  touched; a second repair finds nothing.
- **A delta across a measurement-method change becomes null**, with
  `delta_unavailable`, as the append would have written it.
- **Stdout is one JSON line per correction, empty when clean**, so `--dry-run`
  is a read-only detector; a missing ledger is clean and is not created.
- **It accepts only `--ledger` and `--dry-run`.**

Keep this list current — it is the file's index.
"""

import json
import subprocess
from pathlib import Path

from .test_loss_warrants import _clean_env, _repo
from .test_telemetry_amend import BASELINE, LEDGER, RECORD, _record, _row, _rows, _seed


def _repair(repo: Path, *flags: str):
    return subprocess.run(
        ["bash", str(RECORD), "--repair", *flags],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=30,
    )


def _broken(tmp_path: Path) -> Path:
    """Both shapes: the issue's (append-then-delete, so both deltas describe a
    removed row) and this repo's own (tokens edited in place, delta left)."""
    repo = _repo(tmp_path, "# P\n")
    _seed(
        repo,
        BASELINE,
        _row("2000-01-02", 470, ["demote:X"], delta_tokens=20, delta_days=0),
        _row(
            "2000-01-04", 480, ["baseline:pre-curation"], delta_tokens=10, delta_days=2
        ),
        _row(
            "2000-01-04",
            440,
            ["prune:Y"],
            delta_tokens=-50,
            delta_days=0,
            note="row rewritten to what ships",
        ),
    )
    return repo


class TestRepair:
    def test_corrects_exactly_the_stale_fields(self, tmp_path: Path):
        repo = _broken(tmp_path)
        before = (repo / LEDGER).read_text().splitlines()
        r = _repair(repo)
        assert r.returncode == 0, r.stderr
        fixes = [json.loads(x) for x in r.stdout.splitlines()]
        assert {(f["line"], f["field"], f["was"], f["now"]) for f in fixes} == {
            (2, "delta_days", 0, 1),
            (2, "delta_tokens", 20, -30),
            (4, "delta_tokens", -50, -40),
        }
        rows = _rows(repo)
        after = (repo / LEDGER).read_text().splitlines()
        assert after[0] == before[0] and after[2] == before[2]
        # Observed fields are never the thing corrected.
        assert [x["tokens"] for x in rows] == [500, 470, 480, 440]
        assert rows[3]["note"] == "row rewritten to what ships"

    def test_the_trend_is_quiet_afterwards(self, tmp_path: Path):
        repo = _broken(tmp_path)
        assert "disagrees" in _record(repo, 440, "--dry-run", "--print-trend").stderr
        assert _repair(repo).returncode == 0
        r = _record(repo, 440, "--dry-run", "--print-trend")
        assert "disagrees" not in r.stderr, r.stderr

    def test_a_second_repair_finds_nothing(self, tmp_path: Path):
        repo = _broken(tmp_path)
        assert _repair(repo).returncode == 0
        text = (repo / LEDGER).read_text()
        r = _repair(repo)
        assert r.returncode == 0 and r.stdout == "", r.stdout
        assert (repo / LEDGER).read_text() == text

    def test_a_delta_across_a_method_change_becomes_null(self, tmp_path: Path):
        """The append never writes one; it writes null and says why."""
        repo = _repo(tmp_path, "# P\n")
        _seed(
            repo,
            BASELINE,
            _row(
                "2000-01-02",
                300,
                ["demote:X"],
                tokens_exact=False,
                delta_tokens=-200,
                delta_days=1,
            ),
        )
        assert _repair(repo).returncode == 0
        row = _rows(repo)[1]
        assert row["delta_tokens"] is None
        assert "method changed" in row["delta_unavailable"]

    def test_a_null_is_never_filled_in(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n")
        _seed(repo, BASELINE, _row("2000-01-05", 300, ["demote:X"]))
        text = (repo / LEDGER).read_text()
        r = _repair(repo)
        assert r.returncode == 0 and r.stdout == ""
        assert (repo / LEDGER).read_text() == text

    def test_dry_run_reports_and_writes_nothing(self, tmp_path: Path):
        repo = _broken(tmp_path)
        text = (repo / LEDGER).read_text()
        r = _repair(repo, "--dry-run")
        assert r.returncode == 0, r.stderr
        assert len(r.stdout.splitlines()) == 3
        assert (repo / LEDGER).read_text() == text

    def test_a_missing_ledger_is_clean_and_not_created(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n")
        r = _repair(repo)
        assert r.returncode == 0 and r.stdout == ""
        assert not (repo / LEDGER).exists()

    def test_refuses_any_flag_but_ledger_and_dry_run(self, tmp_path: Path):
        repo = _broken(tmp_path)
        for extra in (
            ["--actions", "x"],
            ["--amend"],
            ["--print-trend"],
            ["--repo-commit", "HEAD"],
        ):
            r = _repair(repo, *extra)
            assert r.returncode == 1, (extra, r.stderr)
