"""Phase 7's "rewrite this run's row" is a command, not a hand-edit (#319).

Phase 7 says that when a late fix moves the count, the author rewrites this
run's row to match what ships. `record-telemetry.sh` had one in-place mode,
`--repo-commit`, which rewrites that single field — so the instruction could
only be carried out by editing the JSONL by hand. `delta_days` and
`delta_tokens` are DERIVED at append time from whatever the previous row is
then, and the natural hand-edit order (append the corrected row, delete the
superseded one) leaves them describing a neighbour that no longer exists. The
row the issue found was dated a day after its predecessor and carried
`delta_days: 0`; this repo's own ledger held two rows whose `delta_tokens` no
longer matched their token change.

What this file pins:

- **`--amend` computes the deltas against the rows that remain**, which is
  the hand-edit trap closed by construction.
- **It replaces, never adds**: one row replaced, other lines (malformed ones
  included) untouched — and the replacement moves last, where the
  `--repo-commit` backfill that follows it looks (CR 1).
- **The run's attributes carry forward by group**, and supplying any flag in a
  group replaces the whole group — so no amend assembles a row no single
  invocation could have written.
- **It refuses** a baseline target, a file with no row, an empty or missing
  ledger (without creating one), and `--baseline` / `--repo-commit` beside it.
- **The method-change refusal still applies** — an amend is not a way round it.
- **A merged row is history**: `--amend` refuses a row `origin/HEAD` already
  holds, backfilled or not, and allows one only this branch carries — asking
  whether the ROW merged, because `repo_commit` names an already-merged parent
  until the backfill. With no `origin/HEAD` it warns and proceeds.
- **`--print-trend` names a row whose deltas disagree with the ledger**, so
  the damage a past hand-edit already did is visible.
- **`--repair` corrects exactly what that warning names** — through the same
  function, so after a repair the trend is quiet — and nothing else: no
  observed field, no null filled in, no other line touched. Its stdout is one
  JSON line per correction, empty when clean, so `--dry-run` is a detector; a
  missing ledger is clean, and it accepts only `--ledger` and `--dry-run`.
- **The prose names the command** where Phase 7 gives the instruction.

Keep this list current — it is the file's index.
"""

import json
import subprocess
from pathlib import Path

from .test_loss_warrants import _clean_env, _git, _repo

SKILL_DIR = (
    Path(__file__).resolve().parent.parent.parent / "skills" / "curating-context"
)
RECORD = SKILL_DIR / "scripts" / "record-telemetry.sh"
SKILL_MD = SKILL_DIR / "SKILL.md"
TELEMETRY = SKILL_DIR / "references" / "telemetry.md"
LEDGER = ".skills/context-metrics.jsonl"


def _payload(tokens: int, *, exact: bool = True, path: str = "AGENTS.md") -> str:
    return json.dumps(
        {
            "policy": {
                "path": path,
                "lines": 10,
                "bytes": 100,
                "tokens": tokens,
                "tokens_exact": exact,
                "bytes_per_token": 2.5,
                "budget": 6000,
                "over_budget": False,
            },
            "totals": {"tokens_live": tokens, "files_docs": 0},
            "docs": [],
            "links": {"dead": [], "orphans": [], "dead_anchors": []},
            "sections": [],
        }
    )


def _row(ts: str, tokens: int, actions: list, **kw) -> dict:
    row = {
        "ts": ts,
        "repo": "r",
        "file": "AGENTS.md",
        "tokens": tokens,
        "tokens_exact": True,
        "actions": actions,
    }
    row.update(kw)
    return row


def _seed(repo: Path, *rows) -> Path:
    p = repo / LEDGER
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def _rows(repo: Path) -> list:
    return [json.loads(x) for x in (repo / LEDGER).read_text().splitlines() if x]


def _record(repo: Path, tokens: int, *flags: str, **kw):
    return subprocess.run(
        ["bash", str(RECORD), *flags],
        input=_payload(tokens, **kw),
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=30,
    )


BASELINE = _row("2000-01-01", 500, ["baseline:pre-curation"])


def _curated(tmp_path: Path) -> Path:
    """A baseline and this run's curation row, as Phase 7 leaves them."""
    repo = _repo(tmp_path, "# P\n")
    _seed(
        repo,
        BASELINE,
        _row(
            "2000-01-03",
            450,
            ["demote:X"],
            no_loss="ok",
            claims_dropped=0,
            claims_warranted=1,
            seams=0,
            seams_acked=2,
            note="first pass",
            delta_tokens=-50,
            delta_days=2,
        ),
    )
    return repo


class TestAmendComputesAgainstWhatRemains:
    def test_deltas_describe_the_surviving_neighbour(self, tmp_path: Path):
        """The #319 trap: computed with the superseded row present, the delta
        would be 470 - 450 and span zero days. Against the baseline that
        remains it is 470 - 500."""
        repo = _curated(tmp_path)
        r = _record(repo, 470, "--amend")
        assert r.returncode == 0, r.stderr
        rows = _rows(repo)
        assert len(rows) == 2, rows
        amended = rows[1]
        assert amended["tokens"] == 470
        assert amended["delta_tokens"] == -30, amended
        assert amended["delta_days"] > 2, amended  # today minus 2000-01-01

    def test_replaces_and_keeps_other_lines(self, tmp_path: Path):
        repo = _curated(tmp_path)
        before = (repo / LEDGER).read_text().splitlines()
        (repo / LEDGER).write_text(
            "\n".join([before[0], "{not json", before[1]]) + "\n"
        )
        r = _record(repo, 470, "--amend")
        assert r.returncode == 0, r.stderr
        after = (repo / LEDGER).read_text().splitlines()
        assert len(after) == 3, after
        assert after[0] == before[0]
        assert after[1] == "{not json"
        assert json.loads(after[2])["tokens"] == 470

    def test_the_amended_row_moves_last_so_the_backfill_finds_it(self, tmp_path: Path):
        """CR 1. `--repo-commit HEAD` backfills the newest row in the whole
        ledger. Amended in place behind another file's row, the backfill
        rewrote that row's commit instead."""
        repo = _curated(tmp_path)
        other = _row(
            "2000-01-03", 90, ["demote:Z"], file="OTHER.md", repo_commit="0ther00"
        )
        rows = _rows(repo)
        _seed(repo, *rows, other)
        assert _record(repo, 470, "--amend").returncode == 0
        r = subprocess.run(
            ["bash", str(RECORD), "--repo-commit", "HEAD"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=_clean_env(),
            timeout=30,
        )
        assert r.returncode == 0, r.stderr
        after = _rows(repo)
        assert [x["file"] for x in after] == ["AGENTS.md", "OTHER.md", "AGENTS.md"]
        assert after[1]["repo_commit"] == "0ther00", after[1]
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            env=_clean_env(),
            check=True,
        ).stdout.strip()
        assert after[2]["tokens"] == 470 and after[2]["repo_commit"] == head

    def test_a_repeat_amend_is_a_no_op(self, tmp_path: Path):
        repo = _curated(tmp_path)
        assert _record(repo, 470, "--amend").returncode == 0
        text = (repo / LEDGER).read_text()
        r = _record(repo, 470, "--amend")
        assert r.returncode == 0, r.stderr
        assert "nothing to amend" in r.stderr
        assert (repo / LEDGER).read_text() == text

    def test_dry_run_writes_nothing(self, tmp_path: Path):
        repo = _curated(tmp_path)
        text = (repo / LEDGER).read_text()
        r = _record(repo, 470, "--amend", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout.strip().splitlines()[-1])["delta_tokens"] == -30
        assert (repo / LEDGER).read_text() == text


class TestTheRunsAttributesCarryByGroup:
    def test_unsupplied_groups_carry_and_are_named(self, tmp_path: Path):
        repo = _curated(tmp_path)
        r = _record(repo, 470, "--amend")
        row = _rows(repo)[1]
        assert row["actions"] == ["demote:X"]
        assert row["note"] == "first pass"
        assert (row["no_loss"], row["claims_dropped"], row["claims_warranted"]) == (
            "ok",
            0,
            1,
        )
        assert (row["seams"], row["seams_acked"]) == (0, 2)
        assert "carried from the amended row" in r.stderr
        assert "no_loss" in r.stderr

    def test_one_flag_replaces_its_whole_group(self, tmp_path: Path):
        """Carrying `claims_warranted: 1` beside a new `--no-loss skipped`
        would write a pairing the append refuses."""
        repo = _curated(tmp_path)
        r = _record(repo, 470, "--amend", "--no-loss", "skipped", "--dry-run")
        assert r.returncode == 0, r.stderr
        row = json.loads(r.stdout.strip().splitlines()[-1])
        assert row["no_loss"] == "skipped"
        assert row["claims_dropped"] is None and row["claims_warranted"] is None
        assert row["seams_acked"] == 2  # another group, still carried

    def test_actions_can_be_replaced(self, tmp_path: Path):
        repo = _curated(tmp_path)
        r = _record(repo, 470, "--amend", "--actions", "demote:X,fix:restore-cmd")
        assert r.returncode == 0, r.stderr
        assert _rows(repo)[1]["actions"] == ["demote:X", "fix:restore-cmd"]


class TestAmendRefuses:
    def test_a_baseline_target(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n")
        _seed(repo, BASELINE)
        r = _record(repo, 470, "--amend")
        assert r.returncode == 1
        assert "baseline" in r.stderr

    def test_a_file_with_no_row(self, tmp_path: Path):
        repo = _curated(tmp_path)
        r = _record(repo, 470, "--amend", path="OTHER.md")
        assert r.returncode == 1
        assert "no row for OTHER.md" in r.stderr

    def test_a_missing_ledger_without_creating_it(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n")
        r = _record(repo, 470, "--amend")
        assert r.returncode == 1
        assert not (repo / LEDGER).exists()

    def test_baseline_and_repo_commit_alongside(self, tmp_path: Path):
        repo = _curated(tmp_path)
        for extra in (["--baseline"], ["--repo-commit", "HEAD"]):
            r = _record(repo, 470, "--amend", *extra)
            assert r.returncode == 1, (extra, r.stderr)

    def test_a_method_change_like_an_append(self, tmp_path: Path):
        repo = _curated(tmp_path)
        text = (repo / LEDGER).read_text()
        r = _record(repo, 470, "--amend", exact=False)
        assert r.returncode == 4, r.stderr
        assert "refusing to amend" in r.stderr
        assert (repo / LEDGER).read_text() == text


def _with_origin(tmp_path: Path, repo: Path) -> None:
    """Publish REPO's current HEAD as origin's default branch."""
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "remote", "set-head", "origin", "main")


def _commit(repo: Path, msg: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", msg)


class TestAMergedRowIsHistory:
    def test_a_merged_row_is_refused(self, tmp_path: Path):
        repo = _curated(tmp_path)
        _commit(repo, "curation")
        _with_origin(tmp_path, repo)
        text = (repo / LEDGER).read_text()
        r = _record(repo, 470, "--amend")
        assert r.returncode == 1, r.stderr
        assert "already on origin/main" in r.stderr
        assert (repo / LEDGER).read_text() == text

    def test_a_row_only_this_branch_carries_is_amended(self, tmp_path: Path):
        """The ordinary Phase 7 case: the baseline is on main — as is the
        parent repo_commit names — and the curation row is not."""
        repo = _repo(tmp_path, "# P\n")
        _seed(repo, BASELINE)
        _commit(repo, "baseline")
        _with_origin(tmp_path, repo)
        rows = [BASELINE, _row("2000-01-03", 450, ["demote:X"])]
        _seed(repo, *rows)
        _commit(repo, "curation, unmerged")
        r = _record(repo, 470, "--amend")
        assert r.returncode == 0, r.stderr
        assert _rows(repo)[1]["tokens"] == 470

    def test_a_backfill_after_merge_does_not_hide_it(self, tmp_path: Path):
        repo = _curated(tmp_path)
        _commit(repo, "curation")
        _with_origin(tmp_path, repo)
        lines = (repo / LEDGER).read_text().splitlines()
        row = json.loads(lines[1])
        row["repo_commit"] = "abc1234"
        lines[1] = json.dumps(row)
        (repo / LEDGER).write_text("\n".join(lines) + "\n")
        r = _record(repo, 470, "--amend")
        assert r.returncode == 1, r.stderr

    def test_a_parallel_runs_row_on_main_is_not_this_row(self, tmp_path: Path):
        """Positional matching would refuse here: main holds as many rows for
        the file as this branch does. Only content says they differ."""
        repo = _repo(tmp_path, "# P\n")
        _seed(repo, BASELINE, _row("2000-01-02", 480, ["demote:Y"]))
        _commit(repo, "another run")
        _with_origin(tmp_path, repo)
        _seed(repo, BASELINE, _row("2000-01-03", 450, ["demote:X"]))
        _commit(repo, "this run")
        r = _record(repo, 470, "--amend")
        assert r.returncode == 0, r.stderr

    def test_no_origin_warns_and_proceeds(self, tmp_path: Path):
        repo = _curated(tmp_path)
        r = _record(repo, 470, "--amend")
        assert r.returncode == 0, r.stderr
        assert "cannot tell whether this row has merged" in r.stderr


class TestTheTrendNamesAStaleDelta:
    def test_the_hand_edit_order_is_flagged(self, tmp_path: Path):
        """Exactly the issue's row: dated after its predecessor, carrying the
        delta it computed against the row the hand-edit then removed."""
        repo = _repo(tmp_path, "# P\n")
        _seed(
            repo,
            BASELINE,
            _row("2000-01-02", 470, ["demote:X"], delta_tokens=20, delta_days=0),
        )
        r = _record(repo, 470, "--baseline", "--print-trend")
        assert r.returncode == 0, r.stderr
        assert "WARN row 2000-01-02 disagrees" in r.stderr
        assert "delta_days 0 (ts gap is 1)" in r.stderr
        assert "delta_tokens +20 (token change is -30)" in r.stderr

    def test_a_consistent_ledger_is_quiet(self, tmp_path: Path):
        repo = _curated(tmp_path)
        r = _record(repo, 470, "--amend", "--print-trend")
        assert r.returncode == 0, r.stderr
        assert "disagrees" not in r.stderr


class TestTheProseNamesTheCommand:
    def test_phase_7_and_telemetry_md_name_amend(self):
        for doc in (SKILL_MD, TELEMETRY):
            assert "--amend" in doc.read_text(), doc


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
