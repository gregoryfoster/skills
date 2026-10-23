"""#442 — tightened-rules.sh: ask which tightened sentences may have lost their rule.

`prove-no-loss.sh --claims --candidates FILE` writes a record for each base
line a `tighten` entry accounted for, with its base block and the section the
rewrite left, and this pass asks TypeSafe one question per sentence on those
lines. What this file pins:

- **The flag is output only.** The report, the trailer and the exit code are
  byte-identical with and without it, on a fixture and on this repo's policy
  file, so the advisory pass can't move the iron law's verdict.
- **A record is exactly a `tighten`-warranted line,** written only once the
  entry behind it is trusted, with the successor its block's rewrite left.
- **Sentences are rebuilt across wrapped lines** by `_sentences.sentences()`,
  which shares `occurrences()`'s units and boundaries.
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
PROVE = SCRIPTS / "prove-no-loss.sh"
WRAPPER = SCRIPTS / "tightened-rules.sh"
REFERENCE = (
    REPO_ROOT / "skills" / "curating-context" / "references" / "keep-cut-rubric.md"
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
sent = _load("_sentences", SCRIPTS / "_sentences.py")
tr = _load("_tightened_rules", SCRIPTS / "_tightened_rules.py")
ev = _load("typesafe_eval", REPO_ROOT / "scripts" / "typesafe-eval.py")
ts = tr._typesafe


def _env() -> dict:
    # Under a hook, GIT_DIR makes tmp_path answer as this repo (#189).
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, env=_env()
    )


BASE = """\
---
name: x
---
# Title

Be terse. Lead with the answer.

## Rules

Never push to main. Only rebase when
the branch is yours, because others pull it.

- Keep `uv sync` first.

## Moved Section

Old text that is tightened here.

### Renamed

Some renamed heading body with distinctive words alpha beta gamma.
"""

AFTER = """\
---
name: x
---
# Title

Be terse; lead with the answer.

## Rules

Never push to main; rebase only your own branch.

- Keep `uv sync` first.

### Renamed Better

Body with distinctive words alpha beta gamma, tightened.
"""

ACK = """\
tighten :: Be terse. Lead with the answer.
tighten :: Never push to main. Only rebase when
tighten :: the branch is yours, because others pull it.
tighten :: Old text that is tightened here.
rename :: ### Renamed
tighten :: Some renamed heading body with distinctive words alpha beta gamma.
"""


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "AGENTS.md").write_text(BASE)
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    (r / "AGENTS.md").write_text(AFTER)
    (r / "docs").mkdir()
    (r / "docs" / "MOVED.md").write_text("## Moved Section\n\nTightened text here.\n")
    (r / ".skills").mkdir()
    (r / ".skills" / "context-loss-ok").write_text(ACK)
    return r


def _prove(repo: Path, *args: str, cwd: Path | None = None):
    return subprocess.run(
        ["bash", str(PROVE), "--claims", *args],
        cwd=cwd or repo,
        capture_output=True,
        text=True,
        env=_env(),
    )


def _records(repo: Path, *args: str) -> list[dict]:
    out = repo.parent / "cand.jsonl"
    r = _prove(repo, "--candidates", str(out), *args)
    assert r.returncode in (0, 3), r.stderr
    return [json.loads(line) for line in out.read_text().splitlines()]


# --- prove-no-loss.sh --candidates -------------------------------------------


def test_a_record_is_a_tighten_warranted_line_and_nothing_else(repo):
    recs = _records(repo)
    assert [r["text"] for r in recs] == [
        "Be terse. Lead with the answer.",
        "Never push to main. Only rebase when",
        "the branch is yours, because others pull it.",
        "Old text that is tightened here.",
        "Some renamed heading body with distinctive words alpha beta gamma.",
    ]
    assert {r["warrant"].split(" :: ")[0] for r in recs} == {"tighten"}


def test_line_numbers_count_the_frontmatter_back_in(repo):
    lines = BASE.splitlines()
    for r in _records(repo):
        assert lines[r["line"] - 1].strip() == r["text"]
        assert lines[r["section_line"] - 1].startswith("#")


def test_the_base_section_is_the_headings_own_block(repo):
    by = {r["text"]: r for r in _records(repo)}
    old = by["Old text that is tightened here."]
    assert old["heading"] == "Moved Section"
    assert old["section"] == "## Moved Section\n\nOld text that is tightened here.\n"


def test_the_successor_is_the_same_heading_in_the_file_first(repo):
    by = {r["text"]: r for r in _records(repo)}
    s = by["Never push to main. Only rebase when"]["successor"]
    assert (s["file"], s["heading"], s["how"]) == ("AGENTS.md", "Rules", "heading")
    assert "rebase only your own branch" in s["text"]
    assert s["line"] == AFTER.splitlines().index("## Rules") + 1


def test_a_heading_that_left_the_file_is_found_in_a_destination(repo):
    by = {r["text"]: r for r in _records(repo)}
    s = by["Old text that is tightened here."]["successor"]
    assert (s["file"], s["how"]) == ("docs/MOVED.md", "heading")


def test_a_renamed_heading_is_found_by_its_words(repo):
    by = {r["text"]: r for r in _records(repo)}
    s = by["Some renamed heading body with distinctive words alpha beta gamma."][
        "successor"
    ]
    assert (s["heading"], s["how"]) == ("Renamed Better", "words")


def test_a_title_owns_its_preamble_not_the_document(repo):
    by = {r["text"]: r for r in _records(repo)}
    s = by["Be terse. Lead with the answer."]["successor"]
    assert s["heading"] == "Title"
    assert s["text"] == "# Title\n\nBe terse; lead with the answer.\n"


def test_nothing_sharing_a_word_has_no_successor(repo):
    (repo / "AGENTS.md").write_text("# Title\n\nUnrelated.\n")
    (repo / "docs" / "MOVED.md").unlink()
    (repo / ".skills" / "context-loss-ok").write_text(
        "tighten :: Old text that is tightened here.\n"
    )
    recs = _records(repo)
    assert [r["successor"] for r in recs] == [None]


def test_the_report_is_byte_identical_with_and_without_the_flag(repo):
    plain = _prove(repo)
    flagged = _prove(repo, "--candidates", str(repo.parent / "c.jsonl"))
    assert plain.returncode == 0
    assert (plain.stdout, plain.stderr, plain.returncode) == (
        flagged.stdout,
        flagged.stderr,
        flagged.returncode,
    )


def test_a_loss_is_still_exit_3_and_the_file_is_written(repo):
    (repo / "AGENTS.md").write_text(AFTER.replace("- Keep `uv sync` first.\n", ""))
    out = repo.parent / "c.jsonl"
    plain = _prove(repo)
    flagged = _prove(repo, "--candidates", str(out))
    assert plain.returncode == flagged.returncode == 3
    assert (plain.stdout, plain.stderr) == (flagged.stdout, flagged.stderr)
    assert len(out.read_text().splitlines()) == 5


def test_this_repos_policy_file_reports_the_same_either_way(tmp_path):
    plain = _prove(REPO_ROOT, cwd=REPO_ROOT)
    flagged = _prove(
        REPO_ROOT, "--candidates", str(tmp_path / "c.jsonl"), cwd=REPO_ROOT
    )
    assert (plain.stdout, plain.stderr, plain.returncode) == (
        flagged.stdout,
        flagged.stderr,
        flagged.returncode,
    )


def test_a_refused_ack_file_writes_no_records(repo):
    (repo / ".skills" / "context-loss-ok").write_text(ACK + "tightened :: x\n")
    out = repo.parent / "c.jsonl"
    r = _prove(repo, "--candidates", str(out))
    assert r.returncode == 1 and not out.exists()


def test_the_flag_needs_claims(repo):
    out = repo.parent / "c.jsonl"
    r = subprocess.run(
        ["bash", str(PROVE), "--candidates", str(out)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert r.returncode == 1 and "--candidates needs --claims" in r.stderr
    assert not out.exists()


def test_an_unwritable_path_is_exit_2(repo):
    r = _prove(repo, "--candidates", str(repo / "no" / "such" / "c.jsonl"))
    assert r.returncode == 2 and "can't write --candidates" in r.stderr


def test_a_relative_path_is_read_from_where_the_caller_stands(repo):
    sub = repo / "docs"
    r = _prove(repo, "--candidates", "c.jsonl", cwd=sub)
    assert r.returncode == 0, r.stderr
    assert (sub / "c.jsonl").is_file() and not (repo / "c.jsonl").exists()


def test_the_help_documents_the_flag_and_points_at_the_pass():
    r = subprocess.run(["bash", str(PROVE), "--help"], capture_output=True, text=True)
    help_text = r.stdout
    assert "--candidates FILE" in help_text and "tightened-rules.sh" in help_text
    for field in ("file", "line", "text", "warrant", "heading", "section_line"):
        assert re.search(rf"^\s+{field}\s", help_text, re.M), field
    assert "--candidates unwritable" in help_text


# --- _sentences.sentences() ---------------------------------------------------


def test_a_wrapped_paragraph_comes_back_as_its_sentences_with_their_lines():
    text = "# H\n\nNever push. Only rebase when\nthe branch is yours.\n\n- One item. Two.\n"
    got = [(s.text, s.line, s.end_line, s.kind) for s in sent.sentences(text)]
    assert got == [
        ("H", 1, 1, "heading"),
        ("Never push.", 3, 3, "para"),
        ("Only rebase when the branch is yours.", 3, 4, "para"),
        ("One item.", 6, 6, "item"),
        ("Two.", 6, 6, "item"),
    ]


def test_code_gives_no_sentences_and_a_row_is_one():
    text = "```\nNot. Prose.\n```\n\n| A. | B. |\n\nAfter `x. Y` it.\n"
    got = [s.text for s in sent.sentences(text)]
    assert got == ["| A. | B. |", "After `x. Y` it."]


def test_sentences_and_occurrences_cut_at_the_same_boundaries():
    text = "One #12 here. Two e.g. three #13. Four."
    refs = [o.sentence for o in sent.occurrences(text)]
    cut = [s.text for s in sent.sentences(text)]
    assert refs == ["One #12 here.", "Two e.g. three #13."]
    assert all(r in cut for r in refs)


# --- the pass ----------------------------------------------------------------

SECTION = (
    "## Rules\n\nNever push to main. Only rebase when\n"
    "the branch is yours, because others pull it.\n\nKept line. Untouched.\n"
)
AFTER_RULES = "## Rules\n\nNever push to main; rebase only your own branch.\n"


def _rec(line, text, successor=AFTER_RULES, file="AGENTS.md"):
    return {
        "file": file,
        "line": line,
        "text": text,
        "warrant": f"tighten :: {text}",
        "heading": "Rules",
        "section_line": 1,
        "section": SECTION,
        "successor": None
        if successor is None
        else {
            "file": file,
            "line": 1,
            "heading": "Rules",
            "how": "heading",
            "text": successor,
        },
    }


RECORDS = [
    _rec(3, "Never push to main. Only rebase when"),
    _rec(4, "the branch is yours, because others pull it."),
]


def _input(tmp_path, records=RECORDS):
    p = tmp_path / "cand.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in records))
    return p


def test_sentences_touching_a_tightened_line_are_asked_and_no_others():
    rows = tr.to_rows(RECORDS, [])
    assert [(r.line, r.end_line, r.sentence, r.status) for r in rows] == [
        (3, 3, "Never push to main.", ""),
        (3, 4, "Only rebase when the branch is yours, because others pull it.", ""),
    ]


def test_a_sentence_still_there_word_for_word_is_kept():
    rows = tr.to_rows(
        [_rec(3, "x", successor="## Rules\n\nNever push\nto  main. Gone.\n")], []
    )
    assert [r.status for r in rows] == ["kept", ""]


def test_a_record_with_no_successor_is_not_sent():
    rows = tr.to_rows([_rec(3, "x", successor=None)], [])
    assert {r.status for r in rows} == {"no-successor"}


@pytest.mark.parametrize("path", ["docs/plans/x.md", "docs/archive/AGENTS.md"])
def test_an_archival_docs_sentence_is_never_sent(path):
    rows = tr.to_rows([_rec(3, "x", file=path)], ["plans", "archive"])
    assert {r.status for r in rows} == {"archival"}


def test_the_passes_share_one_archival_matcher():
    import _archival

    assert tr.is_archival is _archival.is_archival
    assert tr.archival_names is _archival.archival_names


def test_a_case_carries_the_sentence_its_heading_and_the_rewrite():
    state, questions = tr.build_case("Never push.", "Rules", AFTER_RULES)
    assert state == {
        "sentence": "Never push.",
        "heading": "Rules",
        "after_section": AFTER_RULES,
    }
    assert list(questions) == ["dropped"] and questions["dropped"]["type"] == "noul"


def test_a_long_successor_is_clipped_around_the_sentences_words():
    after = "filler " * 9000 + "the distinctive passage here " + "filler " * 9000
    clipped = tr.clip(after, "a distinctive passage", limit=1000)
    assert len(clipped) <= 1002 and "distinctive passage" in clipped
    assert clipped.startswith("…") and clipped.endswith("…")
    assert tr.clip("short", "x") == "short"


def test_the_clip_keeps_a_case_inside_the_per_question_limit():
    after = "word " * (tr.MAX_AFTER_CHARS // 2)
    state, questions = tr.build_case("A word.", "H", after)
    ts._check_size(state, questions)  # raises RequestTooLarge past 32k tokens


class FakeClient:
    def __init__(self, answers, fail_at=None):
        self.answers, self.fail_at, self.asked = dict(answers), fail_at, []

    def ask(self, state, questions):
        self.asked.append((state, list(questions)))
        if self.fail_at is not None and len(self.asked) == self.fail_at:
            raise ts.TypeSafeError(500, "boom (gave up after 3 attempts)")
        return {
            "answers": {
                "dropped": {"type": "noul", "noul": self.answers[state["sentence"]]}
            }
        }


ANSWERS = {
    "Never push to main.": 0.1,
    "Only rebase when the branch is yours, because others pull it.": 0.8,
}


def _main(argv, connect):
    out, err = io.StringIO(), io.StringIO()
    code = tr.main([str(a) for a in argv], stdout=out, stderr=err, connect=connect)
    rows = [line.split("\t") for line in out.getvalue().splitlines()]
    return code, rows, err.getvalue()


def test_a_judged_run_ranks_and_flags_asking_one_question_a_sentence(tmp_path):
    client = FakeClient(ANSWERS)
    code, rows, err = _main([_input(tmp_path)], lambda **kw: client)
    assert code == 0
    assert [r[1:5] for r in rows] == [
        ["3", "judged", "0.800", "dropped?"],
        ["3", "judged", "0.100", ""],
    ]
    assert [q for _, q in client.asked] == [["dropped"]] * 2
    assert "2 judged (1 at or over 0.3)" in err


def test_the_threshold_moves_the_flag_only(tmp_path):
    client = FakeClient(ANSWERS)
    code, rows, _ = _main(
        [_input(tmp_path), "--threshold", "0.05"], lambda **kw: client
    )
    assert code == 0 and [r[4] for r in rows] == ["dropped?", "dropped?"]
    assert len(client.asked) == 2


@pytest.mark.parametrize("reason", ["not-opted-in", "no-key"])
def test_a_skip_is_exit_4_and_still_prints_every_row(tmp_path, reason):
    def connect(**kw):
        raise ts.Skipped(reason, "test")

    code, rows, err = _main([_input(tmp_path)], connect)
    assert code == 4 and [r[2] for r in rows] == ["skipped", "skipped"]
    assert f"skipped ({reason})" in err


def test_nothing_to_send_needs_no_client(tmp_path):
    def connect(**kw):
        raise AssertionError("connected")

    code, rows, _ = _main([_input(tmp_path, [_rec(3, "x", successor=None)])], connect)
    assert code == 0 and {r[2] for r in rows} == {"no-successor"}


def test_a_failure_is_exit_2_and_the_rest_are_not_asked(tmp_path):
    client = FakeClient(ANSWERS, fail_at=1)
    code, rows, err = _main([_input(tmp_path)], lambda **kw: client)
    assert code == 2 and "boom" in err
    assert sorted(r[2] for r in rows) == ["failed", "not-asked"]


@pytest.mark.parametrize("bad", [None, 1.5, True, "0.4"])
def test_an_answer_that_isnt_a_probability_is_a_failure(tmp_path, bad):
    class Bad:
        def ask(self, state, questions):
            return {"answers": {"dropped": {"type": "noul", "noul": bad}}}

    code, rows, err = _main([_input(tmp_path)], lambda **kw: Bad())
    assert code == 2 and "has no noul probability" in err
    # Its shape, never its value: server text reaches stderr only redacted.
    assert "(an object with 2 key(s))" in err and repr(bad) not in err


def test_dry_run_sends_nothing_and_emits_cases_the_evaluator_loads(tmp_path):
    def connect(**kw):
        raise AssertionError("connected")

    out, err = io.StringIO(), io.StringIO()
    code = tr.main(
        ["--dry-run", str(_input(tmp_path))], stdout=out, stderr=err, connect=connect
    )
    assert code == 0 and "2 would-ask" in err.getvalue()
    labelled = tmp_path / "set.jsonl"
    labelled.write_text(
        "".join(
            json.dumps({**json.loads(line), "expected": {"dropped": False}}) + "\n"
            for line in out.getvalue().splitlines()
        )
    )
    cases = ev.load_set(labelled.read_text().splitlines())
    assert [c["id"] for c in cases] == ["AGENTS.md:3#1", "AGENTS.md:3#2"]


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
        '{"file": "A", "line": 3, "section_line": 1, "section": "x", "heading": null}',
        '{"file": "A", "line": "3", "section_line": 1, "section": "x", '
        '"heading": null, "successor": null}',
        '{"file": "A", "line": 3, "section_line": 1, "section": "x", '
        '"heading": null, "successor": {"file": "A"}}',
        "[1, 2]",
    ],
)
def test_input_that_isnt_prove_no_loss_is_exit_1(tmp_path, line):
    p = tmp_path / "c.jsonl"
    p.write_text(line + "\n")
    code, _, err = _main([p], lambda **kw: None)
    assert code == 1 and "--candidates record" in err


def test_help_documents_columns_statuses_exits_and_the_threshold():
    r = subprocess.run(["bash", str(WRAPPER), "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "file line status p flag sentence" in r.stdout
    for needle in ("kept", "no-successor", "archival", "skipped", "failed"):
        assert needle in r.stdout, needle
    assert f"default {tr.DEFAULT_THRESHOLD:g}" in r.stdout


def test_every_status_the_code_sets_is_documented():
    src = (SCRIPTS / "_tightened_rules.py").read_text()
    set_here = set(re.findall(r'status = "([a-z-]+)', src))
    set_here |= set(re.findall(r'r\.status = "([a-z-]+)"', src))
    set_here |= set(re.findall(r'r\.status, failed, exit_code = "([a-z-]+)"', src))
    assert set_here >= {"kept", "no-successor", "archival", "judged", "failed"}
    assert all(s in tr.__doc__ for s in set_here), set_here


def test_the_reference_names_every_field_that_is_sent():
    doc = REFERENCE.read_text()
    state, _ = tr.build_case("s", "h", "a")
    for key in state:
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
        ["bash", str(skill / "tightened-rules.sh"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0 and not (skill / "__pycache__").exists()


def test_the_flag_feeds_the_pass_end_to_end(repo, tmp_path_factory):
    out = tmp_path_factory.mktemp("o") / "c.jsonl"
    r = _prove(repo, "--candidates", str(out))
    assert r.returncode == 0, r.stderr
    r = subprocess.run(
        ["bash", str(WRAPPER), "--dry-run", str(out)],
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert r.returncode == 0, r.stderr
    asked = [json.loads(line)["state"]["sentence"] for line in r.stdout.splitlines()]
    assert asked == [
        "Be terse.",
        "Lead with the answer.",
        "Never push to main.",
        "Only rebase when the branch is yours, because others pull it.",
        "Old text that is tightened here.",
        "Some renamed heading body with distinctive words alpha beta gamma.",
    ]


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
        [py39, "-I", "-B", str(SCRIPTS / "_tightened_rules.py"), "--dry-run"]
        + [str(_input(tmp_path))],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert len(r.stdout.splitlines()) == 2
