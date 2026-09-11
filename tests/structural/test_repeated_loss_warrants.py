"""A line repeated in a deleted code sample is one judgement, not several (#278).

`prove-no-loss.sh` appends a lost line once per base-line OCCURRENCE, charges
each to the first in-scope entry whose CONTENT it contains, and refuses any
entry charged more than one line. The refusal is right to exist — its target is
one entry zeroing many *different* lines, `retarget :: e` — but it could not
tell that from identical copies of one text, so a curation that deleted a code
block whose lines repeat could never reach `ok`:

- one entry per text was charged every copy and refused as over-broad (exit 1);
- one entry per occurrence charged every copy to the FIRST of them, and was
  refused the same way;
- no entry at all exited 3.

That is the normal shape of a deleted code sample. CannObserv/cannobserv#414
deleted three constructor examples — 20 lost lines, 8 distinct texts, every one
`disproven` — and recorded `no_loss: failed`, which tells `score-cohort.sh`
content was dropped: the misreading #111 introduced warrants to prevent.

Every case that relaxes the refusal is paired with the direction that matters:
an entry matching two DIFFERENT lines is still refused, including two lines
whole-line matching would equate. The existing three-line blanket fixture in
test_loss_warrants.py is the issue's third criterion and runs unchanged.
"""

from pathlib import Path

from .test_claim_warrants import CLAIM_ACK, FAITHFUL, TIGHTEN, _tightened
from .test_loss_warrants import _ack, _prove, _repo

# cannobserv#414's three examples, reduced to the lines they shared. The second
# is a class-body excerpt, indented one level deeper: a copy is a copy wherever
# it sits, because the report compares lines with their indentation stripped.
FIRST = (
    "def __init__(self, metadata: WordPressMetadata):\n"
    "    self.metadata = metadata\n"
    "    self.client = WordPressClient(metadata)\n"
)
SECOND = (
    "    def __init__(self, metadata: WordPressMetadata):\n"
    "        self.metadata = metadata\n"
    "        self.client = WordPressClient(metadata)\n"
    "\n"
    "    @cached_property\n"
    "    def _co_core_config(self) -> WordPressConfig:\n"
    "        return metadata_to_config(self.metadata)\n"
    "\n"
    "    @cached_property\n"
    "    def _co_core_drivers(self) -> Drivers:\n"
    "        return make_legacy_drivers()\n"
)
THIRD = (
    "def __init__(self, metadata: WordPressMetadata):\n"
    "    self.metadata = metadata\n"
    "\n"
    "@cached_property\n"
    "def _co_core_config(self) -> WordPressConfig:\n"
    "    return metadata_to_config(self.metadata)\n"
    "\n"
    "@cached_property\n"
    "def _co_core_drivers(self) -> Drivers:\n"
    "    return make_legacy_drivers()\n"
)

# Each distinct text and how many times the three examples carry it — the
# table the issue opens with.
COPIES = {
    "@cached_property": 4,
    "def __init__(self, metadata: WordPressMetadata):": 3,
    "self.metadata = metadata": 3,
    "def _co_core_config(self) -> WordPressConfig:": 2,
    "return metadata_to_config(self.metadata)": 2,
    "def _co_core_drivers(self) -> Drivers:": 2,
    "return make_legacy_drivers()": 2,
    "self.client = WordPressClient(metadata)": 2,
}
OCCURRENCES = sum(COPIES.values())

# What survives the deletion. The `## Imports` block keeps one fenced example
# inline, so the deleted blocks' fence lines are still accounted for and the
# 20 code lines are the only loss.
AFTER = (
    "# P\n\n## Constructors\n\nBuild a site from its metadata.\n\n"
    "## Imports\n\n```python\nimport this\n```\n"
)
BEFORE = (
    "# P\n\n## Constructors\n\nBuild a site from its metadata.\n\n"
    + "".join(f"```python\n{block}```\n\n" for block in (FIRST, SECOND, THIRD))
    + "## Imports\n\n```python\nimport this\n```\n"
)


def _deleted_samples(tmp_path: Path) -> Path:
    repo = _repo(tmp_path, BEFORE)
    (repo / "AGENTS.md").write_text(AFTER)
    return repo


def _one_entry_per_text(repo: Path) -> None:
    _ack(repo, *(f"disproven :: {text}" for text in COPIES))


class TestADeletedCodeSampleCanBeWarranted:
    def test_the_fixture_is_the_issues_shape(self, tmp_path: Path):
        """Twenty lost lines, eight texts. If the fixture drifts from that, the
        cases below stop testing what #278 found.

        Each count is checked against the blocks themselves, not just the sum:
        the report assertions below read only two of the eight, so a COPIES
        table that disagreed with the blocks it describes would pass them."""
        base = [line.strip() for line in BEFORE.splitlines()]
        assert {text: base.count(text) for text in COPIES} == COPIES
        assert OCCURRENCES == 20 and len(COPIES) == 8
        r = _prove(_deleted_samples(tmp_path))
        assert r.returncode == 3, r.stdout + r.stderr
        assert f"lost: {OCCURRENCES}" in r.stdout, r.stdout

    def test_one_entry_per_distinct_text_exits_clean(self, tmp_path: Path):
        """The acceptance criterion. Before #278 this exited 1, every entry
        with a repeated line refused as over-broad."""
        repo = _deleted_samples(tmp_path)
        _one_entry_per_text(repo)
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "over-broad" not in r.stderr, r.stderr
        assert "lost: 0" in r.stdout, r.stdout

    def test_loss_warranted_counts_every_copy(self, tmp_path: Path):
        """The ledger's `no_loss_warrants` is copied from this trailer, and it
        must still reconcile with the lines lost at --base. Counting texts would
        record 8 against a base that lost 20."""
        repo = _deleted_samples(tmp_path)
        _one_entry_per_text(repo)
        r = _prove(repo)
        assert f"loss_warranted: {OCCURRENCES}" in r.stdout, r.stdout
        assert f"UNACCOUNTED FOR:            {OCCURRENCES}" in r.stdout, r.stdout
        assert f"{OCCURRENCES} line(s) warranted, none unexplained" in r.stdout

    def test_the_copies_are_counted_beside_the_entry(self, tmp_path: Path):
        """Folding the copies must not hide them. One entry that waved four
        lines through is still named with the four."""
        repo = _deleted_samples(tmp_path)
        _one_entry_per_text(repo)
        r = _prove(repo)
        assert "1 hit(s) x4: disproven :: @cached_property" in r.stdout, r.stdout
        assert "1 hit(s) x2: disproven :: self.client" in r.stdout, r.stdout

    def test_the_lost_list_names_each_text_once(self, tmp_path: Path):
        """Twenty LOST rows for eight judgements reads as twenty entries to
        write — the one-per-occurrence shape the fix makes redundant."""
        r = _prove(_deleted_samples(tmp_path))
        rows = [x for x in r.stdout.splitlines() if x.startswith("  LOST  ")]
        assert len(rows) == len(COPIES), r.stdout
        assert any("@cached_property" in x and x.endswith("x4") for x in rows), r.stdout


class TestARedundantEntryIsNamedAsOne:
    """An entry that matched only lines an earlier entry was charged with is
    neither stale nor ambiguous: its line is lost, and warranted. Reporting it
    "matched nothing — accounted for now" was false of it, and this change
    made the commonest shape of it passable."""

    def test_one_entry_per_occurrence_passes_and_names_the_extras(self, tmp_path: Path):
        """The shape an operator reached for before this fix. The first of the
        identical entries is charged every copy of its line, so the rest match
        nothing of their own — and "accounted for now" would be false of them:
        their line is lost, and warranted by the entry above them."""
        repo = _deleted_samples(tmp_path)
        _ack(
            repo,
            *(f"disproven :: {t}" for t, n in COPIES.items() for _ in range(n)),
        )
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        extras = OCCURRENCES - len(COPIES)
        assert f"{extras} entry(ies) redundant" in r.stdout, r.stdout
        assert "matched nothing" not in r.stdout, r.stdout
        assert f"loss_warranted: {OCCURRENCES}" in r.stdout, r.stdout

    def test_a_repeated_claim_entry_is_redundant_too(self, tmp_path: Path):
        """The atom side's stale/ambiguous partition mirrors the line side's
        (#251), so the third case lands on both. A second entry for one dropped
        atom was reported as "present again", which is false: it is dropped,
        and warranted by the entry above it."""
        repo = _tightened(tmp_path, FAITHFUL)
        _ack(repo, TIGHTEN)
        _ack(repo, "duplicate :: #412", "duplicate :: #412", path=CLAIM_ACK)
        r = _prove(repo, "--claims")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "1 claim entry(ies) redundant" in r.stdout, r.stdout
        assert "matched nothing" not in r.stdout, r.stdout
        assert "claims_warranted: 1" in r.stdout, r.stdout

    def test_a_narrower_entry_below_a_broader_one_is_redundant(self, tmp_path: Path):
        """The other shape the third case names, and one this change moved: it
        was reported stale, with "re-judge and prune" advice resting on a line
        being accounted for that was in fact lost."""
        repo = _repo(tmp_path, "# P\n\n## A\n\nthe contract lives in the spec\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n")
        _ack(
            repo,
            "disproven :: the contract lives",
            "disproven :: the contract lives in the spec",
        )
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "1 entry(ies) redundant" in r.stdout, r.stdout
        assert "matched nothing" not in r.stdout, r.stdout


class TestBreadthIsStillRefused:
    """Folding copies may relax nothing else. The over-broad refusal exists for
    one entry zeroing many DIFFERENT lines, and that must still exit 1."""

    def test_an_entry_matching_a_repeated_line_and_another_is_refused(
        self, tmp_path: Path
    ):
        """The copies of one line count once; the second line still makes it
        two judgements."""
        repo = _repo(
            tmp_path,
            "# P\n\n## A\n\nfirst rule here\nfirst rule here\nsecond rule here\n",
        )
        (repo / "AGENTS.md").write_text("# P\n\n## A\n")
        _ack(repo, "duplicate :: rule here")
        r = _prove(repo)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "over-broad" in r.stderr, r.stderr
        assert "2 lines matched (3 with copies)" in r.stderr, r.stderr
        assert "loss_warranted" not in r.stdout, r.stdout
        # Neither line is inside the other, so narrowing CAN separate them and
        # the ordering hint below would be wrong advice here.
        assert "ABOVE this one" not in r.stderr, r.stderr

    def test_a_line_inside_another_is_told_to_reorder_not_narrow(self, tmp_path: Path):
        """Deleted code nests lines: `return make_legacy_drivers()` is part of
        `return make_legacy_drivers() or {}`, so no narrowing of the shorter
        line's entry excludes the longer line, and "narrow the content" was
        advice nobody could follow. A line is charged to the FIRST entry that
        matches it, so order is the remedy — and the advice must work."""
        nested = "return make_legacy_drivers()"
        nesting = "return make_legacy_drivers() or {}"
        repo = _repo(
            tmp_path,
            "# P\n\n## Constructors\n\nBuild a site from its metadata.\n\n"
            f"```python\n{nested}\n{nesting}\n```\n\n"
            "## Imports\n\n```python\nimport this\n```\n",
        )
        (repo / "AGENTS.md").write_text(AFTER)
        _ack(repo, f"disproven :: {nested}", f"disproven :: {nesting}")
        r = _prove(repo)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "ABOVE this one" in r.stderr, r.stderr
        assert f"`{nesting}`" in r.stderr, r.stderr

        _ack(repo, f"disproven :: {nesting}", f"disproven :: {nested}")
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "loss_warranted: 2" in r.stdout, r.stdout

    def test_lines_equal_only_after_normalising_are_two_lines(self, tmp_path: Path):
        """normalise() erases a docs-root prefix because a MOVE forces it, so
        `](docs/API.md)` and `](API.md)` compare equal across a demotion. Inside
        one base file they are two links to two different targets, and folding
        them would let one entry warrant both — so copies are identical TEXT,
        not identical comparable form."""
        root_link = "- The contract lives in [the spec](docs/API.md)."
        near_link = "- The contract lives in [the spec](API.md)."
        # The premise, checked so the case below cannot pass vacuously: whole-
        # line matching does equate the two, since a demoted copy of one is
        # accepted as the other.
        repo = _repo(tmp_path / "premise", f"# P\n\n## A\n\n{root_link}\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n")
        (repo / "docs").mkdir()
        (repo / "docs" / "X.md").write_text(f"# X\n\n{near_link}\n")
        assert _prove(repo).returncode == 0, "normalise() no longer equates them"

        repo = _repo(tmp_path / "case", f"# P\n\n## A\n\n{root_link}\n{near_link}\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n")
        _ack(repo, "disproven :: The contract lives in [the spec]")
        r = _prove(repo)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "2 lines matched" in r.stderr, r.stderr
