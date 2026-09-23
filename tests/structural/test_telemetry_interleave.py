"""A merge that interleaves the cadence's row is repaired without a duplicate (#325).

The #319 cohort sweep found three ledgers whose deltas a MERGE had staled, not
a hand-edit: the weekly cadence appended a row to the default branch while a
curation branch was open, and merging (or rebasing) the default branch in put
that row among rows it was never measured beside. `merge=union` merges the
JSONL cleanly, so nothing signalled it.

A merge puts the branch's rows first and the default branch's new rows after
them, so the stale delta can sit on a row the default branch already holds.
Repairing THAT row in place makes it a line both branches changed, and once the
default branch appends again `merge=union` keeps both versions — a duplicated
row. So `--repair` moves this branch's own rows after every row `origin/HEAD`
holds before it recomputes.

What this file pins:

- **The merge shape is repaired by a move**: own rows go last in their own
  order, every held line stays byte-identical, and the curation's later merge
  into the default branch leaves no row twice.
- **The in-place repair is what duplicates** — the reason for the move,
  demonstrated rather than asserted.
- **The rebase shape needs no move**, only the deltas.
- **Both modes share one row identity**, blind to a backfilled `repo_commit`
  and to repaired deltas, so neither breaks the held-row rule with the rewrite
  the other makes (CR 1).
- **After a merge, `--amend` and `--repo-commit` name `--repair`**, and once
  it has run both reach this run's row again (CR 2).
- **A branch row older than the cadence row gets a negative `delta_days`** —
  documented, since the move follows the ledger's order (CR 3).
- **With no `origin/HEAD` it warns** and repairs in file order.
- **The cadence warns** — in corrections, since a move is not a delta (CR 4) —
  on a stale ledger and is silent on a clean one, and
  `--check` names a workflow rendered without the step.
- **`cohort-report.sh` derives the best reduction** from observed tokens, so a
  stale stored `delta_tokens` cannot move it.
- **The prose names the step** where Phase 7 gives it.

Keep this list current — it is the file's index.
"""

import json
import subprocess
from pathlib import Path

import pytest

from .test_loss_warrants import _clean_env, _git, _repo
from .test_telemetry_amend import (
    LEDGER,
    RECORD,
    SKILL_MD,
    TELEMETRY,
    _record,
    _row,
    _rows,
    _seed,
    _with_origin,
)
from .test_telemetry_repair import _repair

SCRIPTS = RECORD.parent
INSTALL_CADENCE = SCRIPTS / "install-cadence.sh"
COHORT = SCRIPTS / "cohort-report.sh"

X = _row("2026-09-03", 500, ["baseline:scheduled"])
PRE = _row("2026-09-10", 500, ["baseline:pre-curation"], delta_tokens=0, delta_days=7)
CUR = _row("2026-09-10", 400, ["demote:Layout"], delta_tokens=-100, delta_days=0)
CAD1 = _row("2026-09-10", 500, ["baseline:scheduled"], delta_tokens=0, delta_days=7)
CAD2 = _row("2026-09-17", 400, ["baseline:scheduled"], delta_tokens=-100, delta_days=7)


def _append(repo: Path, *rows) -> None:
    with (repo / LEDGER).open("a") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in rows))


def _commit(repo: Path, msg: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", msg)


def _lines(repo: Path) -> list:
    return (repo / LEDGER).read_text().splitlines()


def _fixes(r) -> set:
    return {
        (f["line"], f["field"], f["was"], f["now"])
        for f in map(json.loads, r.stdout.splitlines())
    }


def _backfill(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(RECORD), "--repo-commit", "HEAD"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=30,
    )


def _merged(tmp_path: Path, *, origin: bool = True) -> Path:
    """The observo shape: a curation branch that merged the default branch in
    after the cadence appended to it. Left on branch `cur`, with `main` and —
    when ORIGIN — `origin/HEAD` holding the cadence's row."""
    repo = _repo(tmp_path, "# P\n")
    _git(repo, "branch", "-M", "main")
    (repo / ".gitattributes").write_text(f"{LEDGER} merge=union\n")
    _seed(repo, X)
    _commit(repo, "ledger")
    _git(repo, "checkout", "-qb", "cur")
    _append(repo, PRE, CUR)
    _commit(repo, "curation")
    _git(repo, "checkout", "-q", "main")
    _append(repo, CAD1)
    _commit(repo, "weekly context measurement")
    if origin:
        bare = tmp_path / "origin.git"
        _git(tmp_path, "init", "-q", "--bare", str(bare))
        _git(repo, "remote", "add", "origin", str(bare))
        _git(repo, "push", "-q", "origin", "main")
        _git(repo, "fetch", "-q", "origin")
        _git(repo, "remote", "set-head", "origin", "main")
    _git(repo, "checkout", "-q", "cur")
    _git(repo, "merge", "-q", "--no-edit", "main")
    return repo


class TestTheMergeShapeIsRepairedByAMove:
    def test_the_merge_interleaves_cleanly(self, tmp_path: Path):
        """The premise, pinned so a git that orders union merges differently
        is noticed here rather than in a cohort ledger."""
        repo = _merged(tmp_path)
        assert [r["actions"][0] for r in _rows(repo)] == [
            "baseline:scheduled",
            "baseline:pre-curation",
            "demote:Layout",
            "baseline:scheduled",
        ]
        assert _fixes(_repair(repo, "--dry-run")), "the interleave went undetected"

    def test_own_rows_move_last_and_held_rows_stay_byte_identical(self, tmp_path: Path):
        repo = _merged(tmp_path)
        held = _lines(repo)[0], _lines(repo)[3]
        r = _repair(repo)
        assert r.returncode == 0, r.stderr
        assert _fixes(r) == {
            (2, "line", 2, 3),
            (3, "line", 3, 4),
            (2, "delta_days", 7, 0),
        }
        after = _lines(repo)
        assert (after[0], after[1]) == held, "a row the default branch holds changed"
        assert [r["actions"][0] for r in _rows(repo)][2:] == [
            "baseline:pre-curation",
            "demote:Layout",
        ]
        assert _repair(repo, "--dry-run").stdout == ""

    def test_the_curations_merge_keeps_every_row_once(self, tmp_path: Path):
        """The payoff: the default branch appends again before the curation
        merges, and the ledger still holds each row exactly once."""
        repo = _merged(tmp_path)
        assert _repair(repo).returncode == 0
        _commit(repo, "repair")
        _git(repo, "checkout", "-q", "main")
        _append(repo, CAD2)
        _commit(repo, "weekly context measurement")
        _git(repo, "merge", "-q", "--no-edit", "cur")
        lines = _lines(repo)
        assert len(lines) == len(set(lines)) == 5, lines
        # What remains is the case no branch can cover — CAD2 landed after the
        # branch's last merge — and it is exactly what the cadence detects.
        assert _fixes(_repair(repo, "--dry-run"))

    def test_repairing_in_place_is_what_duplicates(self, tmp_path: Path):
        """Without origin/HEAD the repair cannot tell which rows are held, so it
        corrects the cadence's row where it stands — and the next merge keeps
        both versions of it. This is why the move exists."""
        repo = _merged(tmp_path, origin=False)
        assert _repair(repo).returncode == 0
        _commit(repo, "repair")
        _git(repo, "checkout", "-q", "main")
        _append(repo, CAD2)
        _commit(repo, "weekly context measurement")
        _git(repo, "merge", "-q", "--no-edit", "cur")
        cadence_rows = [
            r
            for r in _rows(repo)
            if r["ts"] == "2026-09-10" and r["actions"] == ["baseline:scheduled"]
        ]
        assert len(cadence_rows) == 2, "union no longer duplicates — revisit #325"


class TestOtherShapes:
    def test_the_rebase_shape_needs_no_move(self, tmp_path: Path):
        """broker's shape: a rebase already puts the branch's rows last, so
        only their deltas are stale."""
        repo = _merged(tmp_path)
        _git(repo, "reset", "-q", "--hard", "HEAD^1")
        _git(repo, "rebase", "-q", "main")
        r = _repair(repo)
        assert _fixes(r) == {(3, "delta_days", 7, 0)}, r.stdout

    def test_a_branch_row_older_than_the_cadence_row_gets_a_negative_gap(
        self, tmp_path: Path
    ):
        """Documented, not a defect: the move follows the ledger's order, not
        the calendar, and delta_days is arithmetic on that order (CR 3)."""
        repo = _merged(tmp_path)
        lines = _lines(repo)
        pre = json.loads(lines[1])
        (repo / LEDGER).write_text(
            "\n".join([lines[0], json.dumps({**pre, "ts": "2026-09-09"}), *lines[2:]])
            + "\n"
        )
        assert _repair(repo).returncode == 0
        moved = next(
            r for r in _rows(repo) if r["actions"] == ["baseline:pre-curation"]
        )
        assert moved["delta_days"] == -1, moved

    def test_no_origin_warns_and_repairs_in_file_order(self, tmp_path: Path):
        repo = _merged(tmp_path, origin=False)
        r = _repair(repo, "--dry-run")
        assert "cannot tell which rows the default branch holds" in r.stderr
        assert _fixes(r) == {(4, "delta_tokens", 0, 100), (4, "delta_days", 7, 0)}


class TestPhase7RewritesAfterAMerge:
    """A merge leaves the cadence's baseline row newest, where both rewrites
    look for this run's row. The refusal names --repair, and after it both
    rewrites reach this run's row again (CR 2)."""

    def test_backfill_names_repair_then_lands_on_this_runs_row(self, tmp_path: Path):
        repo = _merged(tmp_path)
        r = _backfill(repo)
        assert r.returncode == 1, r.stderr
        assert "--repair" in r.stderr, r.stderr
        assert _repair(repo).returncode == 0
        assert _backfill(repo).returncode == 0
        last = _rows(repo)[-1]
        assert last["actions"] == ["demote:Layout"], last
        assert last["repo_commit"], last

    def test_amend_names_repair_then_lands_on_this_runs_row(self, tmp_path: Path):
        repo = _merged(tmp_path)
        r = _record(repo, 390, "--amend")
        assert r.returncode == 1, r.stderr
        assert "--repair" in r.stderr, r.stderr
        assert _repair(repo).returncode == 0
        r = _record(repo, 390, "--amend")
        assert r.returncode == 0, r.stderr
        assert [(x["tokens"], x["actions"]) for x in _rows(repo)][-1] == (
            390,
            ["demote:Layout"],
        )
        assert len(_rows(repo)) == 4


class TestOneIdentityForBothModes:
    """--amend refuses what the default branch holds and --repair moves what it
    does not, so both must ask the question the same way — blind to the
    repo_commit a backfill rewrites and the deltas a repair recomputes."""

    def test_repair_does_not_move_a_held_row_whose_repo_commit_was_backfilled(
        self, tmp_path: Path
    ):
        repo = _repo(tmp_path, "# P\n")
        row = _row("2026-09-10", 400, ["demote:Layout"], repo_commit="aaaaaaa")
        _seed(repo, X, row, CAD1)
        _commit(repo, "ledger")
        _with_origin(tmp_path, repo)
        _seed(repo, X, {**row, "repo_commit": "bbbbbbb"}, CAD1)
        r = _repair(repo, "--dry-run")
        assert not [f for f in _fixes(r) if f[1] == "line"], r.stdout

    def test_amend_refuses_a_merged_row_whose_deltas_were_repaired(
        self, tmp_path: Path
    ):
        repo = _repo(tmp_path, "# P\n")
        row = _row("2026-09-10", 400, ["demote:Layout"], delta_tokens=-50)
        _seed(repo, X, row)
        _commit(repo, "ledger")
        _with_origin(tmp_path, repo)
        _seed(repo, X, {**row, "delta_tokens": -100, "delta_days": 7})
        r = _record(repo, 390, "--amend")
        assert r.returncode == 1, r.stderr
        assert "already on origin/main" in r.stderr, r.stderr


def _deltas_step(repo: Path) -> str:
    """The rendered `Check the recorded deltas` step, as the workflow runs it."""
    yaml = pytest.importorskip("yaml")
    rendered = subprocess.run(
        ["bash", str(INSTALL_CADENCE), "--print"],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=30,
    ).stdout
    return next(
        s["run"]
        for s in yaml.safe_load(rendered)["jobs"]["measure"]["steps"]
        if s.get("name") == "Check the recorded deltas"
    )


def _run_step(repo: Path, **env) -> subprocess.CompletedProcess:
    step = _deltas_step(repo).replace("/tmp/", f"{repo}/.tmp-")
    return subprocess.run(
        ["bash", "-e", "-c", step],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env={**_clean_env(), **env},
        timeout=30,
    )


class TestTheCadenceWarns:
    def test_a_stale_ledger_is_warned(self, tmp_path: Path):
        repo = _merged(tmp_path, origin=False)
        r = _run_step(repo, RECORD_TELEMETRY_SH=str(RECORD))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "::warning::2 correction(s) to" in r.stdout, r.stdout
        assert '"field": "delta_tokens"' in r.stdout, r.stdout

    def test_a_clean_ledger_is_silent(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n")
        _seed(repo, X, CAD1)
        r = _run_step(repo, RECORD_TELEMETRY_SH=str(RECORD))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "::warning::" not in r.stdout, r.stdout

    def test_unresolved_scripts_do_not_stack_a_second_failure(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n")
        r = _run_step(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "not resolved" in r.stdout

    def test_check_names_a_workflow_without_the_step(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n")

        def installer(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                ["bash", str(INSTALL_CADENCE), *args],
                capture_output=True,
                text=True,
                cwd=str(repo),
                env=_clean_env(),
                timeout=30,
            )

        installer()
        assert "delta check:        yes" in installer("--check").stdout
        wf = repo / ".github" / "workflows" / "context-cadence.yml"
        wf.write_text(wf.read_text().replace("--repair --dry-run", "--repair"))
        r = installer("--check")
        assert r.returncode == 3, r.stdout
        assert "delta check:        STALE" in r.stdout, r.stdout


class TestTheRollUpDerivesTheReduction:
    def test_a_stale_stored_delta_cannot_move_the_best_reduction(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n")
        _seed(
            repo,
            X,
            _row("2026-09-10", 380, ["demote:Layout"], delta_tokens=-864),
        )
        r = subprocess.run(
            ["bash", str(COHORT), "--local", str(repo), "--format", "json"],
            capture_output=True,
            text=True,
            env=_clean_env(),
            timeout=30,
        )
        assert r.returncode == 0, r.stderr
        (rec,) = json.loads(r.stdout)
        assert rec["best_delta"] == -120, rec
        assert rec["best_actions"] == "demote:Layout", rec


def test_phase_7_names_the_step():
    body = SKILL_MD.read_text()
    assert "Merged or rebased the default branch in? **`--repair`**" in body
    assert "telemetry.md#merging-the-default-branch-in" in body
    assert "### Merging the default branch in" in TELEMETRY.read_text()
