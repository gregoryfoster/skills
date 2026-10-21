"""Committed labelled sets replay offline to the numbers their child chose on (#463).

Epic #451 decided (2026-10-21) that a labelled set built from public material
lands under `tests/fixtures/typesafe-eval/<child>/` with its cache. Each one
is replayed here through `scripts/typesafe-eval.py --offline --public`: no
network, no key. What that pins, and what it doesn't:

- **Pinned:** the set (by sha256), the cache (every case replays, zero
  misses, one model), and the evaluator's metrics (the headline sweep row).
- **Pinned for stale-issue-prose:** `build_case`. Its four inputs are in each
  case's own `state`, so every case is rebuilt through the shipped builder and
  must come back byte-equal: a reworded question or a reshaped state fails here
  instead of at the next re-measure.
- **Not pinned:** what feeds the builder. The splitter needs the source file,
  from 12 repos and often a historical commit (485 KB of paragraph windows
  still reproduced only 111 of 130 cases), and `describe` needs gh's reply.
  A change there shows up only when someone re-measures.

The fixture README says how to add a set, public check included.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL = REPO_ROOT / "scripts" / "typesafe-eval.py"
SETS_DIR = REPO_ROOT / "tests" / "fixtures" / "typesafe-eval"
SCRIPTS = REPO_ROOT / "skills" / "curating-context" / "scripts"

# Importing from skills/*/scripts would leave a __pycache__/ there, which the
# suite's vendoring fixtures then copy as if it were a script.
sys.dont_write_bytecode = True

# child dir -> (set sha256, cases, {question: {threshold: (tp, fp, fn, tn)}})
SETS = {
    "stale-issue-prose": (
        "cc3ee5d181b2050170f185bfa9cfe11eff7e8cb55ee044bff89088b3fb323754",
        130,
        {
            "still_open": {0.2: (14, 28, 1, 69)},
            "already_done": {0.2: (3, 9, 0, 6)},
        },
    ),
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # a dataclass looks its module up while it's built
    spec.loader.exec_module(mod)
    return mod


def _replay(set_path: Path, cache: Path, thresholds: str = "0.2") -> dict:
    r = subprocess.run(
        [sys.executable, str(EVAL), str(set_path), "--cache", str(cache)]
        + ["--offline", "--public", "--thresholds", thresholds],
        capture_output=True,
        text=True,
    )
    # Exit 1 is a cache miss under --offline; 5 an invalid run.
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _row(report: dict, question: str, threshold: float) -> tuple:
    (row,) = [
        s for s in report["questions"][question]["sweep"] if s["threshold"] == threshold
    ]
    return row["tp"], row["fp"], row["fn"], row["tn"]


def test_every_set_directory_is_listed():
    dirs = {p.name for p in SETS_DIR.iterdir() if p.is_dir()}
    assert dirs == set(SETS)


@pytest.mark.parametrize("child", sorted(SETS))
def test_a_set_replays_offline_to_its_headline_numbers(child):
    sha, cases, sweep = SETS[child]
    d = SETS_DIR / child
    report = _replay(d / "set.jsonl", d / "cache.jsonl")
    assert report["valid"], report["invalid_reason"]
    assert report["set_sha256"] == sha
    assert report["cases"] == cases
    assert report["calls"] == {"live": 0, "replayed": cases}
    assert len(report["models_answered"]) == 1
    for question, rows in sweep.items():
        for threshold, counts in rows.items():
            assert _row(report, question, threshold) == counts, (question, threshold)


# --- stale-issue-prose -------------------------------------------------------

SIP_DIR = SETS_DIR / "stale-issue-prose"


@pytest.fixture(scope="module")
def sip():
    _load("_sentences", SCRIPTS / "_sentences.py")
    return _load("_stale_issue_prose", SCRIPTS / "_stale_issue_prose.py")


def _cases() -> list[dict]:
    return [
        json.loads(line) for line in (SIP_DIR / "set.jsonl").read_text().splitlines()
    ]


def test_every_case_is_what_the_shipped_builder_sends(sip):
    for case in _cases():
        st = case["state"]
        state, questions = sip.build_case(
            st["sentence"], st.get("section"), st["reference"], st["issue"]
        )
        sent = json.dumps([state, questions], ensure_ascii=False)
        assert sent == json.dumps([st, case["questions"]], ensure_ascii=False), case[
            "id"
        ]


def test_the_archival_split_is_the_one_463_measured(sip, tmp_path):
    """Judging archival rows last rested on this split; the shipped matcher must still make it."""
    names = sip.archival_names({})
    live, old = [], []
    for line in (SIP_DIR / "set.jsonl").read_text().splitlines():
        # source: "<repo>:<path>:<line>@<rev> (<origin>)"
        path = json.loads(line)["source"].split(":")[1]
        (old if sip.is_archival(path, tmp_path, names) else live).append(line)
    assert (len(live), len(old)) == (100, 30)
    for lines, still_open, already_done in (
        (live, (12, 22, 1, 60), (1, 2, 0, 2)),
        (old, (2, 6, 0, 9), (2, 7, 0, 4)),
    ):
        part = tmp_path / "part.jsonl"
        part.write_text("".join(f"{x}\n" for x in lines))
        report = _replay(part, SIP_DIR / "cache.jsonl")
        assert report["valid"] and report["calls"]["live"] == 0
        assert _row(report, "still_open", 0.2) == still_open
        assert _row(report, "already_done", 0.2) == already_done
