"""Pre-registration: the metric is committed before the arms are read (#117).

`validation-gate.md` said "pre-register a primary metric" in prose, which is
unfalsifiable. Prose cannot be violated, only disagreed with, and the failure it
is aimed at leaves no trace: a proposer who scores four metrics and reports the
one that won has produced output indistinguishable from a proposer who declared
one in advance. The only difference is what existed *before* the rows were read,
so the mechanism has to be an artefact with a history.

That artefact is `.skills/experiments/NN-<slug>.yml`, and the guarantee is
negative: **there is no `--metric` flag.** A flag that names a metric lets the
same run be repeated until the answer is agreeable, which is the identical
failure to picking the before-state after seeing the after-values (#116). The
metric comes from the committed file or the gate scores the default it has always
scored. Git history of the file is the pre-registration proof — checkable by
someone who was not in the room, which is the whole point.

Three registration rules are enforced here rather than asserted in prose:

1. **The arm predicate is `skill_version`, and nothing else.** #118/#168 settled
   that the arm a run belongs to is the version stamped on its own row —
   observed, never assigned. A registration naming `wave` would declare the arm
   assignable, reopening a settled argument in a file nobody re-reads. It is
   refused by name.
2. **A rejected metric cannot be registered.** `tokens_live` was proposed as a
   primary in #118 despite already carrying an entry in `rejected-changes.md` —
   the exact failure that file exists to prevent, occurring in the issue
   proposing the next round of metrics. The registration consults the file.
3. **The arms observed must be the arms registered.** Scoring 1.3-vs-1.2 against
   a registration for 1.4-vs-1.3 is not a weak verdict, it is a verdict about a
   different experiment — and it could write a REJECT naming the wrong change.

And two outcomes that were previously silent:

- A proposal whose metric is null across every control-arm row **added its own
  instrument**, and cannot be judged by it. Named, rather than scored across the
  asymmetry: the comparison that would be needed (detection-on-unswept against
  resolved-during-run) is one the script cannot validate is being used honestly.
- **Saturation is counted and printed.** A round where most pairs saturated is a
  finding about the budget no longer binding, not a tie. It is emphatically NOT
  a licence to retighten the budget after seeing where the cohort landed —
  that is the same integrity failure as choosing the metric late, and
  `rejected-changes.md` already carries the precedent.
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
GATE = REFERENCES / "validation-gate.md"
REJECTED = REFERENCES / "rejected-changes.md"
EXPERIMENTS = ROOT / ".skills" / "experiments"
TEMPLATE = EXPERIMENTS / "TEMPLATE.yml"

REQUIRED_KEYS = (
    "experiment", "proposal", "registered", "treatment_version",
    "control_version", "arm_predicate", "primary_metric", "direction",
    "min_pairs",
)


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    return env


def _flat(text: str) -> str:
    """Prose with its wrapping and emphasis removed — see test_arm_predicate."""
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
            **extra) -> None:
    """A member with a baseline row and one scored curation.

    `extra` lands on the scored row only, which is the row score-cohort.sh
    reads: a field set on the baseline as well would make every "is this field
    null in the control arm" test pass for the wrong reason.
    """
    d = root / name / ".skills"
    d.mkdir(parents=True, exist_ok=True)
    rows = [
        _row(repo=name, tokens=before, actions=["baseline:pre-curation"]),
        _row(repo=name, tokens=after, actions=["demote:Big"], ts="2026-08-06",
             skill_version=version, skill_commit="deadbee", **extra),
    ]
    (d / "context-metrics.jsonl").write_text("\n".join(rows) + "\n")


def _roster(root: Path, spec) -> Path:
    path = root / "cohort"
    path.write_text("".join(
        f"{root / name}  wave:{w} pair:{p}\n" for name, w, p in spec))
    return path


def _cohort(root: Path, *, sizes=None, t_extra=None, c_extra=None,
            t_version="1.3", c_version="1.2") -> Path:
    """Three pairs, treatment newer than control, all six scorable."""
    sizes = sizes or [(52000, 20000, 49000, 12000),
                      (28000, 12000, 26000, 9000),
                      (19000, 10000, 18000, 8000)]
    spec = []
    for i, (cb, ca, tb, ta) in enumerate(sizes, 1):
        _member(root, f"ctl{i}", cb, ca, c_version, **(c_extra or {}))
        _member(root, f"trt{i}", tb, ta, t_version, **(t_extra or {}))
        spec += [(f"ctl{i}", "a", str(i)), (f"trt{i}", "b", str(i))]
    return _roster(root, spec)


def _register(root: Path, name: str = "02-a-proposal.yml", **over) -> Path:
    d = root / "experiments"
    d.mkdir(parents=True, exist_ok=True)
    fields = {
        "experiment": "02",
        "proposal": "https://github.com/gregoryfoster/skills/issues/117",
        "registered": "2026-08-17",
        "treatment_version": "1.3",
        "control_version": "1.2",
        "arm_predicate": "skill_version",
        "primary_metric": "closure",
        "direction": "higher",
        "min_pairs": "3",
    }
    fields.update({k: v for k, v in over.items() if v is not None})
    for k in [k for k, v in over.items() if v is None]:
        fields.pop(k, None)
    (d / name).write_text(
        "".join(f"{k}: {v}\n" for k, v in fields.items()))
    return d


def _score(roster: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCORE), "--cohort-file", str(roster),
         "--treatment", "b", "--control", "a", *args],
        capture_output=True, text=True, env=_clean_env(), timeout=60,
    )


def _refused(r: subprocess.CompletedProcess) -> str:
    """stderr, once it is established the refusal came from the registration.

    An unknown-argument error prints the whole usage text, which mentions the
    direction of the arms, rollout order and #118 — so every "the error names
    X" assertion below would pass on a script that had never heard of
    `--experiment`. Asserted away rather than worked around: these tests have to
    be able to fail before the feature exists.
    """
    assert r.returncode == 1, r.stdout
    assert "unknown argument" not in r.stderr, (
        "this is an argument-parsing error, not a registration refusal:\n"
        + r.stderr)
    return r.stderr


class TestTheMetricCannotComeFromAFlag:
    """The negative guarantee, and the one worth a test of its own.

    Every other rule here can be argued about. This one is what makes the
    argument moot: with no flag, re-running cannot change the metric, so the
    only way to change it is to amend a committed file and leave the amendment
    in the history.
    """

    def test_a_metric_flag_is_refused(self, tmp_path: Path):
        r = _score(_cohort(tmp_path), "--metric", "seams")
        assert r.returncode == 1, r.stdout
        assert "unknown argument" in r.stderr, r.stderr

    def test_the_help_offers_no_way_to_name_a_metric(self):
        r = subprocess.run(["bash", str(SCORE), "--help"],
                           capture_output=True, text=True, timeout=30)
        assert "--metric " not in r.stdout, r.stdout
        assert "--experiment" in r.stdout, r.stdout

    def test_the_help_says_why_there_is_no_flag(self):
        r = subprocess.run(["bash", str(SCORE), "--help"],
                           capture_output=True, text=True, timeout=30)
        flat = _flat(r.stdout).lower()
        assert "no --metric flag" in flat, r.stdout
        assert "committed" in flat, r.stdout


class TestTheGateResolvesACommittedRegistration:
    def test_it_reads_the_file_named_by_its_number(self, tmp_path: Path):
        roster = _cohort(tmp_path)
        _register(tmp_path)
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02", "--format", "json")
        payload = json.loads(r.stdout)
        assert payload["experiment"]["primary_metric"] == "closure"
        assert payload["experiment"]["file"].endswith("02-a-proposal.yml")

    def test_a_missing_registration_is_a_usage_error_naming_the_directory(
            self, tmp_path: Path):
        """Not INCONCLUSIVE. Nothing was scored, so there is no verdict to
        report — and a verdict-shaped output would suggest the experiment ran."""
        roster = _cohort(tmp_path)
        (tmp_path / "experiments").mkdir()
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "07")
        err = _refused(r)
        assert "experiments" in err and "07" in err, err

    def test_two_files_claiming_one_number_are_refused(self, tmp_path: Path):
        roster = _cohort(tmp_path)
        _register(tmp_path, "02-a-proposal.yml")
        _register(tmp_path, "02-another-proposal.yml")
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02")
        err = _refused(r)
        assert "02-a-proposal.yml" in err, err
        assert "02-another-proposal.yml" in err, err

    def test_the_number_inside_must_match_the_filename(self, tmp_path: Path):
        """A registration copied from another and edited keeps the old number
        in its body. The file it is scored as, and the file it says it is, have
        to be the same file — or the history proving pre-registration is some
        other experiment's history."""
        roster = _cohort(tmp_path)
        _register(tmp_path, "02-a-proposal.yml", experiment="03")
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02")
        err = _refused(r)
        assert "03" in err and "02" in err, err

    def test_a_missing_required_key_is_named(self, tmp_path: Path):
        roster = _cohort(tmp_path)
        _register(tmp_path, direction=None)
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02")
        assert "direction" in _refused(r)

    def test_the_default_scoring_needs_no_registration(self, tmp_path: Path):
        """Closure with `higher` is what this gate has always scored, and that
        default is itself pre-registered — in `validation-gate.md`'s `## The
        metric`, committed long before any of these rows. Requiring a file to
        re-state it would buy no integrity and break every existing caller."""
        r = _score(_cohort(tmp_path), "--format", "json")
        payload = json.loads(r.stdout)
        assert payload["experiment"] is None
        assert payload["primary_metric"] == "closure"


class TestTheArmPredicateIsTheRowStamp:
    """#118/#168: the arm is the `skill_version` on the row. Observed, never
    assigned. The schema names the field rather than leaving it implied,
    because the field is the whole content of that decision."""

    def test_skill_version_is_accepted(self, tmp_path: Path):
        roster = _cohort(tmp_path)
        _register(tmp_path)
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02", "--format", "json")
        assert json.loads(r.stdout)["experiment"]["arm_predicate"] \
            == "skill_version"

    def test_wave_is_refused_by_name(self, tmp_path: Path):
        """The specific wrong answer, refused specifically. A generic "not a
        legal value" would let the next reader think it was a typo."""
        roster = _cohort(tmp_path)
        _register(tmp_path, arm_predicate="wave")
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02")
        err = _refused(r)
        assert "wave" in err, err
        assert "rollout order" in _flat(err).lower(), err
        assert "118" in err or "168" in err, err

    def test_the_refusal_gives_the_load_bearing_reason(self, tmp_path: Path):
        """Not the drift argument — #118's CI correction refutes that one. The
        reason is that the rows a pin versions deterministically are exactly
        the rows this script refuses to score."""
        roster = _cohort(tmp_path)
        _register(tmp_path, arm_predicate="wave")
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02")
        assert "baseline:scheduled" in _refused(r)


class TestARejectedMetricCannotBeRegistered:
    def test_tokens_live_is_refused(self, tmp_path: Path):
        roster = _cohort(tmp_path)
        _register(tmp_path, primary_metric="tokens_live")
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02")
        err = _refused(r)
        assert "tokens_live" in err, err
        assert "rejected-changes.md" in err, err

    def test_the_refusal_reads_the_shipped_file_rather_than_a_hardcoded_list(
            self):
        """The coupling that makes this maintainable: adding a rejection entry
        is what retires a metric, in one place. Pinned so that a later
        `REJECTED_METRICS = {...}` constant in the script fails here."""
        assert "`tokens_live`" in REJECTED.read_text()
        assert "tokens_live" not in SCORE.read_text(), (
            "the rejected-metric check must read references/rejected-changes.md, "
            "not carry its own copy of the list")

    def test_a_metric_with_no_rejection_entry_is_allowed(self, tmp_path: Path):
        roster = _cohort(tmp_path, t_extra={"seams": 0}, c_extra={"seams": 4})
        _register(tmp_path, primary_metric="seams", direction="lower")
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02", "--format", "json")
        assert r.returncode == 0, r.stdout + r.stderr
        assert json.loads(r.stdout)["primary_metric"] == "seams"


class TestTheArmsObservedMustBeTheArmsRegistered:
    def test_a_mismatch_is_inconclusive_not_a_rejection(self, tmp_path: Path):
        """The worst output this script can produce is naming a change as
        refuted when the comparison was mislabelled. A registration for a
        comparison that is not the one in front of it is exactly that."""
        roster = _cohort(tmp_path, t_version="1.3", c_version="1.2")
        _register(tmp_path, treatment_version="1.4", control_version="1.3")
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02")
        assert r.returncode == 5, r.stdout
        assert "INCONCLUSIVE" in r.stdout, r.stdout
        assert "1.4" in r.stdout and "1.3" in r.stdout, r.stdout

    def test_spelling_differences_do_not_trip_it(self, tmp_path: Path):
        """`v1.3`, `1.3` and `1.3.0` are one release — the script already
        canonicalises for every other version test and must here too, or the
        registration reads as a mismatch for a cosmetic difference."""
        roster = _cohort(tmp_path, t_version="1.3.0", c_version="1.2")
        _register(tmp_path, treatment_version="v1.3")
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02")
        assert r.returncode == 0, r.stdout + r.stderr


class TestAProposalIsNotJudgedByAnInstrumentItAdded:
    """Proposal 2, as a named outcome rather than as asymmetric scoring.

    A field null on every control-arm row is a field the control arm's version
    did not record. The proposal added the measurement, which buys measurability
    for LATER rounds and not for its own — the rule `validation-gate.md` already
    stated in prose, now reachable from the verdict ladder.
    """

    def test_a_null_control_column_is_named_as_the_reason(self, tmp_path: Path):
        roster = _cohort(tmp_path, t_extra={"seams": 0})
        _register(tmp_path, primary_metric="seams", direction="lower")
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02")
        assert r.returncode == 5, r.stdout
        flat = _flat(r.stdout).lower()
        assert "its own instrument" in flat, r.stdout
        assert "seams" in r.stdout, r.stdout

    def test_it_is_not_recorded_as_a_rejection(self, tmp_path: Path):
        roster = _cohort(tmp_path, t_extra={"seams": 0})
        _register(tmp_path, primary_metric="seams", direction="lower")
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02")
        assert "rejected-changes.md" in r.stdout, r.stdout
        assert "not a rejection" in _flat(r.stdout), r.stdout

    def test_one_control_row_carrying_the_field_is_enough_to_score(
            self, tmp_path: Path):
        """EVERY control row, not most. One measured control surface is a weak
        comparison, and a weak comparison is still a comparison — the script
        does not get to decide it is too weak."""
        sizes = [(52000, 20000, 49000, 12000), (28000, 12000, 26000, 9000),
                 (19000, 10000, 18000, 8000)]
        spec = []
        for i, (cb, ca, tb, ta) in enumerate(sizes, 1):
            _member(tmp_path, f"ctl{i}", cb, ca, "1.2",
                    **({"seams": 9} if i == 1 else {}))
            _member(tmp_path, f"trt{i}", tb, ta, "1.3", seams=0)
            spec += [(f"ctl{i}", "a", str(i)), (f"trt{i}", "b", str(i))]
        roster = _roster(tmp_path, spec)
        _register(tmp_path, primary_metric="seams", direction="lower",
                  min_pairs="1")
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02")
        assert "its own instrument" not in _flat(r.stdout).lower(), r.stdout

    def test_a_safety_failure_still_rejects_ahead_of_it(self, tmp_path: Path):
        """Content lost under the proposed version is lost whether or not the
        metric could see anything. The instrument branch must not swallow the
        safety veto — it sits below it in the ladder for that reason."""
        roster = _cohort(tmp_path, t_extra={"seams": 0, "no_loss": "FAILED"})
        _register(tmp_path, primary_metric="seams", direction="lower")
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02")
        assert r.returncode == 3, r.stdout
        assert "REJECT" in r.stdout, r.stdout


class TestTheRegisteredDirectionDecidesTheWinner:
    def test_lower_is_better_inverts_who_wins(self, tmp_path: Path):
        roster = _cohort(tmp_path, t_extra={"seams": 2}, c_extra={"seams": 7})
        _register(tmp_path, primary_metric="seams", direction="lower")
        won = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                     "--experiment", "02")
        assert won.returncode == 0, won.stdout + won.stderr

        _register(tmp_path, primary_metric="seams", direction="higher")
        lost = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                      "--experiment", "02")
        assert lost.returncode == 3, lost.stdout

    def test_an_unknown_direction_is_refused(self, tmp_path: Path):
        roster = _cohort(tmp_path)
        _register(tmp_path, direction="better")
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02")
        assert "direction" in _refused(r)

    def test_equal_values_are_uninformative_not_a_tie(self, tmp_path: Path):
        """Same rule closure already applies at its cap: "the metric cannot
        separate them" is a different claim from "they are equal"."""
        roster = _cohort(tmp_path, t_extra={"seams": 3}, c_extra={"seams": 3})
        _register(tmp_path, primary_metric="seams", direction="lower")
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02", "--format", "json")
        payload = json.loads(r.stdout)
        assert payload["informative_pairs"] == 0
        assert payload["verdict"] == "INCONCLUSIVE"

    def test_the_registered_pair_floor_is_used(self, tmp_path: Path):
        """The floor is a pre-registered parameter of the experiment, not a
        flag chosen once the pair count is known — the same argument as the
        metric, applied to the number the metric is judged against."""
        roster = _cohort(tmp_path, sizes=[(52000, 20000, 49000, 12000)])
        _register(tmp_path, min_pairs="3")
        r = _score(roster, "--experiments-dir", str(tmp_path / "experiments"),
                   "--experiment", "02", "--format", "json")
        payload = json.loads(r.stdout)
        assert payload["min_pairs"] == 3
        assert payload["verdict"] == "INCONCLUSIVE"


class TestSaturationIsCountedAndPrinted:
    """Proposal 3. Four uninformative pairs out of six because closure hit its
    cap is a finding about the budget no longer binding for most of the cohort,
    and it read as "nothing happened"."""

    def test_the_count_is_printed(self, tmp_path: Path):
        roster = _cohort(tmp_path, sizes=[(52000, 3000, 49000, 3000),
                                          (28000, 12000, 26000, 9000),
                                          (19000, 10000, 18000, 8000)])
        r = _score(roster)
        assert "saturated" in r.stdout.lower(), r.stdout
        assert "1 of 3" in r.stdout, r.stdout

    def test_a_majority_saturated_round_is_a_finding(self, tmp_path: Path):
        roster = _cohort(tmp_path, sizes=[(52000, 3000, 49000, 3000),
                                          (28000, 3000, 26000, 3000),
                                          (19000, 10000, 18000, 8000)])
        r = _score(roster)
        flat = _flat(r.stdout).lower()
        assert "finding" in flat, r.stdout
        assert "no longer the binding constraint" in flat, r.stdout

    def test_the_finding_refuses_to_license_retightening_the_budget(
            self, tmp_path: Path):
        """The trap this proposal walks straight into. Changing the budget
        after seeing where the cohort landed is the same integrity failure as
        choosing the metric late, and `rejected-changes.md` carries the
        precedent — the 4,000 budget was refused for being derived from where
        repos happened to sit."""
        roster = _cohort(tmp_path, sizes=[(52000, 3000, 49000, 3000),
                                          (28000, 3000, 26000, 3000),
                                          (19000, 10000, 18000, 8000)])
        r = _score(roster)
        flat = _flat(r.stdout).lower()
        assert "retroactive" in flat or "not a reason to tighten" in flat, r.stdout
        assert "pre-registered" in flat, r.stdout

    def test_json_carries_the_count(self, tmp_path: Path):
        roster = _cohort(tmp_path, sizes=[(52000, 3000, 49000, 3000),
                                          (28000, 12000, 26000, 9000)])
        payload = json.loads(_score(roster, "--format", "json").stdout)
        assert payload["saturated_pairs"] == 1

    def test_it_does_not_move_the_verdict(self, tmp_path: Path):
        """It reports. A saturated round is not a reason to adopt or reject
        anything, and a notice that moved an exit code would be a gate."""
        clean = _score(_cohort(tmp_path / "a"))
        (tmp_path / "b").mkdir(parents=True, exist_ok=True)
        sat = _score(_cohort(tmp_path / "b",
                             sizes=[(52000, 3000, 49000, 3000),
                                    (28000, 12000, 26000, 9000),
                                    (19000, 10000, 18000, 8000)]))
        assert clean.returncode == sat.returncode, (clean.stdout, sat.stdout)


class TestTheCommittedRegistrationsAreValid:
    def test_the_directory_exists(self):
        assert EXPERIMENTS.is_dir(), (
            "`.skills/experiments/` is where a registration is committed; "
            "without it there is nowhere for the proof to live")

    def test_the_template_carries_every_required_key(self):
        text = TEMPLATE.read_text()
        missing = [k for k in REQUIRED_KEYS if f"{k}:" not in text]
        assert not missing, f"TEMPLATE.yml omits {missing}"

    def test_the_template_is_not_itself_an_experiment(self):
        """The filename pattern is the discriminator, so the template cannot be
        picked up by `--experiment NN` and scored as a real registration."""
        assert not TEMPLATE.name[:2].isdigit()

    def test_experiment_one_was_never_back_registered(self):
        """The finding in #117 is that experiment 1 had no pre-registered
        metric. Writing one now would be back-dating the artefact whose only
        value is its date — the precise dishonesty this mechanism exists to
        make visible."""
        assert not list(EXPERIMENTS.glob("01-*.yml")), (
            "experiment 1 ran unregistered; a file for it now would be a "
            "pre-registration written after the results")

    def test_every_committed_registration_validates(self, tmp_path: Path):
        registrations = sorted(EXPERIMENTS.glob("[0-9][0-9]-*.yml"))
        roster = _cohort(tmp_path)
        for path in registrations:
            r = _score(roster, "--experiments-dir", str(EXPERIMENTS),
                       "--experiment", path.name[:2])
            assert r.returncode != 1, (
                f"{path.name} is not a valid registration:\n{r.stderr}")


class TestTheGateRecordsTheRule:
    """`validation-gate.md` is where the rationale lives; the script cites it."""

    def test_pre_registration_is_an_artefact_with_a_path(self):
        text = GATE.read_text()
        assert ".skills/experiments/" in text, text[-3000:]

    def test_the_absence_of_a_metric_flag_is_stated_as_the_guarantee(self):
        flat = _flat(GATE.read_text())
        assert "no --metric flag" in flat, flat[-2000:]

    def test_the_arm_predicate_field_is_named(self):
        flat = _flat(GATE.read_text())
        assert "arm_predicate" in flat, flat[-2000:]

    def test_the_instrument_outcome_is_recorded(self):
        flat = _flat(GATE.read_text()).lower()
        assert "its own instrument" in flat, flat[-2000:]

    def test_saturation_does_not_license_a_retroactive_budget_change(self):
        flat = _flat(GATE.read_text()).lower()
        assert "retroactive" in flat, flat[-2000:]
