"""#436 — harvest-candidates.sh: rank which paragraphs of a closed child bear on which open child.

The step reads the source child's thread since its hand-off, settles every
pair whose paragraph names the child, and asks TypeSafe one question about
each other pair. What this file pins:

- **What "named" means.** A `For #N` heading, bold lead or list item scopes
  the paragraphs under it; a linked `#N` names its own paragraph. A ref only
  in code names nothing, as GitHub renders it.
- **Which comments are read.** Those after the last hand-off brief (or
  `--since`), before `--until`, and never a "Changed since filed" comment:
  that is the coordinator's own harvest into the thread.
- **The run's contract.** Named rows first, then judged rows likeliest first;
  a skip or a failure still prints every row with its documented exit code;
  `--max-calls` refuses before anything is sent; `--dry-run` emits cases the
  evaluator loads. Nothing is written to GitHub.

No network: the TypeSafe client and the loader are replaced by fakes.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "skills" / "coordinating-epics" / "scripts"
WRAPPER = SCRIPTS / "harvest-candidates.sh"
CHECK_IN = REPO_ROOT / "skills" / "coordinating-epics" / "references" / "check-in.md"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # a dataclass looks its module up while it's built
    spec.loader.exec_module(mod)
    return mod


# Importing from skills/*/scripts would leave a __pycache__/ there, which the
# suite's vendoring fixtures then copy as if it were a script.
sys.dont_write_bytecode = True
sys.path.insert(0, str(SCRIPTS))
hv = _load("_harvest", SCRIPTS / "_harvest.py")
ts = hv._typesafe
ev = _load("typesafe_eval", REPO_ROOT / "scripts" / "typesafe-eval.py")

HOST = "o/r"


def _names(*texts: str) -> list[set[str]]:
    return hv.scope_names(list(texts), HOST)


def _k(n: int, repo: str = HOST) -> str:
    return f"{repo}#{n}"


# --- what a paragraph names -------------------------------------------------


def test_a_for_heading_scopes_everything_to_the_next_heading():
    got = _names("### For #3", "A plain line.", "- an item", "### Other", "After.")
    assert got == [{_k(3)}, {_k(3)}, {_k(3)}, set(), set()]


def test_a_bold_lead_scopes_its_list_and_ends_at_the_next_plain_paragraph():
    got = _names("**For #3, #4 and #5:**", "- one", "  - nested", "Plain again.")
    want = {_k(3), _k(4), _k(5)}
    assert got == [want, want, want, set()]


def test_an_item_scopes_only_the_items_indented_under_it():
    got = _names("- **For #3:** the gist", "  - a detail", "- a sibling")
    assert got == [{_k(3)}, {_k(3)}, set()]


def test_a_cross_repo_for_names_that_repo():
    assert _names("**For x/y#9:** see this") == [{"x/y#9"}]


def test_for_in_running_prose_scopes_nothing():
    # Only a heading, a bold lead or an item opens a scope; prose saying
    # "useful for #3" doesn't route the paragraphs after it.
    assert _names("This is useful for #3 later.", "Next.") == [set(), set()]


def test_a_linked_ref_names_its_paragraph_and_one_in_code_does_not():
    c = {"id": 1, "html_url": "u", "body": "Touches #4.\n\nQuotes `#5` only."}
    paras = hv.comment_paras(c, HOST)
    assert [p.named for p in paras] == [{_k(4)}, set()]


def test_a_paragraph_keeps_its_index_in_the_comment():
    c = {"id": 1, "html_url": "u", "body": "One.\n\n-\n\nThree."}
    assert [(p.k, p.text) for p in hv.comment_paras(c, HOST)] == [
        (0, "One."),
        (2, "Three."),
    ]


# --- which comments are read ------------------------------------------------


def _c(i: int, body: str, at: str) -> dict:
    return {"id": i, "html_url": f"u{i}", "body": body, "created_at": at}


THREAD = [
    _c(1, "Early chatter.", "2026-10-01T00:00:00Z"),
    _c(2, "## Coordinator brief: #7\n\nDo it.", "2026-10-02T00:00:00Z"),
    _c(3, "## Shipped\n\nDone.", "2026-10-03T00:00:00Z"),
    _c(4, "**Changed since filed:** from #6.", "2026-10-04T00:00:00Z"),
    _c(5, "Late note.", "2026-10-05T00:00:00Z"),
]


def test_the_thread_starts_after_the_last_brief_and_skips_harvests():
    assert [c["id"] for c in hv.select(THREAD, None, None)] == [3, 5]


def test_since_and_until_bound_the_thread_and_since_replaces_the_brief():
    got = hv.select(THREAD, "2026-10-01T12:00:00Z", "2026-10-05T00:00:00Z")
    assert [c["id"] for c in got] == [2, 3]


@pytest.mark.parametrize(
    "first",
    [
        "## Coordinator brief: #7",
        "## Brief (coordinator, epic #1, 2026-10-16)",
        "## Hand-off brief: #7 (coordinator)",
        "**Coordinator brief.** Do it.",
    ],
)
def test_each_brief_heading_the_cohort_uses_is_a_brief(first):
    assert hv.BRIEF_RE.match(first)


def test_a_comment_mentioning_a_brief_is_not_one():
    assert not hv.BRIEF_RE.match("The brief said to do it.")


# --- the run ------------------------------------------------------------------


def _child(n: int, title: str = "t", body: str = "b") -> object:
    return hv.Child(key=_k(n), label=f"#{n}", number=n, title=title, body=body)


CHILDREN = [_child(3), _child(4)]
COMMENTS = [
    {"id": 10, "html_url": "U10", "body": "**For #3:** use the new lock.\n\nA limit."}
]


def _load_fake(opts):
    return CHILDREN, COMMENTS


class FakeClient:
    def __init__(self, answers, fail_at=None):
        self.answers, self.fail_at, self.asked = answers, fail_at, []

    def ask(self, state, questions):
        self.asked.append((state, list(questions)))
        if self.fail_at is not None and len(self.asked) == self.fail_at:
            raise ts.TypeSafeError(500, "boom (gave up after 3 attempts)")
        p = self.answers[(state["paragraph"], state["child"]["number"])]
        return {"answers": {"bears_on": {"type": "noul", "noul": p}}}


ANSWERS = {
    ("**For #3:** use the new lock.", 4): 0.2,
    ("A limit.", 3): 0.4,
    ("A limit.", 4): 0.9,
}
ARGS = ["--repo", HOST, "--epic", "1", "--source", "2"]


def _main(argv, connect=None, load=_load_fake):
    out, err = io.StringIO(), io.StringIO()
    code = hv.main(argv, stdout=out, stderr=err, connect=connect, load=load)
    rows = [line.split("\t") for line in out.getvalue().splitlines()]
    return code, rows, err.getvalue()


def test_named_rows_come_first_then_judged_rows_likeliest_first():
    client = FakeClient(ANSWERS)
    code, rows, err = _main(ARGS, lambda **kw: client)
    assert code == 0
    assert [r[:3] for r in rows] == [
        ["named", "", "#3"],
        ["judged", "0.900", "#4"],
        ["judged", "0.400", "#3"],
        ["judged", "0.200", "#4"],
    ]
    assert rows[0][3] == "U10"
    assert [q for _, q in client.asked] == [["bears_on"]] * 3
    assert "2 paragraph(s) x 2 open child(ren) = 4 row(s)" in err


def test_a_request_carries_the_paragraph_the_source_and_one_child():
    client = FakeClient(ANSWERS)
    _main(ARGS, lambda **kw: client)
    state, _ = client.asked[0]
    assert set(state) == {"paragraph", "from", "child"}
    assert state["from"] == f"a comment on {HOST}#2, a closed child of the epic"
    assert state["child"] == {"number": 4, "title": "t", "body": "b"}


def test_a_long_body_is_clipped_to_fit_one_question():
    body = "word " * hv.MAX_BODY_CHARS
    state, questions = hv.build_case(
        "p", HOST, 2, {"number": 3, "title": "t", "body": body}
    )
    assert len(state["child"]["body"]) == hv.MAX_BODY_CHARS
    ts._check_size(state, questions)  # raises RequestTooLarge past 32k tokens


@pytest.mark.parametrize("reason", ["not-opted-in", "no-key"])
def test_a_skip_is_exit_4_and_still_prints_every_row(reason):
    def connect(**kw):
        raise ts.Skipped(reason, "test")

    code, rows, err = _main(ARGS, connect)
    assert code == 4
    assert [r[0] for r in rows] == ["named", "skipped", "skipped", "skipped"]
    assert f"skipped ({reason})" in err


def test_a_failure_is_exit_2_and_the_rest_are_not_asked():
    client = FakeClient(ANSWERS, fail_at=1)
    code, rows, err = _main(ARGS, lambda **kw: client)
    assert code == 2 and "boom" in err
    assert sorted(r[0] for r in rows) == ["failed", "named", "not-asked", "not-asked"]


@pytest.mark.parametrize("bad", [None, 1.5, True, "0.4"])
def test_an_answer_that_isnt_a_probability_is_a_failure(bad):
    class Bad:
        def ask(self, state, questions):
            return {"answers": {"bears_on": {"type": "noul", "noul": bad}}}

    code, _, err = _main(ARGS, lambda **kw: Bad())
    assert code == 2 and "has no noul probability" in err


def test_over_max_calls_is_refused_before_anything_is_asked():
    client = FakeClient(ANSWERS)
    code, rows, err = _main(ARGS + ["--max-calls", "2"], lambda **kw: client)
    assert code == 1 and rows == [] and client.asked == []
    assert "needs 3 calls, over --max-calls 2; nothing was sent" in err


def test_a_repo_not_opted_in_skips_whatever_the_cap():
    def connect(**kw):
        raise ts.Skipped("not-opted-in", "test")

    code, rows, err = _main(ARGS + ["--max-calls", "2"], connect)
    assert code == 4 and "max-calls" not in err
    assert [r[0] for r in rows] == ["named", "skipped", "skipped", "skipped"]


def test_all_named_needs_no_client():
    def connect(**kw):
        raise AssertionError("connected")

    one = [{"id": 1, "html_url": "U", "body": "**For #3 and #4:** both."}]
    code, rows, _ = _main(ARGS, connect, load=lambda o: (CHILDREN, one))
    assert code == 0 and [r[0] for r in rows] == ["named", "named"]


def test_dry_run_emits_cases_the_evaluator_loads():
    def connect(**kw):
        raise AssertionError("connected")

    out, err = io.StringIO(), io.StringIO()
    code = hv.main(
        ARGS + ["--dry-run"], stdout=out, stderr=err, connect=connect, load=_load_fake
    )
    assert code == 0
    lines = out.getvalue().splitlines()
    assert [json.loads(x)["id"] for x in lines] == ["10:p0:#4", "10:p1:#3", "10:p1:#4"]
    labelled = [
        json.dumps({**json.loads(x), "expected": {"bears_on": False}}) for x in lines
    ]
    assert len(ev.load_set(labelled)) == 3


def test_the_client_prints_its_first_call_line_and_a_count_of_the_rest():
    class Talky(FakeClient):
        def __init__(self, stderr):
            super().__init__(ANSWERS)
            self.stderr = stderr

        def ask(self, state, questions):
            print(
                "typesafe: answered by jev-1.13.0 (asked for jev-1.13.0)",
                file=self.stderr,
            )
            return super().ask(state, questions)

    code, _, err = _main(ARGS, lambda **kw: Talky(kw["stderr"]))
    assert code == 0
    assert err.count("answered by") == 1
    assert "and 2 more answered-by line(s)" in err
    # print() writes the newline separately; a dropped line leaves no blank one.
    assert "\n\n" not in err


def test_a_gh_failure_is_exit_2_with_ghs_cause():
    def load(opts):
        raise hv.Infra("x", stderr="HTTP 404: Not Found", code=1)

    code, rows, err = _main(ARGS, load=load)
    assert code == 2 and rows == [] and "HTTP 404: Not Found" in err


@pytest.mark.parametrize(
    "argv,msg",
    [
        ([], "--repo is required"),
        (["--repo", "o/r", "--epic", "1"], "--source is required"),
        (ARGS + ["--max-calls", "0"], "positive integer"),
        (ARGS + ["--since", "2026-10-01T00:00"], "ISO 8601 time with a zone"),
        (["--repo", "nope"], "OWNER/REPO"),
        (ARGS + ["--threshold", "0.5"], "unknown argument"),
    ],
)
def test_a_usage_error_is_exit_1(argv, msg):
    code, rows, err = _main(argv)
    assert code == 1 and rows == [] and msg in err


# --- the loader against a fake gh ---------------------------------------------


def test_open_children_are_the_open_checklist_items_less_the_source(monkeypatch):
    issues = {
        "repos/o/r/issues/1": {
            "body": "- [x] #2 the source\n- [ ] #3 open\n- [ ] #4 closed\n"
            "- [ ] x/y#5 elsewhere\n- #6 not a checklist line\n- [ ] #3 again"
        },
        "repos/o/r/issues/3": {"state": "open", "title": "three", "body": "B3"},
        "repos/o/r/issues/4": {"state": "closed", "title": "four", "body": ""},
        "repos/x/y/issues/5": {"state": "open", "title": "five", "body": None},
    }
    monkeypatch.setattr(hv, "gh_json", lambda args, what: issues[args[1]])
    got = hv.open_children("o/r", 1, 2)
    assert [(c.label, c.title, c.body) for c in got] == [
        ("#3", "three", "B3"),
        ("x/y#5", "five", ""),
    ]


def test_the_step_never_writes_to_github():
    src = (SCRIPTS / "_harvest.py").read_text()
    for verb in ("PATCH", "POST", "PUT", "DELETE", "--method", "-X", "--input"):
        assert f'"{verb}"' not in src, verb
    assert not re.search(r"\bissue\s+comment\b|\bgh\s+issue\b", src)


# --- the wrapper and the docs -------------------------------------------------


def test_the_wrapper_prints_help_and_exits_0():
    r = subprocess.run(["bash", str(WRAPPER), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.startswith("harvest-candidates.sh")


def test_the_wrapper_writes_no_bytecode_beside_itself(tmp_path):
    # A copy, so bytecode another test's import left in SCRIPTS can't count.
    copy = tmp_path / "scripts"
    shutil.copytree(SCRIPTS, copy, ignore=shutil.ignore_patterns("__pycache__"))
    r = subprocess.run(
        ["bash", str(copy / WRAPPER.name), "--help"], capture_output=True, text=True
    )
    assert r.returncode == 0
    assert not (copy / "__pycache__").exists()


def test_check_in_runs_it_where_it_harvests():
    text = CHECK_IN.read_text()
    harvest = text[text.index("## 2. Harvest") : text.index("## 3.")]
    assert "<harvest-candidates.sh>" in harvest
