"""check-seams.sh on a doc-to-doc split, and the anchoring that makes it usable (#191).

Two halves of one measured defect, found dogfooding `curating-context` v1.9 on
CannObserv/power-map#444 — a split of `docs/RUNBOOKS.md` into `docs/AUDITS.md`
plus `docs/RUNBOOK_DB_TRIAGE.md`:

- **The sweep never looked.** The moved-title class derives its title set from
  `--file` alone, and a doc-to-doc split moves nothing out of the policy file.
  So the run Phase 6.5 prescribes reported `seams: 0` while six headings
  changed home, and two stale prose cross-references rode a verbatim move into
  a brand-new doc where they read as freshly authored.
- **Passing `--file` was 69% noise.** Titles were matched as unanchored
  case-insensitive substrings, so the one-word `Fix` claimed `prefix`,
  `suffix`, `Prefix` and `IMF-fixdate`. Nine of thirteen hits on that run were
  that shape, and the noise is what made the correct invocation impractical.

The anchoring had to land at BOTH pattern sites — the docs class and the
tracked-source class each compiled their own `re.escape(orig)` — or the noise
would merely have moved from `moved-title` into `source-moved-title`. The two
`test_..._in_source` cases below are the second site's guard.

The Iron Law constrains the fix: the report is hits to JUDGE, so precision may
not be bought by making the sweep blind. Every anchoring case here is paired
with a recall case proving the real hit survives.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SEAMS = ROOT / "skills" / "curating-context" / "scripts" / "check-seams.sh"
SKILL = ROOT / "skills" / "curating-context" / "SKILL.md"


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


# The split source as it stood at --base. `Fix` and `Identify` are the short
# generic subsection titles that produced the flood; the other two are the
# descriptive titles whose references are the real fallout.
BASE_RUNBOOKS = (
    "# Runbooks\n\n"
    "## Audit cadence and retention\n\nAudits run weekly.\n\n"
    "## Org lifespan bounds on assignments\n\nBounds are inclusive.\n\n"
    "## DB triage\n\n### Identify\n\nFind the slow query.\n\n"
    "### Fix\n\nApply the index.\n\n"
    "## Deploy rollback\n\nRoll back with the script.\n"
)


def _split_repo(tmp_path: Path, delete_source: bool = False) -> Path:
    """A doc-to-doc split, one commit old. Nothing leaves AGENTS.md, which is
    precisely why a policy-file sweep of this run reports nothing.

    `delete_source` picks the two shapes a split comes in: power-map's source
    survived (10,886 -> 4,104 tokens), but a split that moves everything out
    deletes its source by construction.
    """
    repo = tmp_path / "split"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _write(
        repo,
        "AGENTS.md",
        "# Guide\n\n## Build\n\nrun make\n\n## Detail docs\n\n"
        "- [docs/RUNBOOKS.md](docs/RUNBOOKS.md) — runbooks\n",
    )
    _write(repo, "docs/RUNBOOKS.md", BASE_RUNBOOKS)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "pre")

    if delete_source:
        (repo / "docs" / "RUNBOOKS.md").unlink()
    else:
        _write(
            repo,
            "docs/RUNBOOKS.md",
            "# Runbooks\n\n## Deploy rollback\n\nRoll back with the script.\n",
        )
    _write(
        repo,
        "docs/AUDITS.md",
        "# Audits\n\n## Audit cadence and retention\n\nAudits run weekly.\n\n"
        "## Org lifespan bounds on assignments\n\nBounds are inclusive.\n",
    )
    _write(
        repo,
        "docs/RUNBOOK_DB_TRIAGE.md",
        "# Triage\n\n## Identify\n\nFind the slow query.\n\n"
        "## Fix\n\nApply the index.\n",
    )
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SEAMS), "--base", "HEAD", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=60,
    )


def _seam_count(r: subprocess.CompletedProcess) -> int:
    for line in reversed(r.stdout.splitlines()):
        if line.startswith("seams: "):
            return int(line.split(": ", 1)[1])
    raise AssertionError(f"no machine-readable seams line:\n{r.stdout}")


class TestTheSweepReachesADocToDocSplit:
    """Half one: the class was structurally empty, not merely quiet."""

    def test_without_file_a_doc_split_reports_nothing(self, tmp_path: Path):
        """The command Phase 6.5 used to show, on the run that filed #191.

        Asserted so the *reason* `--file` is prescribed cannot quietly stop
        being true: this is not a defect to fix in the policy-file run, it is
        the correct answer to the question that run asks. Nothing left
        AGENTS.md, so nothing about the split is knowable from it.
        """
        repo = _split_repo(tmp_path)
        _write(
            repo,
            "docs/SCHEMA.md",
            '# Schema\n\nSee docs/RUNBOOKS.md § "Audit cadence and retention".\n',
        )
        r = _run(repo)
        assert _seam_count(r) == 0, r.stdout
        assert r.returncode == 0, r.stdout

    def test_with_file_the_split_fallout_is_found(self, tmp_path: Path):
        """The same tree, swept the way Phase 6.5 now prescribes."""
        repo = _split_repo(tmp_path)
        _write(
            repo,
            "docs/SCHEMA.md",
            '# Schema\n\nSee docs/RUNBOOKS.md § "Audit cadence and retention".\n',
        )
        r = _run(repo, "--file", "docs/RUNBOOKS.md")
        assert r.returncode == 3, r.stdout
        assert "moved-title" in r.stdout
        assert "docs/SCHEMA.md:3" in r.stdout
        assert "Audit cadence and retention" in r.stdout

    def test_file_may_name_a_doc_the_split_deleted(self, tmp_path: Path):
        """The regression that made the documented fix unrunnable.

        A split that moves everything out deletes its source, and the live-file
        requirement then rejected `--file docs/RUNBOOKS.md` with exit 1 and
        "no policy file found" — on exactly the split it was meant to sweep.
        prove-no-loss.sh has always allowed this for the same reason.
        """
        repo = _split_repo(tmp_path, delete_source=True)
        _write(
            repo,
            "docs/SCHEMA.md",
            '# Schema\n\nSee § "Org lifespan bounds on assignments".\n',
        )
        r = _run(repo, "--file", "docs/RUNBOOKS.md")
        assert r.returncode == 3, f"{r.returncode}\n{r.stdout}\n{r.stderr}"
        assert "no policy file found" not in r.stderr
        assert "docs/SCHEMA.md:3" in r.stdout

    def test_a_deleted_source_says_so(self, tmp_path: Path):
        """ "Every title moved" is indistinguishable in the report from a doc
        emptied in place, and the two want different review."""
        repo = _split_repo(tmp_path, delete_source=True)
        r = _run(repo, "--file", "docs/RUNBOOKS.md")
        assert "docs/RUNBOOKS.md no longer exists" in r.stdout, r.stdout

    def test_autodetection_still_requires_a_live_file(self, tmp_path: Path):
        """Relaxing the check for an explicitly named file must not relax it for
        a guess. A repo with no policy file is a usage error, not an empty
        sweep that exits clean."""
        repo = tmp_path / "bare"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _write(repo, "README.md", "# R\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre")
        r = _run(repo)
        assert r.returncode == 1, f"{r.returncode}\n{r.stdout}\n{r.stderr}"
        assert "no policy file found" in r.stderr


class TestTitlesMatchAsWholeWords:
    """Half two. Each suppression case is paired with a recall case: precision
    bought by blinding the sweep is the failure mode the Iron Law names."""

    def test_a_short_title_does_not_match_inside_a_longer_word(self, tmp_path: Path):
        """The four measured shapes, on lines that all carry a pointer — so the
        generic tier's `.md`/`§` requirement is satisfied and cannot be what
        rejects them. Only anchoring can."""
        repo = _split_repo(tmp_path)
        _write(
            repo,
            "docs/PUBLIC_API.md",
            "# API\n\n"
            "Dates are RFC 9110 §5.6.7 IMF-fixdate strings.\n"
            "A suffix match is unsupported; see docs/SCHEMA.md.\n"
            "Prefix search is documented in docs/SCHEMA.md.\n"
            "Ordering uses a last-token prefix FTS index, see docs/X.md.\n",
        )
        r = _run(repo, "--file", "docs/RUNBOOKS.md", "--no-source")
        assert "moved-title" not in r.stdout, r.stdout
        assert _seam_count(r) == 0, r.stdout

    def test_a_short_title_is_still_caught_where_a_line_points_at_it(
        self, tmp_path: Path
    ):
        """Recall for the same title the case above suppresses. `Fix` is
        generic, so it needs a pointer — and quoted beside a § it has one."""
        repo = _split_repo(tmp_path)
        _write(
            repo,
            "docs/OPS.md",
            '# Ops\n\nWhen it stalls see docs/RUNBOOKS.md § "Fix".\n',
        )
        r = _run(repo, "--file", "docs/RUNBOOKS.md", "--no-source")
        assert r.returncode == 3, r.stdout
        assert "references 'Fix'" in r.stdout
        assert "docs/OPS.md:3" in r.stdout

    def test_a_short_title_does_not_match_inside_a_longer_word_in_source(
        self, tmp_path: Path
    ):
        """The SECOND pattern site. Anchoring only the docs class would have
        relocated these two hits into source-moved-title, not removed them."""
        repo = _split_repo(tmp_path)
        _write(
            repo,
            "src/app.py",
            'PREFIX = "IMF-fixdate"  # docs/SCHEMA.md\n'
            'SUFFIX_RE = r"suffix"  # docs/SCHEMA.md\n',
        )
        _git(repo, "add", "-A")
        r = _run(repo, "--file", "docs/RUNBOOKS.md")
        assert "source-moved-title" not in r.stdout, r.stdout

    def test_a_title_is_still_caught_in_source(self, tmp_path: Path):
        """Recall at the second site. A multi-word title is swept bare, which
        is the shape seven of #113's sixteen misses had."""
        repo = _split_repo(tmp_path)
        _write(
            repo,
            "src/app.py",
            '"""Ordering follows Org lifespan bounds on assignments."""\n',
        )
        _git(repo, "add", "-A")
        r = _run(repo, "--file", "docs/RUNBOOKS.md")
        assert r.returncode == 3, r.stdout
        assert "source-moved-title" in r.stdout
        assert "src/app.py:1" in r.stdout

    def test_a_descriptive_title_still_matches_bare_prose(self, tmp_path: Path):
        """Anchoring must not cost the bare tier its reach — a reference with no
        pointer on the line is a seam nothing else can see."""
        repo = _split_repo(tmp_path)
        _write(
            repo,
            "docs/OPS.md",
            "# Ops\n\nThe Audit cadence and retention rules apply here.\n",
        )
        r = _run(repo, "--file", "docs/RUNBOOKS.md", "--no-source")
        assert r.returncode == 3, r.stdout
        assert "docs/OPS.md:3" in r.stdout

    def test_a_title_whose_edges_are_punctuation_still_matches(self, tmp_path: Path):
        """Why the guard is per-edge and not a blanket `\\b`.

        A title is RAW heading text and may begin or end with punctuation. At
        such an edge `\\b` asserts that the NEIGHBOUR is a word character —
        the opposite of what is wanted — and the title would match nothing at
        all, silently deleting a whole class of real hits.
        """
        repo = tmp_path / "ticks"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _write(repo, "AGENTS.md", "# G\n\n## `--base` and its fallbacks\n\nx\n")
        _write(repo, "docs/K.md", "# K\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre")
        _write(repo, "AGENTS.md", "# G\n\n## Build\n\nx\n")
        _write(
            repo, "docs/K.md", "# K\n\nSee AGENTS.md § `--base` and its fallbacks.\n"
        )
        r = _run(repo, "--no-source")
        assert "moved-title" in r.stdout, r.stdout
        assert "docs/K.md:3" in r.stdout


class TestThePrescriptionIsDocumented:
    """The asymmetry #191 names is a DOCS defect first: the capability existed,
    and both the skill and the script steered away from it."""

    def test_phase_6_5_prescribes_file_for_a_split(self):
        body = SKILL.read_text().split("## Phase 6.5")[1].split("\n## ")[0]
        assert "--file" in body, body
        assert "split" in body, body

    def test_help_documents_file_beyond_the_policy_file(self):
        r = subprocess.run(
            ["bash", str(SEAMS), "--help"],
            capture_output=True,
            text=True,
            env=_clean_env(),
        )
        assert r.returncode == 0
        block = r.stdout.split("--file PATH")[1].split("--docs-dir")[0]
        assert "split" in block, block
        assert "REFERENCE DOC" in block, block
