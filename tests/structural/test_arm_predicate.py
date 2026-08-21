"""The arm predicate: what `wave:` and `pair:` are allowed to mean.

#118 and #168 are one decision. #168 argued the wave A/B split was forfeit by
drift; #118's last comment corrected the premise it rested on — CI checks out
with `submodules: recursive`, so a scheduled run resolves the *committed*
gitlink and a wave assignment is deterministic for that series.

Settled here as **observed**, and the reason is not the drift. It is that a pin
cannot label a scored run even where CI honours it: the cadence writes
`baseline:scheduled`, and `score_repo()` skips every `baseline*` row when it
looks for the run to score. The rows a pin versions deterministically are
exactly the rows this gate refuses to score.

So `wave:`/`pair:` are rollout order — which half a change reaches first, and
which two repos were size-matched — and never evidence about which version a
repo runs. These tests pin that: the roster says so, the gate says so when its
own table has gone historical, and the reference docs record the decision and
the steady-state metric that replaces first-curation closure.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "skills" / "curating-context" / "scripts"
REFERENCES = ROOT / "skills" / "curating-context" / "references"
SCORE = SCRIPTS / "score-cohort.sh"
ROSTER = ROOT / ".skills" / "cohort"


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    return env


def _flat(text: str) -> str:
    """Prose with its wrapping and emphasis removed.

    A phrase assertion against raw markdown is really an assertion about where
    the line breaks fell and whether a word is bold, which is not the claim any
    of these tests are making — and a reflow would fail them for no reason.
    """
    return " ".join(text.replace("**", "").replace("*", "").split())


def _row(**kw) -> str:
    row = {
        "ts": "2026-08-05", "repo": "x", "file": "AGENTS.md",
        "tokens": None, "tokens_exact": True, "skill_version": None,
        "skill_commit": None, "budget": 6000, "docs_orphaned": 0,
        "links_dead": 0, "no_loss": "ok", "actions": [],
    }
    row.update(kw)
    return json.dumps(row, sort_keys=True)


def _member(root: Path, name: str, before: int, after: int, version: str,
            later: str | None = None) -> None:
    """A member with a baseline, a scored curation, and optionally a LATER
    curation on a newer version — the shape every cohort repo now has."""
    d = root / name / ".skills"
    d.mkdir(parents=True, exist_ok=True)
    rows = [
        _row(repo=name, tokens=before, actions=["baseline:pre-curation"]),
        _row(repo=name, tokens=after, actions=["demote:Big"], ts="2026-08-06",
             skill_version=version, skill_commit="deadbee"),
    ]
    if later is not None:
        rows.append(_row(repo=name, tokens=after, actions=["prune:Small"],
                         ts="2026-08-16", skill_version=later,
                         skill_commit="cafebab"))
    (d / "context-metrics.jsonl").write_text("\n".join(rows) + "\n")


def _roster(root: Path, spec) -> Path:
    path = root / "cohort"
    path.write_text("".join(
        f"{root / name}  wave:{w} pair:{p}\n" for name, w, p in spec))
    return path


def _two_pairs(root: Path, later: str | None = None) -> Path:
    spec = []
    for i, (cb, ca, tb, ta) in enumerate(
            [(52000, 20000, 49000, 12000), (28000, 12000, 26000, 9000)], 1):
        _member(root, f"ctl{i}", cb, ca, "1.2", later=later)
        _member(root, f"trt{i}", tb, ta, "1.3", later=later)
        spec += [(f"ctl{i}", "a", str(i)), (f"trt{i}", "b", str(i))]
    return _roster(root, spec)


def _score(roster: Path, *args: str) -> subprocess.CompletedProcess:
    """The flags name VERSIONS (#194) — 1.3 over 1.2 here. The `wave:` values in
    the roster are rollout order and no longer decide anything."""
    return subprocess.run(
        ["bash", str(SCORE), "--cohort-file", str(roster),
         "--treatment", "1.3", "--control", "1.2", *args],
        capture_output=True, text=True, env=_clean_env(), timeout=60,
    )


class TestTheGateSaysWhenItsArmsAreHistorical:
    """The scored run is each repo's FIRST attributed curation, and that never
    moves. Six releases later the header still prints `wave b: 1.3 / wave a:
    1.2` off rows written in August, with nothing saying those versions are
    spent — which is exactly the failure #168 raises against the roster,
    sitting in the script instead. Derived from the ledgers, never asserted.
    """

    def test_newer_rows_in_the_ledger_are_named(self, tmp_path: Path):
        roster = _two_pairs(tmp_path, later="1.9")
        r = _score(roster)
        assert "1.9" in r.stdout, r.stdout
        assert "historical" in r.stdout.lower(), r.stdout
        # The arms it is actually scoring are still named, so the reader can see
        # the gap rather than being told there is one.
        assert "1.3" in r.stdout and "1.2" in r.stdout, r.stdout

    def test_no_notice_when_the_scored_runs_are_the_newest_rows(
            self, tmp_path: Path):
        """A live experiment must not carry the banner, or it stops meaning
        anything on the run where it would matter."""
        roster = _two_pairs(tmp_path)
        r = _score(roster)
        assert "historical" not in r.stdout.lower(), r.stdout

    def test_json_carries_it_as_data(self, tmp_path: Path):
        roster = _two_pairs(tmp_path, later="1.9")
        r = _score(roster, "--format", "json")
        payload = json.loads(r.stdout)
        assert payload["arms_are_historical"] is True
        assert payload["newest_version_in_ledgers"] == "1.9"

    def test_json_is_false_and_populated_on_a_live_comparison(
            self, tmp_path: Path):
        """Not null: a reader distinguishing "no newer version" from "the field
        was not computed" needs the newest version either way."""
        roster = _two_pairs(tmp_path)
        r = _score(roster, "--format", "json")
        payload = json.loads(r.stdout)
        assert payload["arms_are_historical"] is False
        assert payload["newest_version_in_ledgers"] == "1.3"

    def test_the_notice_does_not_change_the_verdict(self, tmp_path: Path):
        """It reports. A historical table is not a reason to reject anything,
        and the exit code is what a caller acts on."""
        live = _score(_two_pairs(tmp_path / "live"))
        (tmp_path / "old").mkdir(parents=True, exist_ok=True)
        old = _score(_two_pairs(tmp_path / "old", later="1.9"))
        assert live.returncode == old.returncode, (live.stdout, old.stdout)


class TestTheRosterSaysWhatItsAnnotationsAre:
    """`.skills/cohort`'s header is where the rationale is written, and it
    documented a control that has never existed — no repo carries
    `.skills/skills-pin`, so nothing has ever held wave B back."""

    def test_header_dates_the_decision_and_names_it(self):
        text = ROSTER.read_text()
        assert "2026-08-17" in text
        assert "#168" in text or "issues/168" in text

    def test_header_calls_the_annotations_rollout_order(self):
        head = ROSTER.read_text().split("\n# pair 1")[0]
        low = head.lower()
        assert "rollout order" in _flat(low), head
        assert "not in force" in _flat(low) or "not an assignment" in _flat(low), head

    def test_header_no_longer_claims_the_split_holds_a_version(self):
        """The forfeited claim, verbatim from the old header. Kept as a
        tripwire: if it comes back, so does the reasoning it licensed."""
        head = ROSTER.read_text().split("\n# pair 1")[0]
        assert "forfeits the comparison permanently" not in _flat(head), head

    def test_the_annotations_themselves_survive(self):
        """Retired as a control, retained as staging. Removing them would take
        `cohort-report.sh`'s split and the rollout order with them."""
        text = ROSTER.read_text()
        assert text.count("wave:a") == 6 and text.count("wave:b") == 6


class TestTheGateRecordsTheDecision:
    """references/validation-gate.md is what the roster cites for rationale."""

    GATE = REFERENCES / "validation-gate.md"

    def test_the_arm_predicate_is_settled_and_dated(self):
        text = self.GATE.read_text()
        assert "2026-08-17" in text
        assert "observed, not assigned" in _flat(text)

    def test_it_gives_the_reason_a_pin_cannot_label_a_scored_run(self):
        """The load-bearing half. Without it the entry reads as a concession to
        drift, and the next reader re-opens it with #118's CI correction — which
        is true, and does not reach this."""
        text = self.GATE.read_text()
        assert "baseline:scheduled" in text
        assert "skills-pin" in text

    def test_the_pin_mechanism_is_explicitly_kept(self):
        assert "issues/100" in self.GATE.read_text()

    def test_the_superseded_block_no_longer_argues_from_drift_alone(self):
        """`observo` moving itself to v1.3 within a day was the whole argument,
        and #118's last comment refuted it: CI resolves the committed gitlink,
        so drift in a working tree says nothing about a scheduled run."""
        text = self.GATE.read_text()
        assert "moved itself to v1.3 within a day" not in _flat(text)


class TestTheSteadyStateMetric:
    """First curations are spent, so a proposal is judged on maintenance runs.
    The metric registered for that has to match what the row can carry."""

    GATE = REFERENCES / "validation-gate.md"

    def test_seams_is_registered_as_a_rate_not_an_accrual(self):
        """`seams` is a standing count plus an interval count and the row
        records only the sum (#169). Summing it across rows re-counts the
        standing half every week; reading the latest row loses every interval
        hit. A rate over rows is defined under both halves."""
        text = self.GATE.read_text()
        assert "seams: 0" in text
        assert "accrual" in text.lower()

    def test_the_empty_interval_is_handled_explicitly(self):
        """`check-seams.sh` reports `seam_interval: empty` precisely so a reader
        can tell whether a count covered anything. A metric reading `seams` has
        to say what it does with one."""
        text = self.GATE.read_text()
        assert "empty" in text
        assert "denominator" in text

    def test_regrowth_normalises_by_activity_and_derives_it(self):
        """#118 proposed a recorded `commits_since` field. #169 shipped
        `repo_commit` on the row first, which makes the covariate derivable from
        two consecutive rows — recomputable for history, and no schema change."""
        text = self.GATE.read_text()
        assert "repo_commit" in text
        assert "delta_days" in text

    def test_tokens_live_is_refused_by_name(self):
        """It was in #118's candidate table as a primary. The file that refutes
        it is the one the registration is supposed to consult first — the exact
        failure `rejected-changes.md` exists to prevent, occurring in the issue
        proposing the next round of metrics. The gate already cites the entry
        for the closure cap; what it lacked was the registration rule."""
        text = self.GATE.read_text()
        assert "not registerable" in _flat(text), text[-3000:]

    def test_a_proposal_is_not_scored_on_the_metric_it_introduced(self):
        """v1.3 added `seams`, and registering seam-cleanliness is exactly where
        someone will be tempted to score v1.3 on it. That is what made v1.3
        unjudgeable in the first place (#117)."""
        text = self.GATE.read_text()
        assert "a metric it introduced" in _flat(text), text[-3000:]


class TestTheRowSchemaSaysTheCovariateIsDerived:
    """The activity covariate and the seam interval are both read off the
    `repo_commit` pair. Recording either would be a second source of truth for
    something two rows already answer.

    #206 moved *which commit* the field carries — from the one HEAD happened to
    be at when the append ran, to the one that ships the curation, backfilled
    after the commit. So these assertions are re-anchored on the post-backfill
    meaning, and each one locates the `repo_commit` schema row first: a split on
    a heading that has been renamed returns the whole file, and every phrase
    below would then pass against some other paragraph while pinning nothing.
    """

    TELEMETRY = REFERENCES / "telemetry.md"

    def _schema(self) -> str:
        text = self.TELEMETRY.read_text()
        assert "### Action tags" in text, (
            "telemetry.md no longer has `### Action tags`, so the row-schema "
            "section cannot be delimited and every assertion below would run "
            "against the whole file"
        )
        return text.split("### Action tags")[0]

    def _repo_commit_row(self) -> str:
        rows = [ln for ln in self._schema().splitlines()
                if ln.startswith("| `repo_commit` |")]
        assert len(rows) == 1, (
            f"expected exactly one `repo_commit` schema row, found {len(rows)}"
        )
        return rows[0]

    def test_repo_commit_names_what_is_derived_from_it(self):
        assert "commits_since" in self._repo_commit_row(), self._repo_commit_row()

    def test_repo_commit_names_the_commit_that_ships_the_curation(self):
        """The two meanings the field carries — which state of this tree the row
        describes, and where the next sweep starts — are only satisfied by one
        commit if the row is backfilled after Phase 7 commits (#206). The schema
        row has to say which commit that is, or a reader reconstructs the lag."""
        row = self._repo_commit_row()
        assert "--repo-commit" in row, row
        assert "backfill" in row.lower(), row
        assert "at measurement time" not in row, (
            "the superseded meaning is still on the schema row: the value is no "
            "longer whatever HEAD was when the append ran.\n" + row
        )

    def test_no_commits_since_field_was_added_to_the_schema(self):
        """A field would have to be recorded going forward and would be null for
        every row already written. The derivation covers history."""
        rows = [ln for ln in self._schema().splitlines()
                if ln.startswith("| `commits_since`")]
        assert rows == [], rows


class TestPreRegistrationChecksTheRejectionFile:
    """The failure `rejected-changes.md` exists to prevent, occurring in the
    issue proposing the next round of metrics: #118's candidate table listed
    `tokens_live`, which has an entry in that file."""

    REJECTED = REFERENCES / "rejected-changes.md"

    def test_the_tokens_live_entry_says_it_is_not_registerable(self):
        text = self.REJECTED.read_text()
        entry = text.split("## `tokens_live` as the telemetry trend metric")[1]
        entry = entry.split("\n## ")[0]
        assert "primary" in entry.lower(), entry

    def test_the_file_states_the_check_that_reads_it(self):
        """A rejection nobody consults is a rejection nobody has. The check is
        cheap and it is the one this file failed to get applied."""
        text = self.REJECTED.read_text()
        assert "pre-register" in text.lower() or "registering" in text.lower()
