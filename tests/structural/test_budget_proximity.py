"""The proximity tier: a budget is a gradient, not a cliff (#273).

Before this, every budget in `curating-context` fired on one condition —
`tokens > budget` — so a file at 9,999 tokens against a 10,000 budget was
reported exactly as a file at 3,000 was: not at all. The first signal a repo
ever got was a file already over, at which point the fix gets made under
whatever deadline the crossing edit was made for.

That is not hypothetical. The consumer repo that filed #273 was found with
`AGENTS.md` at 5,997/6,000 and `docs/CONVENTIONS.md` at 9,999/10,000 — 3 and 1
tokens of headroom, silent on every surface.

The same issue found a second, worse gap: the weekly cadence's drift report read
`["policy"]` and nothing else, while `measure-context.sh` had already computed
`over_budget` for every `docs[]` row and the job threw it away. A reference doc
could go **over** its budget and the scheduled run said nothing. Nothing else
covers that path — the write guard sees only the writes its `PostToolUse`
matcher intercepts, so a `sed -i` or a heredoc append escapes it entirely.

Four things are pinned here, and the fourth is the one that decays quietly:

- the knob resolves and range-checks like every other knob in this library;
- `near_budget` and `over_budget` are **disjoint**, so a breach is never also
  reported as approaching one;
- each surface renders the two tiers **differently** — a proximity signal read
  as a breach costs the breach warning its meaning, which is worse than not
  having the tier;
- and all three surfaces draw the band in the **same place**, which is the same
  rule #126 established for the budgets themselves.

No API calls: every path here uses the offline estimate.
"""

import json
import os
import re
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
DELTA = SCRIPTS / "context-delta.sh"
INSTALL_GUARD = SCRIPTS / "install-guard.sh"
INSTALL_CADENCE = SCRIPTS / "install-cadence.sh"

KNOB = ".skills/context-proximity-pct"

# The library's own default divisor, with no .skills/context-token-ratio in the
# tree: 2.70 bytes per token. Every sized file below is built through it.
BPT_X100 = 270


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in (
        "CONTEXT_BUDGET",
        "CONTEXT_DOC_BUDGET",
        "CONTEXT_DOCS_DIR",
        "CONTEXT_PROXIMITY_PCT",
        "CTX_BPT_X100",
        "ANTHROPIC_API_KEY",
    ):
        env.pop(k, None)
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env=_clean_env(),
    )


def _call(func: str, *args: str) -> subprocess.CompletedProcess:
    """Source the library and call one function."""
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


def _tokens(path: Path, tokens: int) -> None:
    """Write a file the offline estimator prices at exactly `tokens`.

    Content is irrelevant to the estimator, which only ever calls `wc -c`, so
    the tests can name the number they mean instead of counting lines toward it
    and hoping. Every assertion below is about a boundary — at the threshold,
    one token under it, exactly at budget — and a fixture that cannot hit a
    boundary cannot test one.
    """
    # Ceiling, not floor: the estimator itself floors, so the smallest byte
    # count that prices AT `tokens` is the one just past the boundary. Flooring
    # here lands a token low on any value the division does not divide evenly,
    # which is most of the boundaries these tests are made of.
    byte_count = -(-tokens * BPT_X100 // 100)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x" * (byte_count - 1) + "\n")
    assert path.stat().st_size == byte_count
    assert byte_count * 100 // BPT_X100 == tokens, "fixture missed its own mark"


def _repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    return repo


def _measure(repo: Path, *args: str) -> dict:
    r = subprocess.run(
        ["bash", str(MEASURE), "--no-write", *args],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _guard(repo: Path, file_path: Path) -> str | None:
    payload = json.dumps(
        {"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}
    )
    r = subprocess.run(
        ["bash", str(GUARD)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=30,
    )
    # The hook's contract is exit 0 on every path, tier or no tier.
    assert r.returncode == 0, f"guard exited {r.returncode}: {r.stderr}"
    out = r.stdout.strip()
    return json.loads(out)["systemMessage"] if out else None


def _guard_log(repo: Path) -> str:
    gitdir = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"],
        capture_output=True,
        text=True,
        env=_clean_env(),
    ).stdout.strip()
    log = Path(gitdir) / "context-budget.log"
    return log.read_text() if log.exists() else ""


def _delta_rows(repo: Path, *args: str) -> dict:
    """The review delta's table as {path: status}."""
    r = subprocess.run(
        ["bash", str(DELTA), *args],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    rows = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and (parts[0].endswith(".md")):
            rows[parts[0]] = " ".join(parts[4:])
    return rows


def _drift_step(tmp_path: Path) -> str:
    """The rendered `Report drift` step, as the workflow will run it."""
    yaml = pytest.importorskip("yaml")
    repo = _repo(tmp_path, "render")
    doc = yaml.safe_load(
        subprocess.run(
            ["bash", str(INSTALL_CADENCE), "--print"],
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=_clean_env(),
            timeout=30,
        ).stdout
    )
    return next(
        s["run"]
        for s in doc["jobs"]["measure"]["steps"]
        if s.get("name") == "Report drift"
    )


def _run_drift(tmp_path: Path, ctx: dict) -> str:
    step = _drift_step(tmp_path)
    path = tmp_path / "ctx.json"
    path.write_text(json.dumps(ctx))
    r = subprocess.run(
        ["bash", "-e", "-c", step.replace("/tmp/ctx.json", str(path))],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={**_clean_env(), "SEAMS": "0", "COUNTS": "0"},
        timeout=30,
    )
    # `bash -e`: a raised exception in the python would take the seam and count
    # warnings below it down with the step, so the exit code is part of the
    # contract, not incidental.
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


class TestTheKnobResolvesLikeEveryOtherKnob:
    """Override, then env, then file, then default — the same three-step lookup
    the budgets, the docs-dir and the ratio all use. Written out because a knob
    that resolves differently from its neighbours is one a repo configures
    correctly and gets ignored."""

    def test_the_default_is_ninety(self, tmp_path: Path):
        r = _call("ctx_proximity_pct", str(tmp_path))
        assert r.returncode == 0, r.stderr
        assert r.stdout == "90"

    def test_the_file_is_read(self, tmp_path: Path):
        (tmp_path / ".skills").mkdir()
        (tmp_path / KNOB).write_text("75\n")
        assert _call("ctx_proximity_pct", str(tmp_path)).stdout == "75"

    def test_the_env_var_wins_over_the_file(self, tmp_path: Path):
        (tmp_path / ".skills").mkdir()
        (tmp_path / KNOB).write_text("75\n")
        r = subprocess.run(
            [
                "bash",
                "-c",
                '. "$1"; ctx_proximity_pct "$2"',
                "lib",
                str(LIB),
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            env={**_clean_env(), "CONTEXT_PROXIMITY_PCT": "60"},
            timeout=30,
        )
        assert r.stdout == "60", r.stderr

    def test_an_override_wins_over_both(self, tmp_path: Path):
        (tmp_path / ".skills").mkdir()
        (tmp_path / KNOB).write_text("75\n")
        assert _call("ctx_proximity_pct", str(tmp_path), "55").stdout == "55"

    @pytest.mark.parametrize("value", ["0", "101", "1000"])
    def test_out_of_range_degrades_loudly(self, tmp_path: Path, value: str):
        """Both ends fail silently if accepted, and in opposite directions:
        above 100 no token count can be both at the threshold and under the
        budget, so the tier turns itself off; at 0 every file is in the band and
        the tier is noise. Either is a repo that looks configured and is not."""
        (tmp_path / ".skills").mkdir()
        (tmp_path / KNOB).write_text(f"{value}\n")
        r = _call("ctx_proximity_pct", str(tmp_path))
        assert r.stdout == "90", r.stdout
        assert value in r.stderr and "1-100" in r.stderr, r.stderr

    def test_a_non_integer_degrades(self, tmp_path: Path):
        """A knob FILE a repo cannot parse falls back with a warning rather than
        failing the measurement — #132's rule, inherited from
        ctx_read_num_knob rather than re-implemented here."""
        (tmp_path / ".skills").mkdir()
        (tmp_path / KNOB).write_text("ninety\n")
        r = _call("ctx_proximity_pct", str(tmp_path))
        assert r.stdout == "90"
        assert "not a bare integer" in r.stderr, r.stderr


class TestTheTwoTiersAreDisjoint:
    """`ctx_near_budget` is the single predicate every surface asks, so its
    boundaries are the boundaries. Under, near, over: exhaustive, and no token
    count is ever in two of them."""

    def near(self, tokens: int, budget: int = 6000, pct: int = 90) -> bool:
        return (
            _call("ctx_near_budget", str(tokens), str(budget), str(pct)).returncode == 0
        )

    def test_at_the_threshold_is_near(self):
        assert self.near(5400)

    def test_one_token_below_the_threshold_is_not(self):
        assert not self.near(5399)

    def test_exactly_at_budget_is_near_not_over(self):
        """`over_budget` is `tokens > budget`, so the file exactly at its budget
        is not over — and it must therefore be caught by the tier below, or it
        falls between the two."""
        assert self.near(6000)

    def test_past_the_budget_is_never_near(self):
        """The disjointness that lets a consumer branch on the two flags in
        either order and get the same answer."""
        assert not self.near(6001)
        assert not self.near(99_000)

    def test_the_threshold_floors_outward(self):
        """90% of 6001 is 5400.9; the band starts at 5400. A token early is an
        advisory, a token late is the silence the tier exists to end."""
        assert self.near(5400, budget=6001)

    def test_the_percentage_moves_the_edge(self):
        assert not self.near(5000)
        assert self.near(5000, pct=80)

    def test_a_zero_budget_is_never_near(self):
        """Nothing to be near. Guarded because the threshold arithmetic would
        otherwise make every file in a misconfigured repo 'approaching'."""
        assert not self.near(0, budget=0)
        assert not self.near(100, budget=0)


class TestMeasureReportsBothTiersOnEveryRow:
    def test_the_filed_case_is_reported(self, tmp_path: Path):
        """#273's own numbers: a policy file 3 tokens under budget and a
        reference doc 1 token under. Both were silent everywhere."""
        repo = _repo(tmp_path)
        _tokens(repo / "AGENTS.md", 5997)
        _tokens(repo / "docs" / "CONVENTIONS.md", 9999)
        d = _measure(repo)
        assert d["policy"]["over_budget"] is False
        assert d["policy"]["near_budget"] is True
        doc = d["docs"][0]
        assert doc["path"] == "docs/CONVENTIONS.md"
        assert doc["over_budget"] is False
        assert doc["near_budget"] is True

    def test_a_comfortable_surface_says_nothing(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _tokens(repo / "AGENTS.md", 3000)
        _tokens(repo / "docs" / "SMALL.md", 2000)
        d = _measure(repo)
        assert d["policy"]["near_budget"] is False
        assert d["docs"][0]["near_budget"] is False

    def test_an_over_budget_row_is_not_also_near(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _tokens(repo / "AGENTS.md", 20_000)
        d = _measure(repo)
        assert d["policy"]["over_budget"] is True
        assert d["policy"]["near_budget"] is False

    def test_every_doc_row_carries_its_own_budget(self, tmp_path: Path):
        """On the row rather than once at the top level, so a consumer warning
        about one doc has the number it must quote without knowing which of two
        budgets applies to it — the shape `policy` already had."""
        repo = _repo(tmp_path)
        _tokens(repo / "AGENTS.md", 1000)
        _tokens(repo / "docs" / "A.md", 2000)
        d = _measure(repo, "--doc-budget", "8000")
        assert d["docs"][0]["budget"] == 8000

    def test_the_knob_moves_the_band(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _tokens(repo / "AGENTS.md", 5000)
        assert _measure(repo)["policy"]["near_budget"] is False
        (repo / ".skills").mkdir()
        (repo / KNOB).write_text("80\n")
        assert _measure(repo)["policy"]["near_budget"] is True

    @pytest.mark.parametrize("value", ["0", "101", "9x"])
    def test_a_malformed_flag_is_refused_outright(self, tmp_path: Path, value: str):
        """The other half of #126's rule: a knob FILE degrades, because a repo
        should not fail to measure over an annotation, but a FLAG is a typo and
        a run that silently measured against a tier nobody asked for would
        record that."""
        repo = _repo(tmp_path)
        _tokens(repo / "AGENTS.md", 1000)
        r = subprocess.run(
            ["bash", str(MEASURE), "--no-write", "--proximity-pct", value],
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=_clean_env(),
            timeout=60,
        )
        assert r.returncode == 1, r.stdout
        assert "--proximity-pct" in r.stderr, r.stderr


class TestTheGuardSpeaksInTwoTiers:
    """The guard is the surface that fires at the moment of the edit, which is
    the only moment the fix is cheap. Growth is required in BOTH tiers — that is
    what lets a tier exist below the budget without turning the hook into
    something everybody switches off."""

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        repo = _repo(tmp_path)
        _tokens(repo / "AGENTS.md", 3000)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        return repo

    def test_growth_into_the_band_speaks(self, repo: Path):
        _tokens(repo / "AGENTS.md", 5500)
        msg = _guard(repo, repo / "AGENTS.md")
        assert msg is not None, "the guard was silent 500 tokens from the budget"
        assert "approaching" in msg, msg

    def test_the_proximity_message_never_says_over(self, repo: Path):
        """The distinction is the whole point. A proximity signal read as a
        breach costs the breach warning its meaning."""
        _tokens(repo / "AGENTS.md", 5500)
        msg = _guard(repo, repo / "AGENTS.md")
        assert "over" not in msg.lower(), msg
        assert "500 left" in msg, msg

    def test_a_breach_still_reads_as_a_breach(self, repo: Path):
        _tokens(repo / "AGENTS.md", 7000)
        msg = _guard(repo, repo / "AGENTS.md")
        assert "1000 over the 6000 budget" in msg, msg
        assert "approaching" not in msg, msg

    def test_growth_below_the_band_stays_silent(self, repo: Path):
        _tokens(repo / "AGENTS.md", 5399)
        assert _guard(repo, repo / "AGENTS.md") is None

    def test_a_reduction_inside_the_band_is_never_flagged(self, repo: Path):
        """Curating is never nagged, in any tier. A file coming DOWN through the
        band is someone doing the work the advisory asks for."""
        _tokens(repo / "AGENTS.md", 5900)
        _git(repo, "commit", "-qam", "grow")
        _tokens(repo / "AGENTS.md", 5500)
        assert _guard(repo, repo / "AGENTS.md") is None

    def test_a_doc_approaching_its_own_budget_speaks(self, repo: Path):
        _tokens(repo / "docs" / "A.md", 2000)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "doc")
        _tokens(repo / "docs" / "A.md", 9500)
        msg = _guard(repo, repo / "docs" / "A.md")
        assert msg is not None and "approaching" in msg, msg
        assert "of 10000" in msg, msg

    def test_the_knob_moves_the_guards_band_too(self, repo: Path):
        (repo / ".skills").mkdir()
        (repo / KNOB).write_text("99\n")
        _tokens(repo / "AGENTS.md", 5500)
        assert _guard(repo, repo / "AGENTS.md") is None, "the knob was not read"

    def test_the_log_names_the_tier(self, repo: Path):
        """`ok:`, `NEAR:` and `WARN:` — the log is how anyone confirms the hook
        ran at all, so it has to say which decision it made and on what."""
        _tokens(repo / "AGENTS.md", 5500)
        _guard(repo, repo / "AGENTS.md")
        _tokens(repo / "AGENTS.md", 7000)
        _guard(repo, repo / "AGENTS.md")
        log = _guard_log(repo)
        assert re.search(r"^\S+ NEAR: AGENTS\.md .*headroom=500", log, re.M), log
        assert re.search(r"^\S+ WARN: AGENTS\.md .*over=1000", log, re.M), log


class TestTheReviewDeltaMarksTheBand:
    """The delta always printed the headroom; nothing said that 1 was different
    from 4000. Both rows read `ok`."""

    def test_a_near_row_is_labelled(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _tokens(repo / "AGENTS.md", 1000)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        _tokens(repo / "AGENTS.md", 5500)
        assert _delta_rows(repo)["AGENTS.md"] == "NEAR (500 headroom)"

    def test_a_comfortable_row_still_reads_ok(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _tokens(repo / "AGENTS.md", 1000)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        _tokens(repo / "AGENTS.md", 3000)
        assert _delta_rows(repo)["AGENTS.md"] == "ok (3000 headroom)"

    def test_an_over_row_still_reads_over(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _tokens(repo / "AGENTS.md", 1000)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        _tokens(repo / "AGENTS.md", 7000)
        assert _delta_rows(repo)["AGENTS.md"] == "OVER by 1000"

    def test_quiet_mode_speaks_for_a_parked_near_file(self, tmp_path: Path):
        """--quiet used to mean "over budget or growing". A doc parked at 99%
        that this branch merely touched satisfied neither, which is the silence
        the tier exists to end."""
        repo = _repo(tmp_path)
        _tokens(repo / "AGENTS.md", 1000)
        _tokens(repo / "docs" / "A.md", 9500)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        # Touched, not grown: the branch rewrites the doc at the same size.
        _tokens(repo / "docs" / "A.md", 9500)
        (repo / "docs" / "A.md").write_text(
            "y" + (repo / "docs" / "A.md").read_text()[1:]
        )
        rows = _delta_rows(repo, "--quiet", "--base", "HEAD~0")
        assert rows.get("docs/A.md") == "NEAR (500 headroom)", rows


class TestTheCadenceReportsEveryRowItMeasured:
    def _row(self, path: str, tokens: int, budget: int, **kw) -> dict:
        row = {
            "path": path,
            "tokens": tokens,
            "budget": budget,
            "over_budget": tokens > budget,
            "near_budget": budget * 90 // 100 <= tokens <= budget,
            "tokens_source": "exact",
        }
        row.update(kw)
        return row

    def test_a_reference_doc_over_budget_is_warned(self, tmp_path: Path):
        """The hole. The step read ["policy"] and nothing else, so this doc was
        measured, judged over budget, and never mentioned."""
        out = _run_drift(
            tmp_path,
            {
                "policy": self._row("AGENTS.md", 1000, 6000),
                "docs": [self._row("docs/BIG.md", 12000, 10000)],
            },
        )
        assert "::warning::docs/BIG.md is 12000 tokens against a 10000 budget" in out
        assert "AGENTS.md" not in out, out

    def test_proximity_is_a_notice_not_a_warning(self, tmp_path: Path):
        out = _run_drift(
            tmp_path,
            {
                "policy": self._row("AGENTS.md", 5997, 6000),
                "docs": [self._row("docs/CONVENTIONS.md", 9999, 10000)],
            },
        )
        assert "::notice::AGENTS.md is approaching its budget" in out
        assert "3 left" in out
        assert "::notice::docs/CONVENTIONS.md is approaching its budget" in out
        assert "1 left" in out
        assert "::warning::" not in out, "an approach was reported as a breach"
        assert "over" not in out.replace("Not over", ""), out

    def test_breaches_are_printed_before_approaches(self, tmp_path: Path):
        """The tier that needs acting on now is never read after a screenful of
        the tier that does not."""
        out = _run_drift(
            tmp_path,
            {
                "policy": self._row("AGENTS.md", 5997, 6000),
                "docs": [self._row("docs/BIG.md", 12000, 10000)],
            },
        )
        assert out.index("::warning::") < out.index("::notice::"), out

    def test_an_estimated_row_is_marked_as_one(self, tmp_path: Path):
        """An annotation naming a precise count is a claim, and a row whose
        count_tokens call fell back cannot make it (#123). The NUMBER is marked
        rather than the row suppressed — silence about a doc over budget is the
        failure being fixed, so it must not be the fix's own shape."""
        out = _run_drift(
            tmp_path,
            {
                "policy": self._row("AGENTS.md", 7000, 6000, tokens_source="repo"),
                "docs": [],
            },
        )
        assert "~7000 tokens" in out, out
        assert "an estimate (repo), not a count" in out, out

    def test_an_exact_row_is_not_hedged(self, tmp_path: Path):
        out = _run_drift(
            tmp_path,
            {"policy": self._row("AGENTS.md", 7000, 6000), "docs": []},
        )
        assert "is 7000 tokens against a 6000 budget. Run" in out, out

    def test_a_clean_surface_is_silent(self, tmp_path: Path):
        out = _run_drift(
            tmp_path,
            {
                "policy": self._row("AGENTS.md", 1000, 6000),
                "docs": [self._row("docs/A.md", 2000, 10000)],
            },
        )
        assert out.strip() == "", out

    @pytest.mark.parametrize(
        "row",
        [
            {"path": "AGENTS.md", "tokens": 9, "over_budget": False},
            {"path": "AGENTS.md", "budget": 6000, "over_budget": True},
        ],
        ids=["no budget", "no token count"],
    )
    def test_a_row_missing_a_number_is_reported_rather_than_raised(
        self, tmp_path: Path, row: dict
    ):
        """A rolled-back .skills/skills-pin leaves scripts older than the
        workflow they render. An exception here would take the seam and count
        warnings below it down with the step — so the filter has to cover EVERY
        key the loops go on to read, not one of the three. Guarding `budget`
        alone left `r["tokens"]` to raise `KeyError` and exit the step 1, which
        is the failure the guard was written to prevent (CR 2)."""
        out = _run_drift(tmp_path, {"policy": row})
        assert "carry no budget or token count" in out, out
        assert "install-cadence.sh" in out, out

    def test_the_warnings_below_the_report_survive_a_malformed_row(
        self, tmp_path: Path
    ):
        """The blast radius, not just the row. The seam and count warnings are
        printed by shell AFTER the python, so a raise inside it takes them with
        it — and those are the two findings a scheduled run most often has."""
        step = _drift_step(tmp_path)
        ctx = tmp_path / "ctx.json"
        ctx.write_text(json.dumps({"policy": {"path": "AGENTS.md", "budget": 6000}}))
        r = subprocess.run(
            ["bash", "-e", "-c", step.replace("/tmp/ctx.json", str(ctx))],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env={**_clean_env(), "SEAMS": "2", "COUNTS": "1"},
            timeout=30,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "2 unacknowledged cross-reference seam(s)" in r.stdout, r.stdout
        assert "1 unjudged count(s)" in r.stdout, r.stdout

    def test_the_report_survives_a_measurement_with_no_docs_key(self, tmp_path: Path):
        out = _run_drift(tmp_path, {"policy": self._row("AGENTS.md", 7000, 6000)})
        assert "::warning::AGENTS.md is 7000 tokens" in out, out


class TestCheckReportsAStaleReport:
    """How the fix reaches a repo that already has the workflow.

    The cadence is a GENERATED file whose header says to re-run the installer
    rather than edit it, so a cohort repo that updates the vendored skill and
    stops there keeps the old policy-only report and never learns. #237 hit the
    same shape with the counts merge driver and answered it with a marker line
    in `--check`; this is that answer, for the report."""

    def _check(self, repo: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(INSTALL_CADENCE), "--check"],
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=_clean_env(),
            timeout=30,
        )

    def test_a_fresh_install_reports_the_report(self, tmp_path: Path):
        repo = _repo(tmp_path)
        subprocess.run(
            ["bash", str(INSTALL_CADENCE)],
            capture_output=True,
            cwd=str(repo),
            env=_clean_env(),
            timeout=30,
        )
        r = self._check(repo)
        assert r.returncode == 0, r.stdout
        assert "drift report:       yes" in r.stdout, r.stdout

    def test_a_pre_273_workflow_is_named_and_exits_three(self, tmp_path: Path):
        repo = _repo(tmp_path)
        subprocess.run(
            ["bash", str(INSTALL_CADENCE)],
            capture_output=True,
            cwd=str(repo),
            env=_clean_env(),
            timeout=30,
        )
        wf = repo / ".github" / "workflows" / "context-cadence.yml"
        wf.write_text(wf.read_text().replace("near_budget", "OLDFIELD"))
        r = self._check(repo)
        assert r.returncode == 3, r.stdout
        assert "drift report:       STALE" in r.stdout, r.stdout
        # Reported independently: the drivers are current here, and folding the
        # two into one verdict is what hid whichever you were not looking for.
        assert "workflow drivers:   yes" in r.stdout, r.stdout


class TestAllThreeSurfacesDrawOneBand:
    """The pin, and the reason the resolution lives in `_context-lib.sh` rather
    than in three scripts: a file at 99% of its budget must not be a warning in
    one surface and silence in another. Same shape as the budgets' own
    one-knob-one-answer test, one tier up."""

    def test_one_knob_one_verdict(self, tmp_path: Path):
        repo = _repo(tmp_path)
        (repo / ".skills").mkdir()
        (repo / KNOB).write_text("50\n")
        _tokens(repo / "AGENTS.md", 1000)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        # 3,300 of 6,000 is 55% — inside a 50% band, nowhere near the default.
        _tokens(repo / "AGENTS.md", 3300)

        assert _measure(repo)["policy"]["near_budget"] is True

        msg = _guard(repo, repo / "AGENTS.md")
        assert msg is not None and "approaching" in msg, msg

        assert _delta_rows(repo)["AGENTS.md"] == "NEAR (2700 headroom)"

    def test_the_installer_writes_the_knob_the_guard_reads(self, tmp_path: Path):
        """install-guard.sh --budget wrote the budget knob; the supported way to
        configure the band has to be equally supported, or the only way to move
        it is by hand (#126's lesson, which is how a repo came to have two
        surfaces honouring a budget the weekly run did not)."""
        if not shutil.which("jq"):
            pytest.skip("install-guard.sh needs jq for the settings merge")
        repo = _repo(tmp_path)
        _tokens(repo / "AGENTS.md", 1000)
        r = subprocess.run(
            ["bash", str(INSTALL_GUARD), "--proximity-pct", "70"],
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=_clean_env(),
            timeout=30,
        )
        assert r.returncode == 0, r.stderr
        assert (repo / KNOB).read_text().strip() == "70"
        assert _call("ctx_proximity_pct", str(repo)).stdout == "70"

    @pytest.mark.parametrize("value", ["0", "101", "ninety"])
    def test_the_installer_refuses_a_value_that_would_disable_the_tier(
        self, tmp_path: Path, value: str
    ):
        repo = _repo(tmp_path)
        r = subprocess.run(
            ["bash", str(INSTALL_GUARD), "--proximity-pct", value],
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=_clean_env(),
            timeout=30,
        )
        assert r.returncode == 1, r.stdout
        assert "--proximity-pct" in r.stderr, r.stderr
        assert not (repo / KNOB).exists(), "a refused value was written anyway"
