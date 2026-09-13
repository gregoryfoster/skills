"""An index line extended in place has a warrant, and the warrant is checked (#282).

v1.22 (#274) has Phase 5 give every doc in `links.unindexed` an index entry. A
repo that lists several docs on one line gets that entry by extending the line
in place, and `prove-no-loss.sh` then reports the original line lost. None of the
closed set fitted: nothing moved (`retarget`), the same claims plus one in more
words (`tighten`), not verbatim anywhere (`duplicate`). CannObserv/archiver's
run at a9dd136 inserted one link — a routing probe had just measured the doc at
0/24 unnamed and 22/24 named — and could only record `no_loss: null`, which the
validation gate treats as unscorable: the skill prescribing an edit its own gate
cannot score, #250's problem in a different shape.

`index` is the warrant, and unlike the six before it the script CHECKS it. The
entry holds only when one line of the file as it is now keeps every word and
atom of the lost line, and adds among atoms only links to docs the file did not
link at `--base`, at least one. Each relaxation below is paired with the
direction that matters: an `index` entry that its evidence does not bear out is
refused, never waved through, and a lost prose line cannot borrow a nearby
index extension as its excuse.
"""

import subprocess
from pathlib import Path

from .test_claim_warrants import CLAIM_ACK
from .test_loss_warrants import PROVE, _ack, _git, _prove, _repo

# archiver's shape: one grouped line naming the dashboard docs.
GROUPED = (
    "The dashboard docs - [docs/UI.md](docs/UI.md) overview: "
    "[docs/PAGES.md](docs/PAGES.md), [docs/SCREENS.md](docs/SCREENS.md)"
)
REGISTER = "[docs/REGISTER.md](docs/REGISTER.md)"
# The fix: one link inserted mid-line.
EXTENDED = GROUPED.replace("[docs/SCREENS.md]", f"{REGISTER}, [docs/SCREENS.md]")
ENTRY = "index :: The dashboard docs - [docs/UI.md]"
DOCS = ("UI", "PAGES", "SCREENS", "REGISTER", "STYLE")


def _index_repo(
    tmp_path: Path,
    now: str,
    *,
    base_extra: str = "",
    now_extra: str = "",
    new_docs: tuple[str, ...] = (),
) -> Path:
    """AGENTS.md holds GROUPED at --base and `now` in the working tree. Every
    doc in DOCS exists at --base; `new_docs` are created by the run."""
    repo = _repo(tmp_path, f"# P\n\n## Detail Docs\n\n{GROUPED}\n{base_extra}")
    (repo / "docs").mkdir()
    for name in DOCS:
        (repo / "docs" / f"{name}.md").write_text(f"# {name}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "the docs")
    for name in new_docs:
        (repo / "docs" / f"{name}.md").write_text(f"# {name}\n")
    (repo / "AGENTS.md").write_text(f"# P\n\n## Detail Docs\n\n{now}\n{now_extra}")
    return repo


class TestAnIndexExtensionCanBeScored:
    def test_without_a_warrant_it_is_a_loss(self, tmp_path: Path):
        """The status quo, pinned: whole-line matching reports the extended
        line lost, which is right — it is not the same line."""
        r = _prove(_index_repo(tmp_path, EXTENDED))
        assert r.returncode == 3, r.stdout + r.stderr
        assert "lost: 1" in r.stdout, r.stdout

    def test_the_warrant_scores_it(self, tmp_path: Path):
        """The issue's case, end to end."""
        repo = _index_repo(tmp_path, EXTENDED)
        _ack(repo, ENTRY)
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "loss_warranted: 1" in r.stdout, r.stdout
        assert "lost: 0" in r.stdout, r.stdout

    def test_the_row_names_what_it_indexes(self, tmp_path: Path):
        """The judgement stays visible on the row, which is why the issue
        preferred a warrant to a silent normalisation."""
        repo = _index_repo(tmp_path, EXTENDED)
        _ack(repo, ENTRY)
        r = _prove(repo)
        assert "WARRANTED index" in r.stdout, r.stdout
        assert "indexes: docs/REGISTER.md" in r.stdout, r.stdout

    def test_it_holds_under_claims_too(self, tmp_path: Path):
        """Every atom of the old line is on the new one, so the claim check
        has nothing to drop, and `index` does not need --claims to be run."""
        repo = _index_repo(tmp_path, EXTENDED)
        _ack(repo, ENTRY)
        r = _prove(repo, "--claims")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "claims_dropped: 0" in r.stdout, r.stdout

    def test_a_doc_reached_through_another_doc_is_unindexed_too(self, tmp_path: Path):
        """`links.unindexed` proper: reachable, never named by the policy
        file. The eligibility question is only what --file linked."""
        repo = _index_repo(tmp_path, EXTENDED)
        (repo / "docs" / "UI.md").write_text(
            "# UI\n\nSee [the register](REGISTER.md).\n"
        )
        _ack(repo, ENTRY)
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr

    def test_appending_moves_the_punctuation_and_still_holds(self, tmp_path: Path):
        """Words are counted, not placed: appending to a list that ended in a
        full stop moves the full stop, and nothing was removed."""
        base_line = GROUPED + "."
        repo = _repo(tmp_path, f"# P\n\n## Detail Docs\n\n{base_line}\n")
        (repo / "docs").mkdir()
        for name in DOCS:
            (repo / "docs" / f"{name}.md").write_text(f"# {name}\n")
        (repo / "AGENTS.md").write_text(
            f"# P\n\n## Detail Docs\n\n{GROUPED}, {REGISTER}.\n"
        )
        _ack(repo, ENTRY)
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr

    def test_a_description_may_come_with_the_link(self, tmp_path: Path):
        """#274 found a short description routes as well as a full line, so
        plain words beside the new link are part of an index repair."""
        now = GROUPED + f", {REGISTER} — how a register entry is born and retired"
        repo = _index_repo(tmp_path, now)
        _ack(repo, ENTRY)
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr

    def test_a_backticked_label_is_the_links_own(self, tmp_path: Path):
        """`[`docs/X.md`](docs/X.md)` adds a code span as well as a link, and
        the span is the link's label, not a new claim."""
        now = GROUPED + ", [`docs/REGISTER.md`](docs/REGISTER.md)"
        repo = _index_repo(tmp_path, now)
        _ack(repo, ENTRY)
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr

    def test_a_doc_this_run_created_counts(self, tmp_path: Path):
        """The issue's contrast case: a later archiver run added two new docs
        to the line and could say `retarget` only because it had also moved
        content into them. What scores an index extension should not turn on
        that, so a doc the file did not link at --base qualifies whether or
        not it existed there."""
        now = GROUPED + ", [docs/HEALTH_ROW.md](docs/HEALTH_ROW.md)"
        repo = _index_repo(tmp_path, now, new_docs=("HEALTH_ROW",))
        _ack(repo, ENTRY)
        r = _prove(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "indexes: docs/HEALTH_ROW.md" in r.stdout, r.stdout

    def test_a_reference_doc_extends_its_own_index(self, tmp_path: Path):
        """--file need not be the policy file, and a reference doc's links are
        relative to its own directory. Every other case here runs against a
        root AGENTS.md, whose directory is empty, so a join that ignored the
        directory would pass them all."""
        repo = _repo(tmp_path, "# P\n")
        (repo / "docs" / "api").mkdir(parents=True)
        for name in ("a", "b", "c"):
            (repo / "docs" / "api" / f"{name}.md").write_text(f"# {name}\n")
        parts = "Parts: [a](api/a.md), [b](api/b.md)"
        (repo / "docs" / "API.md").write_text(f"# API\n\n{parts}\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "a doc with an index of its own")
        (repo / "docs" / "API.md").write_text(f"# API\n\n{parts}, [c](api/c.md)\n")
        _ack(repo, "index :: Parts: [a](api/a.md)")
        r = _prove(repo, "--file", "docs/API.md")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "indexes: docs/api/c.md" in r.stdout, r.stdout


class TestTheEvidenceIsChecked:
    """Every refusal is exit 1, the code for an acknowledgement file that
    cannot be used as written, and names the reason."""

    def _refused(self, repo: Path, reason: str) -> None:
        r = _prove(repo)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "`index` entry(ies) not borne out" in r.stderr, r.stderr
        assert reason in r.stderr, r.stderr
        assert "loss_warranted" not in r.stdout, (
            "a refused ack file must not also emit a verdict: " + r.stdout
        )

    def test_a_removed_word_is_refused(self, tmp_path: Path):
        """Extended means nothing removed. An atoms-only check would pass this
        line, since `overview` is no atom — and so would pass any rewording
        that kept the links."""
        now = EXTENDED.replace(" overview", "")
        repo = _index_repo(tmp_path, now)
        _ack(repo, ENTRY)
        self._refused(repo, "keeps every word and atom")

    def test_a_removed_link_is_refused(self, tmp_path: Path):
        """Swapping one doc for another is not indexing one."""
        now = EXTENDED.replace("[docs/PAGES.md](docs/PAGES.md), ", "")
        repo = _index_repo(tmp_path, now)
        _ack(repo, ENTRY)
        self._refused(repo, "keeps every word and atom")

    def test_a_line_that_gained_only_words_is_refused(self, tmp_path: Path):
        """An appended clause is what whole-line matching refuses on purpose;
        `index` is for the one appended thing Phase 5 prescribes."""
        now = GROUPED + " — and read them in that order"
        repo = _index_repo(tmp_path, now)
        _ack(repo, ENTRY)
        self._refused(repo, "adds no link to a doc")

    def test_a_link_to_an_already_indexed_doc_is_refused(self, tmp_path: Path):
        """docs/STYLE.md is named elsewhere in the file at --base, so it is not
        in links.unindexed, and linking it again repairs nothing."""
        style = "Style rules: [docs/STYLE.md](docs/STYLE.md)"
        now = GROUPED + ", [docs/STYLE.md](docs/STYLE.md)"
        repo = _index_repo(
            tmp_path, now, base_extra=f"\n{style}\n", now_extra=f"\n{style}\n"
        )
        _ack(repo, ENTRY)
        self._refused(repo, "adds no link to a doc")

    def test_a_padded_link_at_base_still_counts_as_linked(self, tmp_path: Path):
        """measure-context.sh accepts `[l](  docs/X.md )` and counts the doc
        as indexed, so linking it again is no repair. The reading of --base may
        err toward "linked", never away from it: a doc it misses becomes
        eligible, and `index` would certify re-linking a doc already named."""
        style = "Style rules: [the guide](  docs/STYLE.md )"
        now = GROUPED + ", [docs/STYLE.md](docs/STYLE.md)"
        repo = _index_repo(
            tmp_path, now, base_extra=f"\n{style}\n", now_extra=f"\n{style}\n"
        )
        _ack(repo, ENTRY)
        self._refused(repo, "adds no link to a doc")

    def test_a_link_outside_the_docs_is_refused(self, tmp_path: Path):
        """An index points at reference docs; a source file is not one."""
        now = GROUPED + ", [the app](src/app.py)"
        repo = _index_repo(tmp_path, now)
        (repo / "src").mkdir()
        (repo / "src" / "app.py").write_text("")
        _ack(repo, ENTRY)
        self._refused(repo, "adds no link to a doc")

    def test_a_new_claim_riding_along_is_refused(self, tmp_path: Path):
        """A backticked span that is not the link's label is a new claim, and
        the check the warrant rests on cannot weigh it."""
        now = GROUPED + f", {REGISTER} (run `make register` first)"
        repo = _index_repo(tmp_path, now)
        _ack(repo, ENTRY)
        self._refused(repo, "also adds `make register`")

    def test_an_issue_reference_riding_along_is_refused(self, tmp_path: Path):
        now = GROUPED + f", {REGISTER} (#412)"
        repo = _index_repo(tmp_path, now)
        _ack(repo, ENTRY)
        self._refused(repo, "also adds `#412`")

    def test_a_lost_prose_line_cannot_borrow_the_extension(self, tmp_path: Path):
        """The hole an atoms-only check leaves. A prose line has no atom, so
        "every atom of it is on the extended line" is vacuously true, and one
        genuine index repair would warrant every dropped sentence in the file.
        Words close it: the extended line does not hold this one's."""
        prose = "Never deploy the dashboard on a Friday."
        repo = _index_repo(tmp_path, EXTENDED, base_extra=f"\n{prose}\n")
        _ack(repo, ENTRY, "index :: Never deploy the dashboard")
        self._refused(repo, "keeps every word and atom")

    def test_a_split_target_has_no_line_to_extend(self, tmp_path: Path):
        """A doc split deletes its source, so --file names a file with no
        current line at all."""
        repo = _index_repo(tmp_path, EXTENDED)
        (repo / "docs" / "UI.md").write_text(f"# UI\n\n{GROUPED}\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "an index in a doc")
        (repo / "docs" / "UI.md").unlink()
        _ack(repo, "index :: The dashboard docs - [docs/UI.md]")
        r = _prove(repo, "--file", "docs/UI.md")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "no longer exists" in r.stderr, r.stderr

    def test_an_emptied_target_is_not_called_gone(self, tmp_path: Path):
        """A file emptied in place has no current line either, but it is
        there, and "no longer exists" would send its reader looking for a
        deletion that did not happen."""
        repo = _index_repo(tmp_path, EXTENDED)
        (repo / "AGENTS.md").write_text("")
        _ack(repo, ENTRY)
        self._refused(repo, "keeps every word and atom")
        r = _prove(repo)
        assert "no longer exists" not in r.stderr + r.stdout, r.stderr


class TestTheWarrantStaysALineWarrant:
    def test_the_claim_file_does_not_take_it(self, tmp_path: Path):
        """Its evidence is a line extended in place. An atom has none, so an
        `index` claim entry would be the one entry nothing could check."""
        repo = _index_repo(tmp_path, EXTENDED)
        _ack(repo, ENTRY)
        _ack(repo, "index :: docs/REGISTER.md", path=CLAIM_ACK)
        r = _prove(repo, "--claims")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "unknown warrant 'index'" in r.stderr, r.stderr

    def test_the_help_names_it(self):
        r = subprocess.run(
            ["bash", str(PROVE), "--help"], capture_output=True, text=True, timeout=30
        )
        assert r.returncode == 0
        assert "The index warrant:" in r.stdout, r.stdout
        assert "    index      " in r.stdout, r.stdout
