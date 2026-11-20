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

import json
import os
import re
import shutil
import subprocess

import pytest

from tests.utils.skill_loader import SKILLS_DIR, load_skill

SKILL_NAME = "auditing-ci-cost"
SKILL_DIR = SKILLS_DIR / SKILL_NAME
CENSUS = SKILL_DIR / "scripts" / "measure-ci-cost.sh"


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
                    offenders.append(
                        f"{path.relative_to(SKILLS_DIR)}:{lineno}: {line.strip()}"
                    )
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


class TestTheTrapCountStaysTrue:
    """SKILL.md and traps.md each say how many traps there are (#600 added one).

    A count that lags the list tells the reader a trap doesn't exist; this
    derives the number from traps.md's own numbered headings.
    """

    WORDS = "zero one two three four five six seven eight nine ten eleven twelve"

    def test_both_counts_match_the_numbered_traps(self, body):
        traps = (SKILL_DIR / "references" / "traps.md").read_text()
        n = len(re.findall(r"^## \d+\. ", traps, re.M))
        word = self.WORDS.split()[n]
        assert f"The {word} that already bit" in " ".join(body.split()), (
            f"traps.md numbers {n} traps; SKILL.md's Phase 5 must say "
            f"'The {word} that already bit'"
        )
        assert f"of the {word} above" in " ".join(traps.split()), (
            f"traps.md's general form must count {n} traps ('of the {word} above')"
        )

    def test_the_shallow_submodule_trap_is_recorded(self):
        traps = " ".join((SKILL_DIR / "references" / "traps.md").read_text().split())
        assert "fetch-depth: 0" in traps and "skip" in traps, (
            "trap 9 (#600): a shallow submodule checkout turns ancestry tests into "
            "skips that read green; its fix is `fetch-depth: 0` with a guard test"
        )


class TestLocalGateAttestationIsALeverWithConditions:
    """#602: live only where it pays, and only sketched, not shipped."""

    def test_its_conditions_and_its_sketch_mark_are_recorded(self):
        text = " ".join(
            (SKILL_DIR / "references" / "non-levers.md").read_text().split()
        )
        assert "Local-gate attestation" in text
        for condition in ("private", "duration", "Dependabot"):
            assert condition in text, (
                f"the attestation lever must name {condition!r}: it pays only in a "
                "private, duration-shaped repo, and bot PRs still need the full run"
            )
        assert "A sketch, not shipped" in text, (
            "the status-posting step is a sketch; shipping-work has no such step"
        )


def _census(
    tmp_path, rows: list[dict], *args, visibility=None, as_json=True
) -> subprocess.CompletedProcess:
    """Run the census against a synthetic cache — no network, no gh.

    `--cache` exists so a re-classification does not refetch; the same door is
    what makes the billing arithmetic testable offline. A prose claim about how
    a skipped job is handled is worth much less than a run that proves it.

    `visibility` is what a fetch records in the meta record (#597); None writes
    the meta a cache from before that change carries.
    """
    cache = tmp_path / "census.ndjson"
    meta = {"meta": {"repo": "o/r", "since": "2026-08-01", "days": 30}}
    if visibility is not None:
        meta["meta"]["visibility"] = visibility
    cache.write_text("\n".join(json.dumps(r) for r in [meta, *rows]) + "\n")
    return subprocess.run(
        ["bash", str(CENSUS), "--cache", str(cache)]
        + (["--json"] if as_json else [])
        + list(args),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _job(started: str, completed: str, conclusion: str = "success", **kw) -> dict:
    return {
        "job": kw.get("job", "j"),
        "workflow": kw.get("workflow", "W"),
        "attempt": 1,
        "conclusion": conclusion,
        "started": started,
        "completed": completed,
        "branch": "main",
        "event": kw.get("event", "push"),
        "run_id": kw.get("run_id", 1),
        # What a fetch records per job since #597; a pre-#597 cache has neither.
        **{k: kw[k] for k in ("runner_group_id", "runner_group", "labels") if k in kw},
    }


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
class TestTheBillingArithmetic:
    """The formula, executed. Every case here is one the prose can only assert.

    These run the shipped script against a synthetic cache, so they fail if the
    script and the documented model ever disagree — which is the failure that
    matters, since the run trusts the script and reads the prose.
    """

    def test_a_skipped_job_with_a_negative_duration_bills_nothing(self, tmp_path):
        """The phantom minute — #212's formula applied literally produces it.

        The timestamps are cli/cli's, where `started_at` is seven seconds AFTER
        `completed_at`. `max(1, ceil(-7/60))` is 1, so a naive census bills a
        full minute for a job that never occupied a runner.
        """
        result = _census(
            tmp_path,
            [
                _job("2026-08-02T10:00:00Z", "2026-08-02T10:00:30Z"),
                _job(
                    "2026-08-02T10:00:34Z",
                    "2026-08-02T10:00:27Z",
                    "skipped",
                    job="gate",
                ),
            ],
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["raw"]["billed_minutes"] == 1, (
            "a skipped job billed a phantom minute: "
            f"{report['raw']['billed_minutes']} for one real 30s job"
        )
        assert report["excluded"]["skipped_jobs"] == 1, (
            "the skipped job must be reported, not merely dropped — a census "
            "that hides its exclusions cannot be audited"
        )

    def test_a_skipped_job_with_a_POSITIVE_duration_also_bills_nothing(self, tmp_path):
        """The half the duration guard cannot cover.

        Zeroing non-positive durations catches the negative-timestamp shape, and
        it is not sufficient: a skipped job can report a small positive span,
        which the floor then rounds up to a full billed minute. Only the
        `conclusion` test excludes that one, which is why both exist.
        """
        result = _census(
            tmp_path,
            [
                _job("2026-08-02T10:00:00Z", "2026-08-02T10:00:30Z"),
                _job(
                    "2026-08-02T10:00:27Z",
                    "2026-08-02T10:00:34Z",
                    "skipped",
                    job="gate",
                ),
            ],
        )
        report = json.loads(result.stdout)
        assert report["raw"]["billed_minutes"] == 1, (
            "a skipped job reporting +7s billed a minute: "
            f"{report['raw']['billed_minutes']} for one real 30s job"
        )

    def test_a_non_positive_duration_never_bills_a_minute(self, tmp_path):
        """`max(1, ceil(s/60))` taken literally bills 1 for s <= 0.

        That is #212's formula applied to a job list that contains rows the
        formula was never meant to see. The floor applies to work that happened;
        zero seconds of work is not one minute of work.
        """
        report = json.loads(
            _census(
                tmp_path,
                [
                    _job("2026-08-02T10:00:00Z", "2026-08-02T10:00:30Z"),
                    _job(
                        "2026-08-02T10:05:00Z",
                        "2026-08-02T10:05:00Z",
                        "cancelled",
                        job="zero",
                    ),
                ],
            ).stdout
        )
        assert report["raw"]["billed_minutes"] == 1, (
            "a zero-duration job billed a minute: "
            f"{report['raw']['billed_minutes']} for one real 30s job"
        )
        assert report["excluded"]["zero_or_negative_duration_jobs"] == 1, (
            "a non-skipped job with a non-positive duration must be counted "
            "and surfaced — it should be zero, and when it is not, that is "
            "itself a finding rather than something to round away"
        )

    def test_a_job_still_in_flight_does_not_abort_the_census(self, tmp_path):
        """A run in progress has `completed_at: null`, and the runs listing
        has no status filter — so every census of an active repo contains one.

        `fromdateiso8601` on null raises `strptime/1 requires string inputs`
        and takes the whole report with it, meaning the busier a repo is, the
        likelier the audit produces nothing at all. Verified against a live
        repo: home-assistant/core run 32488132218 carried a job with
        `status: in_progress` and a null `completed_at`.

        Excluded rather than estimated: the job is billing right now and its
        final duration is not knowable, so guessing one would invent spend.
        """
        result = _census(
            tmp_path,
            [
                _job("2026-08-02T10:00:00Z", "2026-08-02T10:00:30Z"),
                {
                    "job": "live",
                    "workflow": "w",
                    "attempt": 1,
                    "conclusion": None,
                    "started": "2026-08-02T10:05:00Z",
                    "completed": None,
                    "branch": "main",
                    "event": "push",
                    "run_id": 2,
                },
            ],
        )
        assert result.returncode == 0, (
            "a null completed_at aborted the census instead of being excluded: "
            f"{result.stderr.strip()}"
        )
        report = json.loads(result.stdout)
        assert report["excluded"]["unfinished_jobs"] == 1, (
            "an in-flight job must be counted and surfaced, not dropped "
            "silently — its minutes land in the next census, not this one"
        )
        assert report["raw"]["billed_minutes"] == 1, (
            "the one finished 30s job must still bill exactly one minute"
        )

    def test_a_cached_census_warns_when_it_overrides_an_explicit_flag(self, tmp_path):
        """A cache answers for the repo and window it was fetched against.

        Silently honouring the cache over an explicit `--repo` hands back a
        plausible number for a repository the user did not ask about — the
        exact failure this skill exists to find, from inside its own tool.
        """
        result = _census(
            tmp_path,
            [
                _job("2026-08-02T10:00:00Z", "2026-08-02T10:00:30Z"),
            ],
            "--repo",
            "someone/else",
            "--days",
            "7",
        )
        assert result.returncode == 0
        assert "--repo someone/else ignored" in result.stderr, (
            "an ignored --repo must say so; the cache holds o/r. "
            f"stderr: {result.stderr.strip()}"
        )
        assert "--days 7 ignored" in result.stderr, (
            f"an ignored --days must say so. stderr: {result.stderr.strip()}"
        )

    def test_the_one_minute_floor_is_applied(self, tmp_path):
        """Three seconds of work bills a full minute. The whole premise."""
        result = _census(
            tmp_path, [_job("2026-08-02T10:00:00Z", "2026-08-02T10:00:03Z")]
        )
        assert json.loads(result.stdout)["raw"]["billed_minutes"] == 1

    def test_seconds_round_up_not_down(self, tmp_path):
        """119s bills 2 minutes; 121s bills 3. This is the duration lever."""
        for completed, expected in (("10:01:59Z", 2), ("10:02:01Z", 3)):
            result = _census(
                tmp_path, [_job("2026-08-02T10:00:00Z", f"2026-08-02T{completed}")]
            )
            assert json.loads(result.stdout)["raw"]["billed_minutes"] == expected, (
                f"a job ending at {completed} must bill {expected} minutes"
            )

    def test_a_repo_inside_the_floor_classifies_as_job_count(self, tmp_path):
        rows = [
            _job(f"2026-08-{d:02d}T10:0{n}:00Z", f"2026-08-{d:02d}T10:0{n}:30Z")
            for d in range(2, 8)
            for n in range(3)
        ]
        report = json.loads(_census(tmp_path, rows).stdout)
        assert report["cost_shape"] == "job-count", report["structural"]
        assert report["structural"]["mean_billed_per_job"] == 1

    def test_a_repo_above_the_floor_classifies_as_duration(self, tmp_path):
        rows = [
            _job(f"2026-08-{d:02d}T10:0{n}:00Z", f"2026-08-{d:02d}T10:0{n + 2}:10Z")
            for d in range(2, 8)
            for n in range(3)
        ]
        report = json.loads(_census(tmp_path, rows).stdout)
        assert report["cost_shape"] == "duration", report["structural"]
        assert report["structural"]["under_the_floor"] == 0


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
class TestTheAnomalyGateExecuted:
    """The gate, and the over-flagging failure it was built to avoid."""

    @staticmethod
    def _ordinary_days(first=2, last=8):
        """Six days of three 30-second jobs — 3 billed min/day at 1.00/job."""
        return [
            _job(f"2026-08-{d:02d}T10:0{n}:00Z", f"2026-08-{d:02d}T10:0{n}:30Z")
            for d in range(first, last)
            for n in range(3)
        ]

    def test_an_incident_day_is_flagged_and_excluded_from_the_baseline(self, tmp_path):
        """Nine jobs hung ~900s on one day, the 2026-08-06 signature."""
        incident = [
            _job(f"2026-08-20T1{n}:00:00Z", f"2026-08-20T1{n}:15:02Z", "cancelled")
            for n in range(9)
        ]
        report = json.loads(_census(tmp_path, self._ordinary_days() + incident).stdout)
        assert [d["day"] for d in report["anomaly_days"]] == ["2026-08-20"]
        assert report["structural"]["billed_minutes"] == 18, (
            "the six ordinary days bill 18 minutes; the incident day must not "
            "be in the structural baseline"
        )
        assert report["raw"]["billed_minutes"] > 100

    def test_the_incident_p99_never_appears_under_the_structural_label(self, tmp_path):
        """The second-order error: a raw p99 quoted as if it were the baseline.

        902s next to the word "structural" reads as a duration problem in a repo
        where every real job finishes in 30 seconds.
        """
        incident = [
            _job(f"2026-08-20T1{n}:00:00Z", f"2026-08-20T1{n}:15:02Z", "cancelled")
            for n in range(9)
        ]
        report = json.loads(_census(tmp_path, self._ordinary_days() + incident).stdout)
        assert report["structural"]["p99_seconds"] == 30, (
            "structural percentiles must come from the structural population, "
            f"got p99={report['structural']['p99_seconds']}s"
        )
        assert report["raw"]["p99_seconds"] == 902, (
            "the raw p99 must still be reported — it is the evidence that the "
            "flagged day was an incident rather than a busy day"
        )
        assert report["cost_shape"] == "job-count"

    def test_a_merely_busy_day_is_not_flagged(self, tmp_path):
        """The over-flagging failure a total-only rule produces.

        Measured for real: 2026-08-17 in CannObserv/cannobserv billed 3.1x the
        median day at an entirely normal 1.05 min/job. Subtracting it would have
        understated the spend by 46 minutes — the gate, inverted.
        """
        busy = [
            _job(
                f"2026-08-20T{10 + n // 6:02d}:{n % 6:02d}:00Z",
                f"2026-08-20T{10 + n // 6:02d}:{n % 6:02d}:30Z",
            )
            for n in range(30)
        ]
        report = json.loads(_census(tmp_path, self._ordinary_days() + busy).stdout)
        assert report["anomaly_days"] == [], (
            "a day that is merely busy must not be excluded: it bills a normal "
            "1.00 min/job and every one of those minutes is real spend"
        )
        assert report["structural"]["billed_minutes"] == 48

    def test_raw_and_structural_are_always_both_reported(self, tmp_path):
        """The gate is a separation, never a silent subtraction."""
        report = json.loads(_census(tmp_path, self._ordinary_days()).stdout)
        assert "billed_minutes" in report["raw"]
        assert "billed_minutes" in report["structural"]


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
class TestTheCensusRefusesBadInput:
    """A census that degrades quietly is worse than one that fails."""

    def test_a_cache_without_a_meta_record_is_refused(self, tmp_path):
        """Provenance or nothing — a baseline must know its own window."""
        cache = tmp_path / "c.ndjson"
        cache.write_text('{"job":"x"}\n')
        result = subprocess.run(
            ["bash", str(CENSUS), "--cache", str(cache)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 2, result.stdout
        assert "meta record" in result.stderr

    @pytest.mark.parametrize(
        "args",
        [
            ["--days", "0"],
            ["--days", "abc"],
            ["--anomaly-factor", "x"],
            ["--anomaly-factor", "-1"],
            ["--bogus"],
        ],
        ids=lambda a: " ".join(a),
    )
    def test_bad_arguments_exit_one(self, args):
        result = subprocess.run(
            ["bash", str(CENSUS), *args],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 1, (
            f"{' '.join(args)} should be a usage error, got {result.returncode}"
        )


def _standard(day: int, n: int, **kw) -> dict:
    """A 30-second job on GitHub's standard pool: runner group 0, as measured."""
    return _job(
        f"2026-08-{day:02d}T10:0{n}:00Z",
        f"2026-08-{day:02d}T10:0{n}:30Z",
        runner_group_id=0,
        runner_group="GitHub Actions",
        labels=["ubuntu-latest"],
        **kw,
    )


def _week(**kw) -> list[dict]:
    return [_standard(d, n, **kw) for d in range(2, 8) for n in range(3)]


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
class TestBillingFollowsVisibility:
    """#597: on a public repo, GitHub's standard runners bill nothing.

    CannObserv/power-map is public. Its census reported 65 billed minutes over
    54 jobs (50 of them Dependabot's own), and the lever text ranked cuts by
    minutes saved. None of it was billed, so every cut saved nothing, and the
    path filter the census invited would have caused 3 false skips out of 3.

    What tells a standard runner from another is the job's runner group, not its
    labels. Measured 2026-11-20: standard jobs carry `runner_group_id` 0
    ("GitHub Actions") in power-map, rust-lang/rust and denoland/deno; deno's
    `-xl` larger-runner jobs carry group 3 and rust-lang's EC2 self-hosted jobs
    group 8, and neither one's `labels` says which kind it is.
    """

    def test_a_public_repo_on_standard_runners_is_not_billed(self, tmp_path):
        result = _census(tmp_path, _week(), visibility="public")
        assert result.returncode == 0, result.stderr
        billing = json.loads(result.stdout)["billing"]
        assert billing["visibility"] == "public"
        assert billing["reading"] == "not billed", billing

    def test_its_text_heads_the_figure_as_not_billed(self, tmp_path):
        text = _census(tmp_path, _week(), visibility="public", as_json=False).stdout
        head = text.splitlines()[2]
        assert head.startswith("BILLING") and "NOT BILLED" in head, text
        assert "public repo, standard runners" in text
        assert "billed min" not in text, (
            "a public repo on standard runners bills nothing, so no line may "
            f"call its minutes billed:\n{text}"
        )
        assert "runner min" in text

    def test_its_prescription_moves_to_what_costs_there(self, tmp_path):
        text = _census(tmp_path, _week(), visibility="public", as_json=False).stdout
        normalised = " ".join(text.split())
        for cost in ("latency", "concurrent-job limit", "Dependabot"):
            assert cost in normalised, f"the public branch must name {cost!r}:\n{text}"
        assert "Delete and MERGE jobs" not in text, (
            "the job-count spend lever must not be prescribed where no minute is billed"
        )

    def test_an_off_standard_job_makes_a_public_repo_partly_billed(self, tmp_path):
        rows = _week() + [
            _job(
                "2026-08-03T11:00:00Z",
                "2026-08-03T11:04:10Z",
                job="build",
                runner_group_id=3,
                runner_group="custom managed runners",
                labels=["windows-2022-xl"],
            )
        ]
        result = _census(tmp_path, rows, visibility="public")
        billing = json.loads(result.stdout)["billing"]
        assert billing["reading"] == "partly billed", billing
        assert billing["runners"]["off_standard"] == 1
        assert billing["off_standard_billed_minutes"] == 5
        [row] = billing["off_standard"]
        assert row["job"] == "W / build"
        assert row["labels"] == ["windows-2022-xl"]
        text = _census(tmp_path, rows, visibility="public", as_json=False).stdout
        assert "PARTLY BILLED" in text and "self-hosted" in text, text

    def test_partly_billed_advice_follows_the_jobs_that_bill(self, tmp_path):
        """CR 2614: the free jobs' shape must not prescribe for the billed ones.

        Fourteen free 400-second jobs make the whole repo duration-shaped, and
        fourteen 20-second off-standard jobs, the only ones that can bill, sit
        inside the floor: splitting them adds billed minutes.
        """
        rows = [
            _job(
                f"2026-08-{2 + n // 2:02d}T1{n % 2}:00:00Z",
                f"2026-08-{2 + n // 2:02d}T1{n % 2}:06:40Z",
                job="slow",
                runner_group_id=0,
            )
            for n in range(14)
        ] + [
            _job(
                f"2026-08-{2 + n // 2:02d}T1{n % 2}:30:00Z",
                f"2026-08-{2 + n // 2:02d}T1{n % 2}:30:20Z",
                job="fast",
                runner_group_id=3,
                labels=["ubuntu-24.04-arm64-xl"],
            )
            for n in range(14)
        ]
        report = json.loads(_census(tmp_path, rows, visibility="public").stdout)
        assert report["cost_shape"] == "duration"
        assert report["billing"]["off_standard_shape"] == "job-count", report["billing"]
        text = _census(tmp_path, rows, visibility="public", as_json=False).stdout
        assert "Never split a workflow" in text, text
        assert "Cache, narrow, and split" not in text, (
            "the duration advice comes from free jobs; it would split billed ones\n"
            + text
        )

    def test_a_mixed_off_standard_shape_reads_the_off_standard_rows(self, tmp_path):
        """CR 2622: by_job is mostly free jobs; a mixed shape points elsewhere."""
        off = {"runner_group_id": 3, "labels": ["x-xl"]}
        rows = _week() + [
            _job("2026-08-03T11:00:00Z", "2026-08-03T11:00:20Z", job="a", **off),
            _job("2026-08-03T12:00:00Z", "2026-08-03T12:01:10Z", job="b", **off),
            _job("2026-08-03T13:00:00Z", "2026-08-03T13:00:20Z", job="c", **off),
        ]
        report = json.loads(_census(tmp_path, rows, visibility="public").stdout)
        assert report["billing"]["off_standard_shape"] == "mixed", report["billing"]
        assert all("median_seconds" in r for r in report["billing"]["off_standard"])
        text = _census(tmp_path, rows, visibility="public", as_json=False).stdout
        assert "Read billing.off_standard" in text and "Read by_job" not in text, text

    def test_public_rows_without_runner_fields_read_unknown(self, tmp_path):
        """CR 2617: a public meta over rows with no runner group can't say not billed."""
        rows = [_job("2026-08-02T10:00:00Z", "2026-08-02T10:00:30Z")]
        result = _census(tmp_path, rows, visibility="public")
        assert json.loads(result.stdout)["billing"]["reading"] == "unknown"

    def test_a_private_repo_is_billed_as_before(self, tmp_path):
        result = _census(tmp_path, _week(), visibility="private")
        report = json.loads(result.stdout)
        assert report["billing"]["reading"] == "billed"
        assert report["raw"]["billed_minutes"] == 18
        text = _census(tmp_path, _week(), visibility="private", as_json=False).stdout
        assert "billed min over" in text and "Delete and MERGE jobs" in text, text
        assert "runner min" not in text

    def test_an_internal_repo_bills_like_a_private_one(self, tmp_path):
        result = _census(tmp_path, _week(), visibility="internal")
        assert json.loads(result.stdout)["billing"]["reading"] == "billed"

    def test_a_private_repo_names_its_off_standard_jobs(self, tmp_path):
        """Self-hosted minutes were never billed; the census can't say which."""
        rows = _week() + [
            _standard(3, 5, job="hosted-elsewhere")
            | {
                "runner_group_id": 8,
                "runner_group": "gha-self-hosted",
                "labels": ["ec2-x86_64ami-c8a.8xlarge-x64-linux-1-1"],
            }
        ]
        text = _census(tmp_path, rows, visibility="private", as_json=False).stdout
        assert "off GitHub's standard runners" in text, text

    def test_a_cache_from_before_the_reading_says_unknown(self, tmp_path):
        """No API call on reuse, so the reading stays unknown, never a guess."""
        rows = [_job("2026-08-02T10:00:00Z", "2026-08-02T10:00:30Z")]
        result = _census(tmp_path, rows)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["billing"]["reading"] == "unknown"
        text = _census(tmp_path, rows, as_json=False).stdout
        assert "re-fetch" in text.lower(), text

    def test_a_job_no_runner_picked_up_does_not_make_it_billed(self, tmp_path):
        """`runner_group_id: null` — cancelled before pickup — ran nowhere."""
        rows = _week() + [
            _job(
                "2026-08-04T12:00:00Z",
                "2026-08-04T12:00:20Z",
                "cancelled",
                job="never-ran",
                runner_group_id=None,
            )
        ]
        result = _census(tmp_path, rows, visibility="public")
        billing = json.loads(result.stdout)["billing"]
        assert billing["reading"] == "not billed", billing
        assert billing["runners"]["unassigned"] == 1


class TestVisibilityIsInTheProcedure:
    """#597 in prose: the census reads visibility, and the procedure acts on it."""

    def test_the_billing_model_names_where_it_does_not_bill(self, body):
        normalised = " ".join(body.split())
        assert "bill nothing" in normalised and "public" in normalised, (
            "SKILL.md must say a public repo's standard-runner jobs bill nothing: "
            "the formula is the bill only where GitHub bills at all"
        )

    def test_phase_2_branches_on_not_billed(self, body):
        normalised = " ".join(body.split())
        assert "cutting minutes is not a lever by itself" in normalised, (
            "Phase 2 must say what a `not billed` reading changes: the levers "
            "are weighed by latency, concurrency and Dependabot fan-out"
        )

    def test_non_levers_carries_the_public_row(self):
        text = (SKILL_DIR / "references" / "non-levers.md").read_text()
        assert "Cutting minutes on a public repo" in text, (
            "non-levers.md must record #597's row so the next audit of a public "
            "repo doesn't re-derive minute cuts that save nothing"
        )

    def test_the_runner_group_decides_not_the_labels(self):
        text = " ".join(_all_text().split())
        assert "runner_group_id" in text and "runner group" in text, (
            "the skill must say the runner group decides the pool: a job's labels "
            "are what its runs-on asked for, measured not to say which pool it ran on"
        )


_FAKE_GH = r"""#!/usr/bin/env bash
# A stand-in for gh: answers the three calls the census makes from canned JSON.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
echo "$*" >>"$here/calls.log"
q=""; prev=""
for a in "$@"; do [ "$prev" = "-q" ] && q="$a"; prev="$a"; done
case "$1 $2" in
  "repo view") cat "$here/visibility" ;;
  api\ *) case "$2" in
      */jobs*) jq -c "$q" "$here/jobs.json" ;;
      *) jq -c "$q" "$here/runs.json" ;;
    esac ;;
esac
"""


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
class TestTheFetchRecordsWhatTheReadingNeeds:
    """The cache tests above write the fields by hand. This runs the real fetch.

    A fake `gh` serves one run and its jobs, so a fetch that forgot to record
    visibility in the meta record, or a job's runner group, fails here instead
    of reporting `unknown` on every live census.
    """

    def test_a_fetch_writes_visibility_and_runner_groups(self, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(_FAKE_GH)
        gh.chmod(0o755)
        (bin_dir / "visibility").write_text("PUBLIC\n")
        (bin_dir / "runs.json").write_text(
            json.dumps({"workflow_runs": [{"id": 7, "event": "pull_request"}]})
        )
        job = {
            "name": "gate",
            "workflow_name": "CI",
            "run_attempt": 1,
            "conclusion": "success",
            "started_at": "2026-08-02T10:00:00Z",
            "completed_at": "2026-08-02T10:00:40Z",
            "head_branch": "b",
            "labels": ["ubuntu-24.04"],
            "runner_group_id": 0,
            "runner_group_name": "GitHub Actions",
        }
        (bin_dir / "jobs.json").write_text(json.dumps({"jobs": [job]}))
        cache = tmp_path / "c.ndjson"
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
        result = subprocess.run(
            [
                "bash",
                str(CENSUS),
                "--repo",
                "o/r",
                "--days",
                "3",
                "--cache",
                str(cache),
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        lines = [json.loads(x) for x in cache.read_text().splitlines()]
        assert lines[0]["meta"]["visibility"] == "public", lines[0]
        assert lines[1]["runner_group_id"] == 0, lines[1]
        assert lines[1]["labels"] == ["ubuntu-24.04"], lines[1]
        assert json.loads(result.stdout)["billing"]["reading"] == "not billed"
        assert "repo view o/r" in (bin_dir / "calls.log").read_text()

    def test_a_failed_visibility_read_is_fatal(self, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text('#!/usr/bin/env bash\n[ "$1" = repo ] && exit 1\nexit 0\n')
        gh.chmod(0o755)
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
        result = subprocess.run(
            ["bash", str(CENSUS), "--repo", "o/r"],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        assert result.returncode == 2, (result.stdout, result.stderr)
        assert "visibility" in result.stderr
