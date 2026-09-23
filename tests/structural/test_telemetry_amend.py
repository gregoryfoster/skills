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
- **It rewrites in place**: one row replaced, nothing appended, other lines
  (malformed ones included) untouched.
- **The run's attributes carry forward by group**, and supplying any flag in a
  group replaces the whole group — so no amend assembles a row no single
  invocation could have written.
- **It refuses** a baseline target, a file with no row, an empty or missing
  ledger (without creating one), and `--baseline` / `--repo-commit` beside it.
- **The method-change refusal still applies** — an amend is not a way round it.
- **`--print-trend` names a row whose deltas disagree with the ledger**, so
  the damage a past hand-edit already did is visible.
- **The prose names the command** where Phase 7 gives the instruction.

Keep this list current — it is the file's index.
"""

import json
import subprocess
from pathlib import Path

from .test_loss_warrants import _clean_env, _repo

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

    def test_rewrites_in_place_and_keeps_other_lines(self, tmp_path: Path):
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
