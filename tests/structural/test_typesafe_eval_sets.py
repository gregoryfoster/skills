"""Committed labelled sets replay offline to the numbers their child chose on (#463).

Epic #451 decided (2026-10-21) that a labelled set built from public material
lands under `tests/fixtures/typesafe-eval/<child>/` with its cache. Each one
is replayed here through `scripts/typesafe-eval.py --offline --public`: no
network, no key. What that pins, and what it doesn't:

- **Pinned:** the set (by sha256), the cache (every case replays, zero
  misses, one model), and the evaluator's metrics (the headline sweep row).
- **Pinned for stale-issue-prose, bare-digit-counts and tightened-rules:** the
  case builders. Its four inputs are in each
  case's own `state`, so every case is rebuilt through the shipped builder and
  must come back byte-equal: a reworded question or a reshaped state fails here
  instead of at the next re-measure.
- **Pinned for tightened-rules' second label (#470):** `held.tsv` covers every
  positive, and the ceiling it implies, computed from the committed cache.
  The step-1 figures read docs at each curation commit, so they need the
  clones: `mine.py delegated` re-derives them, and nothing here does.
- **Pinned for index-lines (#447):** the labels match the set, and the
  pairs result #447 closed on, from the cache. No pass shipped, so there is no
  builder to pin: `mine.py build` rebuilds the set from the clones.
- **Pinned for section-class (#435):** the labels match the set, the
  confusion and the pairs result #435 closed on, and the repeat noise the
  pairs are read against, all from the cache. No pass shipped either.
- **Pinned for harvest-candidates (#436):** every case is what the shipped
  `_harvest.build_case` sends, the labels match the set, and the ranks #436
  built on (against the plain-matching baseline, with the repeat noise), plus
  the whole-thread table from `scores.tsv`. `mine.py build` rebuilds the set
  from the raw threads, through the shipped paragraph reader.
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
    "bare-digit-counts": (
        "31f064bca50a50217aa3f2f2ebb7d8b1776517974d2d7dc73c853c61b3d5072d",
        664,
        {"tally": {0.8: (5, 0, 13, 646), 0.5: (13, 28, 5, 618)}},
    ),
    "tightened-rules": (
        "551c3c7c10ac33836a1d466cd211a5fcf707d4566f63698a242e991a1ea2e5e6",
        421,
        {"dropped": {0.3: (52, 128, 9, 232), 0.5: (46, 65, 15, 295)}},
    ),
    "index-lines": (
        "c5a99b92ba64109c80fe255c37d4e03e98e176097d38d24106e7a40eac00f1d8",
        198,
        {"inaccurate": {0.3: (4, 25, 13, 156), 0.5: (1, 3, 16, 178)}},
    ),
    "section-class": (
        "a24ecb5ef6673b7fe0ba8ae11263cddbd9caae910cf6de458e7e3f81cce52616",
        1178,
        {"default": {0.3: (0, 39, 0, 1139), 0.5: (0, 0, 0, 1178)}},
    ),
    "harvest-candidates": (
        "504a91a8273ad6b29b77c965c1ece10d25e2ac76944e3607cca4dc2242d96bcb",
        156,
        {"bears_on": {0.3: (14, 48, 8, 86), 0.5: (10, 22, 12, 112)}},
    ),
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # a dataclass looks its module up while it's built
    spec.loader.exec_module(mod)
    return mod


def _replay(set_path: Path, cache: Path, thresholds: str = "0.2,0.3,0.5,0.8") -> dict:
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


# --- bare-digit-counts (#441) ------------------------------------------------

BDC_DIR = SETS_DIR / "bare-digit-counts"


@pytest.fixture(scope="module")
def mine():
    _load("_sentences", SCRIPTS / "_sentences.py")
    _load("_stale_issue_prose", SCRIPTS / "_stale_issue_prose.py")
    _load("_bare_digit_counts", SCRIPTS / "_bare_digit_counts.py")
    return _load("bdc_mine", BDC_DIR / "mine.py")


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_the_bare_digit_set_is_what_the_shipped_code_builds(mine):
    """inputs.jsonl is check-counts.sh's own records, so the whole path past the gate is pinned."""
    inputs = _jsonl(BDC_DIR / "inputs.jsonl")
    built = mine.cases(inputs, mine.read_labels(BDC_DIR / "labels.tsv"))
    as_text = "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in built)
    assert as_text == (BDC_DIR / "set.jsonl").read_text()


def test_every_bare_digit_case_is_what_the_shipped_builder_sends(mine):
    bdc = mine.bdc
    for case in _jsonl(BDC_DIR / "set.jsonl"):
        st = case["state"]
        sent = bdc.build_tally_case(st["clause"], st["numbers"], st.get("heading"))
        assert list(sent) == [st, case["questions"]], case["id"]


def test_no_policy_file_clause_is_in_the_set(mine):
    """The pass never sends one, so the measurement holds none (#441)."""
    cases = _jsonl(BDC_DIR / "set.jsonl")
    assert cases and all(c["id"][0] in "SR" for c in cases)
    assert not [c for c in cases if mine.bdc.is_policy_file(c["source"].split(":")[1])]


def test_no_labelled_tally_is_prefiltered(mine):
    """A prefilter that drops a tally is a recall loss nothing downstream can see.

    Measured on every candidate, the policy files' included: P is kept for this
    even though the pass sends none of it.
    """
    labels = mine.read_labels(BDC_DIR / "labels.tsv")
    inputs = _jsonl(BDC_DIR / "inputs.jsonl")
    dropped = [r for r in inputs if not mine.bdc.prefilter(r["clause"])[0]]
    assert len(inputs) == 1082 and len(dropped) == 302
    # S and R were drawn from survivors; CR 459's time mask came after.
    assert sorted(r["id"] for r in dropped if r["id"][0] != "P") == [
        "R088",
        "S276",
        "S427",
        "S435",
        "S496",
        "S515",
        "S545",
    ]
    assert not [r["id"] for r in dropped if labels[r["id"]]]


def test_the_random_docs_slice_flags_nothing_at_the_default(tmp_path):
    """R is a seeded sample of the docs' own rate, so it is what a run sees."""
    lines = (BDC_DIR / "set.jsonl").read_text().splitlines()
    part = tmp_path / "r.jsonl"
    part.write_text("".join(f"{x}\n" for x in lines if json.loads(x)["id"][0] == "R"))
    report = _replay(part, BDC_DIR / "cache.jsonl")
    assert report["valid"] and report["calls"]["live"] == 0
    assert _row(report, "tally", 0.8) == (0, 0, 0, 99)


# --- tightened-rules (#442) --------------------------------------------------

TR_DIR = SETS_DIR / "tightened-rules"


@pytest.fixture(scope="module")
def tr_mine():
    _load("_sentences", SCRIPTS / "_sentences.py")
    _load("_tightened_rules", SCRIPTS / "_tightened_rules.py")
    return _load("tr_mine", TR_DIR / "mine.py")


def test_the_tightened_set_is_what_the_shipped_code_builds(tr_mine):
    """inputs.jsonl is prove-no-loss.sh's own records, so the splitter, the
    kept test, the clip and the case builder are all pinned."""
    inputs = _jsonl(TR_DIR / "inputs.jsonl")
    built = tr_mine.cases(inputs, tr_mine.read_labels(TR_DIR / "labels.tsv"))
    as_text = "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in built)
    assert as_text == (TR_DIR / "set.jsonl").read_text()


def test_the_inputs_are_records_the_pass_reads(tr_mine):
    lines = (TR_DIR / "inputs.jsonl").read_text().splitlines()
    assert len(tr_mine.tr.read_candidates(lines)) == len(lines) == 580


def test_the_default_threshold_is_the_one_measured(tr_mine):
    assert tr_mine.tr.DEFAULT_THRESHOLD == 0.3


def test_the_random_slice_is_caught_at_the_default(tmp_path):
    """R is a seeded sample of the sentences with no history, so it is the rate a run sees."""
    lines = (TR_DIR / "set.jsonl").read_text().splitlines()
    part = tmp_path / "r.jsonl"
    part.write_text(
        "".join(f"{x}\n" for x in lines if json.loads(x)["source"].endswith("(R)"))
    )
    report = _replay(part, TR_DIR / "cache.jsonl")
    assert report["valid"] and report["calls"]["live"] == 0
    assert report["cases"] == 150
    assert _row(report, "dropped", 0.3) == (23, 56, 3, 68)


# --- tightened-rules: a rule held at a destination (#470) ---------------------


def test_held_labels_every_positive_once(tr_mine):
    """held.tsv is the second label, on labels.tsv's positives and nothing else."""
    labels = tr_mine.read_labels(TR_DIR / "labels.tsv")
    held = tr_mine.read_held(TR_DIR / "held.tsv")
    assert set(held) == {c for c, lab in labels.items() if lab["dropped"]}
    for cid, h in held.items():
        if h["held"]:
            assert h["where"] and h["how"] in ("verbatim", "reworded"), cid
        else:
            assert not h["where"] and not h["how"] and h["note"], cid


def test_counting_a_held_rule_as_kept_hides_review_restored_drops(tr_mine):
    """The ceiling #470 closed on: even a perfect "held at the destination"
    judgment clears flags only by hiding drops a later review put back."""
    inputs = _jsonl(TR_DIR / "inputs.jsonl")
    labels = tr_mine.read_labels(TR_DIR / "labels.tsv")
    p = tr_mine.probabilities(inputs, labels, TR_DIR / "cache.jsonl")
    got = tr_mine.ceiling(labels, tr_mine.read_held(TR_DIR / "held.tsv"), p)
    assert (got["all"]["flags"], got["R"]["flags"]) == (142, 58)
    assert got["cleared_catches"] == 38
    assert len(got["hidden_drops"]) == 14
    assert got["hidden_restored"] == [
        "archiver:9882165:AGENTS.md:170#1",
        "replicator:2a9e9f2:docs/contracts/content-fetch-outcome-reference.md:90#1",
        "watcher:4b85744:AGENTS.md:54#3",
    ]
    assert len(got["restored_at_any_threshold"]) == 8


def test_pointers_read_the_cohorts_three_forms(tr_mine):
    text = (
        "See [the doc](docs/A.md#one) and `docs/B.md`.\n"
        'Full rules → `docs/C.md#two` §"Two"; [ref]: ../D.md\n'
        "[x]: https://example.com/e.md\n"
    )
    assert sorted(tr_mine.pointers(text)) == sorted(
        [
            ("docs/A.md#one", False),
            ("docs/B.md", True),
            ("docs/C.md#two", True),
            ("https://example.com/e.md", False),
        ]
    )
    assert tr_mine.pointers("[ref]: ../D.md\n") == [("../D.md", False)]


def test_an_anchor_names_its_section_as_github_slugs_it(tr_mine):
    doc = "# T\n## Run `it`\nfirst\n### Sub\nnested\n## Run it\nsecond\n```\n## Run it\n```\n"
    assert tr_mine.anchored(doc, "run-it") == "## Run `it`\nfirst\n### Sub\nnested"
    assert tr_mine.anchored(doc, "run-it-1").startswith("## Run it\nsecond")
    assert tr_mine.anchored(doc, "run-it-2") is None
    tilde = "~~~\n```\n## Not a heading\n~~~\n## Real\nbody\n"
    assert tr_mine.anchored(tilde, "not-a-heading") is None
    assert tr_mine.anchored(tilde, "real") == "## Real\nbody"


# --- index-lines (#447) -------------------------------------------------------

IL_DIR = SETS_DIR / "index-lines"


@pytest.fixture(scope="module")
def il_mine():
    return _load("il_mine", IL_DIR / "mine.py")


def test_the_index_line_labels_are_the_sets(il_mine):
    """Every case is labelled once, as the set expects, and every positive has its fix."""
    labels = il_mine.read_labels(IL_DIR / "labels.tsv")
    cases = _jsonl(IL_DIR / "set.jsonl")
    assert [c["id"] for c in cases] == list(labels)
    for c in cases:
        lab = labels[c["id"]]
        assert c["expected"]["inaccurate"] == lab["inaccurate"], c["id"]
        assert c["source"] == lab["source"], c["id"]
    hp = {c[2:] for c in labels if c.startswith("HP")}
    assert hp == {c[2:] for c in labels if c.startswith("HN")}
    assert len(hp) == 17
    assert all(lab["inaccurate"] == c.startswith("HP") for c, lab in labels.items())
    border = [c for c, lab in labels.items() if lab["borderline"]]
    assert len(border) == 18 and all(c.startswith("R") for c in border)


def test_a_fixed_index_line_scores_no_higher_than_its_fix(il_mine):
    """The result #447 closed on: against the same doc, the line before a review's
    fix scored above the fixed line in 8 of 17 pairs, a coin flip."""
    got = il_mine.pairs(IL_DIR / "set.jsonl", IL_DIR / "cache.jsonl")
    assert got == {"pairs": 17, "before_above": 8, "tied": 0}


def test_an_outline_fence_closes_only_on_its_own_character(il_mine):
    doc = (
        "# T\n~~~\n```\n## Not a heading\n~~~\n## Real\n````\n```\n## Also not\n````\n"
    )
    assert il_mine.outline(doc)["headings"] == ["# T", "## Real"]


# --- section-class (#435) -----------------------------------------------------

SC_DIR = SETS_DIR / "section-class"


@pytest.fixture(scope="module")
def sc_mine():
    return _load("sc_mine", SC_DIR / "mine.py")


def test_the_section_class_labels_are_the_sets(sc_mine):
    """Every case is labelled once, as the set expects, and A means left alone."""
    labels = sc_mine.read_labels(SC_DIR / "labels.tsv")
    cases = _jsonl(SC_DIR / "set.jsonl")
    assert [c["id"] for c in cases] == list(labels)
    for c in cases:
        lab = labels[c["id"]]
        assert c["expected"] == {"class": lab["label"], "default": False}, c["id"]
        assert (c["source"], c["state"]["heading"]) == (lab["source"], lab["heading"])
        assert c["questions"] == sc_mine.QUESTIONS
    assert all(
        lab["after_state"] == "same" for lab in labels.values() if lab["label"] == "A"
    )


def test_the_same_section_text_carries_two_labels(sc_mine):
    """Why no state-only judgment can match the ledger: 32 byte-identical sections
    were tagged by one curation and left alone by another."""
    by_state = {}
    for c in _jsonl(SC_DIR / "set.jsonl"):
        by_state.setdefault(json.dumps(c["state"], sort_keys=True), set()).add(
            c["expected"]["class"]
        )
    mixed = [sorted(v) for v in by_state.values() if len(v) > 1]
    assert len(mixed) == 32
    assert sorted(map(tuple, mixed)).count(("A", "C")) == 30


def test_jev_never_answers_tighten(sc_mine):
    """The confusion #435 closed on: no section is called C, and always-A beats Jev."""
    report = _replay(SC_DIR / "set.jsonl", SC_DIR / "cache.jsonl")
    cls = report["questions"]["class"]
    assert cls["confusion"]["labels"] == ["A", "B", "C", "D"]
    assert cls["confusion"]["matrix"] == [
        [627, 351, 0, 11],
        [25, 20, 0, 0],
        [92, 51, 0, 0],
        [1, 0, 0, 0],
    ]
    assert cls["correct"] == 647 < 989


def test_a_curated_section_reads_no_differently_after(sc_mine):
    """The pairs #435 closed on, [right, wrong, tied]: past Jev's own repeat noise,
    a section reads about as often more as less like its class after the edit."""
    noise = sc_mine.repeats(SC_DIR / "cache.jsonl")
    assert noise == {
        "repeated": 186,
        "choice_changed": 7,
        "max_move": 0.14,
        "p90_move": 0.07,
    }
    pairs = SC_DIR / "pairs.jsonl"
    cache = SC_DIR / "cache.jsonl"
    assert sc_mine.pairs(pairs, cache) == {
        "tightened": {"C_falls": [38, 12, 87], "A_rises": [61, 57, 19]},
        "part-demoted": {"B_falls": [23, 17, 3]},
    }
    assert sc_mine.pairs(pairs, cache, noise["p90_move"]) == {
        "tightened": {"C_falls": [2, 0, 135], "A_rises": [14, 11, 112]},
        "part-demoted": {"B_falls": [8, 8, 27]},
    }


def test_a_section_fence_closes_only_on_its_own_character(sc_mine):
    text = "## One\n~~~\n```\n## Not a heading\n~~~\n### Sub\n## Two\nbody\n"
    secs = sc_mine.sections(text)
    assert [h for h, _, _ in secs] == ["One", "Two"]
    assert secs[0][2] == ["Sub"]
    assert "## Not a heading" in secs[0][1]
    # A closing fence takes no info string, so ```bash opens nothing and closes nothing.
    info = "## One\n```\n```bash\n## Not a heading\n```\n## Two\n"
    assert [h for h, _, _ in sc_mine.sections(info)] == ["One", "Two"]


def test_a_repeated_heading_names_no_section(sc_mine):
    text = "## Notes\none\n## `Notes`\ntwo\n"
    assert sc_mine.ambiguous(sc_mine.sections(text))
    assert sc_mine.v1_state(text, "Notes", "AGENTS.md") is None
    assert (
        sc_mine.v1_state("## Notes\none\n", "Notes", "AGENTS.md")["text"]
        == "## Notes\none\n"
    )


def test_a_tag_names_a_heading_before_a_subsection_or_a_prefix(sc_mine):
    secs = sc_mine.sections("## Scripts\n### Style\n## Style guide\n## Style\n")
    assert sc_mine.match("Style", secs) == (2, "exact")
    assert sc_mine.match("`Scripts`", secs) == (0, "exact")
    assert sc_mine.match("Scripts gate discipline", secs) == (0, "prefix")
    assert sc_mine.match("redundant-heading", secs) == (None, "none")


# --- harvest-candidates ---------------------------------------------------------

HC_DIR = SETS_DIR / "harvest-candidates"


@pytest.fixture(scope="module")
def hc_mine():
    return _load("hc_mine", HC_DIR / "mine.py")


def _hc_cases() -> list[dict]:
    return [json.loads(x) for x in (HC_DIR / "set.jsonl").read_text().splitlines()]


def test_every_harvest_case_is_what_the_shipped_builder_sends(hc_mine):
    for c in _hc_cases():
        repo, source, _para, _child = c["id"].split("|")
        state, questions = hc_mine.H.build_case(
            c["state"]["paragraph"], repo, int(source), c["state"]["child"]
        )
        assert (state, questions) == (c["state"], c["questions"]), c["id"]


def test_the_harvest_labels_match_the_set(hc_mine):
    labels = hc_mine.read_labels()
    want = {
        f"{r['repo']}|{r['source']}|{r['comment']}:{r['k']}|{r['target']}"
        for r in labels
        if r["verdict"] == "genuine" and r["kind"] == "unnamed"
    }
    got = {c["id"] for c in _hc_cases() if c["expected"]["bears_on"]}
    assert got == want and len(got) == 22
    # 58 public harvests: 40 from a child's thread, 18 from elsewhere.
    harvests = {(r["repo"], r["source"], r["target"], r["harvest_at"]) for r in labels}
    assert len(harvests) == 58
    assert sum(r["source"] == "-" for r in labels) == 18


def test_the_harvest_ranks_436_built_on(hc_mine):
    got = hc_mine.rank(HC_DIR / "set.jsonl", HC_DIR / "cache.jsonl")
    assert got["pairs"] == 22
    assert got["baseline"] == [3, 12] and got["random"] == [3.8, 11.4]
    assert got["noul_last"] == [14, 16] and got["noul_mean"] == [14, 16]
    assert got["paired"] == [15, 2, 5] and got["sign_p"] == 0.0012
    assert got["repeats"] == {"repeated": 156, "max_move": 0.11, "p90_move": 0.04}


def test_the_whole_thread_table(hc_mine):
    got = hc_mine.scores(HC_DIR / "scores.tsv")
    assert sum(n for n, _, _ in got.values()) == 1732
    assert sum(len(r) for _, r, _ in got.values()) == 16
    assert sum(top for _, _, top in got.values()) == 10
