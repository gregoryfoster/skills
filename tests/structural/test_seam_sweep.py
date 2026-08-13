"""What check-seams.sh sweeps, and what it refuses to sweep (#131, #113).

Separate from test_context_surface.py's TestCheckSeams, which covers the three
original classes, because both cases here are about the sweep's *reach*: which
moved titles are specific enough to match bare prose (#131), and which files
the sweep looks at at all (#113). The helpers are local rather than imported —
these repos need tracked source files, which no existing fixture builds.

Every case is a measured defect, not a hypothetical:

- #131: a `curating-context` run on CannObserv/power-map split a doc into six
  per-resource docs with one-word titles (`People`, `Organizations`,
  `Jurisdictions`). The sweep returned 205 moved-title hits, every one a
  verified false positive — an admin breadcrumb, a scope-table row — against 0
  real references. The pre-existing floor was CHARACTER-based (>= 8), and
  `Organizations` is thirteen characters.
- #113: 16 docstring references across 13 shipped Python files cited the policy
  file for content the same run had just relocated, and the sweep reported zero
  of them while exiting clean. Seven of the sixteen cited the section title
  rather than the filename, so a filename-only grep finds nine.
"""

import os
import subprocess
from pathlib import Path

SEAMS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills" / "curating-context" / "scripts" / "check-seams.sh"
)


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, env=_clean_env())


def _write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


BASE_POLICY = (
    "# Guide\n\n## Build\n\nrun make\n\n"
    "## People\n\nEvery person carries a canonical name.\n\n"
    "## Organizations\n\nOrgs own assignments.\n\n"
    "## Deployment Topology\n\nThe workers connect to the bus directly.\n"
)

NOW_POLICY = (
    "# Guide\n\n## Build\n\nrun make\n\n## Detail Docs\n\n"
    "- [docs/ENTITIES.md](docs/ENTITIES.md) — entities\n"
)


def _moved_repo(tmp_path: Path, name: str = "seams") -> Path:
    """A curation one commit old: `People`, `Organizations` and `Deployment
    Topology` all left the policy file for docs/ENTITIES.md."""
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _write(repo, "AGENTS.md", BASE_POLICY)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "pre")
    _write(repo, "AGENTS.md", NOW_POLICY)
    _write(repo, "docs/ENTITIES.md",
           "# Entities\n\n## People\n\nEvery person carries a canonical "
           "name.\n\n## Organizations\n\nOrgs own assignments.\n\n"
           "## Deployment Topology\n\nThe workers connect to the bus "
           "directly.\n")
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SEAMS), "--base", "HEAD", *args],
        cwd=repo, capture_output=True, text=True, env=_clean_env(), timeout=60,
    )


class TestGenericMovedTitles:
    """#131: a one-word title matches every ordinary mention of the word."""

    def test_ordinary_prose_mentioning_a_one_word_title_is_not_a_seam(
            self, tmp_path: Path):
        """The three shapes measured on power-map, verbatim. None of them
        points at anything; all three were reported."""
        repo = _moved_repo(tmp_path)
        _write(repo, "docs/UI.md",
               "# UI\n\n"
               '<a href="/admin/orgs/">Organizations</a><span>*</span>\n'
               "| POST | /api/v1/organizations | organizations:write scope |\n"
               "- **No dup surface** — organizations have no dup tables\n")
        r = _run(repo)
        assert "moved-title" not in r.stdout, r.stdout
        assert r.returncode == 0, r.stdout

    def test_a_one_word_title_is_still_caught_where_something_points_at_it(
            self, tmp_path: Path):
        """The case the class exists for. `People` is one word, so it is only
        swept on lines that point somewhere — and this one does."""
        repo = _moved_repo(tmp_path)
        _write(repo, "docs/API.md",
               "# API\n\nSee docs/ENTITIES.md § People for the field list.\n")
        r = _run(repo)
        assert r.returncode == 3, r.stdout
        assert "moved-title" in r.stdout
        assert "docs/API.md:3" in r.stdout

    def test_a_section_marker_alone_corroborates(self, tmp_path: Path):
        repo = _moved_repo(tmp_path)
        _write(repo, "docs/API.md", "# API\n\nField list: § Organizations.\n")
        r = _run(repo)
        assert r.returncode == 3, r.stdout
        assert "docs/API.md:3" in r.stdout

    def test_a_markdown_link_corroborates(self, tmp_path: Path):
        repo = _moved_repo(tmp_path)
        _write(repo, "docs/API.md",
               "# API\n\nRead [People](#people) before adding a field.\n")
        r = _run(repo)
        assert r.returncode == 3, r.stdout
        assert "docs/API.md:3" in r.stdout

    def test_a_specific_title_is_still_swept_bare(self, tmp_path: Path):
        """Descriptive titles produced ZERO false positives on the same
        programme, and #113's source sweep depends on bare matching: seven of
        its sixteen misses named the title and nothing else."""
        repo = _moved_repo(tmp_path)
        _write(repo, "docs/API.md",
               "# API\n\nThe Deployment Topology section has the diagram.\n")
        r = _run(repo)
        assert r.returncode == 3, r.stdout
        assert "moved-title" in r.stdout
        assert "docs/API.md:3" in r.stdout

    def test_a_long_one_word_title_is_generic_too(self, tmp_path: Path):
        """The character floor was the whole filter, and `Organizations` is
        thirteen characters. Word count is what separates a pointer from a
        noun."""
        repo = _moved_repo(tmp_path)
        _write(repo, "docs/UI.md",
               "# UI\n\nOrganizations are listed alphabetically.\n")
        r = _run(repo)
        assert r.returncode == 0, r.stdout

    def test_the_report_names_the_titles_it_only_swept_for_pointers(
            self, tmp_path: Path):
        """A silent narrowing is the failure mode of a heuristic that fixes a
        flood: the run must be able to see which titles got the weaker sweep."""
        r = _run(_moved_repo(tmp_path))
        assert "People" in r.stdout and "Organizations" in r.stdout
        assert "Deployment Topology" not in r.stdout


class TestSourceSweep:
    """#113: the sweep read the policy file and docs/*.md and nothing else, so
    16 docstring references in shipped packages survived a clean exit — worse
    than missing all of them, because the clean exit reads as 'swept'."""

    def test_a_docstring_naming_the_policy_file_is_reported(
            self, tmp_path: Path):
        repo = _moved_repo(tmp_path)
        _write(repo, "src/app.py",
               '"""Bounds semantics live in AGENTS.md."""\n')
        _git(repo, "add", "-A")
        r = _run(repo)
        assert r.returncode == 3, r.stdout
        assert "source-back-reference" in r.stdout
        assert "src/app.py:1" in r.stdout

    def test_a_docstring_naming_only_the_moved_title_is_reported(
            self, tmp_path: Path):
        """Seven of the sixteen cited the section title and not the filename,
        so a filename-only grep finds nine."""
        repo = _moved_repo(tmp_path)
        _write(repo, "src/app.py",
               '"""Ordering follows the Deployment Topology section."""\n')
        _git(repo, "add", "-A")
        r = _run(repo)
        assert r.returncode == 3, r.stdout
        assert "source-moved-title" in r.stdout
        assert "src/app.py:1" in r.stdout

    def test_one_source_line_is_one_hit(self, tmp_path: Path):
        """A line naming both is one judgement, not two — the source classes
        must not drown the docs classes they sit beside."""
        repo = _moved_repo(tmp_path)
        _write(repo, "src/app.py",
               '"""See AGENTS.md, the Deployment Topology section."""\n')
        _git(repo, "add", "-A")
        r = _run(repo)
        assert "seams: 1" in r.stdout, r.stdout

    def test_untracked_source_is_not_swept(self, tmp_path: Path):
        """git ls-files keeps the sweep to tracked files and inherits the
        repo's ignore rules for free."""
        repo = _moved_repo(tmp_path)
        _write(repo, "build/generated.py", '"""See AGENTS.md."""\n')
        r = _run(repo)
        assert r.returncode == 0, r.stdout

    def test_markdown_outside_the_docs_tree_is_not_a_source_hit(
            self, tmp_path: Path):
        repo = _moved_repo(tmp_path)
        _write(repo, "README.md", "Conventions live in AGENTS.md.\n")
        _git(repo, "add", "-A")
        r = _run(repo)
        assert r.returncode == 0, r.stdout

    def test_archival_source_is_not_swept(self, tmp_path: Path):
        """A dated spec recording what AGENTS.md said at the time is correct
        history — the same exemption the docs sweep makes."""
        repo = _moved_repo(tmp_path)
        _write(repo, "specs/2026-01-01/gen.py", '"""Per AGENTS.md."""\n')
        _git(repo, "add", "-A")
        r = _run(repo)
        assert r.returncode == 0, r.stdout

    def test_the_skill_state_dir_is_not_swept(self, tmp_path: Path):
        """.skills holds the ack file and the telemetry ledger, both of which
        quote the policy filename by design."""
        repo = _moved_repo(tmp_path)
        _write(repo, ".skills/context-metrics.jsonl",
               '{"policy": "AGENTS.md", "tokens": 1}\n')
        _git(repo, "add", "-A")
        r = _run(repo)
        assert r.returncode == 0, r.stdout

    def test_binary_files_are_not_swept(self, tmp_path: Path):
        repo = _moved_repo(tmp_path)
        (repo / "blob.bin").write_bytes(b"AGENTS.md\x00\x01\x02")
        _git(repo, "add", "-A")
        r = _run(repo)
        assert r.returncode == 0, r.stdout

    def test_source_is_not_swept_when_nothing_left_the_policy_file(
            self, tmp_path: Path):
        """A source mention is fallout only if content moved. Sweeping
        unconditionally makes the class unreadable: this repo alone carries 180
        legitimate mentions in scripts that read the policy file for a living.
        The report says so rather than implying coverage it does not have."""
        repo = tmp_path / "unmoved"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _write(repo, "AGENTS.md", "# Guide\n\n## Build\n\nrun make\n")
        _write(repo, "src/app.py", '"""Bounds live in AGENTS.md."""\n')
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre")
        r = _run(repo)
        assert r.returncode == 0, r.stdout
        assert "not swept" in r.stdout

    def test_no_source_disables_the_class_and_says_so(self, tmp_path: Path):
        repo = _moved_repo(tmp_path)
        _write(repo, "src/app.py", '"""Bounds live in AGENTS.md."""\n')
        _git(repo, "add", "-A")
        r = _run(repo, "--no-source")
        assert r.returncode == 0, r.stdout
        assert "--no-source" in r.stdout

    def test_a_swept_run_reports_its_coverage(self, tmp_path: Path):
        repo = _moved_repo(tmp_path)
        _write(repo, "src/app.py", '"""Nothing to see."""\n')
        _git(repo, "add", "-A")
        r = _run(repo)
        assert r.returncode == 0, r.stdout
        assert "tracked source file(s)" in r.stdout

    def test_a_source_hit_can_be_acknowledged(self, tmp_path: Path):
        """The ack file's substring form works on the new classes, so a
        docstring that legitimately names the policy file is judged once."""
        repo = _moved_repo(tmp_path)
        _write(repo, "src/app.py",
               '"""Bounds semantics live in AGENTS.md."""\n')
        # The :: form, because a docstring's content does not start its line.
        _write(repo, ".skills/context-seams-ok",
               "src/app.py :: Bounds semantics live in AGENTS.md\n")
        _git(repo, "add", "-A")
        r = _run(repo)
        assert r.returncode == 0, r.stdout
        assert "seams_acked: 1" in r.stdout


SKILL_BASE = (
    "# Demo\n\n## Build\n\nrun make\n\n"
    "## Deployment Topology\n\nThe workers connect to the bus directly.\n"
)

SKILL_NOW = (
    "# Demo\n\n## Build\n\nrun make\n\n"
    "- [references/TOPOLOGY.md](references/TOPOLOGY.md) — topology\n"
)


def _skill_repo(tmp_path: Path, name: str = "skillseams") -> Path:
    """A skill's OWN surface: the policy file is `skills/demo/SKILL.md` and the
    docs root is its sibling `references/`. `AGENTS.md` exists at the root too,
    because a real repo has one — and it must not become the sweep's target
    just by existing."""
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _write(repo, "AGENTS.md", "# Repo policy\n\nnothing moved from here.\n")
    _write(repo, "skills/demo/SKILL.md", SKILL_BASE)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "pre")
    _write(repo, "skills/demo/SKILL.md", SKILL_NOW)
    _write(repo, "skills/demo/references/TOPOLOGY.md",
           "# Topology\n\n## Deployment Topology\n\nThe workers connect to "
           "the bus directly.\n")
    return repo


def _run_skill(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return _run(repo, "--file", "skills/demo/SKILL.md",
                "--docs-dir", "skills/demo/references", *args)


class TestBackReferencesFollowTheNamedPolicyFile:
    """#138: `--file` selected the target for every class except this one.

    `policy_names` was the hardcoded tuple `("AGENTS.md", "CLAUDE.md")`, so a
    run against `skills/curating-context/SKILL.md` hunted for the literal
    strings `AGENTS.md`/`CLAUDE.md` — and in a skill *about* curating
    `AGENTS.md` that returned 296 hits, every one subject matter and none a
    back-reference to the swept file. The only ack entry that silences noise at
    that scale is a blanket pattern, so the class was unusable rather than
    merely noisy: it forced a choice between ignoring the run and poisoning the
    repo's real seam ledger.
    """

    def test_the_policy_files_own_name_is_the_back_reference(
            self, tmp_path: Path):
        repo = _skill_repo(tmp_path)
        _write(repo, "skills/demo/references/TOPOLOGY.md",
               "# Topology\n\n## Deployment Topology\n\nThe workers connect "
               "to the bus directly.\n\nSee SKILL.md for the rest.\n")
        r = _run_skill(repo)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "back-reference" in r.stdout, r.stdout
        assert "See SKILL.md for the rest." in r.stdout, r.stdout

    def test_the_default_policy_names_are_not_swept_for_another_target(
            self, tmp_path: Path):
        """The 296-hit case. A doc that discusses `AGENTS.md` is discussing a
        file this run is not sweeping; it is subject matter, not a seam."""
        repo = _skill_repo(tmp_path)
        _write(repo, "skills/demo/references/TOPOLOGY.md",
               "# Topology\n\n## Deployment Topology\n\nThe workers connect "
               "to the bus directly.\n\nCurate AGENTS.md against a budget, "
               "and CLAUDE.md when it is a real file.\n")
        r = _run_skill(repo)
        assert r.returncode == 0, (
            f"a mention of another repo's policy file was called a seam:"
            f"\n{r.stdout}{r.stderr}"
        )

    def test_the_source_class_follows_the_target_too(self, tmp_path: Path):
        """The second call site, added by #113. Its guard is `src and moved`,
        so it needs a moved title present to run at all."""
        repo = _skill_repo(tmp_path)
        _write(repo, "src/app.py",
               '"""Curating AGENTS.md is what the demo skill documents."""\n')
        _git(repo, "add", "-A")
        r = _run_skill(repo)
        assert r.returncode == 0, (
            f"the source class swept for the wrong policy name:\n{r.stdout}"
        )

    def test_the_source_class_still_catches_the_named_policy_file(
            self, tmp_path: Path):
        repo = _skill_repo(tmp_path)
        _write(repo, "src/app.py",
               '"""Bounds semantics live in skills/demo/SKILL.md."""\n')
        _git(repo, "add", "-A")
        r = _run_skill(repo)
        assert r.returncode == 3, r.stdout
        assert "source-back-reference" in r.stdout, r.stdout

    def test_autodetection_still_sweeps_for_both_default_names(
            self, tmp_path: Path):
        """The cohort norm is `CLAUDE.md -> ./AGENTS.md`, so a doc naming
        either one back-references the one policy file. An autodetected run
        must not lose the sibling name."""
        repo = _moved_repo(tmp_path)
        _write(repo, "docs/ENTITIES.md",
               "# Entities\n\n## People\n\nEvery person carries a canonical "
               "name.\n\n## Organizations\n\nOrgs own assignments.\n\n"
               "## Deployment Topology\n\nThe workers connect to the bus "
               "directly.\n\nSee CLAUDE.md for the rest.\n")
        r = _run(repo)
        assert r.returncode == 3, r.stdout
        assert "See CLAUDE.md for the rest." in r.stdout, r.stdout

    def test_a_bare_name_outside_the_policy_files_own_tree_is_not_a_hit(
            self, tmp_path: Path):
        """The basename alone is not enough when the target is a SKILL.md.

        Deriving `policy_names` from the basename and stopping there trades 296
        AGENTS.md hits for 95 SKILL.md ones: this repo has twenty skills, and
        `SKILL.md` written in another skill's script or in a test is that other
        file's name, not a reference to the swept one. A bare mention resolves
        to the swept file only from inside its own directory tree; from
        anywhere else it takes a path.
        """
        repo = _skill_repo(tmp_path)
        _write(repo, "skills/other/SKILL.md", "# Other\n")
        _write(repo, "src/app.py",
               '"""Every skill ships a SKILL.md at its root."""\n')
        _git(repo, "add", "-A")
        r = _run_skill(repo)
        assert r.returncode == 0, (
            f"another skill's SKILL.md was called a back-reference:\n{r.stdout}"
        )

    def test_a_bare_name_inside_the_policy_files_own_tree_is_a_hit(
            self, tmp_path: Path):
        repo = _skill_repo(tmp_path)
        _write(repo, "skills/demo/scripts/run.sh",
               '# Bounds semantics live in SKILL.md.\n')
        _git(repo, "add", "-A")
        r = _run_skill(repo)
        assert r.returncode == 3, r.stdout
        assert "skills/demo/scripts/run.sh:1" in r.stdout, r.stdout

    def test_a_root_policy_file_is_swept_bare_everywhere(self, tmp_path: Path):
        """The scoping must not narrow the canonical shape: a policy file at
        the repo root owns the whole tree, so every file is inside it."""
        repo = _moved_repo(tmp_path)
        _write(repo, "src/deep/nested/app.py",
               '"""Bounds semantics live in AGENTS.md."""\n')
        _git(repo, "add", "-A")
        r = _run(repo)
        assert r.returncode == 3, r.stdout
        assert "src/deep/nested/app.py:1" in r.stdout, r.stdout
