"""The interval a scheduled seam sweep measures over (#169).

The cadence swept with `check-seams.sh --base HEAD`. `check-seams.sh` reads the
base policy file with `git show "$BASE:$REL"` and compares it against the policy
file in the working tree, so on a clean CI checkout the two are the same content
and the diff is empty. Only one of the four seam classes — moved-title, and the
source-moved-title shape that rides on the same `moved` set — depends on that
diff, and it was therefore **zero in every scheduled run, in every repo,
forever, by construction**. `references/cadence.md` meanwhile lists *seam
accrual* as one of the three metrics the cadence exists to collect, and #118 is
about to register it as the primary one.

The fix is a real base: the repo commit recorded by the previous ledger row, so
each week's sweep spans the interval since the last measurement. That needs two
things this file pins:

- `record-telemetry.sh` puts the measured **repo** commit on the row.
  `skill_commit` is the *skill's* commit and was never a candidate.
- `check-seams.sh --base-ledger PATH` reads that commit back out and sweeps from
  it, with the no-predecessor case defined rather than left to fall through to
  `HEAD` — which is exactly the bug.

Kept out of test_seam_sweep.py because that file is about the sweep's *reach*
(which titles match, which files are read) and this one is about the *interval*;
and out of test_cadence_rendered_shell.py because the workflow is only one of
the three surfaces the change has to move together.
"""

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "skills" / "curating-context" / "scripts"
SEAMS = SCRIPTS / "check-seams.sh"
MEASURE = SCRIPTS / "measure-context.sh"
RECORD = SCRIPTS / "record-telemetry.sh"
INSTALL_CADENCE = SCRIPTS / "install-cadence.sh"

LEDGER_REL = ".skills/context-metrics.jsonl"


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    return env


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True, env=_clean_env())


def _write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


BASE_POLICY = (
    "# Guide\n\n## Build\n\nrun make\n\n"
    "## Deployment Topology\n\nThe workers connect to the bus directly.\n"
)

NOW_POLICY = (
    "# Guide\n\n## Build\n\nrun make\n\n## Detail docs\n\n"
    "- [docs/TOPOLOGY.md](docs/TOPOLOGY.md) — how the workers connect\n"
)

TOPOLOGY_DOC = (
    "# Topology\n\n## Deployment Topology\n\n"
    "The workers connect to the bus directly.\n"
)

# The seam: prose still sending a reader to a section that left the policy file.
STALE_REF = "# API\n\nThe Deployment Topology section has the diagram.\n"


def _curated_repo(tmp_path: Path, name: str = "interval") -> tuple[Path, str]:
    """A repo whose curation is COMMITTED, which is the scheduled case.

    Returns the repo and the commit that was current when the previous
    measurement was taken — the interval start a real base has to use. The
    curation lands on top of it, so `--base HEAD` sees no change at all and
    `--base <that commit>` sees the section leave.
    """
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _write(repo, "AGENTS.md", BASE_POLICY)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "before the curation")
    measured = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()

    _write(repo, "AGENTS.md", NOW_POLICY)
    _write(repo, "docs/TOPOLOGY.md", TOPOLOGY_DOC)
    _write(repo, "docs/API.md", STALE_REF)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "the curation, danglers and all")
    return repo, measured


def _ledger(repo: Path, **fields) -> None:
    row = {"ts": "2026-08-10", "repo": "r", "file": "AGENTS.md", "tokens": 100,
           "tokens_exact": True, "actions": ["baseline:scheduled"]}
    row.update(fields)
    _write(repo, LEDGER_REL, json.dumps(row, sort_keys=True) + "\n")


def _sweep(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SEAMS), *args], cwd=repo,
                          capture_output=True, text=True, env=_clean_env(),
                          timeout=60)


class TestTheRowCarriesTheMeasuredRepoCommit:
    """`skill_commit` is the skill's. Nothing on the row said which state of the
    REPO was measured, so nothing downstream could name the interval."""

    def _row(self, repo: Path) -> dict:
        out = subprocess.run(
            ["bash", "-c",
             f'cd "{repo}" && bash "{MEASURE}" --no-write 2>/dev/null'
             f' | bash "{RECORD}" --dry-run'],
            capture_output=True, text=True, env=_clean_env(), timeout=90)
        assert out.stdout.strip(), out.stderr
        return json.loads(out.stdout)

    def test_the_row_records_the_repo_commit(self, tmp_path: Path):
        repo, _ = _curated_repo(tmp_path, "rowcommit")
        head = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
        row = self._row(repo)
        assert row["repo_commit"] == head, row

    def test_repo_commit_is_not_skill_commit(self, tmp_path: Path):
        """They are different repositories and the row must not conflate them."""
        repo, _ = _curated_repo(tmp_path, "notskill")
        row = self._row(repo)
        assert row["repo_commit"] != row.get("skill_commit"), row

    def test_a_repo_with_no_commits_records_null(self, tmp_path: Path):
        """Null, never a guess: a row that invents a commit sends the next
        sweep to a revision that was never measured."""
        repo = tmp_path / "nocommits"
        repo.mkdir()
        _git(repo, "init", "-q")
        _write(repo, "AGENTS.md", BASE_POLICY)
        row = self._row(repo)
        assert row["repo_commit"] is None, row


class TestBaseLedgerResolvesTheInterval:
    def test_it_sweeps_from_the_commit_the_last_row_recorded(
            self, tmp_path: Path):
        """The whole point. Against HEAD this repo shows no change at all."""
        repo, measured = _curated_repo(tmp_path, "resolve")
        _ledger(repo, repo_commit=measured)
        r = _sweep(repo, "--base-ledger", LEDGER_REL)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "moved-title" in r.stdout, r.stdout
        assert "docs/API.md:3" in r.stdout, r.stdout

    def test_the_same_repo_reports_nothing_against_head(self, tmp_path: Path):
        """The bug, pinned so the fix cannot be mistaken for the fixture being
        generous: the identical tree under the old default finds nothing."""
        repo, _ = _curated_repo(tmp_path, "againsthead")
        r = _sweep(repo, "--base", "HEAD")
        assert "moved-title" not in r.stdout, r.stdout
        assert "seams: 0" in r.stdout, r.stdout

    def test_the_resolved_base_is_reported(self, tmp_path: Path):
        repo, measured = _curated_repo(tmp_path, "reported")
        _ledger(repo, repo_commit=measured)
        r = _sweep(repo, "--base-ledger", LEDGER_REL)
        assert f"seam_base: {measured}" in r.stdout, r.stdout

    def test_the_counts_are_still_the_last_two_lines(self, tmp_path: Path):
        """Three readers parse the tail. The base line goes ABOVE them."""
        repo, measured = _curated_repo(tmp_path, "tail")
        _ledger(repo, repo_commit=measured)
        r = _sweep(repo, "--base-ledger", LEDGER_REL)
        lines = r.stdout.rstrip().splitlines()
        assert lines[-1].startswith("seams: "), lines[-4:]
        assert lines[-2].startswith("seams_acked: "), lines[-4:]
        assert lines[-3].startswith("seam_base: "), lines[-4:]

    def test_the_newest_row_wins(self, tmp_path: Path):
        """The interval starts at the LAST measurement, not the first one."""
        repo, measured = _curated_repo(tmp_path, "newest")
        rows = [
            json.dumps({"ts": "2026-01-01", "file": "AGENTS.md",
                        "repo_commit": "0000000"}, sort_keys=True),
            json.dumps({"ts": "2026-08-10", "file": "AGENTS.md",
                        "repo_commit": measured}, sort_keys=True),
        ]
        _write(repo, LEDGER_REL, "\n".join(rows) + "\n")
        r = _sweep(repo, "--base-ledger", LEDGER_REL)
        assert f"seam_base: {measured}" in r.stdout, r.stdout
        assert r.returncode == 3, r.stdout

    def test_rows_predating_the_field_are_skipped(self, tmp_path: Path):
        """Every ledger in the cohort is full of them. A row with no
        repo_commit cannot name an interval, so it is not a predecessor."""
        repo, measured = _curated_repo(tmp_path, "predating")
        rows = [
            json.dumps({"ts": "2026-08-01", "file": "AGENTS.md",
                        "repo_commit": measured}, sort_keys=True),
            json.dumps({"ts": "2026-08-10", "file": "AGENTS.md"},
                       sort_keys=True),
        ]
        _write(repo, LEDGER_REL, "\n".join(rows) + "\n")
        r = _sweep(repo, "--base-ledger", LEDGER_REL)
        assert f"seam_base: {measured}" in r.stdout, r.stdout

    def test_a_malformed_line_does_not_stop_the_sweep(self, tmp_path: Path):
        repo, measured = _curated_repo(tmp_path, "malformed")
        _write(repo, LEDGER_REL,
               "{not json\n" + json.dumps(
                   {"ts": "2026-08-10", "file": "AGENTS.md",
                    "repo_commit": measured}, sort_keys=True) + "\n")
        r = _sweep(repo, "--base-ledger", LEDGER_REL)
        assert f"seam_base: {measured}" in r.stdout, r.stdout


class TestTheFirstRunIsDefinedRatherThanFallenInto:
    """No predecessor means no interval — which is a statement the report has to
    make, because the number it produces is not comparable with a later week's
    on the base-dependent classes."""

    def test_no_ledger_at_all_sweeps_the_standing_classes_and_says_so(
            self, tmp_path: Path):
        repo, _ = _curated_repo(tmp_path, "noledger")
        r = _sweep(repo, "--base-ledger", LEDGER_REL)
        assert r.returncode == 0, r.stdout
        assert "no previous measurement" in r.stdout, r.stdout
        assert "seam_base: HEAD" in r.stdout, r.stdout

    def test_an_empty_ledger_is_the_same_case(self, tmp_path: Path):
        repo, _ = _curated_repo(tmp_path, "emptyledger")
        _write(repo, LEDGER_REL, "")
        r = _sweep(repo, "--base-ledger", LEDGER_REL)
        assert "no previous measurement" in r.stdout, r.stdout

    def test_the_standing_classes_still_fire_on_a_first_run(
            self, tmp_path: Path):
        """The base-dependent classes are empty; the sweep is not."""
        repo, _ = _curated_repo(tmp_path, "standing")
        _write(repo, "docs/OPS.md", "# Ops\n\nSee AGENTS.md for the rest.\n")
        r = _sweep(repo, "--base-ledger", LEDGER_REL)
        assert r.returncode == 3, r.stdout
        assert "back-reference" in r.stdout, r.stdout

    def test_a_commit_that_is_not_in_this_history_falls_back_loudly(
            self, tmp_path: Path):
        """A rewrite, or a shallow clone. Falling back silently would zero the
        class for good in exactly the repo whose history moved."""
        repo, _ = _curated_repo(tmp_path, "unreachable")
        _ledger(repo, repo_commit="deadbee")
        r = _sweep(repo, "--base-ledger", LEDGER_REL)
        assert "deadbee" in r.stdout, r.stdout
        assert "WARN" in r.stdout, r.stdout
        assert "seam_base: HEAD" in r.stdout, r.stdout


class TestBaseAndBaseLedgerAreMutuallyExclusive:
    def test_passing_both_is_a_usage_error(self, tmp_path: Path):
        repo, measured = _curated_repo(tmp_path, "bothflags")
        _ledger(repo, repo_commit=measured)
        r = _sweep(repo, "--base", "HEAD", "--base-ledger", LEDGER_REL)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "mutually exclusive" in r.stderr, r.stderr


class TestTheCadenceUsesIt:
    """The workflow is the reason any of this exists: the interactive path could
    always pass a branch point by hand."""

    def _sweep_step(self, tmp_path: Path) -> str:
        yaml = __import__("yaml")
        render_repo = tmp_path / "render"
        render_repo.mkdir()
        _git(render_repo, "init", "-q")
        out = subprocess.run(
            ["bash", str(INSTALL_CADENCE), "--print"], capture_output=True,
            text=True, cwd=str(render_repo), env=_clean_env(), timeout=30)
        assert out.returncode == 0, out.stderr
        doc = yaml.safe_load(out.stdout)
        return next(s["run"] for s in doc["jobs"]["measure"]["steps"]
                    if s.get("name") == "Sweep the seams")

    def _run_step(self, tmp_path: Path, repo: Path) -> tuple[
            subprocess.CompletedProcess, str]:
        env = _clean_env()
        env["SKILL_SCRIPTS"] = str(SCRIPTS)
        gh_env = tmp_path / "gh_env"
        gh_env.write_text("")
        env["GITHUB_ENV"] = str(gh_env)
        r = subprocess.run(
            ["bash", "-e", "-c", self._sweep_step(tmp_path)],
            capture_output=True, text=True, cwd=str(repo), env=env, timeout=90)
        return r, gh_env.read_text()

    def test_the_scheduled_sweep_reports_a_moved_title_seam(
            self, tmp_path: Path):
        """The defect, at the layer it actually shipped in. A curation that
        relocated a section and left a dangler behind produced NO moved-title
        contribution to any weekly row, because by the next run the relocation
        was already in HEAD."""
        repo, measured = _curated_repo(tmp_path, "wfhit")
        _ledger(repo, repo_commit=measured)
        r, written = self._run_step(tmp_path, repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "moved-title" in r.stdout, r.stdout
        assert "SEAMS=1" in written, written

    def test_the_first_scheduled_run_still_records_a_count(
            self, tmp_path: Path):
        """No ledger yet is the state every adopting repo starts in, and the
        step must still hand a number to the recorder."""
        repo, _ = _curated_repo(tmp_path, "wffirst")
        r, written = self._run_step(tmp_path, repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "SEAMS=0" in written, written
        assert "SEAMS_ACKED=0" in written, written

    def test_the_step_does_not_pass_base_head(self, tmp_path: Path):
        step = self._sweep_step(tmp_path)
        assert "--base HEAD" not in step, step
        assert "--base-ledger" in step, step
