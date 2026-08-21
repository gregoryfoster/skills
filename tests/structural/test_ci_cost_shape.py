"""Invariants for `auditing-ci-cost` (#212).

The skill exists because two real audits, three weeks apart, reached opposite
conclusions from the same procedure — and either one's playbook applied to the
other repo would have been wrong:

- CannObserv/cannabis.observer-wordpress billed 1.85 min/job with 38% of jobs
  under the one-minute floor. Seconds convert to minutes there; caching and
  path-filtering are live levers.
- CannObserv/cannobserv billed 1.01 min/job with 96% of jobs under the floor.
  Duration tuning has no lever at all; the whole spend is job COUNT, and its
  single largest line item was a job doing seven seconds of work.

Both figures are reproduced by this skill's own `measure-ci-cost.sh`, so the
divergence is a property of the repos rather than of the two authors.

What must therefore never be edited out:

1. The prescription BRANCHES on a measured shape. A skill that prescribes
   without measuring is a checklist, and it is wrong half the time.
2. Anomaly separation is a GATE, not advice. cannobserv's raw 30-day total is
   588 billed minutes and its structural baseline is 392 — one GitHub incident
   day accounts for the 33% difference, and quoting the raw number does not
   merely overstate the total, it points at duration when the lever is count.
3. Three API behaviours that were verified by probe here and are wrong in the
   originating issue (#212). Each silently corrupts the census.
4. The two outputs both audits produced deliberately — a numbered findings list
   with a confidence label, and a non-levers section — so the same dead ends are
   not re-litigated by the next audit.

Each assertion below pins a sentence whose deletion turns a measurement back
into a guess. No API calls required.
"""

import re

import pytest

from tests.utils.skill_loader import SKILLS_DIR, load_skill

SKILL_NAME = "auditing-ci-cost"
SKILL_DIR = SKILLS_DIR / SKILL_NAME


@pytest.fixture(scope="module")
def ci_cost():
    return load_skill(SKILL_DIR)


@pytest.fixture(scope="module")
def body(ci_cost) -> str:
    return ci_cost.body


def _surface() -> list:
    """SKILL.md, every reference doc, and every script — the whole skill.

    An invariant about what the skill TELLS an agent to run has to cover the
    scripts too: a correction stated in prose and contradicted by the shipped
    command is worse than one stated nowhere, because the run trusts the
    command.
    """
    return sorted(
        [SKILL_DIR / "SKILL.md"]
        + list(SKILL_DIR.glob("references/**/*.md"))
        + list(SKILL_DIR.glob("scripts/*"))
    )


def _all_text() -> str:
    return "\n".join(p.read_text() for p in _surface())


class TestTheSkillExists:
    def test_directory_and_skill_md(self):
        assert (SKILL_DIR / "SKILL.md").is_file(), (
            f"skills/{SKILL_NAME}/SKILL.md must exist"
        )

    def test_registered_in_readme(self):
        readme = (SKILLS_DIR.parent / "README.md").read_text()
        assert f"[`{SKILL_NAME}`](skills/{SKILL_NAME}/)" in readme, (
            f"{SKILL_NAME} is missing from the README skills table — a skill "
            "that exists but is unlisted is invisible to anyone choosing one"
        )


class TestPrescriptionBranchesOnAMeasuredShape:
    """The insight that makes this a skill and not a checklist."""

    def test_billing_formula_names_the_one_minute_floor(self, body):
        assert "max(1, ceil(job_seconds / 60))" in body, (
            "SKILL.md must state the billing model verbatim — "
            "`max(1, ceil(job_seconds / 60))`. Without the floor, a repo whose "
            "jobs all run under a minute looks cheap and is not."
        )

    def test_both_cost_shapes_are_named(self, body):
        for shape in ("job-count", "duration"):
            assert shape in body, (
                f"SKILL.md must name the `{shape}` cost shape. The whole point "
                "is that the prescription forks; a body naming one fork is the "
                "checklist this skill replaces."
            )

    def test_the_job_count_branch_forbids_splitting(self, body):
        normalised = " ".join(body.split())
        assert "never split" in normalised.lower(), (
            "The job-count branch must forbid splitting workflows. Under a "
            "1.00 min/job mean every new job adds a whole billed minute and "
            "saves nothing — an agent arriving with the duration playbook "
            "would make the bill worse."
        )

    def test_the_duration_branch_prescribes_the_opposite(self, body):
        normalised = " ".join(body.split()).lower()
        for lever in ("cache", "narrow", "split"):
            assert lever in normalised, (
                f"The duration branch must name `{lever}` as a lever. These are "
                "the moves that are wrong in a job-count repo and right here."
            )

    def test_a_mean_of_one_is_stated_as_the_discriminator(self, body):
        normalised = " ".join(body.split())
        assert re.search(r"mean billed", normalised, re.I), (
            "SKILL.md must name `mean billed` per job as the number the "
            "classification reads. A shape asserted from a workflow file "
            "instead of from the census is a guess."
        )

    def test_measurement_precedes_classification_precedes_findings(self, body):
        measure = body.find("Phase 1 — Measure")
        classify = body.find("Phase 2 — Classify")
        findings = body.find("Phase 4 — Findings")
        assert measure != -1, "Phase 1 — Measure header not found"
        assert classify != -1, "Phase 2 — Classify header not found"
        assert findings != -1, "Phase 4 — Findings header not found"
        assert measure < classify < findings, (
            "Measure must precede Classify, which must precede Findings. Any "
            "other order lets a finding be written before the shape that "
            "decides whether it is a saving or a regression."
        )


class TestAnomalySeparationIsAGate:
    """Not a suggestion — the issue is explicit, and the numbers say why."""

    def test_iron_law_binds_the_baseline_to_the_separation(self, body):
        assert "NO BASELINE QUOTED BEFORE ANOMALY DAYS ARE SEPARATED" in body, (
            "The Iron Law must carry the anomaly gate verbatim. Demoting it to "
            "prose is what makes it skippable, and #212 asks for the opposite."
        )

    def test_iron_law_binds_prescription_to_measurement(self, body):
        assert "NO PRESCRIPTION WITHOUT A MEASURED COST SHAPE" in body, (
            "The Iron Law must forbid prescribing from an unmeasured shape."
        )

    def test_the_anomaly_cost_is_quantified_somewhere(self):
        """A gate with no number attached reads as caution rather than fact."""
        text = _all_text()
        assert "incident" in text.lower(), (
            "The skill must say what an anomaly day IS — a platform incident "
            "hanging jobs — not merely that outliers exist."
        )
        assert re.search(r"\b(33|36)%", text), (
            "The skill must quote the measured overstatement a raw baseline "
            "carries (33% in CannObserv/cannobserv's 30-day window as measured "
            "here; 36% in the window #212 reports). A gate whose cost is "
            "unstated is the first thing a hurried run skips."
        )

    def test_a_busy_day_is_distinguished_from_an_incident_day(self):
        """Total alone over-flags; the mean-per-job test is what separates them."""
        text = _all_text()
        normalised = " ".join(text.split()).lower()
        assert "min/job" in normalised or "per job" in normalised, (
            "The anomaly rule must key on billed-minutes-PER-JOB as well as on "
            "the day's total. Total alone flags a merely busy day — measured "
            "here, 2026-08-17 billed 3.1x the median day at an entirely normal "
            "1.05 min/job — and subtracting it understates the real spend."
        )


class TestApiCorrectionsVerifiedByProbe:
    """Three behaviours probed against the live API, each wrong in #212.

    All three corrupt the census silently, which is the only reason they are
    worth pinning: a census that fails loudly gets fixed.
    """

    JOBS_ENDPOINT = re.compile(r"actions/runs/[^/\s]+/jobs")

    def test_every_jobs_endpoint_call_passes_filter_all(self):
        """`filter=latest` is the default and it hides billed work.

        Verified: run 32311306786 in CannObserv/cannabis.observer-wordpress
        reports total_count 1 by default and 2 with `filter=all`. The hidden
        job is attempt 1, which ran 2m36s and was billed 3 minutes — 60% of
        that run's true cost, invisible.
        """
        offenders = []
        for path in _surface():
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                if self.JOBS_ENDPOINT.search(line) and "filter=all" not in line:
                    offenders.append(f"{path.relative_to(SKILLS_DIR)}:{lineno}: {line.strip()}")
        assert not offenders, (
            "Every jobs-endpoint call in this skill must pass `filter=all`:\n  "
            + "\n  ".join(offenders)
            + "\n\nThe endpoint defaults to `filter=latest`, which omits every "
            "re-run attempt but the last. Each attempt was billed in full, so "
            "the default undercounts and the shortfall lands entirely on the "
            "runs someone already had reason to re-run."
        )

    def test_the_timing_endpoint_is_documented_as_unusable(self):
        """#212 says /timing gives no per-job breakdown. It gives a zeroed one.

        `billable.<OS>.job_runs[]` is a real per-job array. Its `duration_ms`
        and the enclosing `total_ms` read 0 on every repo probed here — public
        and private — against runs of 35 to 99 seconds. So the endpoint is not
        merely coarse, it is empty, and a run that "improves" on the timestamp
        census by adopting it would report zero spend.
        """
        text = _all_text()
        assert "timing" in text, (
            "The skill must address the `/timing` endpoint — it is the first "
            "thing anyone reaches for, and it is the wrong answer."
        )
        normalised = " ".join(text.split())
        assert re.search(r"total_ms", normalised), (
            "Name the field that reads zero (`total_ms`), not just the "
            "endpoint. `/timing` looks authoritative; only the field shows why "
            "it is not."
        )

    def test_skipped_jobs_are_excluded_from_the_billing_sum(self):
        """`max(1, ceil(...))` bills a phantom minute for a job that never ran.

        A skipped job appears in the jobs list with `conclusion: skipped` and a
        zero or NEGATIVE duration — observed in cli/cli, started_at 21:51:34
        against completed_at 21:51:27. Under the floor rule that is one billed
        minute of nothing. In a job-count repo the phantom is indistinguishable
        from a real one-minute job, so it corrupts exactly the measurement the
        prescription branches on.
        """
        text = _all_text()
        normalised = " ".join(text.split())
        assert "skipped" in normalised, (
            "The skill must say how `conclusion: skipped` jobs are handled."
        )
        assert re.search(r"negative", normalised, re.I), (
            "State that a skipped job can carry a NEGATIVE duration. Without "
            "that, `max(1, ceil(...))` reads as safe and quietly bills it."
        )


class TestRequiredOutputs:
    def test_non_levers_is_a_phase_not_a_nicety(self, body):
        assert "Phase 6 — Non-levers" in body, (
            "Both audits produced a non-levers section specifically so the "
            "same dead ends would not be re-litigated. #212 makes it a "
            "required output; a phase header is what makes it one."
        )

    def test_findings_carry_a_confidence_label(self, body):
        normalised = " ".join(body.split()).lower()
        assert "measured" in normalised and "estimated" in normalised, (
            "Every finding must be labelled measured or estimated. The two "
            "audits' biggest wins came from turning estimates into "
            "measurements; a report that does not distinguish them loses that."
        )

    def test_the_false_skip_gate_is_zero(self):
        """A path filter is shipped on a replay, not on a reading of the docs."""
        text = " ".join(_all_text().split())
        assert "false skip" in text.lower(), (
            "The path-filter replay must define a `false skip` — a "
            "code-carrying commit the filter would have skipped."
        )
        assert re.search(r"zero false skips|0 false skips", text, re.I), (
            "The gate is ZERO false skips, not 'few'. wp#726 replayed 45 "
            "merged PRs and cannobserv#355 replayed 104 main-push commits "
            "precisely so the number could be zero rather than small."
        )

    def test_handoff_to_enforcing_architecture(self, body):
        assert "enforcing-architecture" in body, (
            "Phase 7 hands the accepted filter to `enforcing-architecture`, "
            "which graduates it into an executable contract. Without the "
            "handoff the filter drifts the first time a build input moves."
        )


class TestProbeOverDocs:
    """Both audits were burned reading GitHub's docs instead of probing."""

    def test_the_stance_is_stated(self, body):
        normalised = " ".join(body.split()).lower()
        assert "probe" in normalised, (
            "The probe-don't-read stance must appear in SKILL.md, not only in "
            "a reference. It changes what an agent does first."
        )

    def test_the_glob_leniency_finding_is_recorded(self):
        """The specific case where a review 'corrected' a working filter."""
        text = " ".join(_all_text().split())
        assert "**/composer.json" in text or "leading `**/`" in text, (
            "Record wp#726's probe result: a leading `**/` matches zero "
            "directories, so `**/composer.json` DOES match the root file. A "
            "review round had already re-broken the committed filter from the "
            "stricter reading of the docs, which is why the probe result has "
            "to live next to the rule."
        )

    def test_workflow_call_context_inheritance_is_warned_about(self):
        text = _all_text()
        assert "workflow_call" in text, (
            "A reusable workflow inherits the CALLER's `github` context, so a "
            "job condition matching on `head_commit.message` silently "
            "disabled a release gate in cannobserv. Any commit-message-based "
            "condition needs the `github.ref` guard beside it."
        )
