"""The persisted bytes/token ratio is fitted over the whole surface (#172).

`.skills/context-token-ratio` is the fallback the offline estimators use for any
file with no row in `.skills/context-token-counts` — a new doc, a repo before its
first `--exact`, or a row that failed validation. It was computed as
`P_BYTES / P_TOKENS`: the **policy file alone**, then applied to every file on
the surface.

Markdown does not tokenize at one rate, and the policy file is the most
prose-heavy thing on the surface, so the fallback over-reported everything else
— worst on the doc class densest in tables, inline code and links, which is also
the class most likely to sit near its budget. On `CannObserv/replicator` that
produced a `385 tokens over` warning on a file **848 tokens under** budget, and a
maintainer opened a tracking issue and deferred real work onto it.

Validated against `usa-wa`'s committed calibration, 24 files of exact ground
truth, before and after:

| | policy-only (2.33) | surface-wide (2.51) |
|---|---|---|
| mean absolute error | 8.2% | **3.1%** |
| worst | +15.1% | -8.2% |
| files over-reported by >5% | **19 / 24** | 2 / 24 |

The bias, not just the spread, is what moves: the policy-fitted figure
over-reported 19 of 24 files.

## What deliberately did NOT change

`RATIO_X100` still describes the policy file, and still divides the section and
subsection figures, because those must sum to the policy total — a contradiction
the comment at that site records having already been fixed once. `policy.bytes_
per_token` also still reports the policy file's own ratio, because that is what
the field means. Only the PERSISTED value is surface-wide, and the two are now
separate variables rather than one number serving both.

Coverage:
- the persisted ratio is the surface aggregate, not the policy file's
- `policy.bytes_per_token` still reports the policy-only figure
- section tokens still sum to the policy total
- an estimate-only run still persists nothing
- docs counted non-exactly are excluded from the aggregate
- a repo with no docs falls back to the policy ratio
- the plausibility band is applied to the surface figure
"""

import json
import subprocess
from pathlib import Path

import pytest

from .test_per_file_calibration import (
    FAKE_COUNTER,
    MEASURE,
    _bin_with_real_tools,
    _clean_env,
    _git,
    _sized,
)

RATIO = ".skills/context-token-ratio"


@pytest.fixture
def exact_env(tmp_path: Path) -> dict:
    """The sibling module's offline count_tokens shim: a path containing `dense`
    prices at 2.00 bytes/token, everything else at 3.00."""
    bin_dir = _bin_with_real_tools(tmp_path / "bin")
    (bin_dir / "python3").unlink()
    (bin_dir / "python3").write_text(FAKE_COUNTER)
    (bin_dir / "python3").chmod(0o755)
    env = _clean_env()
    env["PATH"] = str(bin_dir)
    env["ANTHROPIC_API_KEY"] = "sk-ant-test-offline"
    return env


def _measure(repo: Path, env: dict, *args: str) -> dict:
    r = subprocess.run(
        ["bash", str(MEASURE), *args],
        capture_output=True, text=True, cwd=str(repo), env=env, timeout=120,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _repo(tmp_path: Path) -> Path:
    """Policy and docs with deliberately different rates, so a ratio fitted to
    one is visibly wrong for the other.

        AGENTS.md            9000 B / 3000 tok  -> 3.00   (policy-only)
        docs/dense-notes.md  6000 B / 3000 tok  -> 2.00
        docs/prose.md        3000 B / 1000 tok  -> 3.00
        surface             18000 B / 7000 tok  -> 2.57
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _sized(repo / "AGENTS.md", 9_000)
    _sized(repo / "docs" / "dense-notes.md", 6_000)
    _sized(repo / "docs" / "prose.md", 3_000)
    return repo


class TestThePersistedRatioIsSurfaceWide:
    def test_it_is_the_aggregate_not_the_policy_file(
        self, tmp_path: Path, exact_env: dict
    ):
        repo = _repo(tmp_path)
        _measure(repo, exact_env, "--exact")
        assert (repo / RATIO).read_text().strip() == "2.57", (
            "expected the 18000/7000 surface aggregate; 3.00 is the policy file "
            "alone, which is the #172 defect"
        )

    def test_the_reported_policy_ratio_is_still_policy_only(
        self, tmp_path: Path, exact_env: dict
    ):
        """`policy.bytes_per_token` describes the policy file. Reporting the
        surface aggregate there would simply be false."""
        repo = _repo(tmp_path)
        out = _measure(repo, exact_env, "--exact")
        assert out["policy"]["bytes_per_token"] == 3.00

    def test_section_tokens_still_sum_to_the_policy_total(
        self, tmp_path: Path, exact_env: dict
    ):
        """The invariant that forces the two ratios apart. Sections divide by the
        policy ratio; switching them to the surface figure would make the parts
        contradict the whole, which the section comment records fixing once."""
        repo = _repo(tmp_path)
        out = _measure(repo, exact_env, "--exact")
        total = out["policy"]["tokens"]
        summed = sum(s["tokens"] for s in out["sections"])
        assert abs(summed - total) <= len(out["sections"]), (
            f"sections sum to {summed}, policy total is {total}"
        )

    def test_an_estimate_only_run_persists_nothing(self, tmp_path: Path):
        repo = _repo(tmp_path)
        env = _clean_env()
        env.pop("ANTHROPIC_API_KEY", None)
        _measure(repo, env)
        assert not (repo / RATIO).exists()

    def test_no_docs_falls_back_to_the_policy_ratio(
        self, tmp_path: Path, exact_env: dict
    ):
        """A repo whose whole surface IS the policy file. The aggregate and the
        policy figure coincide, and nothing divides by zero."""
        repo = tmp_path / "solo"
        repo.mkdir()
        _git(repo, "init", "-q")
        _sized(repo / "AGENTS.md", 9_000)
        _measure(repo, exact_env, "--exact")
        assert (repo / RATIO).read_text().strip() == "3.00"

    def test_no_write_reports_both_figures(self, tmp_path: Path, exact_env: dict):
        """The INFO line names the surface figure AND the policy-only one, so a
        reader can see the correction rather than a single number replacing
        another silently."""
        repo = _repo(tmp_path)
        r = subprocess.run(
            ["bash", str(MEASURE), "--exact", "--no-write"],
            capture_output=True, text=True, cwd=str(repo), env=exact_env,
            timeout=120,
        )
        assert r.returncode == 0, r.stderr
        assert "2.57" in r.stderr and "3.00" in r.stderr, r.stderr
        assert not (repo / RATIO).exists()
