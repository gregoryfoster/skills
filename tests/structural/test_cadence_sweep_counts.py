"""The cadence sweep step owns its output files and fails on a missing count (#526).

`test_the_seam_extraction_parses_real_check_seams_output` once saw
`SEAMS_ACKED=` written empty, with the step exiting 0. Two things let it:

1. **A shared path.** The step wrote `check-seams.sh`'s output to the fixed
   `/tmp/seams.txt` (and `check-counts.sh`'s to `/tmp/counts.txt`), then read
   each count back with its own `sed`. The test runs that step verbatim, so
   two suite runs on one machine (a commit hook's beside a manual one, two
   lanes on one VM) write the same file: one run's `>` truncates it between
   the other's `SEAMS` read and its `SEAMS_ACKED` read. A runner reusing `/tmp`
   between jobs is the same race in CI.
2. **A silent empty.** `$(sed … | tail -1)` matching nothing is an empty string
   and exit 0, and record-telemetry's `${SEAMS_ACKED:+…}` then records the
   field as absent, so a lost count never reddened anything.

The step now writes to files of its own from `mktemp`, and fails, naming the
count and writing nothing to `GITHUB_ENV`, when any of its four counts is
missing. The race is measured, not inferred: four concurrent loops of the
seam test at 5c3e486e failed 7 of 60 runs, each with `SEAMS=` and
`SEAMS_ACKED=` written empty and the step exiting 0. The recorded failure,
with `SEAMS` intact, is the same race with the truncation landing between the
two reads. What ran beside that suite run was not identified.
"""

import re
import subprocess
from pathlib import Path

import pytest

from .test_context_surface import INSTALL_CADENCE, _clean_env, _git

STEP = "Sweep the seams and the counts"
COUNTS = ("SEAMS", "SEAMS_ACKED", "COUNTS", "COUNTS_ACKED")
# The trailers check-seams.sh and check-counts.sh print, as the step parses them.
SEAMS_OUT = "report\nseam_interval: empty\nseam_base: HEAD\nseams_acked: 2\nseams: 1\n"
COUNTS_OUT = "report\n\ncounts_acked: 4\ncounts: 3\n"


@pytest.fixture(scope="module")
def step(tmp_path_factory) -> str:
    yaml = pytest.importorskip("yaml")
    repo = tmp_path_factory.mktemp("render")
    _git(repo, "init", "-q")
    rendered = subprocess.run(
        ["bash", str(INSTALL_CADENCE), "--print"],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=30,
    )
    assert rendered.returncode == 0, rendered.stderr
    steps = yaml.safe_load(rendered.stdout)["jobs"]["measure"]["steps"]
    return next(s["run"] for s in steps if s.get("name") == STEP)


def _stub(path: Path, out: str) -> Path:
    """A tool that prints `out` and exits 3, a finding, as both may."""
    path.with_suffix(".out").write_text(out)
    path.write_text(f"#!/usr/bin/env bash\ncat '{path.with_suffix('.out')}'\nexit 3\n")
    return path


def _run(step: str, tmp_path: Path, seams: str = SEAMS_OUT, counts: str = COUNTS_OUT):
    tmpdir = tmp_path / "tmpdir"
    tmpdir.mkdir(exist_ok=True)
    gh_env = tmp_path / "gh_env"
    gh_env.write_text("")
    env = {
        **_clean_env(),
        "CHECK_SEAMS_SH": str(_stub(tmp_path / "seams.sh", seams)),
        "CHECK_COUNTS_SH": str(_stub(tmp_path / "counts.sh", counts)),
        "GITHUB_ENV": str(gh_env),
        "TMPDIR": str(tmpdir),
    }
    # GitHub runs a `run:` block as `bash --noprofile --norc -eo pipefail {0}`.
    r = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
        timeout=60,
    )
    return r, gh_env.read_text(), tmpdir


class TestTheStepOwnsItsFiles:
    def test_no_fixed_tmp_path(self, step: str):
        assert not re.search(r"/tmp/(seams|counts)\.txt", step), (
            "the sweep step writes a fixed /tmp path, which any other run on "
            "the machine can truncate between its reads (#526)"
        )
        assert "mktemp" in step, step

    def test_its_files_follow_tmpdir_and_are_removed(self, step: str, tmp_path: Path):
        r, written, tmpdir = _run(step, tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
        assert list(tmpdir.iterdir()) == [], "the step left its temp files behind"
        assert written.splitlines() == [
            "SEAMS=1",
            "SEAMS_ACKED=2",
            "COUNTS=3",
            "COUNTS_ACKED=4",
        ], written


class TestAMissingCountFailsLoudly:
    @pytest.mark.parametrize("name", COUNTS)
    def test_each_missing_count_fails_the_step(self, step: str, tmp_path: Path, name):
        prefix = name.lower() + ":"
        seams = "".join(
            ln + "\n" for ln in SEAMS_OUT.splitlines() if not ln.startswith(prefix)
        )
        counts = "".join(
            ln + "\n" for ln in COUNTS_OUT.splitlines() if not ln.startswith(prefix)
        )
        r, written, _ = _run(step, tmp_path, seams, counts)
        assert r.returncode != 0, f"a missing {name} passed:\n{r.stdout}"
        assert "::error::" in r.stdout + r.stderr, r.stdout + r.stderr
        assert name in r.stdout + r.stderr, r.stdout + r.stderr
        assert written == "", f"a partial set reached GITHUB_ENV:\n{written}"

    def test_a_crashed_tool_fails_the_step(self, step: str, tmp_path: Path):
        """`|| true` stays, because exit 3 is a finding; but a tool that died
        before its trailer now reddens the step instead of a null field."""
        r, written, _ = _run(step, tmp_path, seams="ERROR python3 is required\n")
        assert r.returncode != 0, r.stdout
        assert written == "", written
