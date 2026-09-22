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
  self-budget gate measures for it — a decision, which at the time needed
  justifying in three places.

Phase 7's `git add -A` then shipped both inside a commit about one file, and
under `--autonomous` neither appeared in the PR body that is the audit trail.

The rule: a run is SCOPED when `--file` or `--docs-dir` narrowed it. A scoped
run persists nothing unless it also passes `--calibrate`; a whole-surface run
persists both, as before, and now says so on stderr. The docs-dir KNOB
(`CONTEXT_DOCS_DIR`, `.skills/context-docs-dir`) configures what the surface
is and does not scope a run, so a knob-configured weekly run still calibrates.

Since #294 the two files are two decisions. `--anchor` persists the anchors
and never the ratio, on any scope: anchoring every SKILL.md in a skill library
is one scoped run per skill, and `--calibrate` on each would refit the ratio to
every skill in turn and leave it at whichever ran last.
"""

import json
import os
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
        # Exit 2, not 0, since #294 CR 22: see TestAPersistThatDidNotHappenSaysSo.
        r = _run(repo, env, "--exact", "--calibrate", *SCOPE)
        assert r.returncode == 2, r.stderr
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


def _second_corner(repo: Path) -> tuple[str, ...]:
    """A second skill at the repo's own 3.00, so a ratio refit to it lands on a
    different figure from one refit to the dense corner."""
    _sized(repo / "skills" / "y" / "SKILL.md", 3_000)
    _sized(repo / "skills" / "y" / "references" / "prose.md", 3_000)
    return ("--file", "skills/y/SKILL.md", "--docs-dir", "skills/y/references")


class TestAnchorPersistsTheAnchorsAlone:
    """#294: every SKILL.md anchored, by a refresh committed by hand.

    The refresh is one scoped run per skill — `--file` takes one path — and
    before this flag the only way a scoped run could persist an anchor was
    `--calibrate`, which also refits the repo-wide ratio to that corner. Run
    once per skill, that is #263's re-pricing once per skill, ending at
    whichever ran last.
    """

    def test_a_scoped_run_anchors_the_corner_and_leaves_the_ratio(
        self, tmp_path: Path, exact_env: dict
    ):
        repo = _calibrated(tmp_path, exact_env)
        r = _ok(repo, exact_env, "--exact", "--anchor", *SCOPE)
        assert (repo / RATIO).read_text().strip() == "3.00"
        rows = _rows(repo)
        assert rows["skills/x/SKILL-dense.md"] == (6_000, 3_000)
        assert rows["skills/x/references/dense.md"] == (4_000, 2_000)
        assert rows["AGENTS.md"] == (9_000, 3_000), "rows outside the scope kept"
        assert "--anchor: measured 2.00" in r.stderr, r.stderr
        assert "context-token-ratio stays 3.00" in r.stderr, r.stderr

    def test_a_whole_surface_run_anchors_without_refitting(
        self, tmp_path: Path, exact_env: dict
    ):
        """Not only a scoped-run switch: on the flagless surface, where the
        ratio WOULD be written, it still is not."""
        repo = _calibrated(tmp_path, exact_env)
        _sized(repo / "docs" / "dense-extra.md", 6_000)
        _ok(repo, exact_env, "--exact", "--anchor")
        assert (repo / RATIO).read_text().strip() == "3.00"
        assert _rows(repo)["docs/dense-extra.md"] == (6_000, 3_000)

    def test_a_run_per_corner_leaves_the_ratio_where_it_was(
        self, tmp_path: Path, exact_env: dict
    ):
        """The documented refresh in miniature, beside the loop it replaces."""
        repo = _calibrated(tmp_path, exact_env)
        other = _second_corner(repo)
        for corner in (other, SCOPE):
            _ok(repo, exact_env, "--exact", "--anchor", *corner)
        assert (repo / RATIO).read_text().strip() == "3.00"
        assert {"skills/x/SKILL-dense.md", "skills/y/SKILL.md"} <= set(_rows(repo))

        for corner in (other, SCOPE):
            _ok(repo, exact_env, "--exact", "--calibrate", *corner)
        assert (repo / RATIO).read_text().strip() == "2.00", (
            "the same loop under --calibrate should end at the last corner's "
            "rate; if it no longer does, this flag's reason has changed"
        )

    @pytest.mark.parametrize(
        "extra,message",
        [
            (("--no-write",), "--anchor and --no-write contradict"),
            (("--calibrate",), "pass one"),
        ],
    )
    def test_it_is_refused_with_a_contradicting_flag(
        self, tmp_path: Path, exact_env: dict, extra: tuple[str, ...], message: str
    ):
        repo = _repo(tmp_path)
        r = _run(repo, exact_env, "--exact", "--anchor", *extra, *SCOPE)
        assert r.returncode == 1
        assert message in r.stderr, r.stderr
        assert not (repo / COUNTS).exists()
        assert not (repo / RATIO).exists()

    def test_it_is_refused_without_exact(self, tmp_path: Path):
        repo = _repo(tmp_path)
        r = _run(repo, _clean_env(), "--anchor", *SCOPE)
        assert r.returncode == 1
        assert "--anchor needs --exact" in r.stderr
        assert not (repo / COUNTS).exists()

    def test_check_credential_is_not_refused_by_it(self, tmp_path: Path):
        repo = _repo(tmp_path)
        r = _run(repo, _clean_env(), "--check-credential", "--anchor")
        assert r.returncode == 3, r.stderr
        assert "--anchor needs --exact" not in r.stderr

    def test_a_scoped_run_without_it_names_it(self, tmp_path: Path, exact_env: dict):
        repo = _calibrated(tmp_path, exact_env)
        r = _ok(repo, exact_env, "--exact", *SCOPE)
        assert "or --anchor for the anchors alone" in r.stderr, r.stderr

    def test_the_help_documents_it(self):
        r = subprocess.run(
            ["bash", str(MEASURE), "--help"], capture_output=True, text=True, timeout=30
        )
        assert r.returncode == 0
        assert "--anchor" in r.stdout
        assert "#294" in r.stdout


# count_tokens answering for the SKILL.md and failing for everything under
# references/: a rate limit arriving part-way through one skill, which is the
# likeliest way a count in the documented refresh loop falls back.
PARTIAL_COUNTER = """#!/bin/sh
case "$2" in
  *references*) echo "HTTP 429: rate limited" >&2; exit 1 ;;
esac
b=$(wc -c <"$2" | tr -d ' ')
echo $(( b * 100 / 300 ))
"""


@pytest.fixture
def partial_env(tmp_path: Path) -> dict:
    bin_dir = _bin_with_real_tools(tmp_path / "partial-bin")
    (bin_dir / "python3").unlink()
    (bin_dir / "python3").write_text(PARTIAL_COUNTER)
    (bin_dir / "python3").chmod(0o755)
    env = _clean_env()
    env["PATH"] = str(bin_dir)
    env["ANTHROPIC_API_KEY"] = "sk-ant-test-offline"
    return env


def _refusal(stderr: str, flag: str) -> str:
    """The one ERROR line saying `flag` persisted nothing."""
    lines = [
        ln for ln in stderr.splitlines() if ln.startswith(f"ERROR {flag} persisted")
    ]
    assert len(lines) == 1, stderr
    return lines[0]


class TestAPersistThatDidNotHappenSaysSo:
    """#294 CR 22. `--anchor` and `--calibrate` ask for a write, and a run in
    which any count fell back persists nothing — correctly, since an estimate
    cannot anchor the estimator. It used to exit 0 saying nothing about it, so
    docs/STYLE.md's refresh loop, `… --anchor … || break`, never broke on the
    likeliest failure and moved on to the next skill with this one unanchored.
    Now it names what was not written and exits 2, after the measurement.
    """

    @pytest.mark.parametrize("flag", ["--anchor", "--calibrate"])
    def test_a_count_that_fell_back_exits_2_and_writes_nothing(
        self, tmp_path: Path, partial_env: dict, flag: str
    ):
        repo = _repo(tmp_path)
        r = _run(repo, partial_env, "--exact", flag, *SCOPE)
        assert r.returncode == 2, r.stderr
        assert f"ERROR {flag} persisted nothing" in r.stderr, r.stderr
        assert "Exit 2" in _refusal(r.stderr, flag)
        assert "exact count failed" in r.stderr, "the cause is still on stderr"
        assert json.loads(r.stdout)["policy"]["tokens_exact"] is False, (
            "the measurement still prints in full"
        )
        assert not (repo / COUNTS).exists()
        assert not (repo / RATIO).exists()

    def test_no_credential_at_all_is_the_same_refusal(self, tmp_path: Path):
        """The preflight in the documented loop catches this one, but a bare
        `--exact --anchor` must not rely on having been preceded by it."""
        bin_dir = _bin_with_real_tools(tmp_path / "keyless-bin")
        env = _clean_env()
        env["PATH"] = str(bin_dir)
        repo = _repo(tmp_path)
        r = _run(repo, env, "--exact", "--anchor", "--no-env-file", *SCOPE)
        assert r.returncode == 2, r.stderr
        assert "ERROR --anchor persisted nothing" in r.stderr, r.stderr
        assert not (repo / COUNTS).exists()

    def test_a_plain_measurement_that_fell_back_still_exits_0(
        self, tmp_path: Path, partial_env: dict
    ):
        """Nothing was asked to be written, so nothing failed to be: the
        fallback is reported as tokens_exact=false, as it always was."""
        repo = _repo(tmp_path)
        r = _run(repo, partial_env, "--exact", *SCOPE)
        assert r.returncode == 0, r.stderr
        assert "persisted nothing" not in r.stderr

    def test_the_refresh_loop_breaks_on_it(self, tmp_path: Path, partial_env: dict):
        """The loop docs/STYLE.md documents, in miniature: it stops at the
        first skill whose anchor could not be written."""
        repo = _repo(tmp_path)
        _second_corner(repo)
        loop = (
            'for s in skills/x/SKILL-dense.md skills/y/SKILL.md; do bash "$0" '
            '--exact --anchor --file "$s" --docs-dir "${s%/*}/references" '
            '>/dev/null || break; echo "anchored $s"; done'
        )
        r = subprocess.run(
            ["bash", "-c", loop, str(MEASURE)],
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=partial_env,
            timeout=120,
        )
        assert "anchored" not in r.stdout, r.stdout + r.stderr

    def test_an_over_budget_gate_still_gives_its_verdict(
        self, tmp_path: Path, partial_env: dict
    ):
        """Both are said; the gate's exit, the more specific verdict, wins —
        and the refusal names the code the run returns, not the 2 it would
        have returned alone (#294 CR 53). It said "Exit 2" above a run that
        exited 4, so a reader of the log was told the wrong code."""
        repo = _repo(tmp_path)
        gate = ("--gate", "--budget", "1")
        r = _run(repo, partial_env, "--exact", "--anchor", *gate, *SCOPE)
        assert r.returncode == 4, r.stderr
        assert "GATE" in r.stderr
        line = _refusal(r.stderr, "--anchor")
        assert "Exit 4" in line, line
        assert "Exit 2" not in line, line

    def test_an_under_budget_gate_leaves_the_refusal_its_own_exit(
        self, tmp_path: Path, partial_env: dict
    ):
        """--gate alone is not the verdict: a gate that passes leaves exit 2,
        and the refusal says 2."""
        repo = _repo(tmp_path)
        r = _run(repo, partial_env, "--exact", "--anchor", "--gate", *SCOPE)
        assert r.returncode == 2, r.stderr
        assert "GATE" not in r.stderr
        line = _refusal(r.stderr, "--anchor")
        assert "Exit 2" in line, line
        assert "Exit 4" not in line, line

    def test_the_help_documents_it(self):
        r = subprocess.run(
            ["bash", str(MEASURE), "--help"], capture_output=True, text=True, timeout=30
        )
        text = " ".join(r.stdout.split())
        assert "--anchor/--calibrate persisted nothing" in text, text
        assert "could not write what it was asked to persist" in text, text


def _unwritable(tmp_path: Path) -> Path:
    """The fixture repo with `.skills` a FILE, so every write under it fails
    however the script makes it — `printf >`, `mv`, or `mkdir -p` first."""
    repo = _repo(tmp_path)
    (repo / ".skills").write_text("not a directory\n")
    return repo


class TestAWriteThatFailedSaysSo:
    """#294 CR 54. CR 22 made a write that was ASKED for and did not happen
    exit 2 — but only the fallback path. A write that was attempted and failed
    printed `WARN could not write …` and exited 0 under --anchor/--calibrate,
    so the refresh loop's `|| break` carried on past a skill whose anchor is
    not on disk: the same silent miss, by a second road.
    """

    @pytest.mark.parametrize(
        ("flag", "unwritten"),
        [
            ("--anchor", [".skills/context-token-counts"]),
            (
                "--calibrate",
                [".skills/context-token-ratio", ".skills/context-token-counts"],
            ),
        ],
    )
    def test_a_failed_write_exits_2_and_names_the_file(
        self, tmp_path: Path, exact_env: dict, flag: str, unwritten: list
    ):
        repo = _unwritable(tmp_path)
        r = _run(repo, exact_env, "--exact", flag, *SCOPE)
        assert r.returncode == 2, r.stderr
        assert "WARN could not write" in r.stderr, "the cause is still on stderr"
        line = next(
            (ln for ln in r.stderr.splitlines() if ln.startswith(f"ERROR {flag}")),
            "",
        )
        assert "could not write" in line, r.stderr
        for name in unwritten:
            assert name in line, line
        assert "Exit 2" in line, line
        assert "count_tokens" not in line, (
            "every count reached count_tokens; the refusal must not blame it"
        )
        assert json.loads(r.stdout)["policy"]["tokens_exact"] is True, (
            "the measurement still prints in full, and it was exact"
        )

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root writes into a read-only directory",
    )
    def test_a_half_written_calibrate_says_only_that_half_failed(
        self, tmp_path: Path, exact_env: dict
    ):
        """CR 69. The ratio goes into its existing file and the counts are
        moved into .skills/, so a read-only directory holding a writable ratio
        file takes one write and refuses the other. The refusal said "what it
        was asked to persist is not on disk" beneath "INFO wrote
        .skills/context-token-ratio"."""
        repo = _calibrated(tmp_path, exact_env)
        skills = repo / ".skills"
        skills.chmod(0o555)
        try:
            r = _run(repo, exact_env, "--exact", "--calibrate", *SCOPE)
        finally:
            skills.chmod(0o755)
        assert r.returncode == 2, r.stderr
        assert "INFO wrote .skills/context-token-ratio" in r.stderr, r.stderr
        line = next(
            (ln for ln in r.stderr.splitlines() if ln.startswith("ERROR --calibrate")),
            "",
        )
        assert "could not write .skills/context-token-counts" in line, r.stderr
        assert "context-token-ratio" not in line, line
        assert "not all of what it was asked to persist" in line, line

    def test_the_refresh_loop_breaks_on_it(self, tmp_path: Path, exact_env: dict):
        repo = _unwritable(tmp_path)
        _second_corner(repo)
        loop = (
            'for s in skills/x/SKILL-dense.md skills/y/SKILL.md; do bash "$0" '
            '--exact --anchor --file "$s" --docs-dir "${s%/*}/references" '
            '>/dev/null || break; echo "anchored $s"; done'
        )
        r = subprocess.run(
            ["bash", "-c", loop, str(MEASURE)],
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=exact_env,
            timeout=120,
        )
        assert "anchored" not in r.stdout, r.stdout + r.stderr

    def test_an_over_budget_gate_still_wins(self, tmp_path: Path, exact_env: dict):
        repo = _unwritable(tmp_path)
        gate = ("--gate", "--budget", "1")
        r = _run(repo, exact_env, "--exact", "--anchor", *gate, *SCOPE)
        assert r.returncode == 4, r.stderr
        assert "GATE" in r.stderr
        line = next(
            ln for ln in r.stderr.splitlines() if ln.startswith("ERROR --anchor")
        )
        assert "could not write" in line and "Exit 4" in line, line

    def test_a_whole_surface_run_that_was_not_asked_still_exits_0(
        self, tmp_path: Path, exact_env: dict
    ):
        """A flagless whole-surface run persists both by default, but nothing
        asked it to, so a failed write stays the WARN it was — the same line
        CR 22 drew for a fallback."""
        repo = _unwritable(tmp_path)
        r = _run(repo, exact_env, "--exact")
        assert r.returncode == 0, r.stderr
        assert "WARN could not write" in r.stderr
        assert "ERROR" not in r.stderr, r.stderr
