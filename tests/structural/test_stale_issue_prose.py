"""#438 — stale-issue-prose.sh: find each issue reference's sentence again, and rank it.

`verify-facts.sh --issues` stops at the reference. This pass reads its TSV,
finds every occurrence of each reference in its file, and asks TypeSafe one
Noul per occurrence. What this file pins:

- **The grammar is the verifier's.** `_sentences.REF` finds exactly what the
  verifier's `grep -oE` finds, so the two can't disagree about a reference.
- **Code is counted, not judged.** A match inside a fence or a code span is
  reported as `code`.
- **A short cross-repo form is not judged against this repo.** `watcher#278`
  matches as bare `#278`, which the verifier resolves here.
- **Sentences come back whole:** soft wraps joined, abbreviations kept, a
  table row as its first cell plus the cell holding the reference.
- **The pass never changes a verdict,** and on a skip or a failure it still
  prints every row, unjudged, with its own documented exit code.
- **The measured shape is the shipped shape.** `--dry-run` emits cases that
  `typesafe-eval.py` loads once labelled.

No network: `gh` and the TypeSafe client are replaced by fakes.
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
WRAPPER = SCRIPTS / "stale-issue-prose.sh"
VERIFY = SCRIPTS / "verify-facts.sh"


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
sip = _load("_stale_issue_prose", SCRIPTS / "_stale_issue_prose.py")
ev = _load("typesafe_eval", REPO_ROOT / "scripts" / "typesafe-eval.py")
ts = sip._typesafe


def _occ(text: str):
    return [
        (o.ref, o.line, o.sentence, o.in_code, o.short_repo)
        for o in sent.occurrences(text)
    ]


# --- the splitter ------------------------------------------------------------


GRAMMAR_FIXTURE = """\
See #12 and owner/repo#3, also CannObserv/broker#93 and a.b/c.d/e#5.
Inline `#7` and a fence:
```bash
gh issue view #8
```
watcher#278 and skills#81; x/#9; https://github.com/o/r/issues/4#issuecomment-1
   - nested list item citing #10
| col | CannObserv/archiver#151 |
"""


@pytest.mark.skipif(not shutil.which("grep"), reason="no grep")
def test_the_grammar_finds_what_the_verifiers_grep_finds():
    """Same multiset of tokens: the verifier's `sort -u` keys rows on exactly these."""
    grep = subprocess.run(
        ["grep", "-oE", r"(\b[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#[0-9]+"],
        input=GRAMMAR_FIXTURE,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert sorted(o.ref for o in sent.occurrences(GRAMMAR_FIXTURE)) == sorted(grep)


def test_the_grammar_regex_is_spelled_like_the_verifiers():
    assert sent.REF.pattern in VERIFY.read_text().replace("'", " ")


def test_code_is_marked_not_dropped():
    found = {o.ref: o for o in sent.occurrences(GRAMMAR_FIXTURE)}
    assert found["#7"].in_code and found["#8"].in_code
    assert not found["#12"].in_code and found["#12"].sentence


@pytest.mark.parametrize(
    "fence",
    ["```", "~~~", "````", "  ```"],
    ids=["backticks", "tildes", "four", "indented"],
)
def test_every_fence_shape_is_code(fence):
    text = f"- item\n{fence}\nsee #1\n{fence}\nafter #2.\n"
    by = {o.ref: o.in_code for o in sent.occurrences(text)}
    assert by == {"#1": True, "#2": False}


def test_an_inline_triple_backtick_span_is_not_a_fence():
    """A backtick fence's info string can't hold a backtick, so the rest of the file stays prose (CR 421)."""
    text = "```json``` blocks are fine.\n\nBlocked on #4 until spring.\n"
    assert [(o.ref, o.in_code) for o in sent.occurrences(text)] == [("#4", False)]


def test_a_short_cross_repo_form_names_its_repo():
    found = {o.ref: o.short_repo for o in sent.occurrences(GRAMMAR_FIXTURE)}
    assert found["#278"] == "watcher" and found["#81"] == "skills"
    assert found["#12"] is None and found["owner/repo#3"] is None


@pytest.mark.parametrize(
    "text",
    [
        "Blocked on PR#12 still.",
        "See GH#12.",
        "Waiting on _#12_ to land.",
        "issue#12 open.",
    ],
)
def test_a_self_prefix_or_emphasis_is_not_a_cross_repo_ref(text):
    """`PR#12` is this repo's #12; judging it is right, dropping it as short-repo was not (CR 434)."""
    (o,) = sent.occurrences(text + "\n")
    assert o.ref == "#12" and o.short_repo is None


def test_a_soft_wrapped_sentence_comes_back_whole():
    text = "Intro sentence. The fix is\npending in #42 until\nthe release. Next one.\n"
    (o,) = sent.occurrences(text)
    assert o.sentence == "The fix is pending in #42 until the release."
    assert o.line == 2


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Use e.g. the cache (#5). Then go.", "Use e.g. the cache (#5)."),
        ("Done in v1.2 by J. Smith (#5). Next.", "Done in v1.2 by J. Smith (#5)."),
        ("First. `a. B` holds #5 here. Last.", "`a. B` holds #5 here."),
        ("Shipped. #5 is pending! Done.", "#5 is pending!"),
        ("The answer is no. Pending #5 still.", "Pending #5 still."),
    ],
    ids=["abbreviation", "initial", "code-span", "ref-starts-it", "no-ends-it"],
)
def test_sentence_boundaries(text, expected):
    (o,) = sent.occurrences(text)
    assert o.sentence == expected


def test_a_list_item_is_its_own_unit_and_a_heading_is_carried():
    text = "## Known issues\n\n- First item.\n- Blocked on #17\n  until spring.\n"
    (o,) = sent.occurrences(text)
    assert o.sentence == "Blocked on #17 until spring."
    assert o.heading == "Known issues" and o.line == 4


def test_blockquote_markers_stay_out_of_the_sentence():
    """Joined, `>` markers landed mid-sentence: "held until > broker#4 gives…" (CR 428)."""
    text = "> Held until\n> broker#4 gives it a backup.\n>\n> > - nested #5 item\n"
    got = [(o.ref, o.line, o.sentence) for o in sent.occurrences(text)]
    assert got == [
        ("#4", 2, "Held until broker#4 gives it a backup."),
        ("#5", 4, "nested #5 item"),
    ]


@pytest.mark.parametrize("underline", ["=====", "---"])
def test_a_setext_heading_is_a_heading(underline):
    """Its underline used to join the sentence, and the section stayed the old one (CR 435)."""
    text = f"# Old\n\nPending #12\n{underline}\n\nNext #13 here.\n"
    got = [(o.ref, o.sentence, o.heading) for o in sent.occurrences(text)]
    assert got == [
        ("#12", "Pending #12", None),
        ("#13", "Next #13 here.", "Pending #12"),
    ]


def test_a_table_row_gives_its_name_cell_and_the_refs_cell():
    text = "| `stream.x` | live | consumer pending (#9) |\n"
    (o,) = sent.occurrences(text)
    assert o.sentence == "`stream.x` | consumer pending (#9)"


def test_a_long_sentence_is_clipped_around_the_reference():
    text = "word " * 600 + "pending #3 " + "word " * 600 + "."
    (o,) = sent.occurrences(text)
    assert len(o.sentence) <= sent.MAX_CHARS + 2 and "#3" in o.sentence


# --- input -------------------------------------------------------------------


def test_only_issue_rows_are_read():
    rows = sip.read_tsv(
        [
            "TRUE\tpath\tAGENTS.md\tsrc/\texists\n",
            "TRUE\tissue\tAGENTS.md\t#1\tclosed — check\n",
        ]
    )
    assert rows == [("TRUE", "issue", "AGENTS.md", "#1", "closed — check")]


def test_a_six_column_row_of_another_class_is_passed_over():
    """verify-facts.sh splits a backticked path holding a tab into six fields (CR 422)."""
    rows = sip.read_tsv(
        [
            "UNVERIFIABLE\tpath\tTABDOC.md\tsrc/a\tb.py\tabsent here\n",
            "TRUE\tissue\tTABDOC.md\t#1\tclosed — check\n",
        ]
    )
    assert rows == [("TRUE", "issue", "TABDOC.md", "#1", "closed — check")]


@pytest.mark.parametrize(
    "line",
    [
        "not a row\n",
        "MAYBE\tissue\ta\t#1\tx\n",
        "TRUE\tissue\ta\t#1\n",
        "TRUE\tissue\ta\t#1\tx\ty\n",
        "TRUE\tpath\ta\n",
    ],
)
def test_a_line_that_isnt_the_verifiers_is_a_usage_error(line):
    with pytest.raises(sip.UsageError):
        sip.read_tsv([line])


def test_locate_reports_why_an_occurrence_isnt_judged(tmp_path):
    (tmp_path / "AGENTS.md").write_text(
        "Pending #1.\n\n`#1` in code.\n\nwatcher#278 is open.\n\nskills#5 is planned.\n"
    )
    rows = [
        ("TRUE", "issue", "AGENTS.md", "#1", "closed"),
        ("TRUE", "issue", "AGENTS.md", "#278", "closed"),
        ("TRUE", "issue", "AGENTS.md", "#5", "open"),
        ("TRUE", "issue", "AGENTS.md", "#99", "open"),
        ("UNVERIFIABLE", "issue", "AGENTS.md", "o/r#2", "gh could not resolve it"),
    ]
    got = [(r.ref, r.line, r.status) for r in sip.locate(rows, tmp_path, "me/skills")]
    assert got == [
        ("#1", 1, ""),
        ("#1", 3, "code"),
        ("#278", 5, "short-repo"),
        ("#5", 7, ""),  # skills#5 names this repo, so it's judged
        ("#99", None, "not-found"),
        ("o/r#2", None, "unverifiable"),
    ]


def test_the_policy_file_is_read_as_utf8_whatever_the_locale(tmp_path):
    """Under a Latin-1 locale, read_text() alone turned an em dash into mojibake (CR 423)."""
    (tmp_path / "a.md").write_text("Pending — still #1.\n", encoding="utf-8")
    code = (
        "import sys; sys.dont_write_bytecode = True; sys.path.insert(0, sys.argv[1]); "
        "import locale, pathlib, _stale_issue_prose as s; "
        "print(locale.getpreferredencoding(False)); "
        "(r,) = s.locate([('TRUE','issue','a.md','#1','closed')], pathlib.Path(sys.argv[2]), 'o/r'); "
        "print(ascii(r.sentence))"
    )
    env = {**os.environ, "LC_ALL": "en_US.ISO8859-1", "LANG": "en_US.ISO8859-1"}
    r = subprocess.run(
        [sys.executable, "-I", "-c", code, str(SCRIPTS), str(tmp_path)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    encoding, sentence = r.stdout.splitlines()
    if "8859" not in encoding:
        pytest.skip(f"no Latin-1 locale here ({encoding}), so the case can't arise")
    assert sentence == ascii("Pending — still #1.")


def test_a_bare_ref_with_no_repo_is_unresolved(tmp_path):
    (tmp_path / "a.md").write_text("Pending #1.\n")
    (row,) = sip.locate([("TRUE", "issue", "a.md", "#1", "closed")], tmp_path, None)
    assert row.status == "unresolved"


# --- issue metadata ----------------------------------------------------------


class Gh:
    """A fake `gh api graphql`: answers from a {number: item} table, None meaning NOT_FOUND."""

    def __init__(self, items, fail=False):
        self.items, self.fail, self.calls = items, fail, []

    def __call__(self, argv):
        self.calls.append(argv)
        if self.fail:
            return subprocess.CompletedProcess(
                argv, 1, "", "gh: HTTP 401: Bad credentials\n"
            )
        if argv[:3] == ["gh", "repo", "view"]:
            return subprocess.CompletedProcess(argv, 0, "me/skills\n", "")
        query = next(a for a in argv if a.startswith("query="))
        nums = [int(n) for n in re.findall(r"\bn(\d+):", query)]
        data = {f"n{n}": self.items.get(n) for n in nums}
        missing = [n for n in nums if self.items.get(n) is None]
        body = {"data": {"repository": data}}
        if missing:
            body["errors"] = [{"type": "NOT_FOUND"} for _ in missing]
        return subprocess.CompletedProcess(
            argv, 1 if missing else 0, json.dumps(body), ""
        )


CLOSED = {
    "__typename": "Issue",
    "title": "Fix it",
    "state": "CLOSED",
    "stateReason": "COMPLETED",
    "closedAt": "2026-10-01T00:00:00Z",
}
OPEN = {
    "__typename": "Issue",
    "title": "Do it",
    "state": "OPEN",
    "stateReason": None,
    "closedAt": None,
}
MERGED = {
    "__typename": "PullRequest",
    "title": "PR",
    "state": "MERGED",
    "closedAt": "2026-10-02T00:00:00Z",
    "mergedAt": "2026-10-02T00:00:00Z",
}


def test_a_not_found_alias_keeps_the_others_data():
    """gh exits 1 on a NOT_FOUND alias, with the rest of the data on stdout [measured]."""
    got = sip.fetch_meta("me/skills", [1, 2], Gh({1: CLOSED}))
    assert got == {1: CLOSED, 2: None}


def test_an_error_other_than_not_found_is_a_gh_failure():
    """An SSO refusal nulls the repository beside its data; it isn't 'unresolved' (CR 433)."""

    def run(argv):
        body = {
            "data": {"repository": None},
            "errors": [{"type": "FORBIDDEN", "message": "Resource protected by SAML"}],
        }
        return subprocess.CompletedProcess(argv, 1, json.dumps(body), "")

    with pytest.raises(sip.GhError) as e:
        sip.fetch_meta("me/skills", [1], run)
    assert "SAML" in str(e.value)


def test_no_data_at_all_is_a_gh_failure():
    with pytest.raises(sip.GhError) as e:
        sip.fetch_meta("me/skills", [1], Gh({}, fail=True))
    assert "Bad credentials" in str(e.value)


def test_references_are_batched():
    gh = Gh({n: OPEN for n in range(1, 121)})
    assert len(sip.fetch_meta("me/skills", range(1, 121), gh)) == 120
    assert len(gh.calls) == 3


def test_owner_and_name_are_variables_not_query_text():
    gh = Gh({1: OPEN})
    sip.fetch_meta('me/x"y', [1], gh)
    (argv,) = gh.calls
    assert 'name=x"y' in argv and 'x"y' not in next(
        a for a in argv if a.startswith("query=")
    )


def test_describe_reads_a_merged_pr_as_closed_on_its_merge_date():
    assert sip.describe(MERGED) == {
        "kind": "pull request",
        "title": "PR",
        "state": "merged",
        "closed_on": "2026-10-02",
    }
    assert sip.describe(OPEN) == {"kind": "issue", "title": "Do it", "state": "open"}


def test_the_help_names_every_field_that_is_sent():
    """The data-leaves-the-machine line must match build_case, field for field (CR 431)."""
    state, _ = sip.build_case("s", "H", "#1", sip.describe(CLOSED))
    assert set(state) == {"sentence", "reference", "issue", "section"}
    assert set(state["issue"]) == {"kind", "title", "state", "closed_as", "closed_on"}
    sending = " ".join(
        sip.__doc__.split("SENDING", 1)[1].split("exit codes")[0].split()
    )
    for words in (
        "sentence",
        "heading",
        "reference",
        "kind, title",
        "state",
        "close reason",
        "close date",
    ):
        assert words in sending, words


def test_the_question_follows_the_state():
    _, q = sip.build_case("s", None, "#1", sip.describe(CLOSED))
    assert list(q) == ["still_open"] and q["still_open"]["type"] == "noul"
    _, q = sip.build_case("s", "H", "#1", sip.describe(OPEN))
    assert list(q) == ["already_done"]


# --- the run -----------------------------------------------------------------


class FakeClient:
    def __init__(self, ps, fail_at=None):
        self.ps, self.fail_at, self.asked = list(ps), fail_at, []

    def ask(self, state, questions):
        self.asked.append(state)
        if self.fail_at is not None and len(self.asked) == self.fail_at:
            raise ts.TypeSafeError(500, "boom (gave up after 3 attempts)")
        (name,) = questions
        return {"answers": {name: {"type": "noul", "noul": self.ps.pop(0)}}}


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    for k in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(k)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "AGENTS.md").write_text(
        "Blocked on #1 until spring.\n\nShipped in #2.\n\n`#2` in code.\n\nDone in #3.\n"
    )
    tsv = tmp_path.parent / "facts.tsv"
    tsv.write_text(
        "TRUE\tpath\tAGENTS.md\tsrc/\texists\n"
        "TRUE\tissue\tAGENTS.md\t#1\tclosed — check\n"
        "TRUE\tissue\tAGENTS.md\t#2\tclosed — check\n"
        "TRUE\tissue\tAGENTS.md\t#3\topen\n"
    )
    return tsv


def _main(argv, connect, gh=None):
    out, err = io.StringIO(), io.StringIO()
    gh = gh or Gh({1: CLOSED, 2: CLOSED, 3: OPEN})
    code = sip.main(
        [str(a) for a in argv], stdout=out, stderr=err, run=gh, connect=connect
    )
    rows = [line.split("\t") for line in out.getvalue().splitlines()]
    return code, rows, err.getvalue()


def test_a_judged_run_ranks_flags_and_keeps_the_verdicts(checkout):
    client = FakeClient([0.9, 0.1, 0.3])
    code, rows, err = _main([checkout, "--repo", "me/skills"], lambda **kw: client)
    assert code == 0
    assert [(r[3], r[5], r[9], r[10], r[11]) for r in rows] == [
        ("#1", "1", "0.900", "stale?", "judged"),
        ("#3", "7", "0.300", "stale?", "judged"),
        ("#2", "3", "0.100", "", "judged"),
        ("#2", "5", "", "", "code"),
    ]
    assert all(r[:2] == ["TRUE", "issue"] and len(r) == 13 for r in rows)
    assert rows[1][8] == "already_done" and rows[0][8] == "still_open"
    assert "4 occurrences of 3 references: 3 judged (2 at or over 0.2), 1 code" in err
    assert (checkout.parent / checkout.name).read_text().count(
        "\n"
    ) == 4  # input untouched


def test_the_clients_lines_go_to_the_runs_own_stderr(checkout):
    seen = {}

    def connect(**kw):
        seen.update(kw)
        return FakeClient([0.5, 0.5, 0.5])

    code, _, _ = _main([checkout, "--repo", "me/skills"], connect)
    assert code == 0 and isinstance(seen.get("stderr"), io.StringIO)


def test_the_threshold_moves_the_flag_only(checkout):
    code, rows, _ = _main(
        [checkout, "--repo", "me/skills", "--threshold", "0.95"],
        lambda **kw: FakeClient([0.9, 0.1, 0.3]),
    )
    assert code == 0 and [r[10] for r in rows] == ["", "", "", ""]
    assert [r[9] for r in rows][:3] == ["0.900", "0.300", "0.100"]


@pytest.mark.parametrize("reason", ["not-opted-in", "no-key"])
def test_a_skip_is_exit_4_and_still_prints_every_row(checkout, reason):
    def connect(**kw):
        raise ts.Skipped(reason, "test")

    gh = Gh({})
    code, rows, err = _main([checkout, "--repo", "me/skills"], connect, gh)
    assert code == 4 and f"typesafe: skipped ({reason})" in err
    assert [r[11] for r in rows] == ["skipped", "skipped", "code", "skipped"]
    assert not gh.calls, "a skipped run has no reason to ask gh anything"


def test_a_skip_without_repo_asks_gh_nothing(checkout):
    """Connect comes first, so a skipped run never reaches `gh repo view` (CR 424)."""

    def connect(**kw):
        raise ts.Skipped("not-opted-in", "test")

    gh = Gh({})
    code, rows, _ = _main([checkout], connect, gh)
    assert code == 4 and not gh.calls
    assert [r[11] for r in rows] == ["skipped", "skipped", "code", "skipped"]


def test_a_tsv_without_issue_rows_says_how_to_get_them(checkout):
    checkout.write_text("TRUE\tpath\tAGENTS.md\tsrc/\texists\n")
    code, rows, err = _main(
        [checkout, "--repo", "me/skills"], lambda **kw: FakeClient([])
    )
    assert code == 0 and rows == [] and "--issues" in err


def test_a_failure_is_exit_2_and_the_rest_are_not_asked(checkout):
    client = FakeClient([0.9, 0.1, 0.3], fail_at=2)
    code, rows, err = _main([checkout, "--repo", "me/skills"], lambda **kw: client)
    assert code == 2 and "boom" in err and len(client.asked) == 2
    assert sorted(r[11] for r in rows) == ["code", "failed", "judged", "not-asked"]


def test_a_gh_failure_is_exit_2_and_the_rows_are_unresolved(checkout):
    code, rows, err = _main(
        [checkout, "--repo", "me/skills"],
        lambda **kw: FakeClient([]),
        Gh({}, fail=True),
    )
    assert code == 2 and "Bad credentials" in err
    assert sorted(r[11] for r in rows) == [
        "code",
        "unresolved",
        "unresolved",
        "unresolved",
    ]


def test_an_answer_without_a_probability_is_a_failure(checkout):
    class Bad(FakeClient):
        def ask(self, state, questions):
            return {"answers": {next(iter(questions)): {"type": "noul"}}}

    code, rows, err = _main([checkout, "--repo", "me/skills"], lambda **kw: Bad([]))
    assert code == 2 and "no noul probability" in err


def test_without_repo_it_asks_gh_like_the_verifier(checkout):
    gh = Gh({1: CLOSED, 2: CLOSED, 3: OPEN})
    code, _, _ = _main([checkout], lambda **kw: FakeClient([0.5, 0.5, 0.5]), gh)
    assert code == 0 and gh.calls[0][:3] == ["gh", "repo", "view"]


def test_gh_unable_to_infer_the_repo_is_exit_2(checkout):
    """Every bare ref goes unjudged; exit 0 would call that a complete ranking (CR 432)."""

    class NoRepo(Gh):
        def __call__(self, argv):
            if argv[:3] == ["gh", "repo", "view"]:
                self.calls.append(argv)
                return subprocess.CompletedProcess(
                    argv, 1, "", "no git remotes found\n"
                )
            return super().__call__(argv)

    code, rows, err = _main([checkout], lambda **kw: FakeClient([]), NoRepo({}))
    assert code == 2 and "gh can't infer one" in err
    assert sorted(r[11] for r in rows) == [
        "code",
        "unresolved",
        "unresolved",
        "unresolved",
    ]


def test_dry_run_sends_nothing_and_emits_cases_the_evaluator_loads(checkout):
    def connect(**kw):
        raise AssertionError("--dry-run must not connect")

    out, err = io.StringIO(), io.StringIO()
    code = sip.main(
        [str(checkout), "--repo", "me/skills", "--dry-run"],
        stdout=out,
        stderr=err,
        run=Gh({1: CLOSED, 2: CLOSED, 3: OPEN}),
        connect=connect,
    )
    assert code == 0
    cases = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [c["id"] for c in cases] == [
        "AGENTS.md:1:#1",
        "AGENTS.md:3:#2",
        "AGENTS.md:7:#3",
    ]
    labelled = [
        json.dumps({**c, "expected": {next(iter(c["questions"])): True}}) for c in cases
    ]
    assert len(ev.load_set(labelled)) == 3


@pytest.mark.parametrize(
    "argv,needle",
    [
        (["--threshold", "2"], "probability 0-1"),
        (["--repo", "nope"], "owner/repo"),
        (["--bogus"], "unknown option"),
        (["a", "b"], "one TSV only"),
        (["/no/such/file"], "can't read"),
    ],
)
def test_usage_errors_are_exit_1(argv, needle, checkout):
    code, rows, err = _main(argv, lambda **kw: FakeClient([]))
    assert code == 1 and needle in err and rows == []


def test_help_documents_columns_statuses_exits_and_the_threshold():
    r = subprocess.run(["bash", str(WRAPPER), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for needle in (
        "still_open",
        "already_done",
        "short-repo",
        "not-asked",
        "exit codes",
        f"default {sip.DEFAULT_THRESHOLD:g}",
        "never changes a verdict",
    ):
        assert needle in r.stdout, needle


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
        ["bash", str(skill / "stale-issue-prose.sh"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0 and not (skill / "__pycache__").exists()


_PY39_MISSING = (
    "python3.9 is not on PATH, so the pass was NOT run on the client's 3.9 floor. "
    "Install it to get that coverage; set PY39_REQUIRED=1 to make its absence a "
    "failure instead of a skip."
)


def test_the_pass_runs_on_python39(tmp_path):
    """The client's floor (#448). A source check can't see a 3.10+ construct; a run can (CR 427)."""
    py39 = shutil.which("python3.9")
    if not py39:
        if os.environ.get("PY39_REQUIRED", "") not in ("", "0"):
            pytest.fail(_PY39_MISSING)
        pytest.skip(_PY39_MISSING)
    (tmp_path / "a.md").write_text("## Known\n\n- Blocked on #1\n  until spring.\n")
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import pathlib, _stale_issue_prose as s; "
        "(r,) = s.locate([('TRUE','issue','a.md','#1','closed')], pathlib.Path(sys.argv[2]), 'o/r'); "
        "print(r.sentence, '|', r.heading)"
    )
    r = subprocess.run(
        [py39, "-I", "-B", "-c", code, str(SCRIPTS), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "Blocked on #1 until spring. | Known"
    h = subprocess.run(
        [py39, "-I", "-B", str(SCRIPTS / "_stale_issue_prose.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert h.returncode == 0 and "exit codes" in h.stdout, h.stderr
