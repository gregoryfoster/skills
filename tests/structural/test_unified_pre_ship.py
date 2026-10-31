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
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "skills" / "shipping-work" / "scripts" / "pre-ship.sh"

LAUNCHER = '#!/bin/sh\nexec "$STUB_PYTHON" "$FAKE_DIR/fake.py" "${0##*/}" "$@"\n'

FAKE = r"""import json, os, sys
tool, argv = sys.argv[1], sys.argv[2:]
with open(os.environ["TOOL_LOG"], "a") as log:
    log.write(json.dumps([tool, *argv]) + "\n")
line = " ".join([tool, *argv])
fails = [f for f in os.environ.get("FAKE_FAIL", "").split(",") if f]
if argv[:1] == ["--version"]:
    default = os.environ.get("FAKE_VERSION", "1.0")
    print(f"{tool} {os.environ.get('FAKE_VERSION_' + tool.upper(), default)}")
    sys.exit(0)
if tool == "uv":
    rest = argv[1:]
    i = next(i for i, a in enumerate(rest) if a in ("ruff", "python", "pytest"))
    t, targs = rest[i], rest[i + 1:]
    if t == "python" and targs[:1] == ["--version"]:
        print("Python " + os.environ.get("FAKE_PYTHON_VERSION", "3.12.0"))
        sys.exit(0)
    if t == "python" and targs[:1] == ["-c"]:
        code = targs[1]
        if code == "import pytest_cov":
            sys.exit(0 if os.environ.get("FAKE_COV") else 1)
        if code == "import xdist":
            sys.exit(0 if os.environ.get("FAKE_XDIST") else 1)
        if not code.startswith("import "):
            os.execv(sys.executable, [sys.executable, "-c", code])
    if t == "pytest" and not any(f in line for f in fails):
        sys.exit(int(os.environ.get("FAKE_PYTEST_RC", "0")))
if tool == "node":
    data = json.load(open("package.json"))
    if "process.env.SCRIPT" in argv[1]:
        sys.exit(0 if (data.get("scripts") or {}).get(os.environ["SCRIPT"]) else 1)
    sys.exit(0)
if tool == "composer" and argv[:1] == ["run-script"]:
    if os.environ.get("FAKE_COMPOSER_LIST_FAIL"):
        print("composer: could not read composer.json", file=sys.stderr)
        sys.exit(1)
    if os.environ.get("FAKE_COMPOSER_TEST"):
        print("  test   Runs the tests")
    sys.exit(0)
sys.exit(1 if any(f in line for f in fails) else 0)
"""

ALL_TOOLS = ("uv", "composer", "php", "node", "npm")


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
    fake_dir = repo.parent / "fakebin"
    fake_dir.mkdir(exist_ok=True)
    (fake_dir / "fake.py").write_text(FAKE)
    for tool in ALL_TOOLS:
        launcher = fake_dir / tool
        if tool in tools:
            launcher.write_text(LAUNCHER)
            launcher.chmod(0o755)
        elif launcher.exists():
            launcher.unlink()
    base = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("GIT_", "GATE_STAMP", "PRE_SHIP_", "PYTEST_"))
        and k not in ("PRE_COMMIT", "PYTHONPATH")
    }
    base.update(
        PATH=f"{fake_dir}:/usr/bin:/bin",
        STUB_PYTHON=sys.executable,
        FAKE_DIR=str(fake_dir),
        TOOL_LOG=str(repo.parent / "tools.log"),
        PYTEST_XDIST_AUTO_NUM_WORKERS="0",
    )
    base.update(env)
    return base


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

    @pytest.mark.parametrize(
        ("build", "tool"),
        [(_uv_repo, "uv"), (_composer_repo, "composer")],
    )
    def test_a_detected_stack_with_its_tool_missing_is_exit_2(self, repo, build, tool):
        """Row 3."""
        build(repo)
        result = _gate(repo, tools=[t for t in ALL_TOOLS if t != tool])
        assert result.returncode == 2
        assert tool in result.stderr

    def test_it_says_what_it_detected(self, repo):
        """SKILL.md loads references/stack-<framework>.md from this line."""
        _uv_repo(repo, '"fastapi"')
        result = _gate(repo)
        assert "Detected: toolchain uv, framework fastapi" in result.stdout

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

    def test_lint_every_tracked_php_file(self, repo):
        """Row 19."""
        _composer_repo(repo)
        assert _gate(repo).returncode == 0
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
