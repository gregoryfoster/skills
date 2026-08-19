"""A registered metric may name its bound, and a tie there is not a loss (#195).

`score-cohort.sh` scored every tie as a loss — *adopt only if the treatment wins
every informative pair* — with one hardcoded exception: budget-gap closure, whose
cap at 1.0 made a pair with both arms at budget **uninformative — saturated**
rather than tied. The argument for that carve-out was never about closure. At a
metric's good end the control already holds the best attainable score, so **no
treatment result could have won that pair**, and requiring one makes the sweep
rule unsatisfiable. Truthfulness — the share of scheduled rows reading `seams: 0`
— is the case that raised it: two arms both at 1.0 are both perfect, not equal.

The rule these tests pin, and the three things it deliberately is not:

1. **A registration that names `bound` gets the treatment; one that does not
   keeps today's behaviour.** There is emphatically no blanket "ties are
   uninformative" rule. On an unbounded metric a tie is real evidence of no
   effect, and dropping those pairs would make the adoption rule *easier* to
   satisfy by deleting the ones that disagree — the failure
   `rejected-changes.md` exists to record. So `bound` is OPTIONAL, and closure
   still scores a tie below its cap as a loss.
2. **Only ties are affected.** A pair with one arm at the bound and the other
   short of it is a real win or loss; the metric separated them perfectly well.
   And a tie at the metric's *worst* attainable value is a pair the treatment
   could have won and did not, which is why `bound` names ONE end — the good one,
   which `direction` already identifies — rather than a range.
3. **A bound is a claim, and a false one is refused.** A value recorded past the
   declared bound proves the metric is not bounded there. Left standing, such a
   bound would swallow ties away from the real extreme, which is the same
   easier-to-adopt failure arriving by accident instead of by rule. A bound
   nothing *reaches* is the harmless case: it changes no score, and is printed so
   its inertness is visible rather than assumed.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCORE = ROOT / "skills" / "curating-context" / "scripts" / "score-cohort.sh"
GATE = ROOT / "skills" / "curating-context" / "references" / "validation-gate.md"
TEMPLATE = ROOT / ".skills" / "experiments" / "TEMPLATE.yml"


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    return env


def _flat(text: str) -> str:
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
    """A baseline row and one scored curation; `extra` lands on the scored row.

    On the scored row only, deliberately. A registered metric set on the
    baseline as well would be read by no rule here and would mask a scorer that
    took its value from the wrong row.
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


def _cohort(root: Path, values, *, sizes=None) -> Path:
    """One pair per (treatment_value, control_value) in `values`.

    Token counts are held constant across pairs so that the only thing varying
    between them is the registered metric — a pair that dropped out for a
    closure reason would otherwise read as evidence about the bound.
    """
    spec = []
    for i, (tv, cv) in enumerate(values, 1):
        cb, ca, tb, ta = (sizes or (28000, 12000, 26000, 9000))
        _member(root, f"ctl{i}", cb, ca, "1.2", **({} if cv is None
                                                   else {"truth": cv}))
        _member(root, f"trt{i}", tb, ta, "1.3", **({} if tv is None
                                                   else {"truth": tv}))
        spec += [(f"ctl{i}", "a", str(i)), (f"trt{i}", "b", str(i))]
    return _roster(root, spec)


def _register(root: Path, **over) -> Path:
    """A registration for `truth`, higher-is-better, with a ceiling at 1.0.

    `truth` rather than `truthfulness` only because the table column is eight
    characters wide; nothing here depends on the name. It is not an entry in
    rejected-changes.md, which the scorer would refuse.
    """
    d = root / "experiments"
    d.mkdir(parents=True, exist_ok=True)
    fields = {
        "experiment": "02",
        "proposal": "https://github.com/gregoryfoster/skills/issues/195",
        "registered": "2026-08-17",
        "treatment_version": "1.3",
        "control_version": "1.2",
        "arm_predicate": "skill_version",
        "primary_metric": "truth",
        "direction": "higher",
        "bound": "1.0",
        "min_pairs": "1",
    }
    fields.update({k: v for k, v in over.items() if v is not None})
    for k in [k for k, v in over.items() if v is None]:
        fields.pop(k, None)
    (d / "02-a-proposal.yml").write_text(
        "".join(f"{k}: {v}\n" for k, v in fields.items()))
    return d


def _score(roster: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCORE), "--cohort-file", str(roster),
         "--treatment", "1.3", "--control", "1.2", *args],
        capture_output=True, text=True, env=_clean_env(), timeout=60,
    )


def _scored(root: Path, values, **over) -> dict:
    """The JSON payload for a registered run over `values`."""
    roster = _cohort(root, values)
    d = _register(root, **over)
    r = _score(roster, "--experiments-dir", str(d), "--experiment", "02",
               "--format", "json")
    assert r.stdout.startswith("{"), r.stdout + r.stderr
    return json.loads(r.stdout)


class TestATieAtTheBoundIsSaturatedNotTied:
    def test_both_arms_perfect_is_uninformative(self, tmp_path: Path):
        """The motivating case. Two arms both at 1.0 on a share are both
        perfect; scoring that as a tie makes it a loss for the treatment, and
        the treatment had no way to avoid it."""
        payload = _scored(tmp_path, [(1.0, 1.0)])
        pair = payload["pairs"][0]
        assert pair["saturated"] is True, pair
        assert pair["informative"] is False, pair
        assert pair["winner"] is None, pair
        assert payload["saturated_pairs"] == 1

    def test_the_reason_names_the_bound_and_the_metric(self, tmp_path: Path):
        payload = _scored(tmp_path, [(1.0, 1.0)])
        why = payload["pairs"][0]["why"]
        assert "1" in why and "truth" in why and "saturat" in why, why

    def test_the_table_does_not_call_it_a_tie(self, tmp_path: Path):
        roster = _cohort(tmp_path, [(1.0, 1.0)])
        d = _register(tmp_path)
        r = _score(roster, "--experiments-dir", str(d), "--experiment", "02")
        assert "-> tie" not in r.stdout, r.stdout
        assert "saturat" in r.stdout, r.stdout

    def test_a_saturated_pair_does_not_count_toward_adoption(
            self, tmp_path: Path):
        """It leaves the informative set entirely rather than becoming a free
        win. A carve-out that turned an unwinnable pair into a WIN would be the
        adoption-easier failure in its most direct form."""
        payload = _scored(tmp_path, [(1.0, 1.0)])
        assert payload["informative_pairs"] == 0
        assert payload["treatment_wins"] == 0
        assert payload["verdict"] != "ADOPT", payload["verdict"]

    def test_a_floor_saturates_for_a_lower_is_better_metric(
            self, tmp_path: Path):
        """The half a single ceiling would have missed. `direction: lower` puts
        the good end at a floor — two arms both recording no seams are both
        perfect — and it is the same one number in the registration."""
        payload = _scored(tmp_path, [(0, 0)], direction="lower", bound="0")
        assert payload["pairs"][0]["saturated"] is True, payload["pairs"][0]
        assert payload["metric_bound"] == 0


class TestOnlyTiesAtTheBoundAreAffected:
    def test_a_tie_away_from_the_bound_is_still_a_tie(self, tmp_path: Path):
        """The rule is about the bound, not about ties. Both arms at 0.5 have
        room to differ on either side and simply did not."""
        payload = _scored(tmp_path, [(0.5, 0.5)])
        pair = payload["pairs"][0]
        assert pair["saturated"] is False, pair
        assert pair["informative"] is True, pair
        assert pair["winner"] == "tie", pair

    def test_a_tie_at_the_worst_value_is_still_a_tie(self, tmp_path: Path):
        """Why `bound` names one end. Both arms at 0.0 under higher-is-better
        is a pair the treatment COULD have won and did not — a real loss, and
        registering the bad end would delete exactly the disagreeing pairs."""
        payload = _scored(tmp_path, [(0.0, 0.0)])
        pair = payload["pairs"][0]
        assert pair["saturated"] is False, pair
        assert pair["winner"] == "tie", pair

    def test_one_arm_at_the_bound_is_a_real_result(self, tmp_path: Path):
        """The metric separated them. A treatment at the ceiling against a
        control below it is the clearest win the metric can express, and a
        control at the ceiling is a clean loss."""
        won = _scored(tmp_path, [(1.0, 0.4)])["pairs"][0]
        assert won["informative"] is True and won["winner"] == "treatment", won
        lost = _scored(tmp_path / "b", [(0.4, 1.0)])["pairs"][0]
        assert lost["informative"] is True and lost["winner"] == "control", lost


class TestAnUnboundedMetricIsUnchanged:
    """The guarantee the issue is most insistent about. Everything above must
    cost the unbounded case nothing."""

    def test_a_registration_naming_no_bound_scores_a_tie_as_a_tie(
            self, tmp_path: Path):
        payload = _scored(tmp_path, [(0.5, 0.5)], bound=None)
        assert payload["metric_bound"] is None
        assert payload["pairs"][0]["winner"] == "tie"
        assert payload["saturated_pairs"] == 0

    def test_a_tie_at_a_value_that_would_have_saturated_is_a_tie(
            self, tmp_path: Path):
        """Same rows as the motivating case, minus the declaration. The
        difference between them is the registration and nothing else."""
        payload = _scored(tmp_path, [(1.0, 1.0)], bound=None)
        assert payload["pairs"][0]["saturated"] is False
        assert payload["pairs"][0]["winner"] == "tie"

    def test_closure_still_scores_a_tie_as_a_loss(self, tmp_path: Path):
        """Unregistered, below the cap. Two repos that both closed the same
        share of their gap really are indistinguishable, and #195 changed
        nothing about that: the pair is informative, tied, and blocks
        adoption."""
        _member(tmp_path, "ctl1", 12000, 9000, "1.2")
        _member(tmp_path, "trt1", 12000, 9000, "1.3")
        roster = _roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")])
        r = _score(roster, "--min-pairs", "1", "--format", "json")
        payload = json.loads(r.stdout)
        pair = payload["pairs"][0]
        assert pair["winner"] == "tie", pair
        assert pair["informative"] is True and pair["saturated"] is False, pair
        assert payload["verdict"] != "ADOPT", payload

    def test_closure_keeps_its_cap_without_any_registration(
            self, tmp_path: Path):
        """The bound closure has always had, now read as a default rather than
        hardcoded in the pair loop. Both arms reaching budget still saturates."""
        _member(tmp_path, "ctl1", 12000, 3000, "1.2")
        _member(tmp_path, "trt1", 12000, 3000, "1.3")
        roster = _roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")])
        payload = json.loads(
            _score(roster, "--min-pairs", "1", "--format", "json").stdout)
        assert payload["pairs"][0]["saturated"] is True, payload["pairs"][0]
        assert payload["metric_bound"] == 1.0


class TestABoundIsACheckedClaim:
    def test_a_value_past_the_bound_refuses_the_run(self, tmp_path: Path):
        """`bound: 0.9` on a share that records 1.0 is not a bound. Allowed to
        stand it would saturate every tie at 0.9 and above, deleting pairs the
        treatment did not win."""
        roster = _cohort(tmp_path, [(1.0, 1.0)])
        d = _register(tmp_path, bound="0.9")
        r = _score(roster, "--experiments-dir", str(d), "--experiment", "02")
        assert r.returncode == 1, r.stdout
        assert "unknown argument" not in r.stderr, r.stderr
        assert "0.9" in r.stderr and "trt1" in r.stderr, r.stderr

    def test_the_refusal_says_why_it_matters(self, tmp_path: Path):
        roster = _cohort(tmp_path, [(1.0, 1.0)])
        d = _register(tmp_path, bound="0.9")
        r = _score(roster, "--experiments-dir", str(d), "--experiment", "02")
        flat = _flat(r.stderr).lower()
        assert "did not win" in flat, r.stderr

    def test_the_refusal_quotes_the_registration_verbatim(self, tmp_path: Path):
        """It tells the operator to go and edit the file, so it must name the
        value as the file spells it. `:g` renders a registered `bound: 1.0` as
        `1`, and a grep for that finds nothing on the one path where they are
        already unsure which number is wrong."""
        roster = _cohort(tmp_path, [(1.5, 1.5)])
        d = _register(tmp_path, bound="1.0")
        r = _score(roster, "--experiments-dir", str(d), "--experiment", "02")
        assert r.returncode == 1, r.stdout
        assert "`bound: 1.0`" in r.stderr, r.stderr
        assert "`bound: 1`" not in r.stderr, r.stderr


class TestTheBoundCheckIsScopedToTheArms:
    """A repo running neither version is running neither version of the METRIC.

    Six releases back, a share may be computed from a different denominator, so
    its value is not evidence about what the two named versions can produce.
    Letting it refuse the run is the shape #194 removed from the safety gates —
    a repo adrift vetoing a proposal it never ran — and the remedies the refusal
    offers ("fix the registration or drop the key") are both wrong when the
    bound is right for the arms and the stray repo is simply old.
    """

    @staticmethod
    def _with_stray(root: Path, value: float) -> tuple:
        roster = _cohort(root, [(1.0, 1.0), (1.0, 1.0)])
        _member(root, "stray", 9000, 7000, "0.9", truth=value)
        with roster.open("a") as fh:
            fh.write(f"{root / 'stray'}  wave:b pair:9\n")
        return roster, _register(root)

    def test_an_out_of_arm_row_past_the_bound_does_not_refuse(
            self, tmp_path: Path):
        roster, d = self._with_stray(tmp_path, 1.4)
        r = _score(roster, "--experiments-dir", str(d), "--experiment", "02")
        assert r.returncode != 1, (
            "a repo in neither arm must not be able to refuse the run:\n"
            + r.stderr
        )
        assert "is not a bound" not in r.stderr, r.stderr

    def test_it_is_reported_as_a_note_rather_than_swallowed(
            self, tmp_path: Path):
        """Not fatal is not the same as not said. A bound is a claim about the
        metric, and a value past it anywhere is worth a look."""
        roster, d = self._with_stray(tmp_path, 1.4)
        r = _score(roster, "--experiments-dir", str(d), "--experiment", "02")
        flat = _flat(r.stdout)
        assert "OUTSIDE the arms" in flat, r.stdout
        assert "stray (1.4)" in flat, r.stdout
        assert "1.0" in flat, r.stdout

    def test_the_json_carries_it_too(self, tmp_path: Path):
        roster, d = self._with_stray(tmp_path, 1.4)
        r = _score(roster, "--experiments-dir", str(d), "--experiment", "02",
                   "--format", "json")
        payload = json.loads(r.stdout)
        assert payload["bound_exceeded_out_of_arm"] == [
            {"repo": "stray", "skill_version": "0.9", "truth": 1.4}
        ], payload["bound_exceeded_out_of_arm"]

    def test_an_in_arm_row_past_the_bound_still_refuses(self, tmp_path: Path):
        """The scoping must not disarm the check it is scoping — an arm member
        past the bound is still fatal."""
        roster = _cohort(tmp_path, [(1.4, 1.0)])
        d = _register(tmp_path, bound="1.0")
        r = _score(roster, "--experiments-dir", str(d), "--experiment", "02")
        assert r.returncode == 1, r.stdout
        assert "is not a bound" in r.stderr, r.stderr
        assert "trt1" in r.stderr, r.stderr

    def test_a_clean_run_says_nothing_about_bounds_out_of_arm(
            self, tmp_path: Path):
        """The note fires on the condition, not on the presence of a stray."""
        roster, d = self._with_stray(tmp_path, 0.8)
        r = _score(roster, "--experiments-dir", str(d), "--experiment", "02")
        assert "OUTSIDE the arms" not in _flat(r.stdout), r.stdout

    def test_a_floor_is_checked_from_below(self, tmp_path: Path):
        """The `direction: lower` half of the same check — past the bound means
        below it there, and a single-sided implementation would miss it."""
        roster = _cohort(tmp_path, [(0, 0)])
        d = _register(tmp_path, direction="lower", bound="1")
        r = _score(roster, "--experiments-dir", str(d), "--experiment", "02")
        assert r.returncode == 1, r.stdout
        assert "trt1" in r.stderr, r.stderr

    def test_a_non_numeric_bound_is_refused_before_any_fetch(
            self, tmp_path: Path):
        roster = _cohort(tmp_path, [(1.0, 1.0)])
        d = _register(tmp_path, bound="perfect")
        r = _score(roster, "--experiments-dir", str(d), "--experiment", "02")
        assert r.returncode == 1, r.stdout
        assert "perfect" in r.stderr, r.stderr
        assert "finite" in r.stderr, r.stderr

    def test_an_infinite_bound_is_refused(self, tmp_path: Path):
        """`bound: inf` parses as a float and would register a bound nothing can
        reach as though it were a real one."""
        roster = _cohort(tmp_path, [(1.0, 1.0)])
        d = _register(tmp_path, bound="inf")
        r = _score(roster, "--experiments-dir", str(d), "--experiment", "02")
        assert r.returncode == 1, r.stdout
        assert "finite" in r.stderr, r.stderr

    def test_an_unreachable_bound_is_inert_not_an_error(self, tmp_path: Path):
        """The other pathology, and the opposite answer. A ceiling of 2.0 on a
        share is never reached, so the rule never fires and every pair scores
        exactly as it would unregistered. Refusing here would need the script to
        know a metric's true range, which it cannot; scoring is unaffected, so
        it is reported instead."""
        payload = _scored(tmp_path, [(1.0, 1.0)], bound="2")
        assert payload["pairs"][0]["saturated"] is False
        assert payload["pairs"][0]["winner"] == "tie"

    def test_a_registered_bound_is_printed_whether_or_not_it_fires(
            self, tmp_path: Path):
        """So an inert bound is visible as a declaration that was honoured and
        did not apply, rather than as one nobody read."""
        roster = _cohort(tmp_path, [(0.5, 0.5)])
        d = _register(tmp_path)
        r = _score(roster, "--experiments-dir", str(d), "--experiment", "02")
        assert "saturates at 1" in r.stdout, r.stdout


class TestTheSchemaAndTheGateRecordTheRule:
    def test_bound_is_optional_in_the_schema(self, tmp_path: Path):
        """Registered without it, the run still scores — the whole point of
        putting it in OPTIONAL rather than REQUIRED."""
        payload = _scored(tmp_path, [(0.4, 0.6)], bound=None)
        assert payload["verdict"] is not None

    def test_an_unknown_bound_like_key_is_still_refused(self, tmp_path: Path):
        """Adding one optional key must not open the schema. A misspelling
        reads as a declaration that was never honoured."""
        roster = _cohort(tmp_path, [(1.0, 1.0)])
        d = _register(tmp_path, bounds="1.0")
        r = _score(roster, "--experiments-dir", str(d), "--experiment", "02")
        assert r.returncode == 1, r.stdout
        assert "bounds" in r.stderr, r.stderr

    def test_the_template_documents_the_key(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        assert "bound:" in text, text
        flat = _flat(text).lower()
        assert "optional" in flat, flat

    def test_the_help_names_the_bound(self):
        r = subprocess.run(["bash", str(SCORE), "--help"],
                           capture_output=True, text=True, timeout=30)
        flat = _flat(r.stdout).lower()
        assert "bound" in flat, r.stdout

    def test_the_gate_records_that_a_bound_is_optional_and_why(self):
        flat = _flat(GATE.read_text(encoding="utf-8")).lower()
        assert "`bound` is optional" in flat, flat[-3000:]
        # The rule that was explicitly rejected, recorded so it is not
        # re-proposed as an obvious simplification.
        assert "ties are uninformative" in flat, flat[-3000:]

    def test_the_gate_says_one_number_and_which_end(self):
        flat = _flat(GATE.read_text(encoding="utf-8")).lower()
        assert "one number, not two" in flat, flat[-3000:]
        assert "ceiling under `higher`" in flat, flat[-3000:]
