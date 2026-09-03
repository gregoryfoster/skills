"""Per-file token calibration for the offline estimators (#145).

One bytes-per-token ratio for a whole repo describes exactly one file well: the
one it was derived from. `measure-context.sh` computes it as
`P_BYTES / P_TOKENS` — the **policy file alone**, not the whole context surface —
and then every offline estimator divides every other file by it.

Measured on this repo on 2026-08-13, across all 56 files of the skill library's
own surface, the per-file ratio runs from **2.041** (a scaffolding reference doc
that is almost entirely TOML and Python) to **3.029** (a review-dimensions doc
that is almost entirely prose and tables), against a global of 2.65. The
estimate that follows is wrong by **-23.0% to +14.3%**, and it is wrong in both
directions at once: 37 of the 56 files are under-reported and 19 over-reported.

Two things follow, and both contradict the shape #145 proposed.

- **The error has no fixed sign, and "code-heavy" does not predict it.** #145
  was filed from a repo whose code-block-heavy docs measured 2.485 and 2.549
  against a 2.32 global — *over*-reported. On this repo the code-heaviest files
  are the *densest* (2.04-2.32) and are *under*-reported by up to 23%, while the
  prose-and-table-heaviest are the sparsest (2.84-3.03) and over-reported by up
  to 14%. Both observations are correct about their own repo; neither
  generalises. What actually varies is how well the content compresses under
  BPE, and a fenced-code fraction does not measure that — which is why #145's
  option 2 (a character-class heuristic) is not implemented here: it would have
  to predict opposite signs in two repos of the same cohort.
- **Under-reporting is the direction that matters.** An over-flag wastes a
  reader's attention, which is what #145 measured. An under-flag lets a file sit
  over budget in silence, which is what the guard exists to prevent, and it is
  the majority case here.

## What is cached, and why it is counts rather than a ratio

`.skills/context-token-counts` holds `<bytes> <tokens> <path>` per file, written
by a genuinely exact run. #145 suggested caching a ratio; caching the two
integers it is computed from is strictly better:

- **It is exact at the measured size.** `tokens = T0 * B1 / B0` collapses to
  `T0` when the file has not changed, with no rounding step at all. A cached
  2-decimal ratio cannot do that: 2.656 stored as `2.65` costs 13 tokens on this
  repo's own `AGENTS.md` before any file has been edited.
- **It is auditable.** A reviewer can see what the ratio was derived from.
- **It carries the staleness signal for free** — see the drift band below.

## Why not a content hash (#145 option 3)

Option 3 caches the exact count against a hash of the content. Its accuracy is
unimprovable and its hot path is empty: the guard runs *because a file was just
edited*, so the hash essentially never matches at the moment an answer is
needed. It answers exactly when nobody is asking. The issue's escape hatch —
"re-estimate the delta since the hash" — is not implementable, because a hash
yields no content to diff against.

What survives from option 3 is its storage, which is what this module tests.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "curating-context"
    / "scripts"
)
LIB = SCRIPTS / "_context-lib.sh"
MEASURE = SCRIPTS / "measure-context.sh"
GUARD = SCRIPTS / "context-budget-guard.sh"

COUNTS = ".skills/context-token-counts"

# The artifact's own default, with no `.skills/context-token-ratio` present.
DEFAULT_RATIO_X100 = 270


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in (
        "CONTEXT_BUDGET",
        "CONTEXT_DOC_BUDGET",
        "CONTEXT_DOCS_DIR",
        "CTX_BPT_X100",
        "ANTHROPIC_API_KEY",
    ):
        env.pop(k, None)
    return env


def _call(func: str, *args: str) -> subprocess.CompletedProcess:
    """Source the library and call one function — the #132 test's shape."""
    return subprocess.run(
        [
            "bash",
            "-c",
            '. "$1"; shift; fn="$1"; shift; "$fn" "$@"',
            "lib",
            str(LIB),
            func,
            *args,
        ],
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=30,
    )


def _est(root: Path, rel: str, byte_count: int) -> tuple[int, str]:
    """`ctx_est_tokens_for` -> (tokens, source)."""
    r = _call("ctx_est_tokens_for", str(root), rel, str(byte_count))
    assert r.returncode == 0, r.stderr
    tokens, _, source = r.stdout.partition("\t")
    return int(tokens), source


def _write_counts(root: Path, body: str) -> None:
    (root / ".skills").mkdir(parents=True, exist_ok=True)
    (root / COUNTS).write_text(body)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env=_clean_env(),
    )


def _sized(path: Path, byte_count: int) -> None:
    """A file of exactly `byte_count` bytes. Content is irrelevant to the
    estimators, which only ever call `wc -c`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x" * (byte_count - 1) + "\n")
    assert path.stat().st_size == byte_count


class TestTheCachedEstimate:
    """`ctx_est_tokens_for <root> <rel> <bytes>` -> `<tokens>\\t<source>`."""

    def test_no_cache_is_not_a_complaint(self, tmp_path: Path):
        tokens, source = _est(tmp_path, "AGENTS.md", 27_000)
        assert source == "repo"
        assert tokens == 27_000 * 100 // DEFAULT_RATIO_X100
        r = _call("ctx_est_tokens_for", str(tmp_path), "AGENTS.md", "27000")
        assert r.stderr == "", "an absent calibration is the normal state"

    def test_an_unchanged_file_estimates_to_its_exact_count(self, tmp_path: Path):
        """The property a cached *ratio* cannot have.

        Storing 23484/9212 as `2.55` and dividing back gives 9209; storing the
        two integers gives 9212, because the division never happens.
        """
        _write_counts(tmp_path, "23484 9212 docs/MODULES-SYNC.md\n")
        assert _est(tmp_path, "docs/MODULES-SYNC.md", 23_484) == (9_212, "file")

    def test_a_grown_file_scales_from_its_own_anchor(self, tmp_path: Path):
        _write_counts(tmp_path, "20000 8000 docs/D.md\n")
        # 2.50 B/token measured here, against the 2.70 the repo would assume.
        assert _est(tmp_path, "docs/D.md", 22_000) == (8_800, "file")

    def test_a_shrunk_file_scales_too(self, tmp_path: Path):
        _write_counts(tmp_path, "20000 8000 docs/D.md\n")
        assert _est(tmp_path, "docs/D.md", 18_000) == (7_200, "file")

    def test_an_unlisted_path_falls_back_without_complaint(self, tmp_path: Path):
        _write_counts(tmp_path, "20000 8000 docs/D.md\n")
        tokens, source = _est(tmp_path, "docs/OTHER.md", 27_000)
        assert source == "repo"
        assert tokens == 27_000 * 100 // DEFAULT_RATIO_X100

    def test_a_path_is_matched_exactly_not_by_prefix(self, tmp_path: Path):
        """`docs/D.md` must not answer for `docs/D.md.bak` or `other/docs/D.md`."""
        _write_counts(tmp_path, "20000 8000 docs/D.md\n")
        assert _est(tmp_path, "docs/D.md.bak", 20_000)[1] == "repo"
        assert _est(tmp_path, "other/docs/D.md", 20_000)[1] == "repo"

    def test_a_path_containing_spaces_survives(self, tmp_path: Path):
        """The path is the rest of the line, not the third whitespace field."""
        _write_counts(tmp_path, "20000 8000 docs/my notes.md\n")
        assert _est(tmp_path, "docs/my notes.md", 20_000) == (8_000, "file")

    def test_crlf_line_endings_still_match(self, tmp_path: Path):
        """A CR is not IFS whitespace, so it survives the field split and would
        make every path in a CRLF checkout miss its lookup — indistinguishable
        from a repo that has never been measured."""
        _write_counts(tmp_path, "20000 8000 docs/D.md\r\n")
        assert _est(tmp_path, "docs/D.md", 20_000) == (8_000, "file")

    def test_comments_and_blank_lines_are_skipped(self, tmp_path: Path):
        _write_counts(
            tmp_path,
            "# bytes tokens path\n\n   \n20000 8000 docs/D.md\n",
        )
        assert _est(tmp_path, "docs/D.md", 20_000) == (8_000, "file")


class TestTheDriftBand:
    """A cached anchor only describes the file while the file still resembles it.

    Past the band the entry is not *wrong* so much as unevidenced, and the global
    ratio — which at least describes the repo — is the better guess. The band is
    +/-25%: with this repo's observed per-file extremes (2.04 and 3.03 against a
    2.65 global), an anchor 25% stale mis-estimates by at most -5.6%/+2.6% even
    if every added byte tokenizes at the opposite extreme, which is inside the
    global estimator's error at its *best*. At 100% drift the same worst case
    reaches -13%, which is global-tier, so the anchor has stopped earning its
    keep well before then.
    """

    @pytest.fixture
    def root(self, tmp_path: Path) -> Path:
        _write_counts(tmp_path, "20000 8000 docs/D.md\n")
        return tmp_path

    @pytest.mark.parametrize("byte_count", [15_000, 20_000, 25_000])
    def test_inside_the_band_the_anchor_is_used(self, root: Path, byte_count: int):
        assert _est(root, "docs/D.md", byte_count)[1] == "file"

    @pytest.mark.parametrize("byte_count", [14_999, 25_001, 60_000, 100])
    def test_outside_the_band_it_falls_back(self, root: Path, byte_count: int):
        tokens, source = _est(root, "docs/D.md", byte_count)
        assert source == "repo"
        assert tokens == byte_count * 100 // DEFAULT_RATIO_X100


class TestAMalformedRowProducesNoNumberRatherThanADifferentOne:
    """The #132 discipline, applied to the new artifact.

    A calibration the library cannot understand must degrade to the global ratio
    and say so. Silence is how a wrong divisor survives — and this one divides
    every byte count on the file it names.

    Falling back and saying so are different jobs, split after CR finding 26.
    Whether a row is usable is asked once per file priced and must stay quiet;
    whether the artifact is intact is asked once per run and must not. Folded
    together, one bad row emitted one identical warning per file looked up —
    four on a three-doc repo — which is the advisory fatigue #145 was about.
    """

    MALFORMED = [
        "20000 docs/D.md",  # two fields, no token count
        "20000 v2 docs/D.md",  # token count is not an integer
        "2e4 8000 docs/D.md",  # byte count is not an integer
        "20000 8000",  # no path at all
        "-20000 8000 docs/D.md",  # negative byte count
        "20000 0 docs/D.md",  # would divide by zero
        "0 8000 docs/D.md",  # would divide by zero the other way
    ]

    @pytest.mark.parametrize("row", MALFORMED)
    def test_it_falls_back(self, tmp_path: Path, row: str):
        _write_counts(tmp_path, row + "\n")
        r = _call("ctx_est_tokens_for", str(tmp_path), "docs/D.md", "20000")
        assert r.returncode == 0, r.stderr
        tokens, _, source = r.stdout.partition("\t")
        assert source == "repo", f"a malformed row was believed: {row!r}"
        assert int(tokens) == 20_000 * 100 // DEFAULT_RATIO_X100

    @pytest.mark.parametrize("row", MALFORMED)
    def test_the_validator_says_so(self, tmp_path: Path, row: str):
        _write_counts(tmp_path, row + "\n")
        r = _call("ctx_validate_counts", str(tmp_path))
        assert r.returncode == 0, r.stderr
        assert "WARN" in r.stderr and COUNTS in r.stderr, r.stderr

    def test_a_truncated_final_row_is_not_the_one_that_escapes(self, tmp_path: Path):
        """CR finding 27. The loop guard tested `p` — the very field a truncated
        row lacks — so a path-less row written without a trailing newline was
        dropped in silence. A truncated write is exactly how a file ends up
        without a trailing newline, so the check was bypassed in its motivating
        case."""
        _write_counts(tmp_path, "20000 8000")  # deliberately no "\n"
        r = _call("ctx_validate_counts", str(tmp_path))
        assert r.returncode == 0, r.stderr
        assert "names no path" in r.stderr, r.stderr

    def test_the_hot_path_stays_quiet_however_many_files_are_priced(
        self, tmp_path: Path
    ):
        """One bad row must not scale its warning by the size of the repo."""
        _write_counts(tmp_path, "GARBAGE\n15600 5873 AGENTS.md\n")
        for rel in ("docs/A.md", "docs/B.md", "docs/C.md"):
            r = _call("ctx_est_tokens_for", str(tmp_path), rel, "5120")
            assert r.returncode == 0, r.stderr
            assert r.stderr == "", f"{rel} warned from the hot path: {r.stderr!r}"

    def test_a_valid_row_after_a_broken_one_is_still_found(self, tmp_path: Path):
        """Skipping quietly must not mean skipping the rest of the file."""
        _write_counts(tmp_path, "GARBAGE\n15600 5873 AGENTS.md\n")
        tokens, source = _est(tmp_path, "AGENTS.md", 15_600)
        assert source == "file"
        assert tokens == 5_873

    @pytest.mark.parametrize(
        "row,ratio",
        [
            ("20000 20000 docs/D.md", "1.00"),
            ("70000 10000 docs/D.md", "7.00"),
        ],
    )
    def test_an_implausible_ratio_is_refused(
        self, tmp_path: Path, row: str, ratio: str
    ):
        """The same 1.50-6.00 band the global ratio is held to.

        A row outside it describes a degenerate file, not a calibration, and
        freezing it would skew every later estimate of that file.
        """
        _write_counts(tmp_path, row + "\n")
        r = _call("ctx_est_tokens_for", str(tmp_path), "docs/D.md", "20000")
        _, _, source = r.stdout.partition("\t")
        assert source == "repo", f"an implausible {ratio} B/token row was believed"
        assert "WARN" in r.stderr, r.stderr

    def test_one_bad_row_does_not_poison_the_others(self, tmp_path: Path):
        _write_counts(tmp_path, "20000 v2 docs/BAD.md\n20000 8000 docs/D.md\n")
        assert _est(tmp_path, "docs/D.md", 20_000) == (8_000, "file")


def _bin_with_real_tools(bin_dir: Path) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    for tool in (
        "git",
        "python3",
        "bash",
        "awk",
        "sed",
        "grep",
        "wc",
        "sort",
        "find",
        "head",
        "tr",
        "dirname",
        "basename",
        "mktemp",
        "date",
        "cat",
        "rm",
        "mkdir",
        "printf",
        "ls",
        "cut",
        "tail",
        "uniq",
        "mv",
        "sh",
    ):
        real = shutil.which(tool)
        if real and not (bin_dir / tool).exists():
            (bin_dir / tool).symlink_to(real)
    return bin_dir


# A `python3` that answers count_tokens without a network or a key. It ignores
# the generated count.py and prices the file itself, so a test can dictate the
# "exact" ratio per file: a path containing `dense` counts at 2.00 bytes/token,
# everything else at 3.00. Both sit inside the plausibility band and neither is
# the 2.70 default, so a number derived from the wrong one is visible.
FAKE_COUNTER = """#!/bin/sh
f="$2"
b=$(wc -c <"$f" | tr -d ' ')
case "$f" in
  *dense*) echo $(( b * 100 / 200 )) ;;
  *) echo $(( b * 100 / 300 )) ;;
esac
"""


@pytest.fixture
def exact_env(tmp_path: Path) -> dict:
    bin_dir = _bin_with_real_tools(tmp_path / "bin")
    (bin_dir / "python3").unlink()
    (bin_dir / "python3").write_text(FAKE_COUNTER)
    (bin_dir / "python3").chmod(0o755)
    env = _clean_env()
    env["PATH"] = str(bin_dir)
    env["ANTHROPIC_API_KEY"] = "sk-ant-test-offline"
    return env


def _measured_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _sized(repo / "AGENTS.md", 9_000)
    _sized(repo / "docs" / "dense-notes.md", 6_000)
    _sized(repo / "docs" / "prose.md", 3_000)
    return repo


def _measure(repo: Path, env: dict, *args: str) -> dict:
    result = subprocess.run(
        ["bash", str(MEASURE), *args],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _rows(repo: Path) -> dict[str, tuple[int, int]]:
    out = {}
    for line in (repo / COUNTS).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        b, t, path = line.split(maxsplit=2)
        out[path] = (int(b), int(t))
    return out


class TestTheExactRunWritesTheCalibration:
    """The artifact is a by-product of a real measurement, never of an estimate."""

    def test_every_measured_file_gets_a_row(self, tmp_path: Path, exact_env: dict):
        repo = _measured_repo(tmp_path)
        _measure(repo, exact_env, "--exact")
        rows = _rows(repo)
        assert set(rows) == {"AGENTS.md", "docs/dense-notes.md", "docs/prose.md"}
        assert rows["AGENTS.md"] == (9_000, 3_000)
        assert rows["docs/dense-notes.md"] == (6_000, 3_000)
        assert rows["docs/prose.md"] == (3_000, 1_000)

    def test_the_rows_are_what_the_estimator_then_reads(
        self, tmp_path: Path, exact_env: dict
    ):
        """End to end: measure exactly once, then estimate offline and land on
        the same numbers rather than on the global ratio's."""
        repo = _measured_repo(tmp_path)
        _measure(repo, exact_env, "--exact")
        assert _est(repo, "docs/dense-notes.md", 6_000) == (3_000, "file")
        assert _est(repo, "docs/prose.md", 3_000) == (1_000, "file")

    def test_an_estimate_only_run_writes_nothing(self, tmp_path: Path, exact_env: dict):
        """The self-confirmation guard the global ratio already has: a
        calibration derived from the divisor it was computed with re-records the
        default and freezes whatever error it carries."""
        repo = _measured_repo(tmp_path)
        _measure(repo, _clean_env())
        assert not (repo / COUNTS).exists()

    def test_no_write_writes_nothing(self, tmp_path: Path, exact_env: dict):
        repo = _measured_repo(tmp_path)
        _measure(repo, exact_env, "--exact", "--no-write")
        assert not (repo / COUNTS).exists()

    def test_a_credential_that_could_not_count_writes_nothing(self, tmp_path: Path):
        bin_dir = _bin_with_real_tools(tmp_path / "bin")
        (bin_dir / "python3").unlink()
        (bin_dir / "python3").write_text("#!/bin/sh\necho boom >&2\nexit 1\n")
        (bin_dir / "python3").chmod(0o755)
        env = _clean_env()
        env["PATH"] = str(bin_dir)
        env["ANTHROPIC_API_KEY"] = "sk-ant-test-offline"
        repo = _measured_repo(tmp_path)
        _measure(repo, env, "--exact")
        assert not (repo / COUNTS).exists()

    def test_a_scoped_run_merges_rather_than_clobbers(
        self, tmp_path: Path, exact_env: dict
    ):
        """`--file`/`--docs-dir` measure one corner of a repo. Rewriting the
        whole artifact from that corner would silently delete the calibration
        for every file the run never looked at — and the caller with the
        narrowest scope would win.

        Since #263 a scoped run writes only on `--calibrate`; the merge is what
        that opt-in then does. `test_scoped_calibration.py` owns the refusal.
        """
        repo = _measured_repo(tmp_path)
        _measure(repo, exact_env, "--exact")
        _sized(repo / "other" / "SOLO.md", 4_000)
        _measure(
            repo,
            exact_env,
            "--exact",
            "--calibrate",
            "--file",
            "other/SOLO.md",
            "--docs-dir",
            "other",
        )
        rows = _rows(repo)
        assert "other/SOLO.md" in rows
        assert rows["AGENTS.md"] == (9_000, 3_000), (
            "a scoped run discarded rows outside its own scope"
        )

    def test_a_re_measurement_replaces_the_row_rather_than_appending(
        self, tmp_path: Path, exact_env: dict
    ):
        repo = _measured_repo(tmp_path)
        _measure(repo, exact_env, "--exact")
        _sized(repo / "docs" / "prose.md", 3_600)
        _measure(repo, exact_env, "--exact")
        text = (repo / COUNTS).read_text()
        assert text.count("docs/prose.md") == 1, text
        assert _rows(repo)["docs/prose.md"] == (3_600, 1_200)

    def test_an_implausible_row_is_never_persisted(
        self, tmp_path: Path, exact_env: dict
    ):
        """A file that measures outside 1.50-6.00 B/token is degenerate, and the
        writer refuses it for the same reason the global ratio's writer does —
        writing nonsense and relying on the reader to reject it is worse than
        not writing it.
        """
        repo = _measured_repo(tmp_path)
        # 9.00 bytes/token: a wall of repeated single characters.
        (repo / "docs" / "degenerate.md").write_text("a" * 9_000)
        bin_dir = Path(exact_env["PATH"])
        (bin_dir / "python3").write_text(
            '#!/bin/sh\nf="$2"\nb=$(wc -c <"$f" | tr -d \' \')\n'
            'case "$f" in *degenerate*) echo $(( b / 9 )) ;;'
            " *) echo $(( b * 100 / 300 )) ;; esac\n"
        )
        _measure(repo, exact_env, "--exact")
        assert "docs/degenerate.md" not in _rows(repo)
        assert "AGENTS.md" in _rows(repo)


class TestTheMeasurementSaysWhereItsNumbersCameFrom:
    """`tokens_source` on every row: "exact", "file" or "repo".

    #145's cost was not the estimate being wrong — estimates are wrong — it was
    that nothing the tool emitted said which of two figures, up to 23% apart,
    had produced a number, so a wrong one was copied into a plan document, an
    issue comment and several status reports before anyone re-derived it. An
    estimate that cannot say where it came from is one readers either over-trust
    or learn to ignore, and both are how the advisory decays.
    """

    def test_an_exact_run_says_exact(self, tmp_path: Path, exact_env: dict):
        repo = _measured_repo(tmp_path)
        data = _measure(repo, exact_env, "--exact")
        assert data["policy"]["tokens_source"] == "exact"
        assert {d["tokens_source"] for d in data["docs"]} == {"exact"}

    def test_an_uncalibrated_estimate_says_repo(self, tmp_path: Path):
        repo = _measured_repo(tmp_path)
        data = _measure(repo, _clean_env())
        assert data["policy"]["tokens_source"] == "repo"
        assert {d["tokens_source"] for d in data["docs"]} == {"repo"}

    def test_a_calibrated_estimate_says_file_per_row(
        self, tmp_path: Path, exact_env: dict
    ):
        """Per row, not per run. One file having an anchor says nothing about
        the next, and a run-wide flag would force a consumer to discard every
        calibrated row because one file had never been counted."""
        repo = _measured_repo(tmp_path)
        _measure(repo, exact_env, "--exact")
        _sized(repo / "docs" / "fresh.md", 2_000)
        data = _measure(repo, _clean_env())
        by_path = {d["path"]: d for d in data["docs"]}
        assert data["policy"]["tokens_source"] == "file"
        assert by_path["docs/dense-notes.md"]["tokens_source"] == "file"
        assert by_path["docs/fresh.md"]["tokens_source"] == "repo"

    def test_the_calibrated_estimate_is_the_measured_count(
        self, tmp_path: Path, exact_env: dict
    ):
        """The estimate-only run that follows an exact one reproduces it, rather
        than re-deriving it through a two-decimal ratio."""
        repo = _measured_repo(tmp_path)
        exact = _measure(repo, exact_env, "--exact")
        estimate = _measure(repo, _clean_env())
        assert estimate["policy"]["tokens"] == exact["policy"]["tokens"]
        assert {d["path"]: d["tokens"] for d in estimate["docs"]} == {
            d["path"]: d["tokens"] for d in exact["docs"]
        }


def _run_guard(repo: Path, file_path: Path) -> str | None:
    payload = json.dumps(
        {"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}
    )
    result = subprocess.run(
        ["bash", str(GUARD)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)["systemMessage"]


class TestTheGuardActsOnTheCalibration:
    """#145's actual complaint, and its mirror.

    The guard is the surface where a wrong estimate becomes a wrong statement in
    someone's transcript. Both directions are tested because this repo's own
    measurement has both, and a fix that assumed the issue's sign would have
    made the majority case worse.
    """

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _sized(repo / "AGENTS.md", 2_000)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        return repo

    def test_the_false_positive_goes_away(self, repo: Path):
        """#145's measured case: a doc the global ratio reports as over budget
        and `count_tokens` reports as under it. 28,080 bytes estimates to 10,400
        at 2.70 and measures 9,700 — 2.895 B/token, the shape of a doc that
        compresses well.
        """
        doc = repo / "docs" / "OVER-REPORTED.md"
        _sized(doc, 28_080)
        assert _run_guard(repo, doc) is not None, (
            "sanity: uncalibrated, the global ratio flags this file"
        )
        _write_counts(repo, "28080 9700 docs/OVER-REPORTED.md\n")
        assert _run_guard(repo, doc) is None, (
            "the guard still reports a file that is under budget as over it"
        )

    def test_the_false_negative_is_caught(self, repo: Path):
        """The direction #145 did not see, and the majority case on this repo:
        25,920 bytes estimates to 9,600 at 2.70 and measures 10,400 — 2.492
        B/token, the shape of a doc dense with paths and code.

        This is the failure the guard exists to prevent, and an uncalibrated
        estimator is silent through it.
        """
        doc = repo / "docs" / "UNDER-REPORTED.md"
        _sized(doc, 25_920)
        assert _run_guard(repo, doc) is None, (
            "sanity: uncalibrated, the global ratio waves this file through"
        )
        _write_counts(repo, "25920 10400 docs/UNDER-REPORTED.md\n")
        msg = _run_guard(repo, doc)
        assert msg is not None, "a file 400 tokens over budget went unreported"
        assert "10,400" in msg or "10400" in msg, msg

    def test_the_policy_file_is_calibrated_too(self, repo: Path):
        """`AGENTS.md` is the one file the global ratio describes well, because
        it is the file the ratio is derived from — but only until it is edited.
        """
        _sized(repo / "AGENTS.md", 16_000)
        _git(repo, "commit", "-qam", "grow")
        _sized(repo / "AGENTS.md", 17_000)
        _write_counts(repo, "17000 6400 AGENTS.md\n")
        msg = _run_guard(repo, repo / "AGENTS.md")
        assert msg is not None
        assert "6400 tokens" in msg, msg
        # 6400 * 16000 / 17000 = 6023, so the growth is +377 — not the +2,104
        # that pricing `prev` at the repo's 2.70 would have reported.
        assert "+377 since HEAD" in msg, msg

    def test_a_delta_is_never_taken_across_two_methods(self, repo: Path):
        """The committed size can sit outside the anchor's drift band while the
        working copy sits inside it. Differencing a calibrated `now` against a
        global `prev` reports the gap between two methods as growth someone
        wrote, in the one sentence a human reads.

        Both sides drop to the repo ratio instead — a slightly worse pair of
        numbers, but a difference that means something.
        """
        _sized(repo / "AGENTS.md", 17_000)  # committed size is 2,000
        _write_counts(repo, "17000 6400 AGENTS.md\n")
        msg = _run_guard(repo, repo / "AGENTS.md")
        assert msg is not None
        assert "6296 tokens" in msg, (
            f"one side was priced by the anchor and the other by the repo ratio: {msg}"
        )
        log = (repo / ".git" / "context-budget.log").read_text()
        assert "est=repo" in log, log

    def test_the_previous_size_uses_the_same_anchor(self, repo: Path):
        """`+N since HEAD` compares two sizes of one file, so both sides must be
        priced by that file's own ratio. Mixing a calibrated `now` with a global
        `prev` fabricates a delta out of the calibration itself.
        """
        doc = repo / "docs" / "D.md"
        _sized(doc, 26_000)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "doc")
        _sized(doc, 27_000)
        _write_counts(repo, "26000 10400 docs/D.md\n")
        msg = _run_guard(repo, doc)
        assert msg is not None
        # 27000 * 10400 / 26000 = 10800; prev is the committed 26,000 -> 10,400.
        assert "+400 since HEAD" in msg, msg
