"""An arm is the version on the row, never the wave on the roster (#194).

#118/#168 settled that the arm a run belongs to is the `skill_version` stamped
on its OWN scored row — observed, never assigned — and that `wave:`/`pair:` are
rollout order. The roster header, `validation-gate.md`, `score-cohort.sh`'s own
comments and `cohort-report.sh`'s output label all said so; the code grouped by
the roster annotation anyway, in five places (#194 and its comment).

The two rules answer different questions and the pairing needs both:

  * `pair:` stays ROSTER-driven — it encodes size-matching against the
    2026-08-05 baseline, a property of the repos rather than of any run.
  * the arm is VERSION-driven, and a repo whose scored run carries neither the
    treatment nor the control version belongs to NO arm rather than to the arm
    its roster line names. That third state did not exist before #194 and is
    the whole content of the change.

None of this can bite on the repo's own ledger: experiment 1's arms are
version-clean — all six wave-B repos ran 1.3 and all six wave-A first curations
stand at 1.2 — so both rules return the same partition there. Every test below
therefore CONSTRUCTS the divergent case, a roster whose `wave:` and whose
recorded `skill_version` disagree, because that is the only shape in which the
two rules give different answers. A test that relied on the shipped ledger would
pass under either rule and pin neither.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "skills" / "curating-context" / "scripts"
SCORE = SCRIPTS / "score-cohort.sh"


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    return env


def _row(**kw) -> str:
    row = {
        "ts": "2026-08-05", "repo": "x", "file": "AGENTS.md",
        "tokens": None, "tokens_exact": True, "skill_version": None,
        "skill_commit": None, "budget": 6000, "docs_orphaned": 0,
        "links_dead": 0, "no_loss": "ok", "actions": [],
    }
    row.update(kw)
    return json.dumps(row, sort_keys=True)


def _member(root: Path, name: str, before: int | None, after: int,
            version: str, *, actions=("demote:Big",), **extra) -> None:
    """A member with a baseline row and one scored curation.

    `extra` lands on the scored row only — the row the gate reads. A field set
    on the baseline too would make every "is this null across the arm" test
    pass for the wrong reason. `before=None` omits the baseline, which is the
    `no_before_state` shape.
    """
    d = root / name / ".skills"
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    if before is not None:
        rows.append(_row(repo=name, tokens=before,
                         actions=["baseline:pre-curation"]))
    rows.append(_row(repo=name, tokens=after, actions=list(actions),
                     ts="2026-08-06", skill_version=version,
                     skill_commit="deadbee", **extra))
    (d / "context-metrics.jsonl").write_text("\n".join(rows) + "\n")


def _roster(root: Path, spec) -> Path:
    path = root / "cohort"
    path.write_text("".join(
        f"{root / name}  wave:{w} pair:{p}\n" for name, w, p in spec))
    return path


def _register(root: Path, name: str = "02-a-proposal.yml", **over) -> Path:
    d = root / "experiments"
    d.mkdir(parents=True, exist_ok=True)
    fields = {
        "experiment": "02",
        "proposal": "https://github.com/gregoryfoster/skills/issues/194",
        "registered": "2026-08-18",
        "treatment_version": "1.3",
        "control_version": "1.2",
        "arm_predicate": "skill_version",
        "primary_metric": "closure",
        "direction": "higher",
        "min_pairs": "1",
    }
    fields.update({k: v for k, v in over.items() if v is not None})
    (d / name).write_text("".join(f"{k}: {v}\n" for k, v in fields.items()))
    return d


def _score(roster: Path, *args: str) -> subprocess.CompletedProcess:
    """No default arms. Each test names the two VERSIONS it is comparing, which
    is the point: the flags stopped naming waves."""
    return subprocess.run(
        ["bash", str(SCORE), "--cohort-file", str(roster), *args],
        capture_output=True, text=True, env=_clean_env(), timeout=60,
    )


def _arms(roster: Path, *args: str) -> subprocess.CompletedProcess:
    return _score(roster, "--treatment", "1.3", "--control", "1.2", *args)


def _json(r: subprocess.CompletedProcess) -> dict:
    assert r.stdout, r.stderr
    return json.loads(r.stdout)


def _rec(payload: dict, name: str) -> dict:
    return next(x for x in payload["repos"] if x["repo"] == name)


def _three_pairs(root: Path, **kw) -> list[tuple[str, str, str]]:
    """Three matched pairs, the treatment (1.3) beating the control (1.2) on
    every one. Closures: 69.6/86.0, 72.7/85.0, 76.9/87.5."""
    spec = []
    for i, (cb, ca, tb, ta) in enumerate(
            [(52000, 20000, 49000, 12000), (28000, 12000, 26000, 9000),
             (19000, 9000, 14000, 7000)], start=1):
        _member(root, f"ctl{i}", cb, ca, "1.2")
        _member(root, f"trt{i}", tb, ta, "1.3", **kw)
        spec += [(f"ctl{i}", "a", str(i)), (f"trt{i}", "b", str(i))]
    return spec


class TestTheArmIsTheVersionOnTheRow:
    """The five sites #194 names, exercised through the one input shape that
    tells the old rule from the new one."""

    def test_a_wave_b_repo_running_the_control_version_scores_as_control(
            self, tmp_path: Path):
        """The pairing (`by_arm`). Under skills-vendor auto-refresh a repo runs
        whatever it last pulled, which is what #118 concluded a wave cannot
        prevent. Grouped by wave this repo carries pair 2 for the treatment;
        grouped by its own row it is a second control repo and pair 2 stops
        being a comparison at all."""
        spec = _three_pairs(tmp_path)
        _member(tmp_path, "trt2", 26000, 9000, "1.2")   # drifted back
        payload = _json(_arms(_roster(tmp_path, spec), "--min-pairs", "1",
                              "--format", "json"))
        assert _rec(payload, "trt2")["arm"] == "control", _rec(payload, "trt2")
        pair2 = next(p for p in payload["pairs"] if p["pair"] == "2")
        assert pair2["informative"] is False, pair2
        assert "0 treatment and 2 control" in pair2["why"], pair2

    def test_a_repo_on_neither_version_belongs_to_no_arm(self, tmp_path: Path):
        """The third state. Before #194 a roster line could only ever put a
        repo in one of two arms, so a run on some third version was scored as
        though it carried the version its wave implied."""
        spec = _three_pairs(tmp_path)
        _member(tmp_path, "stray", 9000, 7000, "0.9")
        spec.append(("stray", "b", "9"))
        r = _arms(_roster(tmp_path, spec), "--format", "json")
        payload = _json(r)
        assert _rec(payload, "stray")["arm"] is None
        assert payload["treatment_versions"] == ["1.3"]
        assert {x["entry"] for x in payload["out_of_arm"]} == {
            str(tmp_path / "stray")}
        assert payload["out_of_arm"][0]["skill_version"] == "0.9"

    def test_the_no_arm_repo_is_reported_not_dropped(self, tmp_path: Path):
        """A gate that quietly shrinks its own sample is the failure out-of-arm
        reporting was added to prevent. Moving the rule from the roster to the
        row must not lose the report with it."""
        spec = _three_pairs(tmp_path)
        _member(tmp_path, "stray", 9000, 7000, "0.9")
        spec.append(("stray", "b", "9"))
        r = _arms(_roster(tmp_path, spec))
        assert "not in either arm" in r.stdout, r.stdout
        assert "stray" in r.stdout
        assert "0.9" in r.stdout

    def test_a_repo_with_no_attributed_run_is_in_no_arm(self, tmp_path: Path):
        """No scored row, no version, no arm — and it must say so rather than
        being counted into the arm its wave names and reported as an arm member
        that measured nothing."""
        spec = _three_pairs(tmp_path)
        d = tmp_path / "fresh" / ".skills"
        d.mkdir(parents=True)
        (d / "context-metrics.jsonl").write_text(
            _row(repo="fresh", tokens=9000, actions=["baseline:exact"]) + "\n")
        spec.append(("fresh", "b", "9"))
        payload = _json(_arms(_roster(tmp_path, spec), "--format", "json"))
        assert _rec(payload, "fresh")["arm"] is None
        assert payload["treatment_versions"] == ["1.3"]

    def test_wave_no_longer_partitions_the_arms_at_all(self, tmp_path: Path):
        """The annotations reversed against the versions. Rollout order is not
        evidence about which version a repo runs, so a roster labelled backwards
        must score exactly as one labelled forwards."""
        spec = []
        for i, (cb, ca, tb, ta) in enumerate(
                [(52000, 20000, 49000, 12000), (28000, 12000, 26000, 9000)], 1):
            _member(tmp_path, f"ctl{i}", cb, ca, "1.2")
            _member(tmp_path, f"trt{i}", tb, ta, "1.3")
            # Deliberately inverted: the control version sits under wave b.
            spec += [(f"ctl{i}", "b", str(i)), (f"trt{i}", "a", str(i))]
        r = _arms(_roster(tmp_path, spec), "--min-pairs", "2")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "verdict: ADOPT" in r.stdout
        assert "arms look" not in r.stdout


class TestSafetyGatesFollowTheVersion:
    """`arm()` is deliberately wider than the pairing — safety is not a property
    of a comparison. Which side of the veto a failure lands on must still be the
    row's version."""

    def test_a_failure_on_the_treatment_version_rejects_whatever_its_wave_says(
            self, tmp_path: Path):
        spec = _three_pairs(tmp_path)
        # wave a — the control side by rollout order — but the row says 1.3.
        _member(tmp_path, "ctl2", 28000, 12000, "1.3", no_loss="failed")
        r = _arms(_roster(tmp_path, spec), "--min-pairs", "1")
        assert r.returncode == 3, r.stdout + r.stderr
        assert "verdict: REJECT" in r.stdout
        assert "safety gate tripped in the treatment arm" in r.stdout
        assert "treatment-arm safety failures:" in r.stdout
        assert "control-arm safety failures" not in r.stdout

    def test_a_failure_on_a_version_in_neither_arm_vetoes_nothing(
            self, tmp_path: Path):
        """A repo six releases adrift did not fail under the proposal, so it
        cannot reject it. Grouped by wave it would have."""
        spec = _three_pairs(tmp_path)
        _member(tmp_path, "stray", 9000, 7000, "0.9", no_loss="failed")
        spec.append(("stray", "b", "9"))
        r = _arms(_roster(tmp_path, spec))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "verdict: ADOPT" in r.stdout
        assert "treatment-arm safety failures" not in r.stdout

    def test_an_unverified_run_is_placed_by_its_version(self, tmp_path: Path):
        """`no_loss` absent blocks adoption without rejecting. Which arm it
        blocks is the row's version."""
        spec = _three_pairs(tmp_path)
        _member(tmp_path, "ctl3", 19000, 9000, "1.3", no_loss=None)
        r = _arms(_roster(tmp_path, spec), "--min-pairs", "1")
        assert r.returncode == 5, r.stdout
        assert "safety could not be verified in the treatment arm" in r.stdout
        assert "ctl3" in r.stdout


class TestThePairingStaysRosterDriven:
    """`pair:` encodes size-matching against the 2026-08-05 baseline — a
    property of the repos, not of any run — so it does NOT move to the row."""

    def test_pair_comes_from_the_roster_not_from_the_versions(
            self, tmp_path: Path):
        """Two repos on the treatment version sharing a pair is still a
        malformed pair. If the pairing had followed the versions there would be
        nothing left to malform."""
        _member(tmp_path, "one", 52000, 20000, "1.3")
        _member(tmp_path, "two", 49000, 12000, "1.3")
        r = _arms(_roster(tmp_path, [("one", "a", "1"), ("two", "b", "1")]),
                  "--min-pairs", "1", "--format", "json")
        pair = _json(r)["pairs"][0]
        assert "2 treatment and 0 control" in pair["why"], pair

    def test_a_pair_whose_member_left_the_arm_names_the_repo(
            self, tmp_path: Path):
        """"0 treatment and 1 control" on its own sends the reader to the
        roster, which is correct and unchanged. The reason is on the other
        repo's row."""
        _member(tmp_path, "one", 52000, 20000, "1.2")
        _member(tmp_path, "two", 49000, 12000, "0.9")
        r = _arms(_roster(tmp_path, [("one", "a", "1"), ("two", "b", "1")]),
                  "--min-pairs", "1")
        assert "two is in neither arm" in r.stdout, r.stdout
        assert "0.9" in r.stdout

    def test_a_pair_with_both_members_out_of_the_arms_still_appears(
            self, tmp_path: Path):
        """Every roster pair is listed. A pair that vanishes because neither
        member matched a version is the sample shrinking silently."""
        spec = _three_pairs(tmp_path)
        _member(tmp_path, "x1", 9000, 7000, "0.9")
        _member(tmp_path, "x2", 9000, 7000, "0.9")
        spec += [("x1", "a", "9"), ("x2", "b", "9")]
        payload = _json(_arms(_roster(tmp_path, spec), "--format", "json"))
        pair9 = next(p for p in payload["pairs"] if p["pair"] == "9")
        assert "0 treatment and 0 control" in pair9["why"], pair9


class TestTheFlagsNameVersions:
    """`--treatment`/`--control` stop naming waves and start naming versions —
    which is what the pre-registration already records as `treatment_version`
    and `control_version`, so the flags and the registration finally agree."""

    def test_the_flags_are_read_as_versions(self, tmp_path: Path):
        """A roster whose waves are neither `a` nor `b`. Under the old rule
        every repo fell out of both arms; under the new one the waves are
        decoration and the versions decide."""
        _member(tmp_path, "one", 52000, 20000, "1.2")
        _member(tmp_path, "two", 49000, 12000, "1.3")
        r = _arms(_roster(tmp_path, [("one", "x", "1"), ("two", "y", "1")]),
                  "--min-pairs", "1")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "verdict: ADOPT" in r.stdout

    def test_omitting_them_without_a_registration_is_a_usage_error(
            self, tmp_path: Path):
        """There is no sensible default version, and picking one off the
        ledgers would choose the comparison after seeing the rows."""
        r = _score(_roster(tmp_path, [("one", "a", "1")]))
        assert r.returncode == 1, r.stdout
        assert "--treatment" in r.stderr and "--control" in r.stderr
        assert "--experiment" in r.stderr, r.stderr

    def test_they_default_to_the_registration(self, tmp_path: Path):
        """The registration is the pre-registered statement of which two
        versions are being compared, so a run that cites one needs no flags."""
        spec = _three_pairs(tmp_path)
        _register(tmp_path)
        r = _score(_roster(tmp_path, spec), "--experiments-dir",
                   str(tmp_path / "experiments"), "--experiment", "02",
                   "--format", "json")
        payload = _json(r)
        assert payload["treatment_version"] == "1.3"
        assert payload["control_version"] == "1.2"
        assert payload["verdict"] == "ADOPT", payload["reasons"]

    def test_flags_disagreeing_with_the_registration_are_refused(
            self, tmp_path: Path):
        """A registration for 1.3-over-1.2 scored as 1.2-over-1.1 is a verdict
        about a different comparison. Checkable directly now that both name
        versions."""
        spec = _three_pairs(tmp_path)
        _register(tmp_path)
        r = _score(_roster(tmp_path, spec), "--experiments-dir",
                   str(tmp_path / "experiments"), "--experiment", "02",
                   "--treatment", "1.2", "--control", "1.1")
        assert r.returncode == 5, r.stdout
        assert "not the experiment that was registered" in r.stdout

    def test_naming_one_release_twice_is_a_usage_error(self, tmp_path: Path):
        """1.2 and v1.2.0 are one release. Before #194 this was a verdict about
        the rows; it is now a mistyped invocation, and no data can fix it."""
        r = _score(_roster(tmp_path, [("one", "a", "1")]),
                   "--treatment", "1.2", "--control", "v1.2.0")
        assert r.returncode == 1, r.stdout
        assert "same release" in r.stderr, r.stderr

    def test_the_older_version_as_treatment_is_still_caught(
            self, tmp_path: Path):
        """Get the direction backwards and a winning change reads as a losing
        one. Read off the flags now rather than inferred from the arms."""
        spec = _three_pairs(tmp_path)
        r = _score(_roster(tmp_path, spec), "--treatment", "1.2",
                   "--control", "1.3")
        assert r.returncode == 5, r.stdout
        assert "--treatment 1.3 --control 1.2" in r.stdout
        assert "verdict: REJECT" not in r.stdout

    def test_a_wave_name_in_the_flags_is_named_as_one(self, tmp_path: Path):
        """`--treatment b --control a` is what every doc said to type until
        #194, and it still runs: `b` and `a` are simply versions no row
        carries, so both arms come out empty and the verdict is INCONCLUSIVE —
        which reads as an experiment that found nothing rather than as a
        mistyped invocation. The roster is what disambiguates."""
        spec = _three_pairs(tmp_path)
        r = _score(_roster(tmp_path, spec), "--treatment", "b", "--control", "a")
        assert r.returncode == 5, r.stdout
        assert "names a wave in this roster" in r.stdout or \
               "name waves in this roster" in r.stdout, r.stdout
        assert "--experiment NN" in r.stdout

    def test_two_real_versions_draw_no_wave_hint(self, tmp_path: Path):
        """The hint keys on the roster's own `wave:` values, so it must stay
        silent for a comparison that merely has nothing measured yet."""
        spec = _three_pairs(tmp_path)
        r = _score(_roster(tmp_path, spec), "--treatment", "9.9",
                   "--control", "9.8")
        assert "in this roster, not versions" not in r.stdout, r.stdout

    def test_a_non_numeric_version_draws_no_inversion_claim(
            self, tmp_path: Path):
        """version_key maps every non-numeric component to 0, so `vNext` keys
        to (0,) and compares older than every numbered release. Reported as an
        inversion it is a confident diagnosis pointing at flags that are not
        the problem — the same shape as the v1.2-vs-1.2 defect, from the other
        side. No numeric lead, no opinion about order."""
        spec = _three_pairs(tmp_path)
        r = _score(_roster(tmp_path, spec), "--treatment", "vNext",
                   "--control", "1.3")
        assert "OLDER than" not in r.stdout, r.stdout
        assert "verdict: REJECT" not in r.stdout

    def test_the_help_calls_them_versions(self):
        r = subprocess.run(["bash", str(SCORE), "--help"],
                           capture_output=True, text=True, timeout=30)
        assert r.returncode == 0
        assert re.search(r"^\s+--treatment VERSION\b", r.stdout, re.M), r.stdout
        assert re.search(r"^\s+--control VERSION\b", r.stdout, re.M), r.stdout


class TestAttributionFollowsTheVersion:
    """`attributed()` — the site #117 added and the issue body's enumeration
    missed. It feeds both named outcomes #117 introduced."""

    def test_instrument_only_reads_the_row_not_the_wave(self, tmp_path: Path):
        """"This proposal added its own instrument" means the field is null on
        every CONTROL row. A wave-a repo that has already moved to the treatment
        version and records the field is a treatment row; counted as a control
        row it silently refutes the outcome."""
        spec = []
        for i, (cb, ca, tb, ta) in enumerate(
                [(52000, 20000, 49000, 12000), (28000, 12000, 26000, 9000)], 1):
            _member(tmp_path, f"ctl{i}", cb, ca, "1.2")
            _member(tmp_path, f"trt{i}", tb, ta, "1.3", seams=2)
            spec += [(f"ctl{i}", "a", str(i)), (f"trt{i}", "b", str(i))]
        # Annotated into the control half, running the treatment version, and
        # recording the instrument.
        _member(tmp_path, "drift", 19000, 9000, "1.3", seams=1)
        spec.append(("drift", "a", "9"))
        _register(tmp_path, primary_metric="seams", direction="lower")
        r = _score(_roster(tmp_path, spec), "--experiments-dir",
                   str(tmp_path / "experiments"), "--experiment", "02",
                   "--format", "json")
        payload = _json(r)
        assert _rec(payload, "drift")["arm"] == "treatment"
        assert payload["added_its_own_instrument"] is True, payload["reasons"]

    def test_an_unreadable_metric_is_not_rescued_by_a_no_arm_row(
            self, tmp_path: Path):
        """The mirror. A repo on a third version carrying the field is evidence
        about neither arm, and counting it into one turns "this gate cannot read
        the metric at all" into "the proposal added an instrument" — a different
        diagnosis pointing somewhere else."""
        spec = []
        for i, (cb, ca, tb, ta) in enumerate(
                [(52000, 20000, 49000, 12000), (28000, 12000, 26000, 9000)], 1):
            _member(tmp_path, f"ctl{i}", cb, ca, "1.2")
            _member(tmp_path, f"trt{i}", tb, ta, "1.3")
            spec += [(f"ctl{i}", "a", str(i)), (f"trt{i}", "b", str(i))]
        _member(tmp_path, "stray", 19000, 9000, "0.9", seams=3)
        spec.append(("stray", "b", "9"))
        _register(tmp_path, primary_metric="seams", direction="lower")
        r = _score(_roster(tmp_path, spec), "--experiments-dir",
                   str(tmp_path / "experiments"), "--experiment", "02",
                   "--format", "json")
        payload = _json(r)
        assert payload["metric_unreadable"] is True, payload["reasons"]
        assert payload["added_its_own_instrument"] is False


class TestTheSystemicDefectCheckCountsByVersion:
    """`t_arm_n`/`c_arm_n`. "No repo in either arm can satisfy this rule" is an
    inference from breadth, and the breadth has to be the arms as scored."""

    def test_a_no_arm_repo_does_not_make_up_the_per_arm_floor(
            self, tmp_path: Path):
        """One treatment repo and one adrift is not two treatment repos, and a
        GATE DEFECT declared off it is the thin evidence the floor refuses."""
        _member(tmp_path, "c1", None, 20000, "1.2")
        _member(tmp_path, "c2", None, 14000, "1.2")
        _member(tmp_path, "t1", None, 12000, "1.3")
        _member(tmp_path, "stray", None, 9000, "0.9")
        roster = _roster(tmp_path, [("c1", "a", "1"), ("t1", "b", "1"),
                                    ("c2", "a", "2"), ("stray", "b", "2")])
        payload = _json(_arms(roster, "--min-pairs", "1", "--format", "json"))
        # Stated positively as well, so the assertion below cannot pass merely
        # because nothing landed in an arm at all.
        assert _rec(payload, "t1")["arm"] == "treatment"
        assert _rec(payload, "stray")["arm"] is None
        assert payload["systemic_unscorable"] is None, payload["reasons"]
        assert "GATE DEFECT" not in _arms(roster, "--min-pairs", "1").stdout

    def test_the_defect_still_fires_when_both_arms_really_are_full(
            self, tmp_path: Path):
        for name, ver in (("c1", "1.2"), ("c2", "1.2"),
                          ("t1", "1.3"), ("t2", "1.3")):
            _member(tmp_path, name, None, 12000, ver)
        r = _arms(_roster(tmp_path, [("c1", "a", "1"), ("t1", "b", "1"),
                                     ("c2", "a", "2"), ("t2", "b", "2")]),
                  "--min-pairs", "1")
        assert "GATE DEFECT" in r.stdout, r.stdout
        assert "record-telemetry.sh --baseline" in r.stdout

    def test_an_untagged_run_still_lands_in_its_arm(self, tmp_path: Path):
        """An untagged row carries a `skill_version` — that is how the gate
        found it — so it has an arm even though it cannot be scored. Dropping it
        into no arm would make the untagged-run defect undetectable, which is
        the one hint that tells the reader to re-run Phase 7."""
        for name, ver in (("c1", "1.2"), ("c2", "1.2"),
                          ("t1", "1.3"), ("t2", "1.3")):
            _member(tmp_path, name, 50000, 12000, ver, actions=())
        roster = _roster(tmp_path, [("c1", "a", "1"), ("t1", "b", "1"),
                                    ("c2", "a", "2"), ("t2", "b", "2")])
        payload = _json(_arms(roster, "--min-pairs", "1", "--format", "json"))
        assert _rec(payload, "t1")["arm"] == "treatment"
        assert _rec(payload, "c1")["arm"] == "control"
        r = _arms(roster, "--min-pairs", "1")
        assert "GATE DEFECT" in r.stdout, r.stdout
        assert "--actions" in r.stdout


class TestTheRosterGateAsksForPairs:
    """The roster gate refused a roster carrying no `wave:` assignment, "so
    there are no arms to compare". The arms no longer come from there. What the
    roster still has to carry is `pair:`."""

    def test_a_roster_with_no_pair_annotation_is_refused(self, tmp_path: Path):
        path = tmp_path / "cohort"
        path.write_text("CannObserv/archiver  wave:a\n"
                        "CannObserv/notifier  wave:b\n")
        r = _score(path, "--treatment", "1.3", "--control", "1.2")
        assert r.returncode == 1
        assert "pair" in r.stderr
        assert "wave:a pair:1" in r.stderr

    def test_a_paired_roster_with_no_waves_is_accepted(self, tmp_path: Path):
        """`wave:` is rollout order. A roster that never recorded one still
        describes a comparison."""
        _member(tmp_path, "one", 52000, 20000, "1.2")
        _member(tmp_path, "two", 49000, 12000, "1.3")
        path = tmp_path / "cohort"
        path.write_text(f"{tmp_path / 'one'}  pair:1\n"
                        f"{tmp_path / 'two'}  pair:1\n")
        r = _score(path, "--treatment", "1.3", "--control", "1.2",
                   "--min-pairs", "1")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "verdict: ADOPT" in r.stdout
