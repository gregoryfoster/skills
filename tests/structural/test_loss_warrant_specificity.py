"""A lost line is charged to the most specific entry that reaches it (#347).

`prove-no-loss.sh` charged each lost line to the FIRST in-scope entry of
`.skills/context-loss-ok` whose CONTENT reaches it. An entry an earlier run
judged usually pins a prefix of a line, so it keeps reaching that line after a
later run rewrites the line for a different reason, and the later run's own,
more specific entry below it matched nothing of its own. The report then
called the specific entry "redundant … prune", steering the operator to delete
the only record of the run's own judgement (CannObserv/replicator#137, #143).

The fix is the issue's options 1 and 3: the longest CONTENT that reaches a
line is charged, whatever the file order, and a line more than one entry
reaches is reported with every candidate. Option 1 alone does not settle the
issue's own synthetic case, where the stale entry is the LONGER one, so the
report also stops telling the operator to prune an entry the charged one does
not contain.

#338 point 1 rides along: the `--claims` gate refused a run for any in-scope
`tighten` entry, before a single line was charged, so an unscoped `tighten`
left by an earlier policy-file run refused every per-doc run that tightened
nothing. It now gates on the `tighten` entries this run actually charged.
"""

from pathlib import Path

from .test_loss_warrants import _ack, _prove, _repo

# CannObserv/replicator#137's two in-place tightenings, reduced to one: an
# earlier run's unscoped entry is a suffix of the line, and the later run's
# own, scoped entry names the whole of it.
ARCH_BEFORE = "seams, and the file map: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)."
ARCH_AFTER = "seams and the file map: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)."
OLD_SUFFIX = "tighten :: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)."
OWN_ENTRY = f"AGENTS.md :: tighten :: {ARCH_BEFORE}"

# The issue's synthetic reproduction: the earlier run's `disproven` pins a
# prefix that is LONGER than the later run's `retarget` of the same line.
AUTH_BEFORE = (
    "**Auth:** reads require login; writes require edit rights. "
    "A missing record is a 404 ([details](errors.md))."
)
AUTH_AFTER = (
    "**Auth:** reads require login; writes require edit rights. "
    "A missing record is a 404 ([details](gates.md))."
)
OLD_PREFIX = "disproven :: **Auth:** reads require login; writes require edit rights."
RETARGET = "retarget :: A missing record is a 404 ([details](errors.md))"


def _rewritten(tmp_path: Path, before: str, after: str) -> Path:
    repo = _repo(tmp_path, f"# P\n\n## A\n\n{before}\n")
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "ARCHITECTURE.md").write_text("# Architecture\n")
    (repo / "AGENTS.md").write_text(f"# P\n\n## A\n\n{after}\n")
    return repo


def _section(out: str, header: str) -> str:
    """The report block opened by HEADER, up to the next blank line."""
    assert header in out, out
    return out.split(header, 1)[1].split("\n\n", 1)[0]


class TestTheLongestEntryIsCharged:
    def test_the_specific_entry_wins_whatever_the_order(self, tmp_path: Path):
        """replicator#137: the run's own entry, listed below the old suffix,
        is the one charged — and in either order, since file order is an
        accident of when each entry was appended."""
        for name, order in (
            ("below", (OLD_SUFFIX, OWN_ENTRY)),
            ("above", (OWN_ENTRY, OLD_SUFFIX)),
        ):
            repo = _rewritten(tmp_path / name, ARCH_BEFORE, ARCH_AFTER)
            _ack(repo, *order)
            r = _prove(repo, "--claims")
            assert r.returncode == 0, r.stdout + r.stderr
            assert "loss_warranted: 1" in r.stdout, r.stdout
            assert f"1 hit(s): tighten :: {ARCH_BEFORE[:70]}" in r.stdout, r.stdout
            assert f"hit(s): {OLD_SUFFIX}" not in r.stdout, r.stdout

    def test_the_old_suffix_is_the_redundant_one_now(self, tmp_path: Path):
        """The report used to tell the operator to prune the run's own entry.
        Now the entry it names is the old one the charged entry contains."""
        repo = _rewritten(tmp_path, ARCH_BEFORE, ARCH_AFTER)
        _ack(repo, OLD_SUFFIX, OWN_ENTRY)
        out = _prove(repo, "--claims").stdout
        redundant = _section(out, "1 entry(ies) redundant")
        assert OLD_SUFFIX in redundant, out
        assert ARCH_BEFORE not in redundant, out

    def test_equal_lengths_fall_back_to_file_order(self, tmp_path: Path):
        """A tie has no more specific side, so it keeps the old rule rather
        than inventing one: the first such entry is charged."""
        repo = _repo(tmp_path, "# P\n\n## A\n\nthe contract lives in the spec\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n")
        _ack(repo, "disproven :: contract lives", "duplicate :: lives in the s")
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "1 hit(s): disproven :: contract lives" in r.stdout, r.stdout


class TestShadowingIsReported:
    def test_every_candidate_is_named_beside_the_line(self, tmp_path: Path):
        """The issue's option 3. A line two entries reach is a collision the
        operator has to see, whichever one is charged."""
        repo = _rewritten(tmp_path, AUTH_BEFORE, AUTH_AFTER)
        _ack(repo, OLD_PREFIX, RETARGET)
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        block = _section(r.stdout, "1 lost line(s) reached by more than one entry")
        assert AUTH_BEFORE[:120] in block, r.stdout
        assert f"charged: {OLD_PREFIX[:70]}" in block, r.stdout
        assert f"also:    {RETARGET[:70]}" in block, r.stdout

    def test_a_shadowed_entry_is_not_told_to_prune(self, tmp_path: Path):
        """The issue's own reproduction, which longest-wins does not settle:
        the stale `disproven` is the longer entry, so it is charged. What must
        not happen is the report calling the run's own `retarget` redundant
        and telling the operator to delete it — the charged entry does not
        contain it, so the two may be judgements of two different edits."""
        repo = _rewritten(tmp_path, AUTH_BEFORE, AUTH_AFTER)
        _ack(repo, OLD_PREFIX, RETARGET)
        out = _prove(repo).stdout
        assert "redundant" not in out, out
        shadowed = _section(out, "1 entry(ies) shadowed")
        assert RETARGET[:70] in shadowed, out
        assert "do not prune on this run alone" in out, out

    def test_a_line_one_entry_reaches_reports_no_collision(self, tmp_path: Path):
        repo = _rewritten(tmp_path, AUTH_BEFORE, AUTH_AFTER)
        _ack(repo, RETARGET)
        out = _prove(repo).stdout
        assert "reached by more than one entry" not in out, out
        assert "shadowed" not in out, out


class TestNestedLinesNeedNoOrdering:
    """`return f()` is part of `return f() or {}`, so an entry for the shorter
    line reaches both. First-match made ORDER the remedy; longest-match makes
    an entry for the longer line enough, wherever it sits."""

    NESTED = "return make_default_drivers()"
    NESTING = "return make_default_drivers() or {}"

    def _repo(self, tmp_path: Path) -> Path:
        repo = _repo(
            tmp_path,
            "# P\n\n## C\n\nBuild a site.\n\n"
            f"```python\n{self.NESTED}\n{self.NESTING}\n```\n",
        )
        # The fence lines survive in another block, so the two code lines are
        # the only losses.
        (repo / "AGENTS.md").write_text(
            "# P\n\n## C\n\nBuild a site.\n\n```python\nimport this\n```\n"
        )
        return repo

    def test_either_order_passes(self, tmp_path: Path):
        for name, order in (
            ("short-first", (self.NESTED, self.NESTING)),
            ("long-first", (self.NESTING, self.NESTED)),
        ):
            repo = self._repo(tmp_path / name)
            _ack(repo, *(f"disproven :: {t}" for t in order))
            r = _prove(repo)
            assert r.returncode == 0, r.stdout + r.stderr
            assert "loss_warranted: 2" in r.stdout, r.stdout

    def test_the_shorter_entry_alone_is_told_to_add_the_longer_line(
        self, tmp_path: Path
    ):
        repo = self._repo(tmp_path)
        _ack(repo, f"disproven :: {self.NESTED}")
        r = _prove(repo)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "over-broad" in r.stderr, r.stderr
        assert "ABOVE this one" not in r.stderr, r.stderr
        assert f"`{self.NESTING}`" in r.stderr, r.stderr
        assert "the longest entry that reaches it" in r.stderr, r.stderr


class TestClaimsGateOnlyWhatItCharges:
    """#338 point 1."""

    def test_an_unscoped_tighten_that_matches_nothing_needs_no_claims(
        self, tmp_path: Path
    ):
        """replicator#124's shape: a per-doc run that tightened nothing, and a
        loss file carrying an earlier policy-file run's unscoped `tighten`."""
        repo = _repo(tmp_path, "# P\n\n## A\n\nkept as it was\n")
        _ack(repo, "tighten :: a line some other target lost long ago")
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "without --claims" not in r.stderr, r.stderr

    def test_a_tighten_another_entry_outranks_needs_no_claims(self, tmp_path: Path):
        """Gated on what is CHARGED, not on what reaches: a shorter `tighten`
        the longest-match rule passes over warrants nothing here."""
        repo = _rewritten(tmp_path, AUTH_BEFORE, AUTH_AFTER)
        _ack(repo, "tighten :: A missing record is a 404", OLD_PREFIX)
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert f"1 hit(s): {OLD_PREFIX[:70]}" in r.stdout, r.stdout

    def test_a_charged_tighten_still_needs_claims(self, tmp_path: Path):
        """The direction that matters: the gate itself is untouched."""
        repo = _rewritten(tmp_path, ARCH_BEFORE, ARCH_AFTER)
        _ack(repo, OWN_ENTRY)
        r = _prove(repo)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "tighten without --claims" in r.stderr, r.stderr
