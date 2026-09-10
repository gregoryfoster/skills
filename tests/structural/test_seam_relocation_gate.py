"""The source sweep's gate is relocation, not a vanished heading (#272).

Measured on a real curation of CannObserv/replicator (`main`, `b67a35c`), not
by reading the script. The run moved an ASCII flow diagram and the paragraph
above it out of `AGENTS.md` `## Project Overview` into
`docs/ARCHITECTURE.md`; the heading **stayed**, because it still carries the
identity line and a hard constraint. `check-seams.sh --base <branch-point>`
printed:

    note: 157 tracked source file(s) not swept — nothing left the policy file
    since --base, so a mention there is not fallout from this run.
    OK — no unacknowledged cross-reference seams.

Both halves were wrong. Content did leave — that is what the curation was for —
and the 157 files were skipped on the strength of the claim that it had not.

The gate was `if src and moved:`, and `moved` is a set of section TITLES. Its
docstring in `--help` said the honest thing — swept when a section "actually
LEFT the policy file" — and the proxy and the rationale come apart on the most
ordinary curation shape there is: a demotion out of a section that survives.
Phase 3's class B is "moves to `docs/<TOPIC>.md`" and nothing in the rubric says
the heading goes with it; for a Project Overview it usually must not, because
part of the section is class A.

The staleness the class exists to catch is fully reachable that way — a
docstring citing `AGENTS.md § Project Overview` for a diagram that now lives in
`docs/ARCHITECTURE.md` — and the failure mode is the one #113 named as worse
than missing everything: the clean exit reads as "swept". It is also a silent
under-report on the gate a curation PR cites as evidence, and the ledger row
records `seams: 0` either way, so the cohort data says "swept" too.

The doc-side classes are unaffected: back-references sweep unconditionally, and
a title that never moved has no referent to go stale.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SEAMS = ROOT / "skills" / "curating-context" / "scripts" / "check-seams.sh"


def _clean_env() -> dict:
    """STYLE.md § 'A repo-creating git command must scrub GIT_DIR': an inherited
    GIT_DIR outranks both `git -C` and the cwd, so a fixture repo would silently
    address the real checkout."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env=_clean_env(),
    )


def _write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SEAMS), "--base", "HEAD", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=60,
    )


# The replicator shapes, trimmed to the block that moved. Every line is long
# enough to clear the relocation floor, which is what the real paragraph and
# diagram row both do.
BASE_POLICY = (
    "# Replicator\n\n## Project Overview\n\n"
    "replicator turns bus commands into durable facts.\n\n"
    "The command to fact flow runs through the dispatcher and the fact "
    "writer:\n\n"
    "```\ncommand -> dispatcher -> fact writer -> store\n```\n\n"
    "Hard constraint: a fact is never rewritten in place.\n\n"
    "## Build\n\nrun make\n"
)

# The heading survives, carrying the identity line, the constraint and now a
# pointer. Only the diagram and its paragraph left.
NOW_POLICY = (
    "# Replicator\n\n## Project Overview\n\n"
    "replicator turns bus commands into durable facts.\n\n"
    "Hard constraint: a fact is never rewritten in place.\n\n"
    "What it owns and what it emits: "
    "[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).\n\n"
    "## Build\n\nrun make\n"
)

DEST = (
    "# Architecture\n\n## What it owns, and what it emits\n\n"
    "The command to fact flow runs through the dispatcher and the fact "
    "writer:\n\n"
    "```\ncommand -> dispatcher -> fact writer -> store\n```\n"
)


def _demoted_repo(tmp_path: Path, name: str = "demoted") -> Path:
    """A curation one commit old: a block left `## Project Overview`, and the
    heading stayed behind."""
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _write(repo, "AGENTS.md", BASE_POLICY)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "pre")
    _write(repo, "AGENTS.md", NOW_POLICY)
    _write(repo, "docs/ARCHITECTURE.md", DEST)
    return repo


class TestDemotionOutOfASurvivingSection:
    """No title left the policy file; a block did."""

    def test_the_stale_docstring_is_reported(self, tmp_path: Path):
        """The hit the whole sweep exists for, verbatim from replicator."""
        repo = _demoted_repo(tmp_path)
        _write(
            repo,
            "src/dispatch.py",
            '"""Dispatcher.\n\nThe command -> fact flow is in AGENTS.md '
            '§ Project Overview.\n"""\n',
        )
        _git(repo, "add", "-A")
        r = _run(repo)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "source-back-reference" in r.stdout, r.stdout
        assert "src/dispatch.py:3" in r.stdout, r.stdout

    def test_the_note_does_not_claim_nothing_left_the_policy_file(self, tmp_path: Path):
        """The sentence that talked the run out of checking by hand. "no
        section title left" is defensible; "nothing left" is not."""
        repo = _demoted_repo(tmp_path)
        _write(repo, "src/dispatch.py", '"""Nothing to see."""\n')
        _git(repo, "add", "-A")
        r = _run(repo)
        assert "not swept" not in r.stdout, r.stdout
        assert "swept 1 tracked source file(s)" in r.stdout, r.stdout

    def test_the_note_says_which_of_the_two_triggered_it(self, tmp_path: Path):
        """A reader cannot act on "swept" alone: with no moved title, the sweep
        looked for the filename and nothing else, and the report must say so
        rather than implying both halves ran."""
        repo = _demoted_repo(tmp_path)
        _write(repo, "src/dispatch.py", '"""Nothing to see."""\n')
        _git(repo, "add", "-A")
        r = _run(repo)
        assert "No section title left the policy file" in r.stdout, r.stdout
        assert "body line(s) did" in r.stdout, r.stdout

    def test_the_note_quotes_a_line_that_moved(self, tmp_path: Path):
        """CR 5: a claim a reader cannot check reads exactly like the over-claim
        this branch replaced. The `generic` note names the titles it narrowed to;
        this one names a line it counted."""
        repo = _demoted_repo(tmp_path)
        _write(repo, "src/dispatch.py", '"""Nothing to see."""\n')
        _git(repo, "add", "-A")
        r = _run(repo)
        assert "e.g." in r.stdout, r.stdout
        assert "The command to fact flow runs through the dispatcher" in r.stdout, (
            r.stdout
        )

    def test_no_source_still_disables_the_class(self, tmp_path: Path):
        """Relocation widens the gate; it does not outrank the opt-out."""
        repo = _demoted_repo(tmp_path)
        _write(repo, "src/dispatch.py", '"""Bounds live in AGENTS.md."""\n')
        _git(repo, "add", "-A")
        r = _run(repo, "--no-source")
        assert r.returncode == 0, r.stdout
        assert "--no-source" in r.stdout


class TestTheGateStillGates:
    """An unconditional source sweep is the outcome this gate exists to avoid:
    a repo whose scripts read the policy file for a living reports hundreds of
    legitimate mentions, and the only ack entry that silences noise at that
    scale is a blanket pattern in the repo's real seam ledger."""

    def test_a_pruned_line_that_landed_nowhere_does_not_trigger_the_sweep(
        self, tmp_path: Path
    ):
        """Relocation, not removal. A disproven claim deleted outright makes no
        source mention stale — there is no new home to point at."""
        repo = tmp_path / "pruned"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _write(repo, "AGENTS.md", BASE_POLICY)
        _write(repo, "src/dispatch.py", '"""Bounds live in AGENTS.md."""\n')
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre")
        _write(repo, "AGENTS.md", NOW_POLICY)
        r = _run(repo)
        assert r.returncode == 0, r.stdout
        assert "not swept" in r.stdout, r.stdout

    def test_a_short_line_reappearing_in_a_doc_does_not_trigger_the_sweep(
        self, tmp_path: Path
    ):
        """The floor. A coincidence between two short lines is not evidence of
        a move, and a false trigger here turns the whole class into noise."""
        repo = tmp_path / "short"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _write(repo, "AGENTS.md", "# Guide\n\n## Build\n\nrun make\n\nuv sync\n")
        _write(repo, "src/dispatch.py", '"""Bounds live in AGENTS.md."""\n')
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre")
        _write(repo, "AGENTS.md", "# Guide\n\n## Build\n\nrun make\n")
        _write(repo, "docs/SETUP.md", "# Setup\n\nuv sync\n")
        r = _run(repo)
        assert r.returncode == 0, r.stdout
        assert "not swept" in r.stdout, r.stdout

    def test_a_block_moved_outside_the_docs_root_does_not_trigger_the_sweep(
        self, tmp_path: Path
    ):
        """The predicate is scoped to the reference-doc tree, the same surface
        prove-no-loss.sh searches for a destination."""
        repo = _demoted_repo(tmp_path, "outside")
        (repo / "docs" / "ARCHITECTURE.md").unlink()
        _write(repo, "notes/ARCHITECTURE.md", DEST)
        _write(repo, "src/dispatch.py", '"""Bounds live in AGENTS.md."""\n')
        _git(repo, "add", "-A")
        r = _run(repo)
        assert r.returncode == 0, r.stdout
        assert "not swept" in r.stdout, r.stdout

    def test_an_archival_destination_does_not_trigger_the_sweep(self, tmp_path: Path):
        """An archival subtree recording what the policy file said is history,
        not a new home — the same exemption every other class makes. The names
        come from CTX_ARCHIVAL, so `archive` is one and a bare date is not."""
        repo = _demoted_repo(tmp_path, "archival")
        (repo / "docs" / "ARCHITECTURE.md").unlink()
        _write(repo, "docs/archive/ARCHITECTURE.md", DEST)
        _write(repo, "src/dispatch.py", '"""Bounds live in AGENTS.md."""\n')
        _git(repo, "add", "-A")
        r = _run(repo)
        assert r.returncode == 0, r.stdout
        assert "not swept" in r.stdout, r.stdout


# A command block, the thing Phase 3 demotes most often. Its comment line is a
# shell comment and its commands are short, which is the pair that made the
# first fix blind to it (CR 1).
FENCED_BASE = (
    "# Repo\n\n## Dev setup\n\n"
    "The hooks run the structural suite on every commit.\n\n"
    "```bash\n# activate the local git hooks\npre-commit install\n"
    "uv sync --frozen\n```\n"
)

FENCED_NOW = (
    "# Repo\n\n## Dev setup\n\n"
    "The hooks run the structural suite on every commit.\n\n"
    "Setup: [docs/SETUP.md](docs/SETUP.md).\n"
)

FENCED_DEST = (
    "# Setup\n\n```bash\n# activate the local git hooks\npre-commit install\n"
    "uv sync --frozen\n```\n"
)


def _fenced_repo(tmp_path: Path, name: str = "fenced") -> Path:
    """`## Dev setup` keeps its heading and its prose; only the command block
    moves to docs/SETUP.md."""
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _write(repo, "AGENTS.md", FENCED_BASE)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "pre")
    _write(repo, "AGENTS.md", FENCED_NOW)
    _write(repo, "docs/SETUP.md", FENCED_DEST)
    return repo


class TestAFencedBlockIsContentToo:
    """CR 1: inside a fence the whole line is the code, so a `#` there is a
    shell comment and not a heading — the asymmetry prove-no-loss.sh draws.

    Reading one as a heading discarded `# activate the local git hooks`, and the
    two commands beside it are 18 and 16 characters against a 24-character prose
    floor, so a command-block demotion out of a surviving section reported "not
    swept" with a stale docstring one file away. That is #272 in the shape Phase
    3 moves most often.
    """

    def test_a_demoted_command_block_opens_the_sweep(self, tmp_path: Path):
        repo = _fenced_repo(tmp_path)
        _write(
            repo, "src/hooks.py", '"""Hook installer. The list is in AGENTS.md."""\n'
        )
        _git(repo, "add", "-A")
        r = _run(repo)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "source-back-reference" in r.stdout, r.stdout
        assert "src/hooks.py:1" in r.stdout, r.stdout

    def test_a_fenced_comment_line_is_evidence_on_its_own(self, tmp_path: Path):
        """The line the heading rule used to discard. Alone in the block, it is
        still a line that left the policy file for a doc."""
        repo = tmp_path / "onlycomment"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _write(
            repo,
            "AGENTS.md",
            "# Repo\n\n## Dev setup\n\nThe hooks run on every commit.\n\n"
            "```bash\n# activate the local git hooks, once after cloning\n```\n",
        )
        _write(repo, "src/hooks.py", '"""See AGENTS.md."""\n')
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre")
        _write(
            repo,
            "AGENTS.md",
            "# Repo\n\n## Dev setup\n\nThe hooks run on every commit.\n",
        )
        _write(
            repo,
            "docs/SETUP.md",
            "# Setup\n\n```bash\n# activate the local git hooks, once after "
            "cloning\n```\n",
        )
        r = _run(repo)
        assert r.returncode == 3, r.stdout
        assert "source-back-reference" in r.stdout, r.stdout

    def test_a_markdown_heading_outside_a_fence_is_still_skipped(self, tmp_path: Path):
        """The asymmetry has to stay an asymmetry: a section heading that left
        is `moved`'s business, and counting it here would make every title move
        look like a relocation as well."""
        repo = tmp_path / "headingonly"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        # The heading is the ONLY line long enough to clear either floor, so if
        # it counted, this run would sweep.
        _write(
            repo,
            "AGENTS.md",
            "# Repo\n\n## Build\n\nrun make\n\n### A deliberately long subsection "
            "heading\n\nok\n",
        )
        _write(repo, "src/app.py", '"""See AGENTS.md."""\n')
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre")
        _write(repo, "AGENTS.md", "# Repo\n\n## Build\n\nrun make\n\nok\n")
        _write(
            repo,
            "docs/SUB.md",
            "# Sub\n\n### A deliberately long subsection heading\n\nok\n",
        )
        r = _run(repo)
        # The title left, so `moved` opens the sweep — but on the title, not on
        # a relocation, and the note is what says which.
        assert "moved title(s)" in r.stdout, r.stdout

    def test_a_short_fenced_command_is_still_under_the_floor(self, tmp_path: Path):
        """The fenced floor is lower, not absent. `uv sync` is seven characters
        and is shared by half the repos in the cohort."""
        repo = tmp_path / "shortfenced"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _write(
            repo,
            "AGENTS.md",
            "# Repo\n\n## Build\n\nrun make\n\n```bash\nuv sync\n```\n",
        )
        _write(repo, "src/app.py", '"""See AGENTS.md."""\n')
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre")
        _write(repo, "AGENTS.md", "# Repo\n\n## Build\n\nrun make\n")
        _write(repo, "docs/SETUP.md", "# Setup\n\n```bash\nuv sync\n```\n")
        r = _run(repo)
        assert r.returncode == 0, r.stdout
        assert "not swept" in r.stdout, r.stdout


class TestADemotedLinkIsContentToo:
    """CR 2: a demotion does not add `../` — it REMOVES a directory prefix,
    because the target is already inside the directory the content moved into.
    `](docs/KNOBS.md)` in a root policy file becomes `](KNOBS.md)` once the
    bullet lives in docs/INDEX.md.

    Erasing only the `../` half left every line of a demoted link list
    unmatched, which is the shape #137 measured as the commonest one — 12
    `retarget` warrants on one run and nothing else — and a Detail Docs list is
    what a curation demotes when it runs out of budget.
    """

    @staticmethod
    def _repo(tmp_path: Path, name: str) -> Path:
        repo = tmp_path / name
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _write(
            repo,
            "AGENTS.md",
            "# Repo\n\n## Detail Docs\n\nThe surface is indexed here.\n\n"
            "- [the knob inventory](docs/KNOBS.md) — every .skills/ file\n"
            "- [the style guide](docs/STYLE.md) — the gate-script rules\n",
        )
        _write(
            repo, "src/knobs.py", '"""Knob reader. The inventory is in AGENTS.md."""\n'
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre")
        _write(
            repo,
            "AGENTS.md",
            "# Repo\n\n## Detail Docs\n\nIndexed in [docs/INDEX.md](docs/INDEX.md).\n",
        )
        return repo

    def test_a_demoted_link_list_opens_the_sweep(self, tmp_path: Path):
        repo = self._repo(tmp_path, "linklist")
        _write(
            repo,
            "docs/INDEX.md",
            "# Index\n\n- [the knob inventory](KNOBS.md) — every .skills/ file\n"
            "- [the style guide](STYLE.md) — the gate-script rules\n",
        )
        r = _run(repo)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "source-back-reference" in r.stdout, r.stdout
        assert "src/knobs.py:1" in r.stdout, r.stdout

    def test_a_repointed_link_is_still_a_difference(self, tmp_path: Path):
        """Only the docs ROOT is erasable. `](lib/KNOBS.md)` is a repoint, not
        the prefix a sanctioned move removes, so the line does not compare equal
        — the same line this draws in prove-no-loss.sh."""
        repo = self._repo(tmp_path, "repointed")
        _write(
            repo,
            "docs/INDEX.md",
            "# Index\n\n- [the knob inventory](lib/KNOBS.md) — every .skills/ file\n"
            "- [the style guide](lib/STYLE.md) — the gate-script rules\n",
        )
        r = _run(repo)
        assert r.returncode == 0, r.stdout
        assert "not swept" in r.stdout, r.stdout

    def test_the_docs_root_as_the_policy_file_sees_it_is_erasable_too(
        self, tmp_path: Path
    ):
        """A skill curating its own surface passes `--docs-dir
        skills/demo/references` and writes `](references/X.md)`, so the
        repo-relative string alone is a no-op on every link that needs it — the
        reason prove-no-loss.sh erases two prefixes rather than one."""
        repo = tmp_path / "ownsurface"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _write(repo, "AGENTS.md", "# Repo policy\n\nnothing moved from here.\n")
        _write(
            repo,
            "skills/demo/SKILL.md",
            "# Demo\n\n## Detail Docs\n\nThe surface is indexed here.\n\n"
            "- [the topology](references/TOPOLOGY.md) — how the workers connect\n",
        )
        _write(repo, "src/app.py", '"""Bounds live in skills/demo/SKILL.md."""\n')
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre")
        _write(
            repo,
            "skills/demo/SKILL.md",
            "# Demo\n\n## Detail Docs\n\nIndexed in "
            "[references/INDEX.md](references/INDEX.md).\n",
        )
        _write(
            repo,
            "skills/demo/references/INDEX.md",
            "# Index\n\n- [the topology](TOPOLOGY.md) — how the workers connect\n",
        )
        _git(repo, "add", "-A")
        r = _run(
            repo,
            "--file",
            "skills/demo/SKILL.md",
            "--docs-dir",
            "skills/demo/references",
        )
        assert r.returncode == 3, r.stdout + r.stderr
        assert "source-back-reference" in r.stdout, r.stdout
        assert "src/app.py:1" in r.stdout, r.stdout


class TestRelocationOnADocSplit:
    """CR 6: `--file <doc>` is the documented other half of Phase 6.5, and the
    relocation predicate had no case there.

    #191 exists because a doc-to-doc split was structurally unreachable once
    already — it moves nothing out of the policy file, so the title class is
    empty in a policy-file run. The same split with the HEADING left behind is
    empty in BOTH classes unless relocation is measured against the target the
    run was given, and on this invocation the target's own docs tree is both the
    place a line left and the pool it may have landed in.
    """

    @staticmethod
    def _repo(tmp_path: Path, name: str) -> Path:
        repo = tmp_path / name
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _write(repo, "AGENTS.md", "# Guide\n\nNothing moved from here.\n")
        _write(
            repo,
            "docs/API.md",
            "# API\n\n## Pagination\n\nEvery list endpoint is cursor "
            "paginated.\n\nA cursor is opaque and expires after one hour.\n",
        )
        _write(
            repo,
            "src/paging.py",
            '"""Cursor helpers. The expiry rule is in docs/API.md."""\n',
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre")
        return repo

    def test_a_line_leaving_a_doc_for_a_sibling_opens_the_sweep(self, tmp_path: Path):
        """`## Pagination` keeps its heading and its first line; only the expiry
        rule moves to docs/PAGING.md."""
        repo = self._repo(tmp_path, "docsplit")
        _write(
            repo,
            "docs/API.md",
            "# API\n\n## Pagination\n\nEvery list endpoint is cursor "
            "paginated.\n\nCursor rules: [PAGING.md](PAGING.md).\n",
        )
        _write(
            repo,
            "docs/PAGING.md",
            "# Paging\n\nA cursor is opaque and expires after one hour.\n",
        )
        r = _run(repo, "--file", "docs/API.md")
        assert r.returncode == 3, r.stdout + r.stderr
        assert "source-back-reference" in r.stdout, r.stdout
        assert "src/paging.py:1" in r.stdout, r.stdout

    def test_a_line_still_inline_in_the_target_is_not_a_relocation(
        self, tmp_path: Path
    ):
        """The target is in its own docs tree, so every line it still carries is
        also "present under the docs root" — the pool has to be searched for
        lines the target no longer has, or a doc-split run would sweep on every
        line it kept."""
        repo = self._repo(tmp_path, "stillinline")
        # Both base lines stay; the run only ADDS a sentence. Every line the
        # target kept is reachable in the destination pool — it is the target —
        # so a predicate that did not subtract what is still inline would call
        # this a relocation and sweep.
        _write(
            repo,
            "docs/API.md",
            "# API\n\n## Pagination\n\nEvery list endpoint is cursor "
            "paginated.\n\nA cursor is opaque and expires after one "
            "hour.\n\nThe default page size is fifty items.\n",
        )
        r = _run(repo, "--file", "docs/API.md")
        assert r.returncode == 0, r.stdout
        assert "not swept" in r.stdout, r.stdout
