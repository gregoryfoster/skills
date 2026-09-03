"""The class-C gap, and the check that closes it (#247, #250, #251).

Phase 3 prescribes class C — "Class A content wrapped in prose an agent does not
need … **Rewrite in place**" — and the five original warrants named only *moves*.
So a run that did exactly what the rubric prescribes had no honest verdict, the
same trilemma `prove-no-loss.sh` exists to resolve, reappearing for a case its
own vocabulary did not cover:

  ok       contradicts exit 3
  failed   tells score-cohort.sh content was dropped when none was
  skipped  is false — the check ran

Two cohort runs hit it from opposite ends of the size range. A 62-token trim over
eight lines (#247), and a 1,013-token restructure where a `##` section holding
one 4,416-token bullet was reflowed into subsections and **5 of 5 non-blank lines
reported lost** (#250) — because a one-line section rewritten as fifteen lines is
100% lost at whole-line granularity however faithful the rewrite is.

The fix is NOT a bare sixth warrant, and the reason is the whole point of this
file. `tighten` is the one warrant a run can always claim about its own edit —
`retarget`/`rename` are compulsory, `duplicate`/`disproven`/`default` point at
evidence outside the entry — and the over-broad refusal cannot restrain it,
because class C's defining defect is a section written as ONE paragraph. One
line, one entry, a whole section waved through. So `tighten` is gated on
`--claims`, an atom-level check the rewrite cannot perform on itself.

Every case below is paired with the direction that actually matters: **a genuine
over-compression must still fail.** A gate that lets an author wave away their
own rewrite is strictly worse than the forced choice it replaces.
"""

import subprocess
from pathlib import Path

from .test_loss_warrants import PROVE, _ack, _clean_env, _repo

CLAIM_ACK = ".skills/context-claims-ok"

# #250's shape, reduced: a section that is one paragraph, carrying live contract
# facts wrapped in the changelog narrative CHANGELOG.md already holds. `wp#569`
# is the load-bearing one — the justification for the whole API being write-only,
# and the atom whose loss the run would otherwise have shipped.
NARRATIVE = (
    "The cohort mechanism was introduced in #412 after a long debate, and the "
    "reason it exists at all is that the earlier approach could not express a "
    "write-only surface; see `wp#569` for the justification that made the whole "
    "API write-only, and read [docs/API.md](docs/API.md) for the shape. Run "
    "`uv sync --frozen` first."
)
# The faithful reflow: subsections, every live claim carried across, narrative
# gone. This is what the rubric asks for and what the gate could not score.
FAITHFUL = (
    "# P\n\n## Cohorts\n\n### Shape\n\nThe API is write-only (`wp#569`). See "
    "[docs/API.md](docs/API.md).\n\n### Setup\n\nRun `uv sync --frozen` first.\n"
)
# The same reflow with `wp#569` dropped — indistinguishable from FAITHFUL at
# whole-line granularity, and the failure #250 caught by hand.
OVER_COMPRESSED = (
    "# P\n\n## Cohorts\n\n### Shape\n\nSee [docs/API.md](docs/API.md).\n\n"
    "### Setup\n\nRun `uv sync --frozen` first.\n"
)
TIGHTEN = "tighten :: The cohort mechanism was introduced"


def _tightened(tmp_path: Path, after: str) -> Path:
    repo = _repo(tmp_path, f"# P\n\n## Cohorts\n\n{NARRATIVE}\n")
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "API.md").write_text("# API\n\nthe shape\n")
    (repo / "AGENTS.md").write_text(after)
    return repo


def _prove(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(PROVE), "--base", "HEAD", *extra],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=30,
    )


class TestTighteningHasAVerdictAtAll:
    """#247/#250's direction: an honest run must stop being pushed into
    misreporting."""

    def test_a_faithful_reflow_fails_without_the_warrant(self, tmp_path: Path):
        """The status quo, pinned. The rubric's own prescribed action reported
        as content loss — a false negative in exactly the gate that exists to
        catch true drops."""
        r = _prove(_tightened(tmp_path, FAITHFUL))
        assert r.returncode == 3, r.stdout + r.stderr
        assert "lost: 1" in r.stdout, r.stdout

    def test_a_faithful_reflow_passes_with_tighten_and_claims(self, tmp_path: Path):
        """Two judgements, because a class-C reflow makes two kinds of edit: it
        rewrites a line (the `tighten`) and it deletes the narrative that made
        the line long (the `#412`). The atom is not waved through by the line
        warrant — dropping the changelog reference is the POINT of class C, and
        it is still a claim someone has to have looked at."""
        repo = _tightened(tmp_path, FAITHFUL)
        _ack(repo, TIGHTEN)
        _ack(repo, "duplicate :: #412", path=CLAIM_ACK)
        r = _prove(repo, "--claims")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "lost: 0" in r.stdout, r.stdout
        assert "claims_dropped: 0" in r.stdout, r.stdout

    def test_a_reflow_is_not_clean_until_its_atoms_are_judged_too(self, tmp_path: Path):
        """The warrant is not a blanket over the rewrite. `tighten` accounts for
        the LINE; every atom the line carried is accounted for separately, or
        the gate is back to trusting the author about their own edit."""
        repo = _tightened(tmp_path, FAITHFUL)
        _ack(repo, TIGHTEN)
        r = _prove(repo, "--claims")
        assert r.returncode == 3, r.stdout + r.stderr
        assert "lost: 0" in r.stdout, r.stdout
        assert "claims_dropped: 1" in r.stdout, r.stdout

    def test_the_ledger_can_carry_both_counts(self, tmp_path: Path):
        """`loss_warranted` and `claims_warranted` answer different questions and
        the row needs both — one says how many rewrites were judged, the other
        how many of their claims were."""
        repo = _tightened(tmp_path, FAITHFUL)
        _ack(repo, TIGHTEN)
        _ack(repo, "duplicate :: #412", path=CLAIM_ACK)
        out = _prove(repo, "--claims").stdout
        assert "loss_warranted: 1" in out, out
        assert "claims_warranted: 1" in out, out


class TestTheWarrantCannotCertifyItself:
    """The reason a bare sixth warrant was refused. Without the gate, `tighten`
    is a licence to delete anything a rewrite touched."""

    def test_tighten_without_claims_is_refused_not_warned(self, tmp_path: Path):
        """Refusal, not a warning. Warnings ride in stdout, where the exit code,
        the ledger row and the cohort gate do not read them — the lesson the
        over-broad refusal already paid for."""
        repo = _tightened(tmp_path, OVER_COMPRESSED)
        _ack(repo, TIGHTEN)
        r = _prove(repo)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "--claims" in r.stderr, r.stderr

    def test_the_line_warrant_alone_would_have_passed_the_bad_rewrite(
        self, tmp_path: Path
    ):
        """The heart of #250. Line matching cannot tell FAITHFUL from
        OVER_COMPRESSED — both replace the same one line — so the warrant on its
        own converts a real content drop into exit 0."""
        repo = _tightened(tmp_path, OVER_COMPRESSED)
        _ack(repo, TIGHTEN)
        r = _prove(repo, "--claims")
        assert "lost: 0" in r.stdout, "line matching is blind here, as expected"
        assert r.returncode == 3, r.stdout + r.stderr
        assert "claims_dropped: 2" in r.stdout, r.stdout

    def test_the_dropped_claim_is_named_with_the_line_it_came_from(
        self, tmp_path: Path
    ):
        """An atom alone is unreviewable — `wp#569` says nothing about whether
        dropping it was right, and the sentence it sat in is the whole of the
        evidence."""
        repo = _tightened(tmp_path, OVER_COMPRESSED)
        _ack(repo, TIGHTEN)
        out = _prove(repo, "--claims").stdout
        assert "wp#569" in out, out
        assert "in: The cohort mechanism was introduced" in out, out

    def test_no_ok_line_is_printed_when_only_the_claims_failed(self, tmp_path: Path):
        """Every line being accounted for is TRUE here, and printing it would
        still read as a pass twenty lines above exit 3 — the shape the
        validation gate had to fix in itself."""
        repo = _tightened(tmp_path, OVER_COMPRESSED)
        _ack(repo, TIGHTEN)
        out = _prove(repo, "--claims").stdout
        assert "\nOK —" not in out, out

    def test_tighten_is_not_a_claim_warrant(self, tmp_path: Path):
        """Warranting a dropped atom with the warrant the atom check exists to
        gate would close the loop the gate is there to open."""
        repo = _tightened(tmp_path, OVER_COMPRESSED)
        _ack(repo, TIGHTEN)
        _ack(repo, "tighten :: wp#569", path=CLAIM_ACK)
        r = _prove(repo, "--claims")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "unknown warrant 'tighten'" in r.stderr, r.stderr


class TestJudgingADroppedClaim:
    """A tightening legitimately drops some atoms — pure changelog narrative the
    CHANGELOG already carries. Those are judged, one entry each."""

    def test_a_warranted_atom_clears_the_check(self, tmp_path: Path):
        repo = _tightened(tmp_path, FAITHFUL)
        _ack(repo, TIGHTEN)
        _ack(repo, "duplicate :: #412", path=CLAIM_ACK)
        r = _prove(repo, "--claims")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "claims_warranted: 1" in r.stdout, r.stdout

    def test_an_atom_entry_matches_whole_never_as_a_substring(self, tmp_path: Path):
        """`#41` must not warrant `#412`, and a path must not be waved through
        by an entry naming its parent directory. This is why the atom file needs
        neither a length floor nor an over-broad refusal: a set element matches
        at most one thing."""
        repo = _tightened(tmp_path, FAITHFUL)
        _ack(repo, TIGHTEN)
        _ack(repo, "duplicate :: #41", path=CLAIM_ACK)
        r = _prove(repo, "--claims")
        assert r.returncode == 3, r.stdout + r.stderr
        assert "claims_dropped: 1" in r.stdout, r.stdout

    def test_a_short_atom_is_accepted(self, tmp_path: Path):
        """The loss file's 8-character floor would refuse `#412`. It exists
        because CONTENT is a substring there; an atom identifies itself
        exactly, so the floor does not carry over."""
        repo = _tightened(tmp_path, FAITHFUL)
        _ack(repo, TIGHTEN)
        _ack(repo, "duplicate :: #412", path=CLAIM_ACK)
        assert _prove(repo, "--claims").returncode == 0

    def test_an_unscoped_claim_entry_for_another_surface_is_not_called_stale(
        self, tmp_path: Path
    ):
        """CR finding 3. #251 was fixed for the loss file and reintroduced here
        in the same change — the partition has to hold for both files or the
        shared grammar is only half shared."""
        repo = _tightened(tmp_path, FAITHFUL)
        _ack(repo, TIGHTEN)
        _ack(repo, "duplicate :: #412", "duplicate :: #999", path=CLAIM_ACK)
        r = _prove(repo, "--claims")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Do not prune\n  on this run alone" in r.stdout, r.stdout

    def test_naming_the_claim_file_without_the_flag_is_refused(self, tmp_path: Path):
        """CR finding 4. The file would go unread and its malformed entries
        unrefused, while the run reported a claim column it never computed. A
        flag that quietly does nothing is the mute failure this script refuses
        everywhere else."""
        repo = _tightened(tmp_path, FAITHFUL)
        r = _prove(repo, "--claims-ack-file", "warrants.txt")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "needs --claims" in r.stderr, r.stderr

    def test_claims_are_silent_without_the_flag(self, tmp_path: Path):
        """`claims_dropped: 0` from a run that never looked would read as a
        clean bill of health, and the trailer is what the ledger row is copied
        from."""
        repo = _tightened(tmp_path, OVER_COMPRESSED)
        _ack(repo, "duplicate :: The cohort mechanism was introduced")
        out = _prove(repo).stdout
        assert "claims_dropped" not in out, out
        assert "claims_warranted" not in out, out


class TestAtomsAreNotNoise:
    """Extraction is deliberately narrow. A claim list padded with prose teaches
    its reader to skim, and this one is the sole evidence behind `tighten`."""

    def test_a_demoted_link_is_not_a_dropped_claim(self, tmp_path: Path):
        """Link targets are normalised exactly as whole lines are. Without
        this, every run that demoted a link-carrying bullet would report it as
        a dropped claim — #119/#137's false-LOST storm, one layer down."""
        repo = _repo(tmp_path, "# P\n\n## A\n\nSee [the style doc](docs/S.md).\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n")
        (repo / "docs").mkdir()
        (repo / "docs" / "S.md").write_text("# S\n\nSee [the style doc](S.md).\n")
        r = _prove(repo, "--claims")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "claims_dropped: 0" in r.stdout, r.stdout

    def test_a_deleted_code_block_is_not_double_reported(self, tmp_path: Path):
        """Fenced content is protected line by line already, so extracting from
        it would report every deleted code line twice — once as LOST and once
        as a dropped atom, the second adding nothing."""
        repo = _repo(
            tmp_path, "# P\n\n## A\n\n```bash\nuv run pytest --maxfail=1\n```\n"
        )
        (repo / "AGENTS.md").write_text("# P\n\n## A\n")
        r = _prove(repo, "--claims")
        assert r.returncode == 3, r.stdout + r.stderr
        assert "claims_dropped: 0" in r.stdout, r.stdout

    def test_prose_tightened_into_a_fenced_block_is_not_a_dropped_claim(
        self, tmp_path: Path
    ):
        """CR finding 1. Skipping fences on BOTH sides reported every atom of a
        prose-to-fence tightening as dropped — an ordinary class-C move, failing
        falsely. Reading fenced lines was not enough on its own: inside a fence
        there are no backticks delimiting a span, so the whole line has to count
        as the atom."""
        repo = _repo(
            tmp_path,
            "# P\n\n## A\n\nRun `uv sync --frozen` before anything else here.\n",
        )
        (repo / "AGENTS.md").write_text(
            "# P\n\n## A\n\nSetup:\n\n```bash\nuv sync --frozen\n```\n"
        )
        _ack(repo, "tighten :: Run `uv sync --frozen` before anything")
        r = _prove(repo, "--claims")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "claims_dropped: 0" in r.stdout, r.stdout

    def test_a_heading_is_not_an_issue_reference(self, tmp_path: Path):
        """`## Foo` and `# 2026 plan` must not read as `#NNN`. Two digits
        minimum, abutting the `#`, matching the seam convention."""
        repo = _repo(tmp_path, "# P\n\n## 2026 plan\n\nkeep me\n")
        r = _prove(repo, "--claims")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "claims_dropped: 0" in r.stdout, r.stdout


class TestAnEntryThatMatchedNothing:
    """#251: 'matched nothing' was reported as staleness and paired with 'prune
    it', which is sound advice for only some of them. Pruning on the wrong
    reading discards a live warrant — an unscoped entry pinning an AGENTS.md
    line reported stale on every reference-doc run in one cohort repo."""

    def _two_surfaces(self, tmp_path: Path) -> Path:
        repo = _repo(tmp_path, "# P\n\nRules live in [docs/S.md](docs/S.md).\n")
        (repo / "docs").mkdir(exist_ok=True)
        (repo / "docs" / "OLD.md").write_text(
            "# Old\n\nA line that stays put entirely unchanged forever.\n"
        )
        subprocess.run(
            ["git", "-C", str(repo), "add", "-A"],
            check=True,
            capture_output=True,
            env=_clean_env(),
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-qm", "docs"],
            check=True,
            capture_output=True,
            env=_clean_env(),
        )
        return repo

    def test_an_entry_pinning_another_surface_is_not_called_stale(self, tmp_path: Path):
        repo = self._two_surfaces(tmp_path)
        _ack(repo, "retarget :: Rules live in [docs/S.md]")
        r = _prove(repo, "--file", "docs/OLD.md")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Do not prune on this run alone" in r.stdout, r.stdout

    def test_an_entry_whose_line_is_in_this_target_is_still_called_stale(
        self, tmp_path: Path
    ):
        """The direction that must not regress: where the run CAN judge, the
        prune advice stands. Expiry is the whole promise of content matching."""
        repo = self._two_surfaces(tmp_path)
        _ack(repo, "retarget :: A line that stays put entirely")
        r = _prove(repo, "--file", "docs/OLD.md")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "re-judge and prune" in r.stdout, r.stdout
        assert "Do not prune" not in r.stdout, r.stdout

    def test_a_path_scoped_entry_that_matched_nothing_is_stale(self, tmp_path: Path):
        """A PATH that matched settles it on its own: the entry says which
        target it is about, so this run is entitled to judge it."""
        repo = self._two_surfaces(tmp_path)
        _ack(repo, "docs/OLD.md :: retarget :: Rules live in [docs/S.md]")
        r = _prove(repo, "--file", "docs/OLD.md")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "re-judge and prune" in r.stdout, r.stdout
