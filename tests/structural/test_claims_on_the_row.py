"""The ledger can see the claim check, and can tell tightening from moving (#253).

`prove-no-loss.sh --claims` prints two machine-readable trailer lines —
`claims_warranted:` and `claims_dropped:` — and `record-telemetry.sh` had no
flag for either. So a run that passed the claim check and cleared it wrote **the
same row** as a run that never ran it: exactly the `null` ≠ `0` distinction the
ledger already draws for `no_loss_warrants`, one field over.

Nothing else on the row answers it. `no_loss_warrants` aggregates all six
warrant kinds, so a `tighten` is indistinguishable from a `retarget` in the
count; `actions` carries `prune:<section>`, which says a tightening happened but
not whether its check ran. The ack file would answer it and the scorer cannot
read the ack file — only the row.

What this file pins:

- **Both counts land on the row, and absent is `null`, not `0`.**
- **They answer to a verdict.** A count against `skipped`, or against nothing,
  would claim atoms were compared by a check that did not run — the
  over-statement `--no-loss-warrants` was given the same guard for (#111).
- **A non-zero `claims_dropped` cannot sit beside `ok`.** `prove-no-loss.sh`
  exits 3 on an unwarranted dropped atom, so that pairing records a verdict the
  run never reached — and this pair is the only evidence the ledger will hold
  that a class-C tightening was verified.
- **Surfaced by the scorer, never gated**, the treatment `no_loss_warrants`
  gets and for the reason it gets it.
- **The unmeasured quantity is named as unmeasured.** Tokens recovered by
  rewriting versus by moving is not on the row and not derivable from it; the
  skill says so in prose rather than shipping a proxy the cohort would read as
  measured.

Keep this list current — it is the file's index.
"""

import json
import subprocess
from pathlib import Path

import pytest

from .test_context_surface import _score
from .test_loss_warrants import _clean_env, _repo, _three_good_pairs_local

SKILL_DIR = (
    Path(__file__).resolve().parent.parent.parent / "skills" / "curating-context"
)
RECORD = SKILL_DIR / "scripts" / "record-telemetry.sh"
PROVE = SKILL_DIR / "scripts" / "prove-no-loss.sh"
RUBRIC = SKILL_DIR / "references" / "keep-cut-rubric.md"
REJECTED = SKILL_DIR / "references" / "rejected-changes.md"
TELEMETRY = SKILL_DIR / "references" / "telemetry.md"

PAYLOAD = json.dumps(
    {
        "policy": {
            "path": "AGENTS.md",
            "lines": 10,
            "bytes": 100,
            "tokens": 40,
            "tokens_exact": True,
            "bytes_per_token": 2.5,
            "budget": 6000,
            "over_budget": False,
        },
        "totals": {"tokens_live": 40, "files_docs": 0},
        "docs": [],
        "links": {"dead": [], "orphans": [], "dead_anchors": []},
        "sections": [],
    }
)


def _record(tmp_path: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(RECORD), "--dry-run", *flags],
        input=PAYLOAD,
        capture_output=True,
        text=True,
        cwd=str(_repo(tmp_path, "# P\n")),
        env=_clean_env(),
        timeout=30,
    )


def _row(tmp_path: Path, *flags: str) -> dict:
    r = _record(tmp_path, *flags)
    assert r.returncode == 0, r.stdout + r.stderr
    line = [x for x in r.stdout.splitlines() if x.strip().startswith("{")][-1]
    return json.loads(line)


class TestTheCountsRideTheRow:
    def test_both_counts_land_on_the_row(self, tmp_path: Path):
        row = _row(
            tmp_path,
            "--no-loss",
            "ok",
            "--claims-dropped",
            "0",
            "--claims-warranted",
            "2",
        )
        assert row["claims_dropped"] == 0, row
        assert row["claims_warranted"] == 2, row

    def test_absent_records_null_not_zero(self, tmp_path: Path):
        """The whole point. A `claims_dropped: 0` invented for a run that never
        ran the check would read as a clean bill of health, which is the
        distinction the field exists to draw."""
        row = _row(tmp_path, "--no-loss", "ok")
        assert row["claims_dropped"] is None, row
        assert row["claims_warranted"] is None, row

    def test_zero_survives_the_or_none_shape(self, tmp_path: Path):
        """`--claims-dropped 0` is the positive claim: the check ran and found
        nothing unaccounted for. A truthiness test would fold it back into
        "not measured"."""
        row = _row(tmp_path, "--no-loss", "ok", "--claims-dropped", "0")
        assert row["claims_dropped"] == 0, row

    def test_they_do_not_disturb_the_neighbouring_fields(self, tmp_path: Path):
        row = _row(
            tmp_path,
            "--no-loss",
            "ok",
            "--no-loss-warrants",
            "3",
            "--seams",
            "1",
            "--seams-acked",
            "2",
            "--claims-dropped",
            "0",
            "--claims-warranted",
            "5",
        )
        assert row["no_loss"] == "ok", row
        assert row["no_loss_warrants"] == 3, row
        assert row["seams"] == 1 and row["seams_acked"] == 2, row
        assert row["claims_warranted"] == 5, row


class TestTheyAnswerToAVerdict:
    @pytest.mark.parametrize("flag", ["--claims-dropped", "--claims-warranted"])
    def test_a_count_without_a_verdict_is_refused(self, tmp_path: Path, flag):
        r = _record(tmp_path, flag, "0")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "--no-loss" in r.stderr, r.stderr

    @pytest.mark.parametrize("flag", ["--claims-dropped", "--claims-warranted"])
    def test_a_count_against_skipped_is_refused(self, tmp_path: Path, flag):
        """`skipped` says the check did not run; a count says it compared
        atoms. Both cannot be true of one run."""
        r = _record(tmp_path, "--no-loss", "skipped", flag, "0")
        assert r.returncode == 1, r.stdout + r.stderr

    def test_counts_against_a_failed_verdict_are_allowed(self, tmp_path: Path):
        """Three dropped of which one was judged is a real and informative
        state — the same reason `--no-loss-warrants` is allowed against
        `failed`."""
        row = _row(
            tmp_path,
            "--no-loss",
            "failed",
            "--claims-dropped",
            "3",
            "--claims-warranted",
            "1",
        )
        assert (row["claims_dropped"], row["claims_warranted"]) == (3, 1), row

    def test_a_nonzero_drop_beside_ok_is_refused(self, tmp_path: Path):
        """`prove-no-loss.sh` exits 3 on an unwarranted dropped atom, so `ok`
        beside one is a verdict that run never reached. Refused rather than
        stored: a row saying "checked, clean" over a check that failed is worse
        than the null it replaces."""
        r = _record(tmp_path, "--no-loss", "ok", "--claims-dropped", "2")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "exits 3" in r.stderr, r.stderr

    def test_a_zero_drop_beside_ok_is_the_normal_case(self, tmp_path: Path):
        row = _row(tmp_path, "--no-loss", "ok", "--claims-dropped", "0")
        assert row["no_loss"] == "ok" and row["claims_dropped"] == 0, row

    def test_a_baseline_row_refuses_them(self, tmp_path: Path):
        """A baseline has rewritten nothing, so no atom of its could have been
        dropped — the same reason it already refuses --no-loss."""
        r = _record(tmp_path, "--baseline=pre-curation", "--claims-dropped", "0")
        assert r.returncode == 1, r.stdout + r.stderr

    @pytest.mark.parametrize("flag", ["--claims-dropped", "--claims-warranted"])
    @pytest.mark.parametrize("bad", ["two", "-1", "1.5", ""])
    def test_a_non_numeric_count_is_refused(self, tmp_path: Path, flag, bad):
        r = _record(tmp_path, "--no-loss", "ok", flag, bad)
        assert r.returncode == 1, f"{bad!r} was accepted: {r.stdout}{r.stderr}"

    def test_a_typo_is_diagnosed_as_a_typo_not_as_a_contradiction(self, tmp_path: Path):
        """Ordering, and it is load-bearing.

        With the digits check below the semantic ones, `--claims-dropped two
        --no-loss ok` took the non-zero branch and was answered with
        "prove-no-loss.sh exits 3 on an unwarranted dropped atom … record
        --no-loss failed" — a confident diagnosis of the wrong problem whose
        remedy writes a false `failed` on the row. A value that is not a count
        is not a count whatever the verdict says (#257 CR round 1).
        """
        r = _record(tmp_path, "--no-loss", "ok", "--claims-dropped", "two")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "non-negative integer" in r.stderr, (
            f"a transcription error was diagnosed as a semantic one:\n{r.stderr}"
        )
        assert "exits 3" not in r.stderr, r.stderr

    def test_the_backfill_mode_refuses_them(self, tmp_path: Path):
        """`--repo-commit` reads no measurement and writes no new row, so a
        flag describing a run has nothing to land on. Refused rather than
        silently discarded."""
        r = _record(tmp_path, "--repo-commit", "HEAD", "--claims-dropped", "0")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "--claims-dropped" in r.stderr, r.stderr


class TestTheProducerAndTheConsumerNameEachOther:
    def test_prove_no_loss_names_the_flags_its_trailer_feeds(self):
        """The trailer already told an operator to carry `loss_warranted:` to
        the row; the claim lines told them nothing, which is how they went
        unrecorded for two releases."""
        body = PROVE.read_text()
        assert "--claims-dropped" in body and "--claims-warranted" in body, (
            "prove-no-loss.sh --help must name the record-telemetry.sh flags "
            "its claims trailer feeds — the two lines are otherwise printed "
            "for nobody"
        )

    def test_the_row_schema_documents_both_fields(self):
        body = TELEMETRY.read_text()
        assert "`claims_dropped`" in body and "`claims_warranted`" in body, (
            "references/telemetry.md is the row schema; a field absent from it "
            "is a field a cohort reader cannot interpret"
        )


class TestTheScorerSurfacesThemWithoutGating:
    """Same treatment `no_loss_warrants` gets (#111), for the same reason: a
    run rejected for reporting a judged atom teaches operators to stop
    reporting."""

    def test_a_null_does_not_trip_the_gate(self, tmp_path: Path):
        r = _score(_three_good_pairs_local(tmp_path))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "verdict: ADOPT" in r.stdout, r.stdout

    def test_a_clean_claim_check_is_visible_and_adopts(self, tmp_path: Path):
        r = _score(
            _three_good_pairs_local(tmp_path, claims_dropped=0, claims_warranted=0)
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "verdict: ADOPT" in r.stdout, r.stdout
        assert "ok/c" in r.stdout, (
            "a run that ran the claim check and cleared it must be "
            f"distinguishable from one that never ran it:\n{r.stdout}"
        )

    def test_warranted_atoms_ride_the_marker_and_do_not_gate(self, tmp_path: Path):
        r = _score(
            _three_good_pairs_local(tmp_path, claims_dropped=0, claims_warranted=2)
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ok/c2w" in r.stdout, r.stdout

    def test_a_row_without_the_fields_carries_no_marker(self, tmp_path: Path):
        """A null must not render as a check that ran — the same line the
        `ok+0w` suppression draws."""
        r = _score(_three_good_pairs_local(tmp_path))
        assert "/c" not in r.stdout, r.stdout


class TestTheUnmeasuredQuantityIsNamed:
    """Part 2 of #253, settled as "leave it unmeasured and say so".

    The ledger carries one before/after pair for a whole run, and a curation
    almost always demotes *and* tightens in the same pass. A count of `tighten`
    warrants would be exact and nearly meaningless — one covered a 62-token
    trim, the next a 1,013-token restructure — and the cohort is a held-out
    validation split whose numbers feed adoption decisions, so a proxy that
    weak is worse than an honest gap.
    """

    def test_the_rejection_is_recorded_with_what_refuted_it(self):
        body = REJECTED.read_text()
        assert "62-token" in body and "1,013-token" in body, (
            "references/rejected-changes.md must carry the two measurements "
            "that refuted the warrant-count proxy — an entry without a "
            "refutation is an opinion, by that file's own rule"
        )
        assert "per-section" in body or "before-census" in body, (
            "and must name the measurement that WOULD settle it, so the entry "
            "reads as a decision rather than a dead end"
        )

    def test_the_rubric_says_the_row_does_not_measure_it(self):
        """A reader of class C is the one who would otherwise infer it."""
        body = RUBRIC.read_text()
        assert "--claims-dropped" in body, (
            "keep-cut-rubric.md must tell a class-C tightening to carry its "
            "claim counts to Phase 7 — the row is where the verification "
            "becomes cohort data"
        )
        assert "rejected-changes.md" in body, (
            "and must point at the record of what is deliberately NOT "
            "measured, or the next reader re-proposes the weak proxy"
        )
