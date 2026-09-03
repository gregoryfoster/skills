"""#263 — a scoped `--exact` run reads the calibration and does not write it.

`measure-context.sh --exact` persists two repo-wide files: the surface ratio in
`.skills/context-token-ratio`, which every offline estimate in the repo divides
by, and the per-file anchors in `.skills/context-token-counts`, which make a
file's offline estimate a rescale of its own last exact count. Curating ONE
skill runs `--exact --file skills/X/SKILL.md --docs-dir skills/X/references`,
and that run rewrote both:

- the ratio went 2.68 -> 2.63 — that one file's rate, applied to every file in
  the repo, which put two skills the run never touched over their budgets;
- the counts file gained an anchor row for the file, which changed what the
  self-budget gate measures for it (`test_which_skills_are_anchored_is_declared`
  treats that as a decision needing justification in three places).

Phase 7's `git add -A` then shipped both inside a commit about one file, and
under `--autonomous` neither appeared in the PR body that is the audit trail.

The rule: a run is SCOPED when `--file` or `--docs-dir` narrowed it. A scoped
run persists nothing unless it also passes `--calibrate`; a whole-surface run
persists both, as before, and now says so on stderr. The docs-dir KNOB
(`CONTEXT_DOCS_DIR`, `.skills/context-docs-dir`) configures what the surface
is and does not scope a run, so a knob-configured weekly run still calibrates.
"""

import subprocess
from pathlib import Path

import pytest

from .test_per_file_calibration import (
    COUNTS,
    FAKE_COUNTER,
    MEASURE,
    _bin_with_real_tools,
    _clean_env,
    _git,
    _rows,
    _sized,
)

RATIO = ".skills/context-token-ratio"


@pytest.fixture
def exact_env(tmp_path: Path) -> dict:
    """The sibling module's offline count_tokens shim: a path containing
    `dense` prices at 2.00 bytes/token, everything else at 3.00."""
    bin_dir = _bin_with_real_tools(tmp_path / "bin")
    (bin_dir / "python3").unlink()
    (bin_dir / "python3").write_text(FAKE_COUNTER)
    (bin_dir / "python3").chmod(0o755)
    env = _clean_env()
    env["PATH"] = str(bin_dir)
    env["ANTHROPIC_API_KEY"] = "sk-ant-test-offline"
    return env


def _run(repo: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(MEASURE), *args],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=env,
        timeout=120,
    )


def _ok(repo: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    r = _run(repo, env, *args)
    assert r.returncode == 0, r.stderr
    return r


def _repo(tmp_path: Path) -> Path:
    """A policy surface at 3.00 bytes/token, and one skill corner at 2.00 —
    the same shape as the incident: the corner's rate is not the repo's.

        AGENTS.md                      9000 B / 3000 tok -> 3.00
        docs/prose.md                  3000 B / 1000 tok -> 3.00
        skills/x/SKILL.md (dense)      6000 B / 3000 tok -> 2.00
        skills/x/references/dense.md   4000 B / 2000 tok -> 2.00
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _sized(repo / "AGENTS.md", 9_000)
    _sized(repo / "docs" / "prose.md", 3_000)
    _sized(repo / "skills" / "x" / "SKILL-dense.md", 6_000)
    _sized(repo / "skills" / "x" / "references" / "dense.md", 4_000)
    return repo


SCOPE = ("--file", "skills/x/SKILL-dense.md", "--docs-dir", "skills/x/references")


def _calibrated(tmp_path: Path, env: dict) -> Path:
    """The repo after its whole-surface run: ratio 3.00, two anchors."""
    repo = _repo(tmp_path)
    _ok(repo, env, "--exact")
    assert (repo / RATIO).read_text().strip() == "3.00"
    assert set(_rows(repo)) == {"AGENTS.md", "docs/prose.md"}
    return repo


class TestAScopedRunDoesNotCalibrate:
    def test_the_ratio_is_left_standing(self, tmp_path: Path, exact_env: dict):
        """The issue's diff: `-2.68 +2.63`. Here `3.00` would become `2.00`."""
        repo = _calibrated(tmp_path, exact_env)
        _ok(repo, exact_env, "--exact", *SCOPE)
        assert (repo / RATIO).read_text().strip() == "3.00", (
            "a --file/--docs-dir run re-priced the whole repo from one corner"
        )

    def test_the_corner_is_not_anchored(self, tmp_path: Path, exact_env: dict):
        """The second side effect: an anchor row changes what any gate that
        reads the offline estimate measures for that file."""
        repo = _calibrated(tmp_path, exact_env)
        before = (repo / COUNTS).read_text()
        _ok(repo, exact_env, "--exact", *SCOPE)
        assert (repo / COUNTS).read_text() == before
        assert "skills/x/SKILL-dense.md" not in _rows(repo)

    def test_a_scoped_run_on_a_never_calibrated_repo_creates_nothing(
        self, tmp_path: Path, exact_env: dict
    ):
        repo = _repo(tmp_path)
        r = _ok(repo, exact_env, "--exact", *SCOPE)
        assert not (repo / RATIO).exists()
        assert not (repo / COUNTS).exists()
        # Least obvious exactly here, so the line says what the repo prices
        # from rather than printing a placeholder.
        assert "no .skills/context-token-ratio exists" in r.stderr, r.stderr
        assert "2.70 library default" in r.stderr, r.stderr
        assert "(none)" not in r.stderr

    def test_an_empty_ratio_file_is_named_not_quoted(
        self, tmp_path: Path, exact_env: dict
    ):
        repo = _repo(tmp_path)
        (repo / ".skills").mkdir()
        (repo / RATIO).write_text("")
        r = _ok(repo, exact_env, "--exact", *SCOPE)
        assert (repo / RATIO).read_text() == ""
        assert "is empty or unreadable" in r.stderr, r.stderr
        assert "stays ," not in r.stderr

    def test_file_alone_scopes(self, tmp_path: Path, exact_env: dict):
        repo = _calibrated(tmp_path, exact_env)
        _ok(repo, exact_env, "--exact", "--file", "skills/x/SKILL-dense.md")
        assert (repo / RATIO).read_text().strip() == "3.00"
        assert "skills/x/SKILL-dense.md" not in _rows(repo)

    def test_docs_dir_alone_scopes(self, tmp_path: Path, exact_env: dict):
        repo = _calibrated(tmp_path, exact_env)
        _ok(repo, exact_env, "--exact", "--docs-dir", "skills/x/references")
        assert (repo / RATIO).read_text().strip() == "3.00"
        assert "skills/x/references/dense.md" not in _rows(repo)

    def test_the_scoped_run_still_reads_the_calibration(
        self, tmp_path: Path, exact_env: dict
    ):
        """Consumes, does not write. An OFFLINE scoped run over an anchored
        file prices from its anchor; one over an unanchored file prices from
        the repo ratio the scoped exact run left in place."""
        import json

        repo = _calibrated(tmp_path, exact_env)
        _ok(repo, exact_env, "--exact", *SCOPE)
        env = _clean_env()
        out = json.loads(_ok(repo, env, "--file", "AGENTS.md").stdout)
        assert out["policy"]["tokens_source"] == "file"
        out = json.loads(_ok(repo, env, *SCOPE).stdout)
        assert out["policy"]["tokens_source"] == "repo"
        assert out["policy"]["tokens"] == 2_000, "priced at the 3.00 repo ratio"

    def test_it_says_what_it_left_alone_and_how_to_change_that(
        self, tmp_path: Path, exact_env: dict
    ):
        """Option 3 of the issue, kept alongside option 1: Phase 6's "test
        suite still passes" must not be the only thing that reports it."""
        repo = _calibrated(tmp_path, exact_env)
        r = _ok(repo, exact_env, "--exact", *SCOPE)
        assert "context-token-ratio stays 3.00" in r.stderr, r.stderr
        assert "2.00" in r.stderr, "the corner's own figure, for the record"
        assert "not anchoring the 2 counted file(s)" in r.stderr, r.stderr
        # One call to action, on the line that names both files' fate.
        assert r.stderr.count("--calibrate") == 1, r.stderr
        assert "persist the ratio and the anchors" in r.stderr
        assert "#263" in r.stderr


class TestCalibrateIsTheDecision:
    def test_it_persists_both_from_a_scoped_run(self, tmp_path: Path, exact_env: dict):
        repo = _calibrated(tmp_path, exact_env)
        _ok(repo, exact_env, "--exact", "--calibrate", *SCOPE)
        assert (repo / RATIO).read_text().strip() == "2.00"
        rows = _rows(repo)
        assert rows["skills/x/SKILL-dense.md"] == (6_000, 3_000)
        assert rows["skills/x/references/dense.md"] == (4_000, 2_000)

    def test_it_still_merges_rather_than_clobbers(
        self, tmp_path: Path, exact_env: dict
    ):
        """#145's merge is unchanged: opting in to anchor a corner does not
        drop the anchors outside it."""
        repo = _calibrated(tmp_path, exact_env)
        _ok(repo, exact_env, "--exact", "--calibrate", *SCOPE)
        assert _rows(repo)["AGENTS.md"] == (9_000, 3_000)

    def test_it_is_refused_with_no_write(self, tmp_path: Path, exact_env: dict):
        repo = _repo(tmp_path)
        r = _run(repo, exact_env, "--exact", "--calibrate", "--no-write", *SCOPE)
        assert r.returncode == 1
        assert "--calibrate and --no-write contradict" in r.stderr
        assert not (repo / RATIO).exists()

    def test_it_is_refused_without_exact(self, tmp_path: Path):
        """An estimate cannot calibrate the estimator — the same
        self-confirmation guard the writers already have, one layer earlier."""
        repo = _repo(tmp_path)
        r = _run(repo, _clean_env(), "--calibrate", *SCOPE)
        assert r.returncode == 1
        assert "--calibrate needs --exact" in r.stderr
        assert not (repo / RATIO).exists()

    def test_a_credential_that_could_not_count_still_writes_nothing(
        self, tmp_path: Path
    ):
        """--calibrate opts in to persisting a MEASUREMENT. A failed count is
        an estimate, and the exact_flag gate still refuses it."""
        bin_dir = _bin_with_real_tools(tmp_path / "bin")
        (bin_dir / "python3").unlink()
        (bin_dir / "python3").write_text("#!/bin/sh\necho boom >&2\nexit 1\n")
        (bin_dir / "python3").chmod(0o755)
        env = _clean_env()
        env["PATH"] = str(bin_dir)
        env["ANTHROPIC_API_KEY"] = "sk-ant-test-offline"
        repo = _repo(tmp_path)
        _ok(repo, env, "--exact", "--calibrate", *SCOPE)
        assert not (repo / RATIO).exists()
        assert not (repo / COUNTS).exists()

    def test_check_credential_is_not_refused_by_it(self, tmp_path: Path):
        """The preflight measures nothing, so a flag that only matters to a
        measurement must not stop it answering."""
        repo = _repo(tmp_path)
        r = _run(repo, _clean_env(), "--check-credential", "--calibrate")
        assert r.returncode == 3, r.stderr
        assert "--calibrate needs --exact" not in r.stderr

    def test_the_help_documents_it(self):
        r = subprocess.run(
            ["bash", str(MEASURE), "--help"], capture_output=True, text=True, timeout=30
        )
        assert r.returncode == 0
        assert "--calibrate" in r.stdout
        assert "#263" in r.stdout


class TestAWholeSurfaceRunStillCalibratesAndSaysSo:
    def test_no_flags_persists_both(self, tmp_path: Path, exact_env: dict):
        repo = _repo(tmp_path)
        r = _ok(repo, exact_env, "--exact")
        assert (repo / RATIO).read_text().strip() == "3.00"
        assert set(_rows(repo)) == {"AGENTS.md", "docs/prose.md"}
        assert "wrote .skills/context-token-ratio: 3.00 (was (none))" in r.stderr
        assert (
            "wrote .skills/context-token-counts: 2 of 2 counted file(s) anchored"
            in r.stderr
        )

    def test_a_rewrite_names_the_figure_it_replaced(
        self, tmp_path: Path, exact_env: dict
    ):
        """The `-2.68 +2.63` diff, printed by the run that made it rather than
        found later by `git diff`."""
        repo = _calibrated(tmp_path, exact_env)
        (repo / "docs" / "dense-extra.md").write_text("x" * 6_000)
        r = _ok(repo, exact_env, "--exact")
        assert (repo / RATIO).read_text().strip() != "3.00"
        assert "(was 3.00)" in r.stderr, r.stderr

    def test_the_docs_dir_knob_configures_rather_than_scopes(
        self, tmp_path: Path, exact_env: dict
    ):
        """`.skills/context-docs-dir` is how a repo says where its docs live;
        the weekly cadence runs with no flags against it and must keep
        calibrating (cadence.md: the run "refreshes" both files)."""
        repo = _repo(tmp_path)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-docs-dir").write_text("skills/x/references\n")
        _ok(repo, exact_env, "--exact")
        assert (repo / RATIO).exists()
        assert "skills/x/references/dense.md" in _rows(repo)

    def test_the_env_knob_configures_rather_than_scopes(
        self, tmp_path: Path, exact_env: dict
    ):
        repo = _repo(tmp_path)
        env = dict(exact_env, CONTEXT_DOCS_DIR="skills/x/references")
        _ok(repo, env, "--exact")
        assert (repo / RATIO).exists()
        assert "skills/x/references/dense.md" in _rows(repo)

    def test_calibrate_on_a_whole_surface_run_is_a_no_op(
        self, tmp_path: Path, exact_env: dict
    ):
        repo = _repo(tmp_path)
        a = _ok(repo, exact_env, "--exact").stdout
        ratio_a = (repo / RATIO).read_text()
        b = _ok(repo, exact_env, "--exact", "--calibrate").stdout
        assert a == b
        assert (repo / RATIO).read_text() == ratio_a
