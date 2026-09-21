"""Preflight reports Claude Code's own version and install age (#310).

`preflight.sh` reported the version of nearly everything the install depends on
and never the host running it. A CannObserv workstation sat on Claude Code
2.1.71 from March to September while 2.1.278 was current, preflight green on
every run; #309 then reasoned from current documentation about a six-month-old
binary and shipped two confidently wrong conclusions.

The check has one hard constraint, and this file pins it before anything else:
`claude update` has no check-only mode — it installs — so preflight may never
call it, and it makes no network call to learn what is current either. What it
can read is on disk: the native installer keeps one file per version under
`$XDG_DATA_HOME/claude/versions/` (default `~/.local/share`), links
`~/.local/bin/claude` at the running one, and records
`"installMethod": "native"` in `.claude.json` — which lives in
`CLAUDE_CONFIG_DIR` when that is set and in HOME otherwise. The file's mtime is
its install date.

Every case runs the whole script against a fake HOME and a stub `claude` that
records each argv it is given, on a PATH with nothing else of the host's
Claude Code on it.
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from .test_socraticode_node_gate import STORE_VARIABLES

PREFLIGHT = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "init-socraticode"
    / "scripts"
    / "preflight.sh"
)
BASH = shutil.which("bash")
requires_bash = pytest.mark.skipif(BASH is None, reason="bash runs preflight.sh")
DAY = 86400


def _stub_bin(tmp_path: Path, *, claude_version: str | None) -> Path:
    """Stubs for every tool preflight shells out to that this host may carry.

    `claude` answers `--version` with `claude_version` and exits 0 on anything
    else — Gate 4's marketplace and `mcp list` calls included — after writing
    its argv to `claude-argv.log`, so a test can prove what was never run.
    None leaves `claude` off PATH entirely.
    """
    binv = tmp_path / "bin"
    binv.mkdir()
    stubs = {
        "node": '[ "$1" = "--version" ] && echo v22.11.0\nexit 0',
        "npm": "echo 1.14.0",
        "npx": "exit 0",
        "docker": "exit 0",
        "systemctl": "exit 1",
    }
    if claude_version is not None:
        log = tmp_path / "claude-argv.log"
        stubs["claude"] = (
            f'printf "%s\\n" "$*" >> "{log}"\n'
            f'[ "$1" = "--version" ] && echo "{claude_version} (Claude Code)"\n'
            "exit 0"
        )
    for name, body in stubs.items():
        (binv / name).write_text(f"#!/bin/sh\n{body}\n")
        (binv / name).chmod(0o755)
    return binv


def _config_dir(tmp_path: Path) -> Path:
    """The CLAUDE_CONFIG_DIR `_run` exports unless told not to."""
    return tmp_path / "claude-config"


def _home(
    tmp_path: Path,
    *,
    method: str | None = "native",
    versions: dict[str, int] | None = None,
    link_to: str | None = None,
    config_at: Path | None = None,
    data_home: Path | None = None,
) -> Path:
    """A HOME laid out the way the native installer lays it out.

    `versions` maps a version to its age in days, applied as the file's mtime —
    the fact the check reads. `link_to` names the version `~/.local/bin/claude`
    points at; None leaves no link.

    `.claude.json` goes where Claude Code keeps it: in CLAUDE_CONFIG_DIR, which
    `_run` exports by default — not under `~/.claude`, and not in HOME, which
    is only the fallback when CLAUDE_CONFIG_DIR is unset. `config_at` puts it
    somewhere else. `data_home` stands in for XDG_DATA_HOME, the versions
    directory's root; None is `~/.local/share`.
    """
    home = tmp_path / "home"
    home.mkdir()
    if method is not None:
        config = config_at or _config_dir(tmp_path)
        config.mkdir(parents=True, exist_ok=True)
        (config / ".claude.json").write_text(
            json.dumps({"numStartups": 3, "installMethod": method})
        )
    store = (data_home or home / ".local" / "share") / "claude" / "versions"
    store.mkdir(parents=True)
    now = time.time()
    for version, age in (versions or {}).items():
        path = store / version
        path.write_text("binary\n")
        os.utime(path, (now - age * DAY - 60, now - age * DAY - 60))
    if link_to is not None:
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".local" / "bin" / "claude").symlink_to(store / link_to)
    return home


def _run(
    tmp_path: Path,
    binv: Path,
    home: Path,
    *,
    config_dir: bool = True,
    data_home: Path | None = None,
) -> subprocess.CompletedProcess:
    """preflight.sh under HOME, with CLAUDE_CONFIG_DIR and XDG_DATA_HOME explicit.

    Both are taken out of the inherited environment first: a host that sets
    either would otherwise point the check at its own Claude Code.
    """
    env = {k: v for k, v in os.environ.items() if k not in STORE_VARIABLES}
    for name in ("SOCRATICODE_ENTRY", "CLAUDE_CONFIG_DIR", "XDG_DATA_HOME"):
        env.pop(name, None)
    # The stubs, then the system's own tools and nothing else: the host's real
    # `claude` — often in ~/.local/bin — must not answer for the stub.
    env["PATH"] = os.pathsep.join([str(binv), "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    env["HOME"] = str(home)
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = str(_config_dir(tmp_path))
    if data_home is not None:
        env["XDG_DATA_HOME"] = str(data_home)
    return subprocess.run(
        [BASH, str(PREFLIGHT)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(tmp_path),
    )


def _line(result: subprocess.CompletedProcess) -> str:
    return next(
        (
            ln
            for ln in result.stdout.splitlines()
            if "Claude Code" in ln or "claude CLI" in ln
        ),
        "",
    )


def _argv(tmp_path: Path) -> list[str]:
    log = tmp_path / "claude-argv.log"
    return log.read_text().splitlines() if log.exists() else []


class TestTheVersionIsAlwaysReported:
    @requires_bash
    def test_a_fresh_native_install_reports_version_and_age(
        self, tmp_path: Path
    ) -> None:
        home = _home(
            tmp_path, versions={"2.1.278": 2, "2.1.71": 195}, link_to="2.1.278"
        )
        result = _run(tmp_path, _stub_bin(tmp_path, claude_version="2.1.278"), home)
        line = _line(result)
        assert "✓" in line and "2.1.278" in line and "installed 2 day" in line, (
            f"{line!r}\n{result.stdout}"
        )

    @requires_bash
    def test_a_stale_install_warns_and_names_the_remedy(self, tmp_path: Path) -> None:
        """The workstation #310 was filed from: 2.1.71, 195 days old."""
        home = _home(tmp_path, versions={"2.1.71": 195}, link_to="2.1.71")
        result = _run(tmp_path, _stub_bin(tmp_path, claude_version="2.1.71"), home)
        line = _line(result)
        assert "•" in line and "195 days" in line, f"{line!r}\n{result.stdout}"
        assert "claude update" in result.stdout, result.stdout

    @requires_bash
    def test_the_age_warning_is_advisory(self, tmp_path: Path) -> None:
        """A stale CLI does not stop an index, so it cannot fail preflight."""
        home = _home(tmp_path, versions={"2.1.71": 195}, link_to="2.1.71")
        result = _run(tmp_path, _stub_bin(tmp_path, claude_version="2.1.71"), home)
        assert result.returncode == 0, result.stdout
        assert "Preflight PASSED" in result.stdout, result.stdout

    @requires_bash
    def test_thirty_days_is_still_current(self, tmp_path: Path) -> None:
        home = _home(tmp_path, versions={"2.1.250": 30}, link_to="2.1.250")
        result = _run(tmp_path, _stub_bin(tmp_path, claude_version="2.1.250"), home)
        assert "✓" in _line(result), result.stdout


class TestItReadsWhereClaudeCodeWrites:
    """The two locations Claude Code moves with its environment (#310 CR 6).

    `.claude.json` is `join(CLAUDE_CONFIG_DIR || homedir(), ".claude.json")` in
    the 2.1.278 binary, and the versions directory is
    `XDG_DATA_HOME ?? join(home, ".local", "share")`. Reading `$HOME` for
    either told a host that sets them its native install was something else.
    """

    @requires_bash
    def test_the_config_file_is_read_from_claude_config_dir(
        self, tmp_path: Path
    ) -> None:
        """Only CLAUDE_CONFIG_DIR has one — as on any host that sets it."""
        home = _home(tmp_path, versions={"2.1.278": 2}, link_to="2.1.278")
        assert not (home / ".claude.json").exists()
        result = _run(tmp_path, _stub_bin(tmp_path, claude_version="2.1.278"), home)
        line = _line(result)
        assert "✓" in line and "installed 2 day" in line, (
            "with CLAUDE_CONFIG_DIR set, Claude Code keeps .claude.json there, "
            f"and $HOME/.claude.json is not its file\n{line!r}\n{result.stdout}"
        )

    @requires_bash
    def test_without_claude_config_dir_it_is_read_from_home(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        home = _home(
            tmp_path, versions={"2.1.278": 2}, link_to="2.1.278", config_at=home
        )
        result = _run(
            tmp_path,
            _stub_bin(tmp_path, claude_version="2.1.278"),
            home,
            config_dir=False,
        )
        assert "installed 2 day" in _line(result), result.stdout

    @requires_bash
    def test_the_versions_directory_follows_xdg_data_home(self, tmp_path: Path) -> None:
        """No link to follow, so the versions directory is the only witness."""
        data = tmp_path / "xdg-data"
        home = _home(tmp_path, versions={"2.1.278": 40}, data_home=data)
        result = _run(
            tmp_path,
            _stub_bin(tmp_path, claude_version="2.1.278"),
            home,
            data_home=data,
        )
        line = _line(result)
        assert "40 days" in line, (
            "the native installer puts versions under $XDG_DATA_HOME/claude/"
            f"versions when it is set\n{line!r}\n{result.stdout}"
        )


class TestItNeverUpdates:
    """`claude update` installs; there is no check-only mode to call instead."""

    @requires_bash
    @pytest.mark.parametrize("age", [2, 195])
    def test_claude_update_is_never_run(self, tmp_path: Path, age: int) -> None:
        home = _home(tmp_path, versions={"2.1.278": age}, link_to="2.1.278")
        _run(tmp_path, _stub_bin(tmp_path, claude_version="2.1.278"), home)
        calls = _argv(tmp_path)
        assert "--version" in calls, "the stub was never asked for a version"
        assert not [c for c in calls if c.split()[:1] in (["update"], ["upgrade"])], (
            f"preflight ran an installing command: {calls}"
        )


class TestWhatItCannotMeasureItSays:
    """Each unresolvable layout reports the version and says the age is unknown."""

    @requires_bash
    @pytest.mark.parametrize(
        "method, why",
        [("npm-global", "installMethod is 'npm-global'"), (None, "no installMethod")],
    )
    def test_a_non_native_install(self, tmp_path: Path, method, why) -> None:
        home = _home(
            tmp_path, method=method, versions={"2.1.278": 2}, link_to="2.1.278"
        )
        result = _run(tmp_path, _stub_bin(tmp_path, claude_version="2.1.278"), home)
        line = _line(result)
        assert "2.1.278" in line and "not determined" in line and why in line, (
            f"{line!r}\n{result.stdout}"
        )

    @requires_bash
    def test_a_link_at_another_version(self, tmp_path: Path) -> None:
        """PATH's claude is not the native install's running one: no age for it."""
        home = _home(tmp_path, versions={"2.1.71": 195}, link_to="2.1.71")
        result = _run(tmp_path, _stub_bin(tmp_path, claude_version="2.1.278"), home)
        line = _line(result)
        assert "not determined" in line and "2.1.71" in line and "2.1.278" in line, line

    @requires_bash
    def test_no_link_falls_back_to_the_versions_file(self, tmp_path: Path) -> None:
        home = _home(tmp_path, versions={"2.1.278": 40}, link_to=None)
        result = _run(tmp_path, _stub_bin(tmp_path, claude_version="2.1.278"), home)
        assert "40 days" in _line(result), result.stdout

    @requires_bash
    def test_no_file_for_the_running_version(self, tmp_path: Path) -> None:
        home = _home(tmp_path, versions={}, link_to=None)
        result = _run(tmp_path, _stub_bin(tmp_path, claude_version="2.1.278"), home)
        line = _line(result)
        assert "2.1.278" in line and "not determined" in line, line

    @requires_bash
    def test_a_version_it_cannot_read(self, tmp_path: Path) -> None:
        home = _home(tmp_path, versions={"2.1.278": 2}, link_to="2.1.278")
        binv = _stub_bin(tmp_path, claude_version="")
        result = _run(tmp_path, binv, home)
        line = _line(result)
        assert "reported no version" in line and "not determined" in line, line

    @requires_bash
    def test_claude_absent_from_path(self, tmp_path: Path) -> None:
        home = _home(tmp_path, versions={"2.1.278": 2}, link_to="2.1.278")
        result = _run(tmp_path, _stub_bin(tmp_path, claude_version=None), home)
        line = _line(result)
        assert "claude CLI not found" in line and "not determined" in line, (
            f"{line!r}\n{result.stdout}"
        )
        assert result.returncode == 0, result.stdout
