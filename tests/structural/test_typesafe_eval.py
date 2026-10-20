"""#449 — the TypeSafe evaluator, `scripts/typesafe-eval.py`, run on a fake transport.

The evaluator splits like `tests/utils/selection_probe.py`: everything but the
one call that reaches the network is pure, and it's all exercised here, every
commit, for free. The transport is a fake that answers from a table keyed on
each case's state, so the API is never called. The cached-responses file the
first run writes is replayed by a second run whose transport fails the test if
it's touched.

Every set and cache lives under `tmp_path`, which is outside any git work tree,
so the private-set guard passes them without `--public`. The guard itself is
tested against a throwaway repo created with GIT_DIR scrubbed (#189).

No API calls.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "typesafe-eval.py"

spec = importlib.util.spec_from_file_location("typesafe_eval", SCRIPT)
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)
ts = ev._typesafe
PIN = ts.MODEL

ON = {"TYPESAFE_OPT_IN": "on", "TYPESAFE_API_KEY": "sk-test-key"}
TONE = {"angry": "hostile", "calm": "neutral", "excited": "eager"}
URGENCY = ["can wait", "this week", "today"]


def _row(rid, state, tone=None, urgency=None, billing=None, **extra):
    questions, expected = {}, {}
    if tone is not None:
        questions["tone"] = {
            "type": "choice",
            "instructions": "Tone?",
            "criteria": TONE,
        }
        expected["tone"] = tone
    if urgency is not None:
        questions["urgency"] = {"type": "score", "criteria": URGENCY}
        expected["urgency"] = urgency
    if billing is not None:
        questions["billing"] = {"type": "noul", "instructions": "Billing?"}
        expected["billing"] = billing
    return {
        "id": rid,
        "state": state,
        "questions": questions,
        "expected": expected,
        **extra,
    }


ROWS = [
    _row("a", "I want my money back NOW", tone="angry", urgency=2, billing=True),
    _row("b", "thanks, all good", tone="calm", urgency=0, billing=False),
    _row(
        "c", "wow, can't wait for the launch", tone="excited", urgency=0, billing=False
    ),
    _row("d", "my invoice looks off", tone="calm", urgency=1, billing=True),
]

# What the fake model says for each state. "d" is wrong on tone (says angry)
# and its urgency of 1.5 rounds up to 2, which is wrong too.
ANSWERS = {
    "I want my money back NOW": {
        "tone": {"choice": "angry", "confidence": 0.95},
        "urgency": {"score": 1.8, "confidence": 0.7},
        "billing": {"noul": 0.92},
    },
    "thanks, all good": {
        "tone": {"choice": "calm", "confidence": 0.85},
        "urgency": {"score": 0.1, "confidence": 0.9},
        "billing": {"noul": 0.05},
    },
    "wow, can't wait for the launch": {
        "tone": {"choice": "excited", "confidence": 0.55},
        "urgency": {"score": 0.4, "confidence": 0.6},
        "billing": {"noul": 0.35},
    },
    "my invoice looks off": {
        "tone": {"choice": "angry", "confidence": 0.42},
        "urgency": {"score": 1.5, "confidence": 0.3},
        "billing": {"noul": 0.65},
    },
}


class FakeTransport:
    """Answers from ANSWERS; records every request. `models` maps a state to the model that answers it."""

    def __init__(self, models=None, fail_on=None, status=200):
        self.calls = []
        self.models = models or {}
        self.fail_on = fail_on
        self.status = status

    def __call__(self, url, data, headers, timeout):
        req = json.loads(data)
        self.calls.append(req)
        if req["state"] == self.fail_on:
            return (
                401,
                {},
                json.dumps({"detail": {"error_type": "authentication_error"}}).encode(),
            )
        answers = {
            name: {"type": q["type"], **ANSWERS[req["state"]][name]}
            for name, q in req["questions"].items()
        }
        body = {
            "model": self.models.get(req["state"], req["model"]),
            "answers": answers,
            "usage": {"input_tokens": 300, "output_tokens": 10},
        }
        return 200, {}, json.dumps(body).encode()


def _forbidden(*_):
    raise AssertionError("the API was called on a run that should only replay")


def _write(path: Path, rows) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def _run(argv, environ=None, transport=None, cwd=None):
    out, err = io.StringIO(), io.StringIO()
    code = ev.main(
        [str(a) for a in argv],
        environ=ON if environ is None else environ,
        transport=transport or _forbidden,
        cwd=str(cwd) if cwd else None,
        stdout=out,
        stderr=err,
    )
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def dataset(tmp_path):
    return _write(tmp_path / "set.jsonl", ROWS)


# --- help --------------------------------------------------------------------


def test_help_documents_the_schema_and_exit_codes():
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    for needle in (
        "id ",
        "state ",
        "questions ",
        "expected ",
        "source ",
        "true or false",
        "--cache",
        "--offline",
        "--public",
        "TYPESAFE_OPT_IN",
        "exit codes:",
        '"valid": false',
        "tokens.missing",
    ):
        assert needle in out.stdout, needle


def test_a_bad_flag_is_exit_1_not_2():
    """argparse exits 2 by default, which here would read as a TypeSafe failure."""
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "--nope"], capture_output=True, text=True
    )
    assert out.returncode == 1


# --- the set -----------------------------------------------------------------


@pytest.mark.parametrize(
    "row, why",
    [
        ({**ROWS[0], "expect": {}}, "unknown key"),
        ({k: v for k, v in ROWS[0].items() if k != "state"}, "state is missing"),
        ({**ROWS[0], "id": ""}, "id must be"),
        ({**ROWS[0], "expected": {"tone": "angry"}}, "label every question"),
        (_row("x", "s", tone="furious"), "not one of"),
        (_row("x", "s", urgency=3), "not a level 0-2"),
        (_row("x", "s", urgency=True), "not a level"),
        (_row("x", "s", billing="yes"), "true or false"),
        (
            {
                "id": "x",
                "state": "s",
                "questions": {"b": {"type": "box"}},
                "expected": {"b": 1},
            },
            "only choice, score, noul",
        ),
        ({**ROWS[0], "source": 3}, "source must be a string"),
    ],
)
def test_a_malformed_case_is_exit_1_and_nothing_is_sent(tmp_path, row, why):
    t = FakeTransport()
    code, _, err = _run([_write(tmp_path / "s.jsonl", [row])], transport=t)
    assert code == 1 and why in err and t.calls == []


def test_a_repeated_id_and_a_type_change_are_both_reported(tmp_path):
    rows = [
        _row("a", "s1", billing=True),
        _row("a", "s2", billing=False),
        {
            **_row("b", "s3", tone="calm"),
            "questions": {"billing": {"type": "choice", "criteria": TONE}},
            "expected": {"billing": "calm"},
        },
    ]
    code, _, err = _run([_write(tmp_path / "s.jsonl", rows)])
    assert code == 1
    assert "id repeats" in err and "was noul on an earlier case" in err


def test_nan_in_a_set_is_refused_before_sending(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(
        '{"id": "a", "state": NaN, "questions": {"b": {"type": "noul"}}, "expected": {"b": true}}\n'
    )
    code, _, err = _run([path])
    assert code == 1 and "NaN" in err


# --- a live run, then its replay ----------------------------------------------


def test_a_run_scores_every_type_and_its_cache_replays(tmp_path, dataset):
    cache = tmp_path / "cache.jsonl"
    t = FakeTransport()
    code, out, err = _run([dataset, "--cache", cache], transport=t)
    assert code == 0, err
    assert len(t.calls) == 4 and all(c["model"] == PIN for c in t.calls)
    report = json.loads(out)
    assert report["valid"] and report["models_answered"] == [PIN]
    assert report["calls"] == {"live": 4, "replayed": 0}
    assert report["tokens"]["input"] == 1200 and report["tokens"]["live_input"] == 1200

    tone = report["questions"]["tone"]
    assert (tone["type"], tone["n"], tone["correct"]) == ("choice", 4, 3)
    assert tone["agreement"] == 0.75
    labels = tone["confusion"]["labels"]
    assert labels == ["angry", "calm", "excited"]
    calm_row = tone["confusion"]["matrix"][labels.index("calm")]
    assert calm_row == [1, 1, 0]  # one calm case called angry
    band4 = tone["by_confidence"][4]  # 0.4-0.5 holds the 0.42 miss
    assert (band4["n"], band4["correct"], band4["accuracy"]) == (1, 0, 0.0)
    assert tone["by_confidence"][0]["accuracy"] is None  # empty band: n/a, not 0

    urgency = report["questions"]["urgency"]
    assert urgency["confusion"]["labels"] == [0, 1, 2]
    assert urgency["correct"] == 3  # 1.5 rounds half up to 2; expected 1
    assert urgency["mean_abs_error"] == pytest.approx((0.2 + 0.1 + 0.4 + 0.5) / 4)

    billing = report["questions"]["billing"]
    assert (billing["positives"], billing["negatives"]) == (2, 2)
    at = {s["threshold"]: s for s in billing["sweep"]}
    assert (at[0.5]["precision"], at[0.5]["recall"]) == (1.0, 1.0)
    assert (at[0.3]["fp"], at[0.3]["precision"]) == (1, pytest.approx(2 / 3))
    assert (at[0.9]["recall"], at[0.9]["precision"]) == (0.5, 1.0)
    assert billing["brier"] == pytest.approx(
        (0.08**2 + 0.05**2 + 0.35**2 + 0.35**2) / 4
    )
    cal = billing["calibration"]
    assert (cal[6]["n"], cal[6]["observed_yes"]) == (1, 1.0)  # 0.65 in 0.6-0.7
    assert "money back" not in out  # aggregates only

    cached = [json.loads(line) for line in cache.read_text().splitlines()]
    assert [c["id"] for c in cached] == ["a", "b", "c", "d"]
    assert "money back" not in cache.read_text()  # the cache holds no state

    code2, out2, _ = _run([dataset, "--cache", cache, "--offline"], environ={})
    report2 = json.loads(out2)
    assert code2 == 0 and report2["calls"] == {"live": 0, "replayed": 4}
    assert report2["tokens"]["input"] == 1200 and report2["tokens"]["live_input"] == 0
    assert report2["questions"] == report["questions"]


def test_a_full_replay_needs_no_opt_in_and_no_offline_flag(tmp_path, dataset):
    cache = tmp_path / "cache.jsonl"
    assert _run([dataset, "--cache", cache], transport=FakeTransport())[0] == 0
    code, _, err = _run([dataset, "--cache", cache], environ={}, cwd=tmp_path)
    assert code == 0, err


def test_an_edited_case_or_another_model_misses_the_cache(tmp_path, dataset):
    cache = tmp_path / "cache.jsonl"
    _run([dataset, "--cache", cache], transport=FakeTransport())
    code, _, err = _run(
        [dataset, "--cache", cache, "--offline", "--model", "jev-latest"]
    )
    assert code == 1 and "4 case(s) aren't in the cache" in err
    edited = [
        {
            **ROWS[0],
            "questions": {
                **ROWS[0]["questions"],
                "tone": {**ROWS[0]["questions"]["tone"], "instructions": "Mood?"},
            },
        }
    ]
    code, _, err = _run(
        [_write(tmp_path / "e.jsonl", edited), "--cache", cache, "--offline"]
    )
    assert code == 1 and ": a" in err


def test_a_malformed_cache_line_is_exit_1(tmp_path, dataset):
    cache = tmp_path / "cache.jsonl"
    cache.write_text('{"key": "k"}\n')
    code, _, err = _run([dataset, "--cache", cache])
    assert code == 1 and "cache line 1" in err


@pytest.mark.parametrize(
    "line",
    [
        '{"key": "k"}',
        '{"key": "k", "reply": {"model": "m"}}',
        '{"key": "k", "reply": {"answers": []}}',
    ],
)
def test_a_cached_reply_without_answers_is_exit_1_not_a_crash(tmp_path, dataset, line):
    """CR 406: a cached reply skips the client's checks, so the cache reader makes them."""
    cache = tmp_path / "cache.jsonl"
    cache.write_text(line + "\n")
    code, _, err = _run([dataset, "--cache", cache, "--offline"])
    assert code == 1 and "cache line 1" in err


def test_a_cached_reply_missing_one_answer_is_exit_2_not_a_crash(tmp_path):
    rows = [_row("a", "thanks, all good", billing=False)]
    path = _write(tmp_path / "s.jsonl", rows)
    key = ev.request_key(PIN, rows[0]["state"], rows[0]["questions"])
    cache = tmp_path / "cache.jsonl"
    reply = {"model": PIN, "answers": {"other": {"type": "noul", "noul": 0.1}}}
    cache.write_text(json.dumps({"id": "a", "key": key, "reply": reply}) + "\n")
    code, _, err = _run([path, "--cache", cache, "--offline"])
    assert code == 2 and "expected a noul answer, got None" in err


def test_markdown_renders_every_table(tmp_path, dataset):
    code, out, _ = _run([dataset, "--format", "markdown"], transport=FakeTransport())
    assert code == 0
    assert "### `tone` (choice, n=4)" in out and "Agreement 0.750 (3/4)" in out
    assert "| expected \\ predicted | 0 | 1 | 2 |" in out
    assert "| threshold | tp | fp | fn | tn | precision | recall |" in out
    assert "INVALID" not in out


def test_report_goes_to_a_file_when_asked(tmp_path, dataset):
    report = tmp_path / "r.json"
    code, out, _ = _run([dataset, "--report", report], transport=FakeTransport())
    assert code == 0 and out == "" and json.loads(report.read_text())["valid"]


# --- skips, failures, invalid runs -------------------------------------------


def test_not_opted_in_is_exit_4_and_nothing_is_sent(tmp_path, dataset):
    t = FakeTransport()
    code, _, err = _run(
        [dataset], environ={"TYPESAFE_API_KEY": "k"}, transport=t, cwd=tmp_path
    )
    assert code == 4 and "typesafe: skipped (not-opted-in)" in err and t.calls == []


def test_no_key_is_exit_4(tmp_path, dataset):
    code, _, err = _run([dataset], environ={"TYPESAFE_OPT_IN": "on"}, cwd=tmp_path)
    assert code == 4 and "skipped (no-key)" in err


def test_a_failure_part_way_is_exit_2_and_the_rerun_resumes(tmp_path, dataset):
    cache = tmp_path / "cache.jsonl"
    t = FakeTransport(fail_on="wow, can't wait for the launch")
    code, out, err = _run([dataset, "--cache", cache], transport=t)
    assert code == 2 and out == ""
    assert "authentication_error" in err and "2 answer(s) are in" in err
    assert "case c failed" in err  # CR 409
    t2 = FakeTransport()
    code, out, _ = _run([dataset, "--cache", cache], transport=t2)
    assert code == 0 and len(t2.calls) == 2
    assert json.loads(out)["calls"] == {"live": 2, "replayed": 2}


def test_two_answering_models_make_the_run_invalid(tmp_path, dataset):
    t = FakeTransport(models={"thanks, all good": "jev-1.14.0"})
    code, out, err = _run([dataset, "--model", "jev-latest"], transport=t)
    report = json.loads(out)
    assert code == 5 and not report["valid"]
    assert "more than one model answered" in report["invalid_reason"]
    assert "invalid run" in err


def test_the_pin_answered_by_another_model_is_invalid(tmp_path, dataset):
    t = FakeTransport(models={r["state"]: "jev-1.14.0" for r in ROWS})
    code, out, err = _run([dataset], transport=t)
    assert code == 5
    assert (
        json.loads(out)["invalid_reason"]
        == f"the pinned {PIN} was asked for and jev-1.14.0 answered"
    )
    assert (
        "typesafe: warning: the pinned" in err
    )  # the client's own line passes through


def test_an_alias_answered_by_one_model_is_valid(tmp_path, dataset):
    t = FakeTransport(models={r["state"]: "jev-1.13.0" for r in ROWS})
    code, out, _ = _run([dataset, "--model", "jev-latest"], transport=t)
    assert code == 0 and json.loads(out)["models_answered"] == ["jev-1.13.0"]


def test_a_malformed_answer_is_exit_2(tmp_path):
    def transport(url, data, headers, timeout):
        body = {"model": PIN, "answers": {"billing": {"type": "noul"}}, "usage": {}}
        return 200, {}, json.dumps(body).encode()

    path = _write(tmp_path / "s.jsonl", [_row("a", "s", billing=True)])
    code, _, err = _run([path], transport=transport)
    assert code == 2 and "noul answer has no number" in err


# --- the private-set guard ----------------------------------------------------


@pytest.fixture
def work_tree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    return repo


def test_a_set_inside_a_work_tree_is_refused_unless_public(work_tree):
    path = _write(
        work_tree / "set.jsonl", [_row("a", "thanks, all good", billing=False)]
    )
    code, _, err = _run([path], transport=FakeTransport())
    assert code == 1 and "inside a git work tree" in err and "--public" in err
    code, _, _ = _run([path, "--public"], transport=FakeTransport())
    assert code == 0


@pytest.mark.parametrize("flag", ["--cache", "--report"])
def test_a_cache_or_report_inside_a_work_tree_is_refused(
    tmp_path, dataset, work_tree, flag
):
    t = FakeTransport()
    code, _, err = _run([dataset, flag, work_tree / "out.jsonl"], transport=t)
    assert code == 1 and "inside a git work tree" in err and t.calls == []
    assert not (work_tree / "out.jsonl").exists()


def test_a_symlink_into_a_work_tree_is_followed(tmp_path, work_tree):
    _write(work_tree / "set.jsonl", ROWS)
    link = tmp_path / "link.jsonl"
    link.symlink_to(work_tree / "set.jsonl")
    code, _, err = _run([link])
    assert code == 1 and "inside a git work tree" in err


def test_git_dir_in_the_environment_does_not_answer_for_the_path(tmp_path, monkeypatch):
    """A hook exports GIT_DIR; the guard must ask about the path, not that repo (#189)."""
    monkeypatch.setenv("GIT_DIR", str(REPO_ROOT / ".git"))
    assert ev.in_work_tree(tmp_path / "set.jsonl") is False
    assert ev.in_work_tree(SCRIPT) is True


def test_the_cache_directory_must_exist(tmp_path, dataset):
    code, _, err = _run([dataset, "--cache", tmp_path / "nope" / "c.jsonl"])
    assert code == 1 and "doesn't exist" in err


def test_a_byte_order_mark_is_not_a_malformed_line(tmp_path, dataset):
    """CR 407."""
    cache = tmp_path / "cache.jsonl"
    _run([dataset, "--cache", cache], transport=FakeTransport())
    bom_set = tmp_path / "bom.jsonl"
    bom_set.write_bytes(b"\xef\xbb\xbf" + dataset.read_bytes())
    cache.write_bytes(b"\xef\xbb\xbf" + cache.read_bytes())
    code, _, err = _run([bom_set, "--cache", cache, "--offline"])
    assert code == 0, err


def test_a_pipe_in_a_choice_name_is_escaped_in_markdown(tmp_path):
    """CR 408."""
    criteria = {"refund|credit": "money back", "other": "anything else"}
    row = {
        "id": "a",
        "state": "s",
        "questions": {"kind": {"type": "choice", "criteria": criteria}},
        "expected": {"kind": "refund|credit"},
    }

    def transport(url, data, headers, timeout):
        answer = {"type": "choice", "choice": "refund|credit", "confidence": 0.9}
        body = {"model": PIN, "answers": {"kind": answer}, "usage": {}}
        return 200, {}, json.dumps(body).encode()

    path = _write(tmp_path / "s.jsonl", [row])
    code, out, _ = _run([path, "--format", "markdown"], transport=transport)
    assert code == 0
    assert "| expected \\ predicted | refund\\|credit | other |" in out
    assert "| refund\\|credit | 1 | 0 |" in out


@pytest.mark.parametrize(
    "extra",
    [
        ["--report", "set.jsonl"],
        ["--cache", "set.jsonl"],
        ["--cache", "c.jsonl", "--report", "c.jsonl"],
    ],
)
def test_one_file_cannot_be_two_of_set_cache_and_report(tmp_path, dataset, extra):
    """CR 410: the report written over the set destroyed the labels."""
    before = dataset.read_bytes()
    t = FakeTransport()
    code, _, err = _run(
        [dataset, *[tmp_path / a if a.endswith(".jsonl") else a for a in extra]],
        transport=t,
    )
    assert code == 1 and "are both" in err and t.calls == []
    assert dataset.read_bytes() == before


def test_a_ceiling_directory_does_not_hide_the_checkout(work_tree, monkeypatch):
    """CR 411."""
    (work_tree / "sub").mkdir()
    path = _write(work_tree / "sub" / "set.jsonl", ROWS)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(work_tree))
    code, _, err = _run([path])
    assert code == 1 and "inside a git work tree" in err


def test_an_overflowing_number_is_refused_before_anything_is_sent(tmp_path):
    """CR 412: 1e400 is inf, which the client refuses only at send time."""
    rows = [_row("a", "thanks, all good", billing=False), _row("b", "s", billing=True)]
    path = tmp_path / "s.jsonl"
    path.write_text(
        json.dumps(rows[0]) + "\n" + json.dumps(rows[1]).replace('"s"', "1e400") + "\n"
    )
    t = FakeTransport()
    code, _, err = _run([path], transport=t)
    assert code == 1 and "overflows" in err and t.calls == []


def test_a_report_path_that_is_a_directory_is_refused_up_front(tmp_path, dataset):
    """CR 413."""
    (tmp_path / "out").mkdir()
    t = FakeTransport()
    code, _, err = _run([dataset, "--report", tmp_path / "out"], transport=t)
    assert code == 1 and "is a directory" in err and t.calls == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes through file modes")
def test_a_report_write_that_fails_late_is_exit_2_and_goes_to_stdout(tmp_path, dataset):
    """CR 413: exit 1 means nothing was sent, which is no longer true here."""
    report = tmp_path / "r.json"
    report.write_text("")
    report.chmod(0o444)
    code, out, err = _run([dataset, "--report", report], transport=FakeTransport())
    assert code == 2 and json.loads(out)["valid"] and "so it's on stdout" in err


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes through file modes")
def test_a_cache_append_that_fails_is_exit_2(tmp_path, dataset):
    cache = tmp_path / "c.jsonl"
    cache.write_text("")
    cache.chmod(0o444)
    code, _, err = _run([dataset, "--cache", cache], transport=FakeTransport())
    assert code == 2 and "case a was answered" in err


def test_the_report_holds_no_case_id(tmp_path):
    """CR 415: aggregates only. The fixture's one-letter ids can't be searched for."""
    rows = [{**r, "id": f"private-case-{r['id']}-7f3a"} for r in ROWS]
    path = _write(tmp_path / "s.jsonl", rows)
    for fmt in ("json", "markdown"):
        code, out, _ = _run([path, "--format", fmt], transport=FakeTransport())
        assert code == 0 and "private-case" not in out


def test_thresholds_and_bins_take_effect(tmp_path, dataset):
    code, out, _ = _run(
        [dataset, "--thresholds", "0.25,0.75", "--bins", "4"], transport=FakeTransport()
    )
    report = json.loads(out)
    assert code == 0 and report["thresholds"] == [0.25, 0.75] and report["bins"] == 4
    assert [s["threshold"] for s in report["questions"]["billing"]["sweep"]] == [
        0.25,
        0.75,
    ]
    assert len(report["questions"]["tone"]["by_confidence"]) == 4


@pytest.mark.parametrize(
    "flag, value",
    [
        ("--thresholds", "0.5,x"),
        ("--thresholds", "1.5"),
        ("--bins", "0"),
        ("--bins", "x"),
    ],
)
def test_a_bad_threshold_or_bin_count_is_exit_1(dataset, flag, value):
    out = subprocess.run(
        [sys.executable, str(SCRIPT), str(dataset), flag, value],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 1 and flag in out.stderr


def test_an_invalid_run_says_so_in_markdown_and_writes_its_report(tmp_path, dataset):
    t = FakeTransport(models={"thanks, all good": "jev-1.14.0"})
    report = tmp_path / "r.md"
    code, out, _ = _run(
        [dataset, "--model", "jev-latest", "--format", "markdown", "--report", report],
        transport=t,
    )
    assert code == 5 and out == ""
    assert "**INVALID RUN:** more than one model answered" in report.read_text()


def test_the_opt_in_is_the_current_directorys_checkout(tmp_path, dataset, monkeypatch):
    """CR 416: run from inside a repo whose knob is on, that repo opts the run in."""
    # The client's knob lookup inherits the environment, and a pre-commit hook
    # exports GIT_DIR, which would answer for this repo instead (#189).
    for k in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(k)
    repo = tmp_path / "source"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".skills").mkdir()
    (repo / ".skills" / "typesafe").write_text("on\n")
    t = FakeTransport()
    code, _, err = _run(
        [dataset], environ={"TYPESAFE_API_KEY": "sk-test-key"}, transport=t, cwd=repo
    )
    assert code == 0, err
    assert len(t.calls) == 4


def test_a_repeated_request_counts_its_tokens_once(tmp_path):
    """CR 417: one call, so 300 tokens, not 300 per row."""
    rows = [_row(rid, "thanks, all good", billing=False) for rid in ("x", "y", "z")]
    t = FakeTransport()
    code, out, _ = _run([_write(tmp_path / "s.jsonl", rows)], transport=t)
    report = json.loads(out)
    assert code == 0 and len(t.calls) == 1
    assert report["calls"] == {"live": 1, "replayed": 2}
    assert report["tokens"]["input"] == 300 and report["tokens"]["live_input"] == 300


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes through file modes")
def test_an_invalid_run_says_so_even_when_its_report_write_fails(tmp_path, dataset):
    """CR 418."""
    report = tmp_path / "r.json"
    report.write_text("")
    report.chmod(0o444)
    t = FakeTransport(models={"thanks, all good": "jev-1.14.0"})
    code, out, err = _run(
        [dataset, "--model", "jev-latest", "--report", report], transport=t
    )
    assert code == 2 and "invalid run: more than one model answered" in err
    assert json.loads(out)["valid"] is False


# --- pure helpers --------------------------------------------------------------


@pytest.mark.parametrize(
    "score, levels, want",
    [(0.49, 3, 0), (0.5, 3, 1), (1.5, 3, 2), (2.4, 3, 2), (-0.2, 3, 0), (9.0, 3, 2)],
)
def test_nearest_level_rounds_half_up_and_clamps(score, levels, want):
    assert ev.nearest_level(score, levels) == want


@pytest.mark.parametrize(
    "value, want", [(0.0, 0), (0.0999, 0), (0.1, 1), (0.95, 9), (1.0, 9)]
)
def test_bands_close_the_last_one_at_1(value, want):
    assert ev.band_of(value, 10) == want


def test_a_value_on_a_band_edge_lands_in_that_band():
    """CR 414: 0.57 * 100 is 56.99999999999999."""
    for bins in (10, 20, 100):
        for i in range(bins):
            assert ev.band_of(i / bins, bins) == i
    assert [ev.band_of(v, 100) for v in (0.29, 0.57, 0.58)] == [29, 57, 58]


def test_precision_with_no_predicted_yes_is_none_not_zero():
    m = ev.noul_metrics([{"p": 0.2, "expected": True}], (0.5,), 10)
    assert m["sweep"][0]["precision"] is None and m["sweep"][0]["recall"] == 0.0


def test_the_request_key_ignores_key_order_but_not_content():
    q1 = {"b": {"type": "noul", "instructions": "x"}}
    q2 = {"b": {"instructions": "x", "type": "noul"}}
    assert ev.request_key(PIN, {"a": 1, "b": 2}, q1) == ev.request_key(
        PIN, {"b": 2, "a": 1}, q2
    )
    assert ev.request_key(PIN, "s", q1) != ev.request_key("jev-latest", "s", q1)
    assert ev.request_key(PIN, "s", q1) != ev.request_key(PIN, "t", q1)


def test_the_evaluator_imports_only_the_standard_library_and_the_client():
    import ast

    names = set()
    for node in ast.walk(ast.parse(SCRIPT.read_text())):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    names -= {"__future__", "_typesafe"}
    assert names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)
