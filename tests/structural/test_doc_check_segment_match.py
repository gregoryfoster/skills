"""Behavioral tests for doc-check.sh: segment matching, dead-list reporting,
the project override file, and argument parsing.

Background ([#252](https://github.com/gregoryfoster/skills/issues/252)): the
matcher anchored every entry at position 0, so `src/` matched `src/foo.py` but
not `packages/co-core/src/foo.py`, and `pyproject.toml` matched only the root
one. Shipping a uv workspace that changed six library source files across three
packages, the gate printed `No sensitive paths changed` and exited 0. A gate
whose miss is byte-identical to its pass is worse than no gate, because the
skill presents it as a checkpoint that was cleared.

Three properties are pinned here, and they are load-bearing together:

- **Segment matching.** Entries match whole path components at any depth, so
  nested-package layouts — the ordinary shape of a uv or hatch workspace — stop
  being invisible. Every continuation requires a literal `/`, so
  `pyproject.toml` does not also claim `pyproject.toml.bak`, while a slash-less
  `docs` still names the directory the way prefix matching used to. Paths are
  read with `core.quotePath=false`: git's C-quoting puts a `"` in front of any
  path with a non-ASCII byte, which defeats an anchored match and reproduces
  the same silent green via a filename rather than via nesting.
- **Dead-entry reporting, on the green path only.** When nothing matched, the
  script probes the tree and says which entries could not have matched. When
  *no* entry can match anything tracked, that is not a pass — it exits 2, the
  documented "the gate did not run" code, which Step 1.5 already tells the
  agent to investigate. The probe is skipped on the exit-1 path, where the list
  has demonstrably hit and a dead-entry census would be noise.
- **The override file.** `.skills/doc-sensitive-paths` replaces the defaults,
  reusing the grammar `.skills/import-targets` already established, so a
  project tailors the list without forking a script that lives in four copies.

`TestBodyParity` is what keeps this true in all four copies at once.

No API calls. Self-contained: each test builds a throwaway git repo.
"""

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

VARIANTS = [
    "shipping-work",
    "shipping-work-php",
    "shipping-work-python-click",
    "shipping-work-python-fastapi",
]

# A nested path that each variant's own defaults must flag. Every row must MISS
# under the pre-#252 root-anchored matcher, or the case proves nothing — a
# Bedrock path under `web/app/plugins/` is already root-anchored, so the obvious
# php choice is exactly the one that passes against the unfixed script.
# `test_nested_hit_rows_are_real_regression_cases` enforces that.
NESTED_HITS = {
    "shipping-work": "vendor/co-core/src/api/routes.py",
    "shipping-work-php": "bedrock/web/app/themes/co/functions.php",
    "shipping-work-python-click": "packages/co-core/src/co_core/api.py",
    "shipping-work-python-fastapi": "services/ingest/src/models/user.py",
}


def _script(variant: str) -> Path:
    return SKILLS_DIR / variant / "scripts" / "doc-check.sh"


def _default_entries(variant: str) -> list[str]:
    """The variant's built-in SENSITIVE_PATHS, read out of the script."""
    block = re.search(
        r"^SENSITIVE_PATHS=\(\n(.*?)^\)", _script(variant).read_text(), re.S | re.M
    )
    assert block, f"{variant}/scripts/doc-check.sh must declare SENSITIVE_PATHS=(…)"
    entries = re.findall(r'"([^"]+)"', block.group(1))
    assert entries, f"{variant}/scripts/doc-check.sh declares an empty SENSITIVE_PATHS"
    return entries


def _root_anchored_hit(file: str, entry: str) -> bool:
    """The pre-#252 matcher: `case "$file" in "$entry"|"$entry"*)`."""
    return file.startswith(entry)


def _clean_env() -> dict:
    """Env without inherited GIT_* vars.

    Pre-commit and other tooling set GIT_INDEX_FILE / GIT_DIR / GIT_WORK_TREE,
    which would otherwise leak into the throwaway repo and point git at the
    parent checkout.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=_clean_env(),
    )


def _write(repo: Path, rel: str, body: str = "x\n") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def _run(
    repo: Path, variant: str = "shipping-work-python-click", *args: str
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_script(variant)), *args],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
    )


def _repo(tmp_path: Path, base_files: list[str], branch_files: list[str]) -> Path:
    """A repo with `base_files` committed on main and `branch_files` added on a
    feature branch. doc-check.sh auto-detects `main` as the base ref when no
    remote exists.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    for rel in base_files:
        _write(repo, rel)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    _git(repo, "checkout", "-b", "feature")
    for rel in branch_files:
        _write(repo, rel, "changed\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "work")
    return repo


# A tree where every click default is live, so the dead-entry probe stays quiet
# and each test's assertion is about the thing it names.
CLICK_LIVE_TREE = [
    "AGENTS.md",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "src/co/__init__.py",
    ".env.example",
    "docs/notes.md",
]


class TestSegmentMatching:
    def test_nested_src_is_flagged(self, tmp_path: Path):
        """The #252 repro: a library source file under packages/*/src/."""
        repo = _repo(
            tmp_path,
            CLICK_LIVE_TREE + ["packages/co-core/pyproject.toml"],
            ["packages/co-core/src/co_core/api.py"],
        )
        result = _run(repo)
        assert result.returncode == 1, (
            "a change under packages/co-core/src/ must be flagged; got exit "
            f"{result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "packages/co-core/src/co_core/api.py" in result.stdout

    def test_nested_pyproject_is_flagged(self, tmp_path: Path):
        """In a workspace, pyproject.toml exists once per package and is exactly
        the file a version bump touches."""
        repo = _repo(
            tmp_path,
            CLICK_LIVE_TREE + ["packages/co-core/pyproject.toml"],
            ["packages/co-core/pyproject.toml"],
        )
        result = _run(repo)
        assert result.returncode == 1, (
            f"a nested pyproject.toml must be flagged; got exit {result.returncode}\n"
            f"stdout: {result.stdout}"
        )
        assert "packages/co-core/pyproject.toml" in result.stdout

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_nested_hit_rows_are_real_regression_cases(self, variant: str):
        """A row that the old matcher already caught tests nothing. Keep the
        table honest here rather than discovering it the next time someone
        trusts a green parametrized case."""
        nested = NESTED_HITS[variant]
        already = [e for e in _default_entries(variant) if _root_anchored_hit(nested, e)]
        assert not already, (
            f"NESTED_HITS[{variant}] = {nested} is matched root-anchored by "
            f"{already}, so the case passes against the pre-#252 script and "
            "proves nothing about segment matching. Bury the path deeper."
        )

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_every_variant_matches_its_own_defaults_at_depth(
        self, variant: str, tmp_path: Path
    ):
        """The bug shipped in four copies; the fix has to hold in four copies."""
        nested = NESTED_HITS[variant]
        repo = _repo(tmp_path, ["README.md", nested], [nested])
        result = _run(repo, variant)
        assert result.returncode == 1, (
            f"{variant} must flag {nested}; got exit {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert nested in result.stdout

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_every_variant_matches_a_nested_readme(self, variant: str, tmp_path: Path):
        """README.md is a filename entry in all four; a package README is still
        a README."""
        repo = _repo(
            tmp_path, ["README.md", "packages/co-core/README.md"], ["packages/co-core/README.md"]
        )
        result = _run(repo, variant)
        assert result.returncode == 1, (
            f"{variant} must flag a nested README.md; got exit {result.returncode}\n"
            f"stdout: {result.stdout}"
        )

    @pytest.mark.parametrize(
        "suffixed", ["pyproject.toml.bak", "packages/co/pyproject.tomlish"]
    )
    def test_filename_entries_do_not_claim_suffixed_siblings(
        self, suffixed: str, tmp_path: Path
    ):
        """Segment matching must not degrade into prefix matching on filenames —
        `pyproject.toml*` would swallow backups and near-misses."""
        repo = _repo(tmp_path, CLICK_LIVE_TREE + [suffixed], [suffixed])
        result = _run(repo)
        assert result.returncode == 0, (
            f"{suffixed} is not pyproject.toml and must not be flagged; got exit "
            f"{result.returncode}\nstdout: {result.stdout}"
        )

    def test_root_anchored_matches_still_work(self, tmp_path: Path):
        """Segment matching is a superset — the root case must not regress."""
        repo = _repo(tmp_path, CLICK_LIVE_TREE, ["src/co/cli.py"])
        result = _run(repo)
        assert result.returncode == 1, (
            f"a change under root src/ must still be flagged; got exit {result.returncode}"
        )

    def test_slash_less_entries_still_name_directories(self, tmp_path: Path):
        """Root-anchored prefix matching accepted `docs` for the docs directory,
        whatever the header said about trailing slashes. Projects wrote lists
        against the behavior, so segment matching has to keep honoring it or a
        tailored list quietly loses coverage on upgrade."""
        repo = _repo(tmp_path, CLICK_LIVE_TREE, ["docs/other.md"])
        _write(repo, ".skills/doc-sensitive-paths", "docs\nsrc\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "slash-less list")
        result = _run(repo)
        assert result.returncode == 1, (
            "`docs` without a trailing slash must still cover docs/other.md; got "
            f"exit {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "docs/other.md" in result.stdout

    def test_non_ascii_paths_are_not_c_quoted(self, tmp_path: Path):
        """git C-quotes paths with non-ASCII bytes unless core.quotePath is off,
        and the leading quote defeats the anchored half of the matcher — the
        #252 miss-as-pass, reached by a filename instead of by nesting."""
        repo = _repo(tmp_path, CLICK_LIVE_TREE, ["src/co/café.py"])
        result = _run(repo)
        assert result.returncode == 1, (
            "a non-ASCII filename under src/ must be flagged; got exit "
            f"{result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "\\303" not in result.stdout, (
            f"paths must be reported raw, not octal-escaped:\n{result.stdout}"
        )


class TestDeadEntryReporting:
    def test_wholly_dead_list_exits_two(self, tmp_path: Path):
        """No entry can match anything tracked → the gate did not run. Reporting
        that as exit 0 is the #252 failure mode one layer up."""
        repo = _repo(tmp_path, ["docs/notes.md", "Makefile"], ["docs/other.md"])
        result = _run(repo)
        assert result.returncode == 2, (
            "a list that cannot match any tracked file is not a pass; got exit "
            f"{result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "misconfigured" in result.stderr
        assert ".skills/doc-sensitive-paths" in result.stderr
        assert "No sensitive paths changed" not in result.stdout, (
            "the green line must not appear alongside a did-not-run verdict"
        )

    def test_partially_dead_list_passes_with_a_note(self, tmp_path: Path):
        """Some entries live → the result is trustworthy, but say which entries
        could not have contributed to it."""
        repo = _repo(
            tmp_path, ["README.md", "pyproject.toml", "docs/notes.md"], ["docs/other.md"]
        )
        result = _run(repo)
        assert result.returncode == 0, (
            f"expected a pass; got exit {result.returncode}\nstderr: {result.stderr}"
        )
        assert "No sensitive paths changed" in result.stdout
        assert "match no tracked file" in result.stdout
        assert "src/" in result.stdout
        assert "uv.lock" in result.stdout
        assert "README.md" not in result.stdout.split("match no tracked file")[1], (
            "a live entry must not be listed as dead"
        )

    def test_fully_live_list_passes_without_a_note(self, tmp_path: Path):
        """The note is a signal, not decoration — a correctly tailored list must
        ship a clean green with nothing appended."""
        repo = _repo(tmp_path, CLICK_LIVE_TREE, ["docs/other.md"])
        result = _run(repo)
        assert result.returncode == 0, (
            f"expected a pass; got exit {result.returncode}\nstderr: {result.stderr}"
        )
        assert "No sensitive paths changed" in result.stdout
        assert "Note:" not in result.stdout, (
            f"no entry is dead, so no note is due:\n{result.stdout}"
        )

    def test_entries_live_only_at_depth_are_not_called_dead(self, tmp_path: Path):
        """The probe and the matcher have to agree. If the probe were written
        against root-anchored pathspecs it would call `src/` dead in exactly the
        workspace layout #252 is about — a false 'misconfigured' on a correctly
        tailored repo, which is the same defect pointed the other way."""
        repo = _repo(
            tmp_path,
            [
                "AGENTS.md",
                "README.md",
                "uv.lock",
                ".env.example",
                "packages/co/pyproject.toml",
                "packages/co/src/co/x.py",
                "docs/notes.md",
            ],
            ["docs/other.md"],
        )
        result = _run(repo)
        assert result.returncode == 0, (
            f"expected a pass; got exit {result.returncode}\nstderr: {result.stderr}"
        )
        assert "Note:" not in result.stdout, (
            "src/ and pyproject.toml exist only under packages/co/, which the "
            f"matcher covers, so neither is dead:\n{result.stdout}"
        )

    def test_non_ascii_paths_do_not_look_dead(self, tmp_path: Path):
        """The probe reads git output too, so it needs the same quoting fix."""
        repo = _repo(
            tmp_path,
            [
                "AGENTS.md",
                "README.md",
                "pyproject.toml",
                "uv.lock",
                ".env.example",
                "packages/café/src/co/x.py",
                "docs/notes.md",
            ],
            ["docs/other.md"],
        )
        result = _run(repo)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Note:" not in result.stdout, (
            "src/ is live — its only instance just has a non-ASCII ancestor:\n"
            f"{result.stdout}"
        )

    def test_failed_ls_files_is_reported_as_tooling_not_misconfiguration(
        self, tmp_path: Path
    ):
        """docs/STYLE.md's gate-script rule, in its concrete form here: if the
        probe's input silently fails, every entry looks unmatched and the script
        blames a path list that was fine. Both exits are 2, so only the message
        distinguishes a real tooling fault from a misconfigured list — and the
        reader acts on the message."""
        real_git = shutil.which("git")
        assert real_git, "git must be on PATH to run this test"
        shim = tmp_path / "bin"
        shim.mkdir()
        (shim / "git").write_text(
            "#!/usr/bin/env bash\n"
            'for a in "$@"; do [[ "$a" == "ls-files" ]] && exit 1; done\n'
            f'exec {shlex.quote(real_git)} "$@"\n'
        )
        (shim / "git").chmod(0o755)
        repo = _repo(tmp_path, CLICK_LIVE_TREE, ["docs/other.md"])
        env = _clean_env()
        env["PATH"] = f"{shim}:{env['PATH']}"
        result = subprocess.run(
            ["bash", str(_script("shipping-work-python-click"))],
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=env,
        )
        assert result.returncode == 2, (
            f"a failed ls-files must not pass; got exit {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "ls-files failed" in result.stderr, (
            f"the message must name the tooling fault:\n{result.stderr}"
        )
        assert "misconfigured" not in result.stderr, (
            f"the list is fine; blaming it sends the reader to the wrong fix:\n"
            f"{result.stderr}"
        )

    def test_no_dead_probe_on_the_hit_path(self, tmp_path: Path):
        """When the list has hit, a dead-entry census is noise: the answer is
        already actionable."""
        repo = _repo(tmp_path, ["README.md", "docs/notes.md"], ["README.md"])
        result = _run(repo)
        assert result.returncode == 1
        assert "match no tracked file" not in result.stdout, (
            f"exit-1 output must stay focused on the hits:\n{result.stdout}"
        )


class TestOverrideFile:
    def test_override_replaces_defaults_and_flags_its_own_paths(self, tmp_path: Path):
        repo = _repo(
            tmp_path,
            CLICK_LIVE_TREE + [".skills/doc-sensitive-paths"],
            ["docs/other.md"],
        )
        _write(repo, ".skills/doc-sensitive-paths", "docs/\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "tailor list")
        result = _run(repo)
        assert result.returncode == 1, (
            f"docs/ is in the override list and changed; got exit {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "docs/other.md" in result.stdout

    def test_override_replaces_rather_than_extends(self, tmp_path: Path):
        """A default that the override drops must stop firing — otherwise a
        project cannot narrow the list, only widen it."""
        repo = _repo(
            tmp_path,
            CLICK_LIVE_TREE + [".skills/doc-sensitive-paths"],
            ["src/co/cli.py"],
        )
        _write(repo, ".skills/doc-sensitive-paths", "docs/\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "tailor list")
        result = _run(repo)
        assert result.returncode == 0, (
            "src/ is not in the override list, so it must not fire; got exit "
            f"{result.returncode}\nstdout: {result.stdout}"
        )
        assert ".skills/doc-sensitive-paths" in result.stdout, (
            "the pass should name the list it consulted"
        )

    def test_override_ignores_comments_and_blank_lines(self, tmp_path: Path):
        repo = _repo(
            tmp_path,
            CLICK_LIVE_TREE + [".skills/doc-sensitive-paths"],
            ["docs/other.md"],
        )
        _write(
            repo,
            ".skills/doc-sensitive-paths",
            "# tailored for this workspace\n\n   docs/   \n\n",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "tailor list")
        result = _run(repo)
        assert result.returncode == 1, (
            "a commented, whitespace-padded entry is still an entry; got exit "
            f"{result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_empty_override_exits_two(self, tmp_path: Path):
        """An override file that yields no entries would otherwise pass
        everything — the same silent green, deliberately committed."""
        repo = _repo(
            tmp_path,
            CLICK_LIVE_TREE + [".skills/doc-sensitive-paths"],
            ["src/co/cli.py"],
        )
        _write(repo, ".skills/doc-sensitive-paths", "# nothing yet\n\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "empty list")
        result = _run(repo)
        assert result.returncode == 2, (
            f"an empty override list is a did-not-run; got exit {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "lists no paths" in result.stderr

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_every_variant_reads_the_override(self, variant: str, tmp_path: Path):
        repo = _repo(tmp_path, ["docs/notes.md"], ["docs/other.md"])
        _write(repo, ".skills/doc-sensitive-paths", "docs/\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "tailor list")
        result = _run(repo, variant)
        assert result.returncode == 1, (
            f"{variant} must honor .skills/doc-sensitive-paths; got exit "
            f"{result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestArgumentParsing:
    """#252 aside: --help and --base were checked only against $1, so every
    unrecognized argument was silently dropped. A typo then compared against
    the auto-detected base and reported a confident result for the wrong diff.
    """

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_unknown_argument_exits_two(self, variant: str, tmp_path: Path):
        repo = _repo(tmp_path, ["README.md"], ["README.md"])
        result = _run(repo, variant, "--bases", "main")
        assert result.returncode == 2, (
            f"{variant} must refuse an unknown argument rather than diff against "
            f"the wrong base; got exit {result.returncode}\nstdout: {result.stdout}"
        )
        assert "unknown argument: --bases" in result.stderr

    def test_base_without_a_ref_exits_two(self, tmp_path: Path):
        repo = _repo(tmp_path, ["README.md"], ["README.md"])
        result = _run(repo, "shipping-work-python-click", "--base")
        assert result.returncode == 2
        assert "--base requires a ref" in result.stderr

    def test_base_is_honored_and_not_positional(self, tmp_path: Path):
        """--base must work wherever it appears in the argument list."""
        repo = _repo(tmp_path, CLICK_LIVE_TREE, ["docs/other.md"])
        _git(repo, "branch", "other", "main")
        result = _run(repo, "shipping-work-python-click", "--base", "other")
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "vs other" in result.stdout, (
            f"--base must select the compared ref:\n{result.stdout}"
        )

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_help_exits_zero_and_documents_the_override(
        self, variant: str, tmp_path: Path
    ):
        repo = _repo(tmp_path, ["README.md"], ["README.md"])
        result = _run(repo, variant, "--help")
        assert result.returncode == 0
        assert ".skills/doc-sensitive-paths" in result.stdout
        assert "segments" in result.stdout


class TestBodyParity:
    """Below the configuration block the four variants are one script kept in
    four files. #252 existed in all four because nothing checked that; this is
    the check.
    """

    MARKER = re.compile(r"^# -{10,}$")

    def _body(self, variant: str) -> str:
        lines = _script(variant).read_text().splitlines()
        ends = [i for i, ln in enumerate(lines) if self.MARKER.match(ln)]
        assert len(ends) == 1, (
            f"{variant}/scripts/doc-check.sh must contain exactly one `# ---…` "
            f"marker line, the one closing its configuration block; found "
            f"{len(ends)} at lines {[i + 1 for i in ends]}. Splitting on the last "
            "of several would silently shrink the region this parity check "
            "compares, which is how four copies drift while the test stays green."
        )
        return "\n".join(lines[ends[0] + 1 :])

    def test_variant_inventory_is_exhaustive(self):
        discovered = sorted(
            p.parent.parent.name
            for p in SKILLS_DIR.glob("shipping-work*/scripts/doc-check.sh")
        )
        assert discovered == sorted(VARIANTS), (
            f"shipping-work* variants shipping a doc-check.sh {discovered} do not "
            f"match the tested set {sorted(VARIANTS)}. Add the new variant here so "
            "its copy of the matcher is held to the same behavior."
        )

    @pytest.mark.parametrize("variant", VARIANTS[1:])
    def test_body_is_identical_to_the_baseline(self, variant: str):
        assert self._body(variant) == self._body(VARIANTS[0]), (
            f"{variant}/scripts/doc-check.sh has drifted from "
            f"{VARIANTS[0]}/scripts/doc-check.sh below the configuration block. "
            "Variants differ in their path list and doc sections, not in their "
            "matcher — a fix applied to one copy has to reach all four."
        )
