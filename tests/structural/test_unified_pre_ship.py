"""The one `shipping-work` gate runs what the repo has (#537, plan Step 5).

`skills/shipping-work/scripts/pre-ship.sh` asks `detect-stack.sh` which
toolchains the repo has and runs every check each one owns, instead of one
variant per named stack. Each test names the Step 5 row it holds.

Every tool is faked: one Python recorder behind a tiny `sh` launcher per tool
name (the launcher dodges the kernel's shebang-length limit). It logs each
call as a JSON list and fails a call whose command line contains a FAKE_FAIL
substring. PATH is the fakes plus /usr/bin:/bin only, so a real uv, composer
or node on the host can never answer for a missing fake. No API calls; each
test gets a fresh repo.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.structural.gate_fakes import ALL_TOOLS, BASE_PATH, fake_env

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "skills" / "shipping-work" / "scripts" / "pre-ship.sh"
# The global pathspec settings git exports to the hooks it runs, from
# `git --literal-pathspecs`, `--glob-pathspecs` and `--noglob-pathspecs`.
PATHSPEC_SETTINGS = [
    "GIT_LITERAL_PATHSPECS",
    "GIT_GLOB_PATHSPECS",
    "GIT_NOGLOB_PATHSPECS",
]


def _git(repo: Path, *args: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env)


def _commit(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "state")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    return repo


def _uv_repo(repo: Path, deps: str = "") -> Path:
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "demo-app"\ndependencies = [{deps}]\n'
    )
    (repo / "uv.lock").write_text("version = 1\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("def test_x(): pass\n")
    _commit(repo)
    return repo


def _composer_repo(repo: Path) -> Path:
    (repo / "composer.json").write_text("{}\n")
    (repo / "index.php").write_text("<?php echo 1;\n")
    (repo / "themes" / "site").mkdir(parents=True)
    (repo / "themes" / "site" / "composer.json").write_text("{}\n")
    (repo / "themes" / "site" / "functions.php").write_text("<?php\n")
    _commit(repo)
    return repo


def _npm_repo(repo: Path, scripts: dict) -> Path:
    (repo / "package.json").write_text(json.dumps({"scripts": scripts}))
    _commit(repo)
    return repo


def _env(repo: Path, tools=ALL_TOOLS, **env: str) -> dict:
    """The fakes on PATH, and an environment that names them."""
    return fake_env(repo.parent / "fakebin", repo.parent / "tools.log", tools, **env)


def _gate(repo: Path, tools=ALL_TOOLS, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(GATE)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_env(repo, tools, **env),
        timeout=120,
    )


def _calls(repo: Path, tool: str | None = None) -> list[list[str]]:
    log = repo.parent / "tools.log"
    if not log.exists():
        return []
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    calls = [c for c in calls if c[1:2] != ["--version"]]
    return [c for c in calls if tool is None or c[0] == tool]


def _uv_tool_calls(repo: Path, name: str) -> list[list[str]]:
    """`uv run [uv args] <name> ...` calls, as the args after <name>."""
    out = []
    for call in _calls(repo, "uv"):
        if name in call:
            out.append(call[call.index(name) + 1 :])
    return out


def _pytest_args(repo: Path) -> list[str]:
    calls = _uv_tool_calls(repo, "pytest")
    assert len(calls) == 1, calls
    return calls[0]


class TestWhatRuns:
    def test_nothing_detected_is_exit_1_naming_the_remedy(self, repo):
        """Row 2."""
        _commit(repo)
        result = _gate(repo)
        assert result.returncode == 1
        assert "scripts/pre-ship.sh" in result.stderr

    def test_a_package_json_with_nothing_to_run_is_not_a_pass(self, repo):
        """A gate that ran no check verifies nothing; green would be a lie."""
        _npm_repo(repo, {"build": "tsc"})
        result = _gate(repo)
        assert result.returncode == 1
        assert "scripts/pre-ship.sh" in result.stderr
        # CR 1854: a root-only repo's line names no list, as `Detected:` does;
        # it said `no package.json (package.json) declares`.
        assert "no package.json declares lint:js" in result.stderr, result.stderr

    @pytest.mark.parametrize(
        ("build", "tool"),
        [(_uv_repo, "uv"), (_composer_repo, "composer")],
    )
    def test_a_detected_stack_with_its_tool_missing_is_exit_2(self, repo, build, tool):
        """Row 3.

        The fake is withheld, so only the real system directories could
        answer: Debian's apt package installs /usr/bin/composer, and there
        "missing" cannot be staged (CR 1397).
        """
        if shutil.which(tool, path=BASE_PATH):
            pytest.skip(
                f"{tool} is installed in {BASE_PATH}; it cannot be missing here"
            )
        build(repo)
        result = _gate(repo, tools=[t for t in ALL_TOOLS if t != tool])
        assert result.returncode == 2
        assert tool in result.stderr

    def test_it_says_what_it_detected(self, repo):
        """SKILL.md loads references/stack-<framework>.md from this line."""
        _uv_repo(repo, '"fastapi"')
        result = _gate(repo)
        assert "Detected: toolchain uv, framework fastapi" in result.stdout

    def test_it_says_when_a_workspaces_framework_is_undetermined(self, repo):
        """#552: a uv workspace whose members it can't read says so on the
        line, where it once printed no framework at all."""
        (repo / "pyproject.toml").write_text(
            '[project]\nname = "ws"\ndependencies = ["cli"]\n\n'
            '[tool.uv.workspace]\nmembers = ["services/*"]\n'
        )
        (repo / "uv.lock").write_text("version = 1\n")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_x.py").write_text("def test_x(): pass\n")
        _commit(repo)
        result = _gate(repo)
        assert "Detected: toolchain uv, undetermined framework" in result.stdout
        assert "services/*" in result.stderr

    def test_every_detected_stack_runs(self, repo):
        """Row 1: wordpress has composer AND npm."""
        _composer_repo(repo)
        _npm_repo(repo, {"test:js": "jest"})
        assert _gate(repo).returncode == 0
        assert _calls(repo, "composer")
        assert ["npm", "run", "test:js"] in _calls(repo)


class TestPython:
    def test_ruff_check_and_format_check(self, repo):
        """Rows 5 and 6: format runs in every uv repo, click ones included."""
        _uv_repo(repo, '"click"')
        assert _gate(repo).returncode == 0
        ruff = _uv_tool_calls(repo, "ruff")
        assert ["check", "."] in ruff
        assert ["format", "--check", "."] in ruff

    @pytest.mark.parametrize("where", ["demo_app", "src/demo_app"])
    def test_import_check_from_the_project_name(self, repo, where):
        """Row 7: every uv repo, `-` read as `_`, when the package is there."""
        (repo / where).mkdir(parents=True)
        (repo / where / "__init__.py").write_text("")
        _uv_repo(repo, '"fastapi"')
        assert _gate(repo).returncode == 0
        assert ["-c", "import demo_app"] in _uv_tool_calls(repo, "python")

    def test_a_guessed_target_with_no_package_is_skipped_with_a_note(self, repo):
        """Row 7, as revised: a guess is checked against the tree first.

        Most cohort services package their code as `src` (hatch
        `packages = ["src"]`), so `import <project name>` fails in every one
        of them. A guess that names no directory in the repo is a wrong guess,
        not broken packaging: it is skipped, and the note names the knob.
        """
        _uv_repo(repo, '"fastapi"')
        result = _gate(repo)
        assert result.returncode == 0, result.stderr
        assert ["-c", "import demo_app"] not in _uv_tool_calls(repo, "python")
        assert ".skills/import-targets" in result.stdout

    def test_import_targets_knob_wins(self, repo):
        _uv_repo(repo)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "import-targets").write_text("# pkgs\nalpha\nbeta\n")
        _commit(repo)
        assert _gate(repo).returncode == 0
        imports = [
            c
            for c in _uv_tool_calls(repo, "python")
            if len(c) > 1 and c[1].startswith("import ")
        ]
        assert [
            c[1] for c in imports if c[1] not in ("import pytest_cov", "import xdist")
        ] == [
            "import alpha",
            "import beta",
        ]

    def test_pytest_flags(self, repo):
        """Rows 10–13: no -x, no -v, integration deselected by plugin, --no-cov."""
        _uv_repo(repo)
        assert _gate(repo, FAKE_COV="1").returncode == 0
        args = _pytest_args(repo)
        assert "-x" not in args and "-v" not in args
        assert "-p" in args and "pre_ship_not_integration" in args
        assert "-m" not in args, "a command-line -m replaces the project's own (#304)"
        assert "--no-cov" in args

    def test_no_cov_only_when_pytest_cov_is_installed(self, repo):
        _uv_repo(repo)
        assert _gate(repo).returncode == 0
        assert "--no-cov" not in _pytest_args(repo)

    def test_collected_nothing_passes_with_a_note(self, repo):
        """Row 9."""
        _uv_repo(repo)
        result = _gate(repo, FAKE_PYTEST_RC="5")
        assert result.returncode == 0
        assert "collected no tests" in result.stdout + result.stderr

    def test_xdist_when_the_project_has_it(self, repo):
        """Row 14."""
        _uv_repo(repo)
        _gate(repo, FAKE_XDIST="1", PYTEST_XDIST_AUTO_NUM_WORKERS="3")
        args = _pytest_args(repo)
        assert args[args.index("-n") + 1] == "3"
        assert "loadfile" in args

    def test_the_dist_knob_reaches_pytest(self, repo):
        """#563, the issue's case: cli's suite sits in one 977-test file, which
        loadfile pins to one worker. `.skills/test-dist` says `load`."""
        _uv_repo(repo)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "test-dist").write_text("load\n")
        _commit(repo)
        result = _gate(repo, FAKE_XDIST="1", PYTEST_XDIST_AUTO_NUM_WORKERS="3")
        assert result.returncode == 0, result.stderr
        args = _pytest_args(repo)
        assert args[args.index("--dist") + 1] == "load"
        assert "loadfile" not in args

    def test_the_dist_env_wins_and_an_unknown_mode_is_loadfile(self, repo):
        _uv_repo(repo)
        _gate(
            repo,
            FAKE_XDIST="1",
            PYTEST_XDIST_AUTO_NUM_WORKERS="3",
            PYTEST_XDIST_DIST="worksteal",
        )
        args = _pytest_args(repo)
        assert args[args.index("--dist") + 1] == "worksteal"
        (repo.parent / "tools.log").unlink()
        result = _gate(
            repo,
            FAKE_XDIST="1",
            PYTEST_XDIST_AUTO_NUM_WORKERS="3",
            PYTEST_XDIST_DIST="each",
            GATE_STAMP="off",
        )
        assert result.returncode == 0, result.stderr
        args = _pytest_args(repo)
        assert args[args.index("--dist") + 1] == "loadfile"
        assert "'each'" in result.stderr

    def test_the_dist_mode_is_not_in_the_stamp_key(self, repo):
        """It sets how the suite is spread, so a pass under one mode is
        reused under another, as one under another worker count is."""
        _uv_repo(repo)
        _gate(repo, FAKE_XDIST="1", PYTEST_XDIST_AUTO_NUM_WORKERS="3")
        second = _gate(
            repo,
            FAKE_XDIST="1",
            PYTEST_XDIST_AUTO_NUM_WORKERS="3",
            PYTEST_XDIST_DIST="load",
        )
        assert "already passed" in second.stdout

    def test_serial_with_a_note_when_it_does_not(self, repo):
        _uv_repo(repo)
        result = _gate(repo, PYTEST_XDIST_AUTO_NUM_WORKERS="3")
        assert "-n" not in _pytest_args(repo)
        assert "xdist" in result.stderr

    def test_uv_args_knob_reaches_every_uv_call(self, repo):
        """Row 17."""
        _uv_repo(repo)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "pre-ship-uv-args").write_text("--group seed\n")
        _commit(repo)
        assert _gate(repo).returncode == 0
        # The import-target resolver's own call only reads pyproject.toml
        # (tomllib), as it does for reviewing-code; every check gets the args.
        runs = [
            c
            for c in _calls(repo, "uv")
            if c[1] == "run" and not any("tomllib" in a for a in c)
        ]
        assert runs and all(c[2:4] == ["--group", "seed"] for c in runs)


class TestPhp:
    def test_validate_every_composer_json(self, repo):
        """Row 18."""
        _composer_repo(repo)
        assert _gate(repo).returncode == 0
        validates = [c for c in _calls(repo, "composer") if "validate" in c]
        assert sorted(c[1] for c in validates) == [
            "--working-dir=.",
            "--working-dir=themes/site",
        ]

    def _validated(self, repo: Path) -> list[str]:
        return sorted(c[1] for c in _calls(repo, "composer") if "validate" in c)

    def test_a_gitignored_plugins_composer_json_is_not_validated(self, repo):
        """#588: composer installs a plugin into a gitignored plugins/<vendor>/,
        and `composer validate` ran on its composer.json as the repo's own,
        where a failure fails the gate on code the repo doesn't own. A
        nested composer.json counts only when git tracks it, as npm's does."""
        (repo / ".gitignore").write_text("/plugins/third-party/\n")
        _composer_repo(repo)
        (repo / "plugins" / "third-party").mkdir(parents=True)
        (repo / "plugins" / "third-party" / "composer.json").write_text("{}\n")
        result = _gate(repo)
        assert result.returncode == 0, result.stdout + result.stderr
        assert self._validated(repo) == [
            "--working-dir=.",
            "--working-dir=themes/site",
        ]

    def test_an_untracked_themes_composer_json_is_not_validated(self, repo):
        _composer_repo(repo)
        (repo / "themes" / "new").mkdir()
        (repo / "themes" / "new" / "composer.json").write_text("{}\n")
        assert _gate(repo).returncode == 0
        assert "--working-dir=themes/new" not in self._validated(repo)

    def test_a_submodule_themes_composer_json_is_not_validated(self, repo, tmp_path):
        """The operator's rule (2026-11-08): a repo gates only its own code,
        so a theme vendored as a submodule is validated in its own repo."""
        src = tmp_path / "theme-src"
        src.mkdir()
        _git(src, "init", "-q", "-b", "main")
        _git(src, "config", "user.email", "test@example.com")
        _git(src, "config", "user.name", "test")
        (src / "composer.json").write_text("{}\n")
        _commit(src)
        _composer_repo(repo)
        _git(
            repo,
            *("-c", "protocol.file.allow=always", "submodule", "add", "-q"),
            *(str(src), "themes/sub"),
        )
        _commit(repo)
        assert (repo / "themes" / "sub" / "composer.json").is_file()
        assert _gate(repo).returncode == 0
        assert self._validated(repo) == [
            "--working-dir=.",
            "--working-dir=themes/site",
        ]

    def test_lint_every_tracked_php_file(self, repo):
        """Row 19."""
        _composer_repo(repo)
        assert _gate(repo).returncode == 0
        linted = sorted(c[2] for c in _calls(repo, "php") if c[1] == "-l")
        assert linted == ["index.php", "themes/site/functions.php"]

    @pytest.mark.parametrize("setting", PATHSPEC_SETTINGS)
    def test_a_global_pathspec_setting_lints_every_tracked_php_file(
        self, repo, setting
    ):
        """CR 1861: git exports these to the hooks it runs. Under the literal
        setting the bare `*.php` listed nothing with exit 0, under noglob
        nothing, and under glob only the root's files: php -l linted less
        than the repo has, and the gate passed."""
        _composer_repo(repo)
        assert _gate(repo, **{setting: "1"}).returncode == 0
        linted = sorted(c[2] for c in _calls(repo, "php") if c[1] == "-l")
        assert linted == ["index.php", "themes/site/functions.php"]

    def test_composer_test_only_when_defined(self, repo):
        """Row 20."""
        _composer_repo(repo)
        _gate(repo)
        assert ["composer", "test"] not in _calls(repo)
        # Same tree, so the first pass would be reused; force the second run.
        _gate(repo, FAKE_COMPOSER_TEST="1", GATE_STAMP="off")
        assert ["composer", "test"] in _calls(repo)

    def test_a_script_list_that_fails_is_shown_and_fails(self, repo):
        """Row 20: today's probe discarded stderr and skipped composer test."""
        _composer_repo(repo)
        result = _gate(repo, FAKE_COMPOSER_LIST_FAIL="1")
        assert result.returncode == 1
        assert "could not read composer.json" in result.stderr


def _manifest(repo: Path, rel: str, scripts: dict | None = None) -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(json.dumps({"scripts": scripts or {}}))


def _cwd_calls(repo: Path, tool: str) -> list[tuple[str, list[str]]]:
    """(directory relative to the repo, argv) for each logged `tool` call."""
    log = repo.parent / "cwd.log"
    if not log.exists():
        return []
    out = []
    for line in log.read_text().splitlines():
        cwd, name, *argv = json.loads(line)
        if name == tool and argv[:1] != ["--version"]:
            rel = os.path.relpath(os.path.realpath(cwd), os.path.realpath(repo))
            out.append((rel, argv))
    return out


def _npm_gate(repo: Path, tools=ALL_TOOLS, **env: str) -> subprocess.CompletedProcess:
    return _gate(repo, tools, TOOL_CWD_LOG=str(repo.parent / "cwd.log"), **env)


class TestNpmManifests:
    """#561: npm is found at the root or one level under themes/ and plugins/,
    as composer is, where a nested manifest counts only when git tracks it
    (CR 1844), and each manifest's scripts run in its own directory."""

    def test_the_issues_layout(self, repo):
        """The issue's own reproduction: no root package.json, and a theme's
        package.json that declares lint:js."""
        _manifest(repo, "themes/sage/package.json", {"lint:js": "eslint ."})
        _commit(repo)
        result = _npm_gate(repo)
        assert result.returncode == 0, result.stderr
        assert "=== npm run lint:js (themes/sage) ===" in result.stdout
        assert _cwd_calls(repo, "npm") == [("themes/sage", ["run", "lint:js"])]

    def test_the_root_keeps_its_heading_beside_nested_ones(self, repo):
        _manifest(repo, "package.json", {"test:js": "jest"})
        _manifest(repo, "themes/sage/package.json", {"lint:js": "eslint ."})
        _manifest(repo, "plugins/blocks/package.json", {"test:js": "jest"})
        _commit(repo)
        result = _npm_gate(repo)
        assert result.returncode == 0, result.stderr
        assert "=== npm run test:js ===" in result.stdout
        assert "=== npm run lint:js (themes/sage) ===" in result.stdout
        assert "=== npm run test:js (plugins/blocks) ===" in result.stdout
        assert _cwd_calls(repo, "npm") == [
            (".", ["run", "test:js"]),
            ("themes/sage", ["run", "lint:js"]),
            ("plugins/blocks", ["run", "test:js"]),
        ]

    def test_the_detected_line_names_the_manifests(self, repo):
        _manifest(repo, "package.json", {"test:js": "jest"})
        _manifest(repo, "themes/sage/package.json", {"lint:js": "eslint ."})
        _commit(repo)
        result = _npm_gate(repo)
        assert (
            "Detected: toolchain npm (package.json, themes/sage/package.json)"
            in result.stdout
        )

    def test_a_root_only_detected_line_is_unchanged(self, repo):
        _npm_repo(repo, {"test:js": "jest"})
        assert "Detected: toolchain npm\n" in _npm_gate(repo).stdout

    def test_a_nested_failure_is_named_by_its_directory(self, repo):
        _manifest(repo, "themes/sage/package.json", {"lint:js": "eslint ."})
        _manifest(repo, "plugins/blocks/package.json", {"test:js": "jest"})
        _commit(repo)
        result = _npm_gate(repo, FAKE_FAIL="lint:js")
        assert result.returncode == 1
        assert "npm run lint:js (themes/sage) (exit 1)" in result.stderr
        assert ("plugins/blocks", ["run", "test:js"]) in _cwd_calls(repo, "npm")

    def test_a_manifest_with_no_scripts_runs_nothing_and_needs_no_npm(self, repo):
        """No declared script anywhere is the empty-array path, run under the
        /bin/bash on PATH (3.2 on macOS, where an empty "${arr[@]}" aborts
        under set -u). composer keeps the gate from stopping at 'nothing to
        run', so the npm loops run empty."""
        if shutil.which("npm", path=BASE_PATH):
            pytest.skip(f"npm is installed in {BASE_PATH}; it cannot be missing here")
        _composer_repo(repo)
        _manifest(repo, "themes/site/package.json", {"build": "vite build"})
        _commit(repo)
        result = _npm_gate(repo, tools=[t for t in ALL_TOOLS if t != "npm"])
        assert result.returncode == 0, result.stderr
        assert _cwd_calls(repo, "npm") == []

    def test_nested_manifests_with_nothing_to_run_are_not_a_pass(self, repo):
        _manifest(repo, "themes/sage/package.json", {"build": "vite build"})
        _commit(repo)
        result = _npm_gate(repo)
        assert result.returncode == 1
        assert "themes/sage/package.json" in result.stderr
        assert "scripts/pre-ship.sh" in result.stderr

    def test_a_nested_manifest_that_does_not_parse_is_exit_2_naming_it(self, repo):
        _manifest(repo, "package.json", {"test:js": "jest"})
        (repo / "plugins" / "broken").mkdir(parents=True)
        (repo / "plugins" / "broken" / "package.json").write_text("{not json\n")
        _commit(repo)
        result = _npm_gate(repo)
        assert result.returncode == 2
        assert "plugins/broken/package.json failed to parse" in result.stderr
        assert _cwd_calls(repo, "npm") == []

    def test_a_gitignored_plugins_manifest_is_not_run(self, repo):
        """CR 1844, the reviewer's reproduction: composer installs a plugin
        into a gitignored plugins/<vendor>/, whose package.json declares
        lint:js. Run, it failed the gate (`wp-scripts: command not found`).
        Only tracked nested manifests run, and detect-stack.sh agrees."""
        (repo / ".gitignore").write_text("/plugins/third-party/\n")
        _manifest(repo, "themes/sage/package.json", {"test:js": "jest"})
        _manifest(repo, "plugins/third-party/package.json", {"lint:js": "wp-scripts"})
        _commit(repo)
        result = _npm_gate(repo)
        assert result.returncode == 0, result.stderr
        assert _cwd_calls(repo, "npm") == [("themes/sage", ["run", "test:js"])]
        assert "plugins/third-party" not in result.stdout

    def test_only_a_gitignored_manifest_is_nothing_detected(self, repo):
        (repo / ".gitignore").write_text("/plugins/third-party/\n")
        _manifest(repo, "plugins/third-party/package.json", {"lint:js": "wp-scripts"})
        _commit(repo)
        result = _npm_gate(repo)
        assert result.returncode == 1
        assert "no toolchain detected" in result.stderr
        assert _cwd_calls(repo, "npm") == []

    def test_a_theme_vendored_as_a_submodule_is_not_run(self, repo, tmp_path):
        """The operator's rule (2026-11-08, on #588 and #605): a repo gates
        only its own code. A theme vendored as a submodule runs its scripts
        in its own repo's gate, so the listing no longer recurses into it.
        This reverses CR 1862. The root's scripts still run."""
        src = tmp_path / "theme-src"
        src.mkdir()
        _git(src, "init", "-q", "-b", "main")
        _git(src, "config", "user.email", "test@example.com")
        _git(src, "config", "user.name", "test")
        _manifest(src, "package.json", {"lint:js": "wp-scripts"})
        _commit(src)
        _manifest(repo, "package.json", {"test:js": "jest"})
        _git(
            repo,
            *("-c", "protocol.file.allow=always", "submodule", "add", "-q"),
            *(str(src), "themes/sub"),
        )
        _commit(repo)
        assert (repo / "themes" / "sub" / "package.json").is_file()
        result = _npm_gate(repo, FAKE_FAIL="lint:js")
        assert result.returncode == 0, result.stdout + result.stderr
        assert _cwd_calls(repo, "npm") == [(".", ["run", "test:js"])]
        assert "themes/sub" not in result.stdout

    def test_an_untracked_themes_user_is_pointed_at_git_add(self, repo):
        """CR 1867: a new theme's package.json, not yet added, is not
        detected; the advice and --help say a nested one must be tracked
        instead of saying it is found one level under themes/."""
        _commit(repo)
        _manifest(repo, "themes/new/package.json", {"lint:js": "eslint ."})
        result = _npm_gate(repo)
        assert result.returncode == 1
        assert "no toolchain detected" in result.stderr
        assert "only once git tracks it (git add" in result.stderr, result.stderr
        help_text = subprocess.run(
            ["bash", str(GATE), "--help"], capture_output=True, text=True
        ).stdout
        assert "each one git" in help_text and "git add" in help_text, help_text

    def test_a_dot_directorys_manifest_is_not_run(self, repo):
        """CR 1866: git's `:(glob)` `*` matches a leading dot, bash's
        `themes/*` (composer's reach) does not, so a tracked
        themes/.old/package.json ran its scripts."""
        _manifest(repo, "package.json", {"test:js": "jest"})
        _manifest(repo, "themes/.old/package.json", {"lint:js": "eslint ."})
        _commit(repo)
        result = _npm_gate(repo)
        assert result.returncode == 0, result.stdout + result.stderr
        assert _cwd_calls(repo, "npm") == [(".", ["run", "test:js"])]
        assert "themes/.old" not in result.stdout

    @pytest.mark.parametrize("setting", PATHSPEC_SETTINGS)
    def test_a_global_pathspec_setting_keeps_a_themes_failure(self, repo, setting):
        """CR 1861: under GIT_LITERAL_PATHSPECS=1, which `git
        --literal-pathspecs` exports to hooks, `:(glob)…` was a literal path,
        so a theme's failing test:js dropped out and the gate passed."""
        _manifest(repo, "themes/sage/package.json", {"test:js": "jest"})
        _manifest(repo, "package.json", {"lint:js": "eslint ."})
        _commit(repo)
        result = _npm_gate(repo, FAKE_FAIL="test:js", **{setting: "1"})
        assert result.returncode == 1, result.stdout + result.stderr
        assert "npm run test:js (themes/sage) (exit 1)" in result.stderr
        assert ("themes/sage", ["run", "test:js"]) in _cwd_calls(repo, "npm")

    def test_a_nested_trigger_keys_the_npm_tools(self, repo):
        """The stamp key carries node's and npm's versions for a nested
        manifest exactly as for a root one."""
        _manifest(repo, "themes/sage/package.json", {"lint:js": "eslint ."})
        _commit(repo)
        assert _npm_gate(repo).returncode == 0
        assert "already passed" in _npm_gate(repo).stdout
        _npm_gate(repo, FAKE_VERSION_NPM="11.0")
        assert len(_cwd_calls(repo, "npm")) == 2


class TestFailures:
    def test_every_check_runs_and_each_failure_is_named(self, repo):
        """Row 22: a lint failure does not stop the tests."""
        _uv_repo(repo)
        result = _gate(repo, FAKE_FAIL="ruff check")
        assert result.returncode == 1
        assert _uv_tool_calls(repo, "pytest"), "the tests still ran"
        assert "Lint (ruff)" in result.stderr

    def test_npm_scripts_follow_the_same_policy(self, repo):
        """Row 21."""
        _npm_repo(repo, {"lint:js": "eslint", "test:js": "jest"})
        result = _gate(repo, FAKE_FAIL="lint:js")
        assert result.returncode == 1
        assert ["npm", "run", "test:js"] in _calls(repo)


class TestStamp:
    """Row 15: gate-stamp.sh over the whole gate, every stack."""

    def test_a_pass_is_reused_on_the_same_tree(self, repo):
        _composer_repo(repo)
        assert _gate(repo).returncode == 0
        before = len(_calls(repo))
        second = _gate(repo)
        assert second.returncode == 0
        assert len(_calls(repo)) == before, "nothing ran the second time"
        assert "already passed" in second.stdout

    def test_a_failure_records_nothing(self, repo):
        _uv_repo(repo)
        _gate(repo, FAKE_FAIL="ruff check")
        _gate(repo)
        assert len(_uv_tool_calls(repo, "pytest")) == 2

    def test_an_untracked_file_means_no_reuse(self, repo):
        _uv_repo(repo)
        _gate(repo)
        (repo / "tests" / "test_new.py").write_text("def test_n(): pass\n")
        _gate(repo)
        assert len(_uv_tool_calls(repo, "pytest")) == 2

    def test_a_tool_upgrade_means_no_reuse(self, repo):
        _uv_repo(repo)
        _gate(repo)
        _gate(repo, FAKE_VERSION="2.0")
        assert len(_uv_tool_calls(repo, "pytest")) == 2

    def test_a_real_git_hooks_pass_is_reused_from_a_plain_shell(self, repo):
        """CR 1394: through an actual `git commit`, not a simulated one.

        Under a hook the key is the tree being committed (PRE_COMMIT=1), and
        git runs the hook with its own exec-path first on PATH and GIT_*
        set. structural-tests.sh needed exactly this test to find that its
        hook's stamp was unreachable from a plain shell.
        """
        _uv_repo(repo)
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text(f'#!/bin/sh\nPRE_COMMIT=1 exec bash "{GATE}"\n')
        hook.chmod(0o755)
        (repo / "tests" / "test_x.py").write_text("def test_h(): pass\n")
        env = _env(repo)
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "via hook"],
            check=True,
            env=env,
            capture_output=True,
        )
        assert len(_uv_tool_calls(repo, "pytest")) == 1, "the hook ran the gate"
        second = _gate(repo)
        assert second.returncode == 0, second.stderr
        assert len(_uv_tool_calls(repo, "pytest")) == 1, second.stderr
        assert "already passed" in second.stdout

    def test_an_interpreter_upgrade_means_no_reuse(self, repo):
        """CR 1396: uv's version says nothing of the Python it resolves."""
        _uv_repo(repo)
        _gate(repo)
        _gate(repo, FAKE_PYTHON_VERSION="3.12.9")
        assert len(_uv_tool_calls(repo, "pytest")) == 2

    def test_only_the_detected_stacks_tools_are_keyed(self, repo):
        """CR 1395: a PHP upgrade is nothing to a uv repo's stamp, and a
        Python gate has no reason to start composer just to read a version."""
        _uv_repo(repo)
        _gate(repo)
        _gate(repo, FAKE_VERSION_COMPOSER="9.9", FAKE_VERSION_PHP="9.9")
        assert len(_uv_tool_calls(repo, "pytest")) == 1
        asked = (repo.parent / "tools.log").read_text()
        assert '["composer", "--version"]' not in asked
        assert '["php", "--version"]' not in asked

    def test_env_names_are_part_of_the_key(self, repo):
        """Row 16 (#497)."""
        _uv_repo(repo)
        _gate(repo, PRE_SHIP_ENV_NAMES="DSN")
        _gate(repo, PRE_SHIP_ENV_NAMES="DSN TOKEN")
        assert len(_uv_tool_calls(repo, "pytest")) == 2

    def test_env_names_in_any_order_are_one_key(self, repo):
        """The names are a set: a wrapper's load order is not a different run."""
        _uv_repo(repo)
        _gate(repo, PRE_SHIP_ENV_NAMES="DSN TOKEN")
        second = _gate(repo, PRE_SHIP_ENV_NAMES="TOKEN DSN")
        assert len(_uv_tool_calls(repo, "pytest")) == 1, second.stderr

    def test_a_repo_with_no_commit_runs_and_records_nothing(self, repo):
        """HEAD does not resolve. The variants' /tmp stamp once keyed such a
        run as `<repo>-tests-clean-HEAD`, shared by every commit-less run
        (pinned until #537's release 2 deleted the variants); the tree stamp
        has no key for it,
        so the gate runs, every time, and writes nothing."""
        (repo / "pyproject.toml").write_text('[project]\nname = "demo-app"\n')
        (repo / "uv.lock").write_text("version = 1\n")
        first = _gate(repo)
        assert first.returncode == 0, first.stderr
        _gate(repo)
        assert len(_uv_tool_calls(repo, "pytest")) == 2
        stamps = repo / ".git" / "gate-stamps"
        assert not stamps.exists() or not any(stamps.iterdir())

    def test_an_empty_env_list_writes_no_stamp(self, repo):
        _uv_repo(repo)
        _gate(repo, PRE_SHIP_ENV_NAMES="")
        _gate(repo, PRE_SHIP_ENV_NAMES="")
        assert len(_uv_tool_calls(repo, "pytest")) == 2


def test_help_names_the_checks_and_the_exit_codes():
    result = subprocess.run(
        ["bash", str(GATE), "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    for word in ("detect-stack.sh", "scripts/pre-ship.sh", "tooling/infra"):
        assert word in result.stdout
