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
