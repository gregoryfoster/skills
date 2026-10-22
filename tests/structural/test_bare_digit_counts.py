"""#441 — bare-digit-counts.sh: ask which bare digits the count gate passed over are tallies.

`check-counts.sh` leaves a bare digit alone on purpose. `--candidates FILE`
writes the clauses it passed over that hold one, and this pass asks TypeSafe
about each one the prefilters leave. What this file pins:

- **The flag is output only.** The report, the trailer and the exit code are
  byte-identical with and without it, on fixtures and on this repo's policy
  file, so the advisory pass can't move the gate.
- **A candidate is exactly what the gate passed over:** not reported, not
  carrying its command, not an index line, not fenced. "Clause" and "fence"
  have one definition, the gate's.
- **The prefilters mask what code can rule out,** and name what they took.
- **The pass never touches the gate,** and on a skip or a failure it still
  prints every row, unjudged, with its own documented exit code.
- **The measured shape is the shipped shape.** `--dry-run` emits cases that
  `typesafe-eval.py` loads once labelled.

No network: the TypeSafe client is replaced by a fake.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "skills" / "curating-context" / "scripts"
CHECK = SCRIPTS / "check-counts.sh"
WRAPPER = SCRIPTS / "bare-digit-counts.sh"
REFERENCE = (
    REPO_ROOT / "skills" / "curating-context" / "references" / "seam-accounting.md"
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # a dataclass looks its module up while it's built
    spec.loader.exec_module(mod)
    return mod


# Importing from skills/*/scripts would leave a __pycache__/ there, which the
# suite's vendoring fixtures then copy as if it were a script.
sys.dont_write_bytecode = True
_load("_sentences", SCRIPTS / "_sentences.py")
bdc = _load("_bare_digit_counts", SCRIPTS / "_bare_digit_counts.py")
ev = _load("typesafe_eval", REPO_ROOT / "scripts" / "typesafe-eval.py")
ts = bdc._typesafe


def _env() -> dict:
    # Under a hook, GIT_DIR makes tmp_path answer as this repo (#189).
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=_env())
    return tmp_path


def _check(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(CHECK), "--index-max", "0", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_env(),
    )


def _candidates(repo: Path, text: str, *args: str) -> list[dict]:
    (repo / "AGENTS.md").write_text(text)
    out = repo.parent / "cand.jsonl"
    r = _check(repo, "--candidates", str(out), *args)
    assert r.returncode in (0, 3), r.stderr
    return [json.loads(line) for line in out.read_text().splitlines()]


# --- check-counts.sh --candidates --------------------------------------------

POLICY = """\
# Title

Intro with port 8000 and three `x` tiers.

## Section A

- The 182 hx-get reveals mean nothing without JS.
- 40 files (`ls src | wc -l`) are in src.
- Status 403 when refused.

```bash
echo 99 bottles
```

| Col | Val |
|---|---|
| a | 12 rows |

### Sub

> Quoted 7 items.

## Section B

No digits here.
"""


def test_a_candidate_is_a_passed_over_clause_holding_a_digit(repo):
    """Split as the gate splits: a list item keeps its marker, a quote its `>`."""
    got = [(c["line"], c["clause"]) for c in _candidates(repo, POLICY)]
    assert got == [
        (7, "- The 182 hx-get reveals mean nothing without JS."),
        (9, "- Status 403 when refused."),
        (17, "| a | 12 rows |"),
        (21, "> Quoted 7 items."),
    ]


def test_a_reported_clause_is_not_a_candidate(repo):
    """`three \\`x\\`` is the gate's own hit, so the port beside it is the gate's to judge."""
    clauses = [c["clause"] for c in _candidates(repo, POLICY)]
    assert not any("8000" in c for c in clauses)


def test_a_clause_carrying_its_command_is_not_a_candidate(repo):
    clauses = [c["clause"] for c in _candidates(repo, POLICY)]
    assert not any("40 files" in c for c in clauses)


def test_fenced_lines_are_not_candidates(repo):
    clauses = [c["clause"] for c in _candidates(repo, POLICY)]
    assert not any("99" in c for c in clauses)


def test_an_index_line_is_not_a_candidate(repo):
    text = (
        "# T\n\n## Detail Docs\n\n- [a.md](a.md) — 12 sections\n\n## Next\n\n5 rules.\n"
    )
    (repo / "AGENTS.md").write_text(text)
    out = repo.parent / "cand.jsonl"
    r = subprocess.run(
        ["bash", str(CHECK), "--candidates", str(out)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert r.returncode in (0, 3), r.stderr
    got = [json.loads(line)["clause"] for line in out.read_text().splitlines()]
    assert got == ["5 rules."]


def test_a_candidate_carries_its_heading_and_nothing_more(repo):
    by = {c["line"]: c for c in _candidates(repo, POLICY)}
    assert by[7]["heading"] == "Section A" and by[21]["heading"] == "Sub"
    assert by[7]["file"] == "AGENTS.md"
    assert set(by[7]) == {"file", "line", "clause", "heading"}


def test_a_heading_inside_a_fence_is_no_heading(repo):
    text = "## Real\n\n```\n## Fake\n```\n\n5 rules.\n"
    (c,) = _candidates(repo, text)
    assert c["heading"] == "Real"


def test_a_candidate_above_every_heading_has_none(repo):
    (c,) = _candidates(repo, "5 rules up top.\n\n## Later\n\nNothing.\n")
    assert c["heading"] is None


def test_the_report_is_byte_identical_with_and_without_the_flag(repo):
    (repo / "AGENTS.md").write_text(POLICY)
    plain = _check(repo)
    flagged = _check(repo, "--candidates", str(repo.parent / "c.jsonl"))
    assert (plain.stdout, plain.stderr, plain.returncode) == (
        flagged.stdout,
        flagged.stderr,
        flagged.returncode,
    )
    assert plain.returncode == 3


def test_this_repos_policy_file_reports_the_same_either_way(tmp_path):
    args = ["bash", str(CHECK)]
    kw = dict(cwd=REPO_ROOT, capture_output=True, text=True, env=_env())
    plain = subprocess.run(args, **kw)
    flagged = subprocess.run(args + ["--candidates", str(tmp_path / "c.jsonl")], **kw)
    assert (plain.stdout, plain.returncode) == (flagged.stdout, flagged.returncode)
    assert (tmp_path / "c.jsonl").read_text().strip()


def test_the_file_is_written_on_an_ack_refusal_too(repo):
    """The candidates don't depend on the ack file, so exit 1 still leaves them."""
    (repo / "AGENTS.md").write_text(POLICY)
    (repo / ".skills").mkdir()
    (repo / ".skills" / "context-counts-ok").write_text("bogus :: x\n")
    out = repo.parent / "c.jsonl"
    r = _check(repo, "--candidates", str(out))
    assert r.returncode == 1
    assert "counts:" not in r.stdout
    assert len(out.read_text().splitlines()) == 4


def test_an_unwritable_path_is_exit_2(repo):
    (repo / "AGENTS.md").write_text(POLICY)
    r = _check(repo, "--candidates", str(repo / "no" / "such" / "dir" / "c.jsonl"))
    assert r.returncode == 2 and "can't write --candidates" in r.stderr


def test_a_relative_path_is_read_from_where_the_caller_stands(repo):
    (repo / "AGENTS.md").write_text(POLICY)
    sub = repo / "sub"
    sub.mkdir()
    r = subprocess.run(
        ["bash", str(CHECK), "--index-max", "0", "--candidates", "c.jsonl"],
        cwd=sub,
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert r.returncode == 3, r.stderr
    assert (sub / "c.jsonl").is_file() and not (repo / "c.jsonl").exists()


def test_the_help_documents_the_flag_and_points_at_the_pass():
    r = subprocess.run(["bash", str(CHECK), "--help"], capture_output=True, text=True)
    for needle in ("--candidates FILE", "OUTPUT ONLY", "bare-digit-counts.sh"):
        assert needle in r.stdout, needle


# --- prefilters --------------------------------------------------------------


@pytest.mark.parametrize(
    "clause,numbers,masks",
    [
        ("The 182 hx-get reveals.", ["182"], []),
        ("Status `403` when refused.", [], ["code"]),
        ("See [#12](https://x.io/issues/12).", [], ["link", "issue"]),
        ("Blocked on #12 and o/r#3.", [], ["issue"]),
        ("Measured 2026-10-21.", [], ["date"]),
        ("Pinned to jev-1.13.0, needs 3.9+.", [], ["version"]),
        ("Built at b8c54db8.", [], ["sha"]),
        ("Serves localhost:8080 only.", [], ["port"]),
        ("Runs at 08:00, reconnected 15:27:00Z.", [], ["time"]),
        ("Covers 72.3% of it.", [], ["percent"]),
        ("2.", [], ["marker"]),
        ("An H1, UTF-8, 5xx and 64k.", [], ["word"]),
        ("max 64 chars, #12 aside.", ["64"], ["issue"]),
        ("from 100+ candidates", ["100+"], []),
        ("a 6,000-token budget", ["6,000"], []),
        ("on port 8000, never 8001.", ["8000", "8001"], []),
        ("1,2 and 12,345,678 rows", ["1", "2", "12,345,678"], []),
    ],
)
def test_prefilters(clause, numbers, masks):
    assert bdc.prefilter(clause) == (numbers, masks)


def test_a_fully_masked_clause_is_prefiltered_and_names_its_masks():
    rec = {"file": "A.md", "line": 3, "clause": "See #12.", "heading": None}
    row = bdc.to_row(rec)
    assert row.status == "prefiltered:issue" and row.numbers == []


@pytest.mark.parametrize(
    "path", ["AGENTS.md", "CLAUDE.md", "sub/AGENTS.md", "docs/x/CLAUDE.md"]
)
def test_a_policy_files_clause_is_never_sent(path):
    """1 tally in the cohort policy files' 411 digits (#441): reference docs only."""
    rec = {"file": path, "line": 3, "clause": "Holds 40 files.", "heading": None}
    row = bdc.to_row(rec)
    assert row.status == "policy-file" and row.numbers == ["40"]


@pytest.mark.parametrize("path", ["docs/AGENTS-notes.md", "README.md", "agents.md"])
def test_a_reference_doc_is_sent(path):
    rec = {"file": path, "line": 3, "clause": "Holds 40 files.", "heading": None}
    assert bdc.to_row(rec).status == ""


# --- the cases ---------------------------------------------------------------


def test_a_tally_case_carries_the_clause_its_numbers_and_heading():
    state, questions = bdc.build_tally_case("The 182 reveals.", ["182"], "Admin")
    assert state == {
        "clause": "The 182 reveals.",
        "numbers": ["182"],
        "heading": "Admin",
    }
    assert list(questions) == ["tally"] and questions["tally"]["type"] == "noul"
    state, _ = bdc.build_tally_case("The 182 reveals.", ["182"], None)
    assert "heading" not in state


# --- the run -----------------------------------------------------------------

RECORDS = [
    {"file": "docs/REF.md", "line": 3, "clause": "See #12.", "heading": None},
    {"file": "docs/REF.md", "line": 5, "clause": "The 182 reveals.", "heading": "A"},
    {"file": "docs/REF.md", "line": 7, "clause": "Port 8000.", "heading": "A"},
    {"file": "docs/REF.md", "line": 9, "clause": "Holds 40 files.", "heading": "B"},
]


def _input(tmp_path, records=RECORDS) -> Path:
    p = tmp_path / "cand.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in records))
    return p


class FakeClient:
    def __init__(self, answers, fail_at=None):
        self.answers, self.fail_at, self.asked = dict(answers), fail_at, []

    def ask(self, state, questions):
        self.asked.append((state, list(questions)))
        if self.fail_at is not None and len(self.asked) == self.fail_at:
            raise ts.TypeSafeError(500, "boom (gave up after 3 attempts)")
        key = (state["clause"], tuple(questions))
        return {
            "answers": {
                q: {"type": "noul", "noul": p} for q, p in self.answers[key].items()
            }
        }


TALLY_ANSWERS = {
    ("The 182 reveals.", ("tally",)): {"tally": 0.9},
    ("Port 8000.", ("tally",)): {"tally": 0.1},
    ("Holds 40 files.", ("tally",)): {"tally": 0.85},
}


def _main(argv, connect):
    out, err = io.StringIO(), io.StringIO()
    code = bdc.main([str(a) for a in argv], stdout=out, stderr=err, connect=connect)
    rows = [line.split("\t") for line in out.getvalue().splitlines()]
    return code, rows, err.getvalue()


def test_a_judged_run_ranks_and_flags_asking_one_question_a_clause(tmp_path):
    client = FakeClient(TALLY_ANSWERS)
    code, rows, err = _main([_input(tmp_path)], lambda **kw: client)
    assert code == 0
    assert [r[1:6] for r in rows] == [
        ["5", "judged", "0.900", "tally?", "182"],
        ["9", "judged", "0.850", "tally?", "40"],
        ["7", "judged", "0.100", "", "8000"],
        ["3", "prefiltered:issue", "", "", ""],
    ]
    assert [q for _, q in client.asked] == [["tally"]] * 3
    assert "3 judged (2 at or over 0.8), 1 prefiltered" in err


def test_the_threshold_moves_the_flag_only(tmp_path):
    client = FakeClient(TALLY_ANSWERS)
    code, rows, _ = _main(
        [_input(tmp_path), "--threshold", "0.88"], lambda **kw: client
    )
    assert code == 0
    assert [r[4] for r in rows] == ["tally?", "", "", ""]
    assert len(client.asked) == 3


def test_a_policy_file_input_sends_nothing_and_says_where_to_point(tmp_path):
    def connect(**kw):
        raise AssertionError("connected")

    recs = [{**r, "file": "AGENTS.md"} for r in RECORDS]
    code, rows, err = _main([_input(tmp_path, recs)], connect)
    assert code == 0 and {r[2] for r in rows} == {"policy-file"}
    assert "AGENTS.md is a policy file" in err and "--file <reference doc>" in err
    assert "4 policy-file" in err


@pytest.mark.parametrize("reason", ["not-opted-in", "no-key"])
def test_a_skip_is_exit_4_and_still_prints_every_row(tmp_path, reason):
    def connect(**kw):
        raise ts.Skipped(reason, "test")

    code, rows, err = _main([_input(tmp_path)], connect)
    assert code == 4 and len(rows) == 4
    assert sorted(r[2] for r in rows) == ["prefiltered:issue"] + ["skipped"] * 3
    assert f"skipped ({reason})" in err


def test_a_fully_prefiltered_input_needs_no_client(tmp_path):
    def connect(**kw):
        raise AssertionError("connected")

    code, rows, _ = _main([_input(tmp_path, RECORDS[:1])], connect)
    assert code == 0 and rows[0][2] == "prefiltered:issue"


def test_a_failure_is_exit_2_and_the_rest_are_not_asked(tmp_path):
    client = FakeClient(TALLY_ANSWERS, fail_at=1)
    code, rows, err = _main([_input(tmp_path)], lambda **kw: client)
    assert code == 2 and "boom" in err
    assert sorted(r[2] for r in rows) == [
        "failed",
        "not-asked",
        "not-asked",
        "prefiltered:issue",
    ]


@pytest.mark.parametrize("bad", [None, 1.5, True, "0.4"])
def test_an_answer_that_isnt_a_probability_is_a_failure(tmp_path, bad):
    class Bad:
        def ask(self, state, questions):
            return {"answers": {"tally": {"type": "noul", "noul": bad}}}

    code, rows, err = _main([_input(tmp_path)], lambda **kw: Bad())
    assert code == 2 and "has no noul probability" in err
    # Its shape, never its value: server text reaches stderr only redacted (CR 462).
    assert "(an object with 2 key(s))" in err and repr(bad) not in err


def test_dry_run_sends_nothing_and_emits_cases_the_evaluator_loads(tmp_path):
    def connect(**kw):
        raise AssertionError("connected")

    out, err = io.StringIO(), io.StringIO()
    code = bdc.main(
        ["--dry-run", str(_input(tmp_path))], stdout=out, stderr=err, connect=connect
    )
    assert code == 0 and "3 would-ask" in err.getvalue()
    lines = out.getvalue().splitlines()
    assert len(lines) == 3
    labelled = tmp_path / "set.jsonl"
    labelled.write_text(
        "".join(
            json.dumps({**json.loads(line), "expected": {"tally": False}}) + "\n"
            for line in lines
        )
    )
    cases = ev.load_set(labelled.read_text().splitlines())
    assert [c["id"] for c in cases] == [
        "docs/REF.md:5",
        "docs/REF.md:7",
        "docs/REF.md:9",
    ]


@pytest.mark.parametrize(
    "argv,needle",
    [
        (["--threshold", "2"], "probability 0-1"),
        (["--threshold"], "needs a value"),
        (["--bogus"], "unknown option"),
        (["a", "b"], "one input only"),
        (["/no/such/file"], "can't read"),
    ],
)
def test_usage_errors_are_exit_1(argv, needle):
    code, _, err = _main(argv, lambda **kw: None)
    assert code == 1 and needle in err


@pytest.mark.parametrize(
    "line",
    [
        "not json",
        '{"file": "A", "line": "3", "clause": "x", "heading": null}',
        '{"file": "A", "line": 3, "clause": "x"}',
        "[1, 2]",
    ],
)
def test_input_that_isnt_check_counts_is_exit_1(tmp_path, line):
    p = tmp_path / "c.jsonl"
    p.write_text(line + "\n")
    code, _, err = _main([p], lambda **kw: None)
    assert code == 1 and "--candidates record" in err


def test_help_documents_columns_statuses_masks_exits_and_the_threshold():
    r = subprocess.run(["bash", str(WRAPPER), "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    head = "file line status p flag numbers clause"
    assert head in r.stdout
    for needle in (
        "skipped",
        "failed",
        "not-asked",
        "would-ask",
        "prefiltered",
        "policy-file",
    ):
        assert needle in r.stdout, needle
    for name, _ in bdc._PREFILTERS:
        assert re.search(rf"^  {name} ", r.stdout, re.M), name
    for name in ("code", "link", "marker"):
        assert re.search(rf"^  {name} ", r.stdout, re.M), name
    assert f"default {bdc.DEFAULT_THRESHOLD:g}" in r.stdout


def test_every_status_the_code_sets_is_documented():
    src = (SCRIPTS / "_bare_digit_counts.py").read_text()
    doc = bdc.__doc__
    set_here = set(re.findall(r'status = "([a-z-]+)', src))
    set_here |= set(re.findall(r'r\.status = "([a-z-]+)"', src))
    assert set_here and all(s in doc for s in set_here), set_here


def test_the_reference_names_every_field_that_is_sent():
    doc = REFERENCE.read_text()
    tally, _ = bdc.build_tally_case("c", ["1"], "h")
    for key in tally:
        assert f"`{key}`" in doc, key


def test_the_wrapper_runs_under_isolated_mode(tmp_path):
    """`python3 -I` drops the script's directory; the module must put it back for its siblings."""
    (tmp_path / "json.py").write_text("raise SystemExit('shadowed')\n")
    r = subprocess.run(
        ["bash", str(WRAPPER), "--help"], capture_output=True, text=True, cwd=tmp_path
    )
    assert r.returncode == 0 and "shadowed" not in r.stdout + r.stderr


def test_the_wrapper_writes_no_bytecode_into_the_skill(tmp_path):
    skill = tmp_path / "scripts"
    shutil.copytree(SCRIPTS, skill, ignore=shutil.ignore_patterns("__pycache__"))
    r = subprocess.run(
        ["bash", str(skill / "bare-digit-counts.sh"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0 and not (skill / "__pycache__").exists()


def test_the_flag_feeds_the_pass_end_to_end(repo, tmp_path_factory):
    out = tmp_path_factory.mktemp("o") / "c.jsonl"
    (repo / "docs").mkdir()
    (repo / "docs" / "REF.md").write_text(POLICY)
    r = _check(repo, "--file", "docs/REF.md", "--candidates", str(out))
    assert r.returncode == 3, r.stderr
    r = subprocess.run(
        ["bash", str(WRAPPER), "--dry-run", str(out)],
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert r.returncode == 0, r.stderr
    sent = [json.loads(line)["state"]["numbers"] for line in r.stdout.splitlines()]
    assert sent == [["182"], ["403"], ["12"], ["7"]]


_PY39_MISSING = (
    "python3.9 is not on PATH, so the pass was NOT run on the client's 3.9 floor. "
    "Install it to get that coverage; set PY39_REQUIRED=1 to make its absence a "
    "failure instead of a skip."
)


def test_the_pass_runs_on_python39(tmp_path):
    """The client's floor (#448). A source check can't see a 3.10+ construct; a run can."""
    py39 = shutil.which("python3.9")
    if not py39:
        if os.environ.get("PY39_REQUIRED", "") not in ("", "0"):
            pytest.fail(_PY39_MISSING)
        pytest.skip(_PY39_MISSING)
    r = subprocess.run(
        [
            py39,
            "-I",
            "-B",
            str(SCRIPTS / "_bare_digit_counts.py"),
            "--dry-run",
            str(_input(tmp_path)),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert len(r.stdout.splitlines()) == 3
