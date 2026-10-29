"""A count hit is charged to the most specific entry that fits it (#347, CR 843).

`check-counts.sh` charged each hit to the FIRST in-scope entry of
`.skills/context-counts-ok` that `fits()` it, and called any later entry that
fit the same hit "redundant … since a hit is charged to the first that matches.
Prune". That is #347's defect in the sibling script: an older, shorter entry
shadows the specific one a later run wrote below it, and the report tells the
operator to delete the specific one.

The same rule as `prove-no-loss.sh` now (b1e64a31): the longest fitting CONTENT
is charged, file order breaking a tie; a hit two different entries fit is
listed with every one; an uncharged entry the charged one contains is
redundant, and one it does not contain is shadowed, with no prune advice. The
broad-entry WARN is not ported to a refusal: this script warns on breadth
rather than refusing it, and still does.
"""

from pathlib import Path

from .test_counts_ack_scope import _counts, _repo, _run

POLICY = "# P\n\nEight timers keep the tree fresh.\n"
OLD_SHORT = "stable :: Eight timers"
SPECIFIC = "AGENTS.md :: enumerated :: Eight timers keep the tree fresh"
TIE_TEXT = "each charged to the longest (file order breaks a tie)"


def _section(out: str, header: str) -> str:
    """The report block opened by HEADER, up to the next blank line."""
    assert header in out, out
    return out.split(header, 1)[1].split("\n\n", 1)[0]


class TestTheLongestEntryIsCharged:
    def test_the_specific_entry_wins_whatever_the_order(self, tmp_path: Path):
        for name, order in (
            ("below", (OLD_SHORT, SPECIFIC)),
            ("above", (SPECIFIC, OLD_SHORT)),
        ):
            repo = _repo(tmp_path / name, "\n".join(order), policy=POLICY)
            r = _run(repo)
            assert _counts(r) == (0, 1), r.stdout
            assert "1 hit(s): AGENTS.md :: enumerated :: Eight timers keep" in (
                r.stdout
            ), r.stdout
            assert f"hit(s): {OLD_SHORT}\n" not in r.stdout, r.stdout

    def test_the_old_shorter_entry_is_the_redundant_one(self, tmp_path: Path):
        repo = _repo(tmp_path, f"{OLD_SHORT}\n{SPECIFIC}", policy=POLICY)
        out = _run(repo).stdout
        redundant = _section(out, "1 entry(ies) redundant")
        assert OLD_SHORT in redundant, out
        assert SPECIFIC not in redundant, out

    def test_equal_lengths_fall_back_to_file_order(self, tmp_path: Path):
        first = "enumerated :: Eight timers"
        second = "stable :: e tree fresh"
        assert len(first.split(" :: ")[1]) == len(second.split(" :: ")[1])
        repo = _repo(tmp_path, f"{first}\n{second}", policy=POLICY)
        r = _run(repo)
        assert f"1 hit(s): {first}" in r.stdout, r.stdout
        assert TIE_TEXT in r.stdout, r.stdout


class TestShadowingIsReported:
    FIRST = "enumerated :: Eight timers keep"
    SECOND = "stable :: timers keep the tree fresh"

    def test_every_entry_that_fits_is_named_beside_the_hit(self, tmp_path: Path):
        repo = _repo(tmp_path, f"{self.FIRST}\n{self.SECOND}", policy=POLICY)
        r = _run(repo)
        block = _section(r.stdout, "1 hit(s) more than one entry fits")
        assert "AGENTS.md:3" in block, r.stdout
        assert f"charged: {self.SECOND}" in block, r.stdout
        assert f"also:    {self.FIRST}" in block, r.stdout
        assert TIE_TEXT in r.stdout, r.stdout

    def test_a_shadowed_entry_is_not_told_to_prune(self, tmp_path: Path):
        """The charged entry does not contain this one, so the two may be
        judgements of different edits of the clause: nothing here says which
        one to delete."""
        repo = _repo(tmp_path, f"{self.FIRST}\n{self.SECOND}", policy=POLICY)
        out = _run(repo).stdout
        assert "redundant" not in out, out
        shadowed = _section(out, "1 entry(ies) shadowed")
        assert self.FIRST in shadowed, out
        assert "do not prune on this run alone" in out, out

    def test_a_hit_one_entry_fits_reports_no_collision(self, tmp_path: Path):
        repo = _repo(tmp_path, SPECIFIC, policy=POLICY)
        out = _run(repo).stdout
        assert "more than one entry fits" not in out, out
        assert "shadowed" not in out, out
