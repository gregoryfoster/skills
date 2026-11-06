"""`detect-stack.sh` says what a repo has, so one gate serves every repo (#537).

Two kinds of answer, kept apart (plan Step 5, rows 1 and 1b):

- `toolchain` decides which CHECKS run: `uv` (a pyproject.toml with a uv.lock
  or a [tool.uv] table), `composer` (a composer.json at the root, or one level
  under themes/ or plugins/), `npm` (a package.json, with composer's reach,
  #561, where a nested one counts only when git tracks it, CR 1844).
- `framework` decides only which DOCS apply — doc-check's default watch list
  and which references/stack-*.md loads: `fastapi` when fastapi is a declared
  dependency, `click` when click or typer is and fastapi is not, `php` for any
  composer toolchain.

A uv workspace (#552) is read as a whole: when the root has a
[tool.uv.workspace] table, the root and every member's pyproject.toml decide
the framework together, and members it cannot read make it `undetermined
framework` rather than nothing.

Output is one `kind<TAB>name` line per finding; nothing found is exit 0 with
no output. No API calls; each test gets a fresh repo.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "skills" / "shipping-work" / "scripts" / "detect-stack.sh"
# The global pathspec settings git exports to the hooks it runs, from
# `git --literal-pathspecs`, `--glob-pathspecs` and `--noglob-pathspecs`.
PATHSPEC_SETTINGS = [
    "GIT_LITERAL_PATHSPECS",
    "GIT_GLOB_PATHSPECS",
    "GIT_NOGLOB_PATHSPECS",
]


def _clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=_clean_env())
    return repo


def _run(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )


def _add(repo: Path) -> None:
    """Stage every file: a nested package.json counts only when tracked."""
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=_clean_env())


GIT_ID = (
    *("-c", "user.email=test@example.com", "-c", "user.name=test"),
    *("-c", "commit.gpgsign=false", "-c", "protocol.file.allow=always"),
)


def _commit_all(repo: Path) -> None:
    for args in (("add", "-A"), ("commit", "-q", "-m", "state")):
        subprocess.run(
            ["git", "-C", str(repo), *GIT_ID, *args], check=True, env=_clean_env()
        )


def _vendor_theme(repo: Path, tmp_path: Path) -> None:
    """A theme with a package.json and a composer.json in a repo of its own,
    added to `repo` as a submodule at themes/sub, and committed."""
    src = tmp_path / "theme-src"
    src.mkdir()
    subprocess.run(["git", "init", "-q", str(src)], check=True, env=_clean_env())
    (src / "package.json").write_text("{}\n")
    (src / "composer.json").write_text("{}\n")
    _commit_all(src)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            *GIT_ID,
            "submodule",
            "add",
            "-q",
            str(src),
            "themes/sub",
        ],
        check=True,
        capture_output=True,
        env=_clean_env(),
    )
    _commit_all(repo)


def _detect(repo: Path) -> set[tuple[str, str]]:
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    return {tuple(line.split("\t")) for line in result.stdout.splitlines()}


def _pyproject(repo: Path, deps: str = "", tool_uv: bool = False) -> None:
    text = f'[project]\nname = "demo-app"\ndependencies = [{deps}]\n'
    if tool_uv:
        text += "\n[tool.uv]\ndev-dependencies = []\n"
    (repo / "pyproject.toml").write_text(text)


class TestToolchains:
    def test_nothing(self, repo):
        assert _detect(repo) == set()

    def test_a_uv_lock_makes_pyproject_a_uv_repo(self, repo):
        _pyproject(repo)
        (repo / "uv.lock").write_text("version = 1\n")
        assert ("toolchain", "uv") in _detect(repo)

    def test_a_tool_uv_table_does_too(self, repo):
        _pyproject(repo, tool_uv=True)
        assert ("toolchain", "uv") in _detect(repo)

    def test_a_pyproject_uv_does_not_manage_is_not_one(self, repo):
        """A Poetry or pip project gets the remedy, not uv run against it."""
        _pyproject(repo)
        assert _detect(repo) == set()

    def test_composer_at_the_root(self, repo):
        (repo / "composer.json").write_text("{}\n")
        assert ("toolchain", "composer") in _detect(repo)

    @pytest.mark.parametrize("parent", ["themes", "plugins"])
    def test_composer_one_level_under_themes_or_plugins(self, repo, parent):
        (repo / parent / "site").mkdir(parents=True)
        (repo / parent / "site" / "composer.json").write_text("{}\n")
        assert ("toolchain", "composer") in _detect(repo)

    def test_npm(self, repo):
        (repo / "package.json").write_text("{}\n")
        assert _detect(repo) == {("toolchain", "npm")}

    @pytest.mark.parametrize("parent", ["themes", "plugins"])
    def test_npm_one_level_under_themes_or_plugins(self, repo, parent):
        """#561: a Sage-style monorepo with themes/ and plugins/ at the root
        keeps every package.json in its theme and plugin directories and none
        at the root, as composer's rule already allowed for composer.json."""
        (repo / parent / "site").mkdir(parents=True)
        (repo / parent / "site" / "package.json").write_text("{}\n")
        _add(repo)
        assert _detect(repo) == {("toolchain", "npm")}

    @pytest.mark.parametrize(
        "rel", ["themes/site/sub/package.json", "web/app/themes/site/package.json"]
    )
    def test_npm_no_deeper_than_composer_looks(self, repo, rel):
        """The same reach as composer's: a deeper manifest is not one."""
        (repo / rel).parent.mkdir(parents=True)
        (repo / rel).write_text("{}\n")
        _add(repo)
        assert _detect(repo) == set()

    def test_the_docs_claim_no_bedrock_reach(self):
        """CR 1852: the reach stops at themes/ and plugins/ at the root (the
        web/app/ case above), so neither the script nor stack-php.md may say
        it covers a Bedrock layout, and stack-php.md's Bedrock paragraph
        names npm beside composer as not searching web/app/."""
        assert "Sage/Bedrock" not in SCRIPT.read_text()
        php = (SCRIPT.parents[1] / "references" / "stack-php.md").read_text()
        bedrock = php.split("## Bedrock layouts", 1)[1].split("\n## ", 1)[0]
        assert "web/app/" in bedrock, bedrock
        assert "composer.json" in bedrock and "package.json" in bedrock, bedrock

    @pytest.mark.parametrize("ignored", [True, False])
    def test_a_nested_npm_manifest_git_does_not_track_is_not_one(self, repo, ignored):
        """CR 1844: a plugin composer installs is gitignored, and its
        package.json declaring lint:js failed the gate (`wp-scripts: command
        not found`). Only a tracked nested manifest counts."""
        (repo / "plugins" / "vendor-plugin").mkdir(parents=True)
        (repo / "plugins" / "vendor-plugin" / "package.json").write_text("{}\n")
        if ignored:
            (repo / ".gitignore").write_text("/plugins/vendor-plugin/\n")
            _add(repo)
        assert _detect(repo) == set()

    def test_a_theme_vendored_as_a_submodule_is_one(self, repo, tmp_path):
        """CR 1862: the superproject tracks a submodule as one gitlink, so the
        tracked-only rule (CR 1844) lost a submodule theme's npm while
        composer, which reads the tree, still found its composer.json."""
        _vendor_theme(repo, tmp_path)
        assert _detect(repo) == {
            ("toolchain", "composer"),
            ("framework", "php"),
            ("toolchain", "npm"),
        }

    def test_an_uninitialised_submodule_theme_is_neither(self, repo, tmp_path):
        """A clone that never ran `git submodule update` has an empty
        directory there: nothing to list and no composer.json on disk, so
        the two stacks agree on nothing, and nothing fails."""
        _vendor_theme(repo, tmp_path)
        clone = tmp_path / "clone"
        subprocess.run(
            ["git", "clone", "-q", str(repo), str(clone)],
            check=True,
            env=_clean_env(),
        )
        assert (clone / "themes" / "sub").is_dir()
        assert _detect(clone) == set()

    def test_a_dot_directory_is_not_one(self, repo):
        """CR 1866: git's `:(glob)` `*` matches a leading dot and bash's
        `themes/*` does not, so a tracked themes/.old/package.json counted
        while composer's reach skipped the same directory."""
        (repo / "themes" / ".old").mkdir(parents=True)
        (repo / "themes" / ".old" / "package.json").write_text("{}\n")
        (repo / "themes" / ".old" / "composer.json").write_text("{}\n")
        _add(repo)
        assert _detect(repo) == set()

    @pytest.mark.parametrize("setting", PATHSPEC_SETTINGS)
    def test_a_global_pathspec_setting_does_not_hide_a_theme(self, repo, setting):
        """CR 1861: `git --literal-pathspecs` exports GIT_LITERAL_PATHSPECS=1
        to the hooks it runs, and under it `:(glob)…` is a literal path:
        ls-files listed nothing, exit 0, and a theme's npm checks dropped out
        of the gate. The glob and noglob settings are held too."""
        (repo / "themes" / "site").mkdir(parents=True)
        (repo / "themes" / "site" / "package.json").write_text("{}\n")
        _add(repo)
        env = _clean_env()
        env[setting] = "1"
        result = subprocess.run(
            ["bash", str(SCRIPT)], cwd=repo, capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "toolchain\tnpm\n"

    def test_a_failing_ls_files_is_exit_2_not_none(self, repo, tmp_path):
        """git's own exit decides: a failure listing the nested manifests is
        a tooling failure, never "no npm"."""
        real = subprocess.run(
            ["sh", "-c", "command -v git"], capture_output=True, text=True, check=True
        ).stdout.strip()
        fakebin = tmp_path / "fakebin"
        fakebin.mkdir()
        (fakebin / "git").write_text(
            "#!/bin/sh\n"
            'case " $* " in *" ls-files "*) echo "fatal: index broken" >&2; exit 128;; esac\n'
            f'exec "{real}" "$@"\n'
        )
        (fakebin / "git").chmod(0o755)
        env = _clean_env()
        env["PATH"] = f"{fakebin}{os.pathsep}{env['PATH']}"
        result = subprocess.run(
            ["bash", str(SCRIPT)], cwd=repo, capture_output=True, text=True, env=env
        )
        assert result.returncode == 2, result.stdout
        assert "git ls-files failed (exit 128)" in result.stderr
        assert "index broken" in result.stderr

    def test_it_makes_no_temp_file_to_leak(self, repo, tmp_path):
        """CR 1868: the listing went through a `mktemp -d` that a signal or a
        set -e exit left behind. It needs none now: a mktemp that fails
        changes nothing."""
        (repo / "themes" / "site").mkdir(parents=True)
        (repo / "themes" / "site" / "package.json").write_text("{}\n")
        _add(repo)
        fakebin = tmp_path / "fakebin"
        fakebin.mkdir()
        (fakebin / "mktemp").write_text('#!/bin/sh\necho "mktemp called" >&2\nexit 1\n')
        (fakebin / "mktemp").chmod(0o755)
        env = _clean_env()
        env["PATH"] = f"{fakebin}{os.pathsep}{env['PATH']}"
        result = subprocess.run(
            ["bash", str(SCRIPT)], cwd=repo, capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, result.stderr
        assert "mktemp called" not in result.stderr
        assert result.stdout == "toolchain\tnpm\n"

    def test_a_lister_that_dies_unreported_is_exit_2(self, repo, tmp_path):
        """With no temp file, git's status arrives as the listing's last
        record. A lister killed before it reports is a failure, never "none"."""
        real = subprocess.run(
            ["sh", "-c", "command -v git"], capture_output=True, text=True, check=True
        ).stdout.strip()
        fakebin = tmp_path / "fakebin"
        fakebin.mkdir()
        (fakebin / "git").write_text(
            "#!/bin/sh\n"
            'case " $* " in *" ls-files "*) kill -9 "$PPID"; exit 0;; esac\n'
            f'exec "{real}" "$@"\n'
        )
        (fakebin / "git").chmod(0o755)
        env = _clean_env()
        env["PATH"] = f"{fakebin}{os.pathsep}{env['PATH']}"
        result = subprocess.run(
            ["bash", str(SCRIPT)], cwd=repo, capture_output=True, text=True, env=env
        )
        assert result.returncode == 2, result.stdout
        assert "git ls-files failed (exit unknown)" in result.stderr

    def test_every_stack_a_repo_has(self, repo):
        (repo / "composer.json").write_text("{}\n")
        (repo / "package.json").write_text("{}\n")
        found = _detect(repo)
        assert ("toolchain", "composer") in found
        assert ("toolchain", "npm") in found


class TestFrameworks:
    @pytest.mark.parametrize(
        "dep", ['"fastapi>=0.110"', '"fastapi[standard]"', '"FastAPI==0.1"']
    )
    def test_fastapi(self, repo, dep):
        _pyproject(repo, dep, tool_uv=True)
        assert ("framework", "fastapi") in _detect(repo)

    @pytest.mark.parametrize("dep", ['"click>=8"', '"typer"'])
    def test_click(self, repo, dep):
        _pyproject(repo, dep, tool_uv=True)
        found = _detect(repo)
        assert ("framework", "click") in found
        assert ("framework", "fastapi") not in found

    def test_fastapi_wins_over_click(self, repo):
        """A service that pulls in click for a management command is a service."""
        _pyproject(repo, '"fastapi", "click"', tool_uv=True)
        found = _detect(repo)
        assert ("framework", "fastapi") in found
        assert ("framework", "click") not in found

    def test_a_name_that_only_starts_with_one_is_not_it(self, repo):
        _pyproject(repo, '"clickhouse-driver", "fastapi-utils-x"', tool_uv=True)
        found = _detect(repo)
        assert ("framework", "click") not in found
        assert ("framework", "fastapi") not in found

    def test_php_comes_with_composer(self, repo):
        (repo / "composer.json").write_text("{}\n")
        assert ("framework", "php") in _detect(repo)

    def test_a_plain_uv_repo_has_no_framework(self, repo):
        _pyproject(repo, '"httpx"', tool_uv=True)
        assert _detect(repo) == {("toolchain", "uv")}


UV = ("toolchain", "uv")
UNDETERMINED = ("undetermined", "framework")


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _member(repo: Path, rel: str, deps: str = "") -> None:
    name = Path(rel).name
    _write(
        repo,
        f"{rel}/pyproject.toml",
        f'[project]\nname = "{name}"\ndependencies = [{deps}]\n',
    )


def _workspace(
    repo: Path,
    members: str | None = '["packages/*"]',
    deps: str = '"cannobserv", "co-core"',
    extra: str = "",
) -> None:
    """cannobserv's root [measured 2026-11-02]: no [build-system], and its
    dependencies are its own members, so the root names no framework."""
    table = "[tool.uv.workspace]\n"
    if members is not None:
        table += f"members = {members}\n"
    _write(
        repo,
        "pyproject.toml",
        '[project]\nname = "demo-workspace"\nrequires-python = ">=3.12"\n'
        f"dependencies = [{deps}]\n\n"
        "[tool.uv.sources]\ncannobserv = { workspace = true }\n\n"
        f"{table}{extra}\n"
        '[dependency-groups]\ndev = ["pytest>=8"]\n',
    )


class TestUvWorkspace:
    def test_a_virtual_root_with_one_click_member(self, repo):
        """#552's report: the framework lives in a member, not the root."""
        _workspace(repo)
        _member(repo, "packages/cannobserv", '"click>=8,<9"')
        _member(repo, "packages/co-core", '"httpx"')
        assert _detect(repo) == {UV, ("framework", "click")}

    def test_fastapi_in_one_member_wins_over_click_in_others(self, repo):
        """co-workspace's shape [measured 2026-11-02]: a root with real
        dependencies, none a framework, and an inner-spaced members array."""
        _workspace(
            repo,
            members='[ "packages/*" ]',
            deps='"co-shared", "pydantic>=2.5.0", "httpx>=0.25.0"',
        )
        _member(repo, "packages/api", '"fastapi>=0.104.0"')
        _member(repo, "packages/api_db", '"click>=8.0.0"')
        _member(
            repo,
            "packages/api_client",
            '"fastapi-code-generator>=0.5.4", "click>=8.0.0"',
        )
        _member(repo, "packages/shared", '"pydantic>=2"')
        assert _detect(repo) == {UV, ("framework", "fastapi")}

    def test_a_multi_line_members_array(self, repo):
        members = (
            "[\n"
            "    # the applications\n"
            '    "apps/*",\n'
            "    'libs/core',  # one path, single-quoted\n"
            "]"
        )
        _workspace(repo, members=members)
        _member(repo, "apps/web", '"httpx"')
        _member(repo, "libs/core", '"typer>=0.12"')
        assert _detect(repo) == {UV, ("framework", "click")}

    def test_exclude_is_honoured(self, repo):
        _workspace(repo, extra='exclude = ["packages/legacy"]\n')
        _member(repo, "packages/legacy", '"fastapi"')
        _member(repo, "packages/cli", '"click"')
        assert _detect(repo) == {UV, ("framework", "click")}

    def test_a_matched_directory_without_a_pyproject_is_skipped(self, repo):
        _workspace(repo)
        (repo / "packages" / "docs").mkdir(parents=True)
        (repo / "packages" / "README.md").write_text("x\n")
        _member(repo, "packages/cli", '"click"')
        assert _detect(repo) == {UV, ("framework", "click")}

    def test_a_member_path_with_a_space_is_one_member(self, repo):
        """bash 3.2 joins an array's words under an empty IFS; the glob's
        matches must stay one path each."""
        _workspace(repo, extra='exclude = ["packages/old one"]\n')
        _member(repo, "packages/my cli", '"click"')
        _member(repo, "packages/old one", '"fastapi"')
        _member(repo, "packages/zz", '"httpx"')
        assert _detect(repo) == {UV, ("framework", "click")}

    def test_no_members_key_is_a_root_only_workspace(self, repo):
        _workspace(repo, members=None, deps='"click"')
        _member(repo, "packages/api", '"fastapi"')
        assert _detect(repo) == {UV, ("framework", "click")}

    def test_an_empty_members_array_is_a_root_only_workspace(self, repo):
        _workspace(repo, members="[]", deps='"httpx"')
        assert _detect(repo) == {UV}

    def test_members_beside_no_workspace_table_are_not_read(self, repo):
        """The read is keyed on the table, not on the directory layout."""
        _pyproject(repo, '"httpx"', tool_uv=True)
        _member(repo, "packages/api", '"fastapi"')
        assert _detect(repo) == {UV}

    def test_fastapi_decides_it_even_when_a_pattern_matches_nothing(self, repo):
        """Nothing unread can outrank fastapi, so the answer is decided."""
        _workspace(repo, members='["packages/*", "services/*"]')
        _member(repo, "packages/api", '"fastapi"')
        assert _detect(repo) == {UV, ("framework", "fastapi")}

    @pytest.mark.parametrize(
        "members",
        [
            "MEMBERS",
            '"packages/*"',
            "[1, 2]",
            '["packages/*"',
            '[\n    "packages/*",\n',
            '["packages/**"]',
            '["services/*"]',
            '["packages/*", "services/*"]',
        ],
        ids=[
            "not-an-array",
            "a-bare-string",
            "not-strings",
            "unclosed-one-line",
            "unclosed-multi-line",
            "globstar",
            "matches-no-member",
            "one-of-two-matches-no-member",
        ],
    )
    def test_members_it_cannot_read_make_the_framework_undetermined(
        self, repo, members
    ):
        _workspace(repo, members=members)
        _member(repo, "packages/cli", '"click"')
        result = _run(repo)
        assert result.returncode == 0, result.stderr
        found = {tuple(line.split("\t")) for line in result.stdout.splitlines()}
        assert found == {UV, UNDETERMINED}
        assert "undetermined" in result.stderr

    def test_an_exclude_it_cannot_read_makes_the_framework_undetermined(self, repo):
        """An exclusion it can't read might be hiding the member that decides."""
        _workspace(repo, extra="exclude = EXCLUDED\n")
        _member(repo, "packages/cli", '"click"')
        assert _detect(repo) == {UV, UNDETERMINED}

    @pytest.mark.parametrize(
        "spelling",
        ['workspace = { members = ["packages/*"] }', 'workspace.members = ["p/*"]'],
        ids=["inline", "dotted"],
    )
    def test_a_workspace_key_under_tool_uv_is_undetermined(self, repo, spelling):
        """The same table in another spelling: flagged, not passed over."""
        _write(
            repo,
            "pyproject.toml",
            f'[project]\nname = "ws"\ndependencies = ["cli"]\n\n[tool.uv]\n{spelling}\n',
        )
        _member(repo, "packages/cli", '"click"')
        assert _detect(repo) == {UV, UNDETERMINED}

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root reads a mode-000 file, so unreadable cannot be staged",
    )
    def test_a_member_it_cannot_open_makes_the_framework_undetermined(self, repo):
        _workspace(repo)
        _member(repo, "packages/cli", '"click"')
        _member(repo, "packages/secret", '"httpx"')
        secret = repo / "packages" / "secret" / "pyproject.toml"
        secret.chmod(0)
        try:
            assert _detect(repo) == {UV, UNDETERMINED}
        finally:
            secret.chmod(0o644)

    def test_click_in_the_root_is_not_printed_beside_undetermined(self, repo):
        """`undetermined framework` replaces the Python framework line: an
        unread member could still declare fastapi."""
        _workspace(repo, members='["services/*"]', deps='"click"')
        found = _detect(repo)
        assert UNDETERMINED in found
        assert ("framework", "click") not in found


def test_outside_a_repository_is_exit_2(tmp_path):
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    assert result.returncode == 2


def test_help(tmp_path):
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "toolchain" in result.stdout and "framework" in result.stdout
    assert "undetermined framework" in result.stdout
