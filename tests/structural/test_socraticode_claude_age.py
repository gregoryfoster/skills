"""Preflight reports the running Claude Code's version and install age (#310, #316).

`preflight.sh` reported the version of nearly everything the install depends on
and never the host running it. A CannObserv workstation sat on Claude Code
2.1.71 from March to September while 2.1.278 was current, preflight green on
every run; #309 then reasoned from current documentation about a six-month-old
binary and shipped two confidently wrong conclusions.

#310 answered with `claude --version` and, where `.claude.json` said
`installMethod: native`, the age of the native installer's versions file. #316
measured that design on the exeuntu image hosts it was filed for and found it
reading the wrong thing twice:

- **Which binary.** `claude --version` answers for PATH, and an IDE session runs
  the extension's own binary instead: PATH said 2.1.258 while the agent ran
  2.1.266, and after `sudo exeuntu update claude` PATH said 2.1.278 with the
  agent unchanged. So inside a session the check walks its own process
  ancestry to the binary actually running, reports a gap between it and PATH's
  first, and never gives PATH's a verdict when the running one is known.
- **No installMethod.** The image bakes its binary in at build time and
  records no `installMethod`, so #310's age never fired there. The age is now
  the mtime of whatever file resolves, with no precondition.

Two constraints are unchanged and pinned here: nothing that installs is ever
run — `claude update` has no check-only mode, and neither does
`exeuntu update` — and nothing asks the network what is current.

Every case runs the whole script against a fake HOME, a stub `claude` that
records each argv it is given, and a stub `ps` that stands in for the process
ancestry: the real one, run from a Claude Code session, would find the
developer's own binary. On Linux the walk reads `/proc/<pid>/exe` first, and
the stub's ancestor is a pid above Linux's `pid_max`, so `/proc` has nothing
for it and the stub answers there too.
"""

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
SYSTEM_PATH = ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
# Above Linux's largest possible pid_max (2**22) and macOS's 99999, so no real
# process has it and /proc/<it>/exe never exists.
FAKE_ANCESTOR = 4194305


def _binary(path: Path, version: str, age_days: float) -> Path:
    """An executable at `path` answering `--version` with `version`, `age_days` old."""
    path.parent.mkdir(parents=True, exist_ok=True)
    log = path.parent / f"{path.name}-argv.log"
    path.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{log}"\n'
        f'[ "$1" = "--version" ] && echo "{version} (Claude Code)"\n'
        "exit 0\n"
    )
    path.chmod(0o755)
    _age(path, age_days)
    return path


def _age(path: Path, age_days: float) -> None:
    then = time.time() - age_days * DAY - 60
    os.utime(path, (then, then))


def _extension(root: Path, version: str, age_days: float) -> Path:
    """The binary a VS Code extension ships, at the path the IDE runs it from."""
    return _binary(
        root
        / f"anthropic.claude-code-{version}-linux-x64"
        / "resources"
        / "native-binary"
        / "claude",
        version,
        age_days,
    )


def _stub_bin(
    tmp_path: Path,
    *,
    claude: Path | str | None,
    ancestor: str = "/sbin/launchd",
    exeuntu: bool = False,
) -> Path:
    """Stubs for every tool preflight shells out to that this host may carry.

    `claude` is the version PATH's claude answers (a stub `bin/claude`, fresh)
    or a file to link `bin/claude` at; None leaves it off PATH. `ancestor` is
    the executable `ps` reports for the one ancestor above preflight's parent.
    `exeuntu` puts the platform's updater on PATH, logging every argv.
    """
    binv = tmp_path / "bin"
    binv.mkdir()
    stubs = {
        "node": '[ "$1" = "--version" ] && echo v22.11.0\nexit 0',
        "npm": "echo 1.14.0",
        "npx": "exit 0",
        "docker": "exit 0",
        "systemctl": "exit 1",
        "ps": (
            f'printf "%s\\n" "$*" >> "{tmp_path / "ps-argv.log"}"\n'
            'field=""; pid=""\n'
            "while [ $# -gt 0 ]; do\n"
            '  case "$1" in -o) field="$2"; shift 2 ;; -p) pid="$2"; shift 2 ;; '
            "*) shift ;; esac\n"
            "done\n"
            f'if [ "$pid" = "{FAKE_ANCESTOR}" ]; then\n'
            f'  case "$field" in ppid=) echo 1 ;; comm=) echo "{ancestor}" ;; esac\n'
            "else\n"
            f'  case "$field" in ppid=) echo {FAKE_ANCESTOR} ;; '
            "comm=) echo /usr/bin/python3 ;; esac\n"
            "fi"
        ),
    }
    if exeuntu:
        stubs["exeuntu"] = f'printf "%s\\n" "$*" >> "{tmp_path / "exeuntu-argv.log"}"'
    for name, body in stubs.items():
        (binv / name).write_text(f"#!/bin/sh\n{body}\n")
        (binv / name).chmod(0o755)
    if isinstance(claude, str):
        _binary(binv / "claude", claude, 0)
    elif isinstance(claude, Path):
        (binv / "claude").symlink_to(claude)
    return binv


def _run(
    tmp_path: Path, binv: Path, *, session: bool = False
) -> subprocess.CompletedProcess:
    """preflight.sh under a fake HOME, inside a Claude Code session or not.

    CLAUDECODE is what a session sets and what gates the ancestry walk, so it is
    taken out of the inherited environment — a developer running this suite
    from Claude Code carries it — and put back only when asked for.
    """
    env = {k: v for k, v in os.environ.items() if k not in STORE_VARIABLES}
    for name in ("SOCRATICODE_ENTRY", "CLAUDECODE", "CLAUDE_CONFIG_DIR"):
        env.pop(name, None)
    # The stubs, then the system's own tools and nothing else: the host's real
    # `claude` — often in ~/.local/bin — must not answer for the stub.
    env["PATH"] = os.pathsep.join([str(binv), *SYSTEM_PATH])
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env["HOME"] = str(home)
    env["CLAUDE_CONFIG_DIR"] = str(tmp_path / "claude-config")
    if session:
        env["CLAUDECODE"] = "1"
    return subprocess.run(
        [BASH, str(PREFLIGHT)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(tmp_path),
    )


def _lines(result: subprocess.CompletedProcess) -> list[str]:
    """The Claude Code readings, each with the hints printed under it."""
    out: list[str] = []
    attach = False
    for ln in result.stdout.splitlines():
        if ln.lstrip().startswith("→"):
            if attach:
                out[-1] += "\n" + ln
        elif "Claude Code" in ln:
            out.append(ln)
            attach = True
        else:
            attach = False
    return out


def _hints(result: subprocess.CompletedProcess) -> list[str]:
    return [
        ln.strip() for ln in result.stdout.splitlines() if ln.lstrip().startswith("→")
    ]


def _on_system_path(name: str) -> bool:
    return shutil.which(name, path=os.pathsep.join(SYSTEM_PATH)) is not None


class TestOutsideASessionItReadsPath:
    """No session, no agent: PATH's claude is the reading, and it says so."""

    @requires_bash
    def test_a_fresh_install_reports_version_and_age(self, tmp_path: Path) -> None:
        binv = _stub_bin(tmp_path, claude="2.1.278")
        _age(binv / "claude", 2)
        result = _run(tmp_path, binv)
        (line,) = _lines(result)
        assert "✓" in line and "2.1.278 installed 2 day" in line, result.stdout
        assert "PATH's claude" in line, (
            f"the reading must say which binary it measured\n{line!r}"
        )

    @requires_bash
    def test_a_stale_install_warns_and_names_the_remedy(self, tmp_path: Path) -> None:
        """The workstation #310 was filed from: 2.1.71, 195 days old."""
        binv = _stub_bin(tmp_path, claude="2.1.71")
        _age(binv / "claude", 195)
        result = _run(tmp_path, binv)
        (line,) = _lines(result)
        assert "•" in line and "195 days" in line, result.stdout
        assert "→ claude update" in line, result.stdout

    @requires_bash
    def test_the_age_warning_is_advisory(self, tmp_path: Path) -> None:
        """A stale CLI does not stop an index, so it cannot fail preflight."""
        binv = _stub_bin(tmp_path, claude="2.1.71")
        _age(binv / "claude", 195)
        result = _run(tmp_path, binv)
        assert result.returncode == 0, result.stdout
        assert "Preflight PASSED" in result.stdout, result.stdout

    @requires_bash
    def test_thirty_days_is_still_current(self, tmp_path: Path) -> None:
        binv = _stub_bin(tmp_path, claude="2.1.250")
        _age(binv / "claude", 30)
        assert "✓" in _lines(_run(tmp_path, binv))[0]

    @requires_bash
    def test_a_link_is_measured_by_what_it_points_at(self, tmp_path: Path) -> None:
        """The native installer's layout: a fresh link at a 195-day-old file."""
        target = _binary(
            tmp_path / "home" / ".local" / "share" / "claude" / "versions" / "2.1.71",
            "2.1.71",
            195,
        )
        result = _run(tmp_path, _stub_bin(tmp_path, claude=target))
        (line,) = _lines(result)
        assert "195 days" in line and str(target.resolve()) in line, result.stdout

    @requires_bash
    def test_no_process_is_walked(self, tmp_path: Path) -> None:
        """Without a session there is no agent's binary to find."""
        _run(tmp_path, _stub_bin(tmp_path, claude="2.1.278"))
        log = tmp_path / "ps-argv.log"
        assert not log.exists(), f"ps was run outside a session: {log.read_text()}"


class TestInASessionItReadsTheRunningBinary:
    """#316 §2: the number people quote must be the program doing the work."""

    @requires_bash
    def test_a_gap_is_reported_before_any_verdict(self, tmp_path: Path) -> None:
        """Archiver after its update: PATH 2.1.278, the agent still on 2.1.266."""
        running = _extension(tmp_path / "extensions", "2.1.266", 40)
        binv = _stub_bin(tmp_path, claude="2.1.278", ancestor=str(running))
        _age(binv / "claude", 1)
        result = _run(tmp_path, binv, session=True)
        lines = _lines(result)
        assert len(lines) >= 2, result.stdout
        gap, verdict = lines[0], lines[1]
        assert "2.1.266" in gap and "2.1.278" in gap and "two programs" in gap, (
            f"the gap between the running binary and PATH's must be reported "
            f"first\n{result.stdout}"
        )
        assert "2.1.266 installed 40 days" in verdict, result.stdout
        assert "installed 1 day" not in result.stdout, (
            "PATH's claude got a verdict of its own on a host where the running "
            f"binary is known and differs (#316)\n{result.stdout}"
        )

    @requires_bash
    def test_a_version_the_path_does_not_name_is_asked_of_the_binary(
        self, tmp_path: Path
    ) -> None:
        """An image binary: /usr/local/bin/claude names no release."""
        running = _binary(tmp_path / "image" / "claude", "2.1.266", 3)
        binv = _stub_bin(tmp_path, claude="2.1.258", ancestor=str(running))
        result = _run(tmp_path, binv, session=True)
        gap = _lines(result)[0]
        assert "runs 2.1.266" in gap and "2.1.258" in gap, result.stdout

    @requires_bash
    def test_one_binary_is_one_line(self, tmp_path: Path) -> None:
        running = _binary(
            tmp_path / "home" / ".local" / "share" / "claude" / "versions" / "2.1.278",
            "2.1.278",
            2,
        )
        binv = _stub_bin(tmp_path, claude=running, ancestor=str(running))
        result = _run(tmp_path, binv, session=True)
        (line,) = _lines(result)
        assert "✓" in line and "running this session and PATH's claude" in line, (
            result.stdout
        )

    @requires_bash
    def test_the_same_release_elsewhere_is_one_line(self, tmp_path: Path) -> None:
        running = _extension(tmp_path / "extensions", "2.1.278", 2)
        binv = _stub_bin(tmp_path, claude="2.1.278", ancestor=str(running))
        (line,) = _lines(_run(tmp_path, binv, session=True))
        assert "✓" in line and "same release" in line, line

    @requires_bash
    def test_an_ide_host_with_no_claude_on_path(self, tmp_path: Path) -> None:
        """The version is still known when the CLI is not installed at all."""
        running = _extension(tmp_path / "extensions", "2.1.278", 2)
        binv = _stub_bin(tmp_path, claude=None, ancestor=str(running))
        result = _run(tmp_path, binv, session=True)
        (line,) = _lines(result)
        assert "2.1.278 installed 2 day" in line and "no claude on PATH" in line, (
            result.stdout
        )
        assert "plugin-connection check is skipped" in result.stdout, result.stdout
        assert result.returncode == 0, result.stdout

    @requires_bash
    def test_not_finding_it_is_said(self, tmp_path: Path) -> None:
        binv = _stub_bin(tmp_path, claude="2.1.278")
        result = _run(tmp_path, binv, session=True)
        lines = _lines(result)
        assert "not found among" in lines[0], result.stdout
        assert "PATH's claude" in lines[1] and "installed 0 day" in lines[1], (
            result.stdout
        )

    @requires_bash
    def test_a_binary_replaced_since_it_started(self, tmp_path: Path) -> None:
        """Linux's /proc marks it; the file now at that path is another one."""
        replaced = _binary(tmp_path / "image" / "claude", "2.1.278", 0)
        binv = _stub_bin(tmp_path, claude="2.1.278", ancestor=f"{replaced} (deleted)")
        result = _run(tmp_path, binv, session=True)
        (line,) = _lines(result)
        assert "replaced on disk" in line and "not determined" in line, line
        assert "Restart" in line, line
        assert "installed 0 day" not in line, (
            f"the file now at that path was aged as if it were running\n{line}"
        )

    @requires_bash
    def test_a_binary_removed_since_it_started(self, tmp_path: Path) -> None:
        """macOS's ps still names the path; nothing is there."""
        gone = tmp_path / "image" / "claude"
        binv = _stub_bin(tmp_path, claude="2.1.278", ancestor=str(gone))
        (line,) = _lines(_run(tmp_path, binv, session=True))
        assert "no longer on disk" in line and "not determined" in line, line


class TestTheAgeNeedsNoInstallMethod:
    """#316 §1 and §4: the image records nothing, and nothing is read from it."""

    @requires_bash
    def test_an_image_binary_is_aged_with_no_config_at_all(
        self, tmp_path: Path
    ) -> None:
        image = _binary(tmp_path / "image" / "claude", "2.1.258", 100)
        binv = _stub_bin(tmp_path, claude=image, ancestor=str(image))
        assert not (tmp_path / "claude-config").exists()
        result = _run(tmp_path, binv, session=True)
        (line,) = _lines(result)
        assert "2.1.258 installed 100 days" in line, (
            "an exeuntu image records no installMethod; the age is the file's "
            f"either way (#316 §1)\n{result.stdout}"
        )

    @requires_bash
    def test_auto_updates_in_the_config_does_not_quiet_it(self, tmp_path: Path) -> None:
        """`claude doctor` says enabled on a host that cannot update itself."""
        config = tmp_path / "claude-config"
        config.mkdir()
        (config / ".claude.json").write_text(
            '{"autoUpdates": true, "autoUpdatesProtectedForNative": true}'
        )
        binv = _stub_bin(tmp_path, claude="2.1.71")
        _age(binv / "claude", 195)
        (line,) = _lines(_run(tmp_path, binv))
        assert "195 days" in line and "•" in line, line


class TestTheRemedyFollowsTheChannel:
    """#316 §3: the wrong updater leaves a second binary for PATH to pick."""

    @requires_bash
    def test_an_exeuntu_host_is_told_the_platform_command(self, tmp_path: Path) -> None:
        image = _binary(tmp_path / "image" / "claude", "2.1.258", 100)
        binv = _stub_bin(tmp_path, claude=image, ancestor=str(image), exeuntu=True)
        result = _run(tmp_path, binv, session=True)
        hints = _hints(result)
        assert any(h.startswith("→ sudo exeuntu update claude") for h in hints), (
            result.stdout
        )
        assert not any(h.startswith("→ claude update") for h in hints), (
            f"an exeuntu host was told to run `claude update` (#316 §3)\n{hints}"
        )

    @requires_bash
    def test_a_native_install_on_an_exeuntu_host_is_claude_update(
        self, tmp_path: Path
    ) -> None:
        """broker#36's shadow copy: the user's own, which exeuntu never updates."""
        native = _binary(
            tmp_path / "home" / ".local" / "share" / "claude" / "versions" / "2.1.258",
            "2.1.258",
            100,
        )
        binv = _stub_bin(tmp_path, claude=native, ancestor=str(native), exeuntu=True)
        hints = _hints(_run(tmp_path, binv, session=True))
        assert any(h.startswith("→ claude update") for h in hints), hints
        assert not any(h.startswith("→ sudo exeuntu") for h in hints), (
            f"a native installer's file was sent to the image's updater\n{hints}"
        )

    @requires_bash
    def test_elsewhere_it_is_claude_update(self, tmp_path: Path) -> None:
        if _on_system_path("exeuntu"):
            pytest.skip("this host has exeuntu on the system PATH")
        binv = _stub_bin(tmp_path, claude="2.1.71")
        _age(binv / "claude", 195)
        hints = _hints(_run(tmp_path, binv))
        assert any(h.startswith("→ claude update") for h in hints), hints

    @requires_bash
    def test_a_binary_it_cannot_write_is_named(self, tmp_path: Path) -> None:
        if os.geteuid() == 0:
            pytest.skip("root can write any file")
        if _on_system_path("exeuntu"):
            pytest.skip("this host has exeuntu on the system PATH")
        binv = _stub_bin(tmp_path, claude="2.1.71")
        _age(binv / "claude", 195)
        (binv / "claude").chmod(0o555)
        hints = _hints(_run(tmp_path, binv))
        assert any("not writable" in h and "second copy" in h for h in hints), hints

    @requires_bash
    def test_a_stale_extension_is_updated_in_the_ide(self, tmp_path: Path) -> None:
        """Even on an exeuntu host: its updater does not reach the extension."""
        running = _extension(tmp_path / "extensions", "2.1.266", 40)
        binv = _stub_bin(
            tmp_path, claude="2.1.266", ancestor=str(running), exeuntu=True
        )
        hints = _hints(_run(tmp_path, binv, session=True))
        assert any("extension" in h and "reload" in h for h in hints), hints
        assert not any(
            h.startswith(("→ claude update", "→ sudo exeuntu")) for h in hints
        ), hints


class TestAStagedExtensionIsNamed:
    """#316 §5: behind its own completed update until the window reloads."""

    @requires_bash
    def test_a_newer_complete_sibling(self, tmp_path: Path) -> None:
        root = tmp_path / "extensions"
        running = _extension(root, "2.1.266", 13)
        _extension(root, "2.1.270", 9)
        binv = _stub_bin(tmp_path, claude="2.1.278", ancestor=str(running))
        lines = _lines(_run(tmp_path, binv, session=True))
        staged = [ln for ln in lines if "2.1.270" in ln]
        assert staged and "reload" in staged[0].lower(), lines
        assert "until then this session runs 2.1.266" in staged[0], staged

    @requires_bash
    @pytest.mark.parametrize("older", [True, False])
    def test_an_older_or_incomplete_sibling_is_not(
        self, tmp_path: Path, older: bool
    ) -> None:
        root = tmp_path / "extensions"
        running = _extension(root, "2.1.266", 13)
        if older:
            _extension(root, "2.1.258", 30)
        else:
            (root / "anthropic.claude-code-2.1.270-linux-x64").mkdir()
        binv = _stub_bin(tmp_path, claude="2.1.266", ancestor=str(running))
        lines = _lines(_run(tmp_path, binv, session=True))
        assert not [ln for ln in lines if "beside it" in ln], lines


class TestItNeverUpdates:
    """Neither updater has a check-only mode, so neither is ever run."""

    @requires_bash
    @pytest.mark.parametrize("age", [2, 195])
    @pytest.mark.parametrize("session", [False, True])
    def test_no_updater_is_run(self, tmp_path: Path, age: int, session: bool) -> None:
        running = _extension(tmp_path / "extensions", "2.1.266", age)
        binv = _stub_bin(
            tmp_path, claude="2.1.266", ancestor=str(running), exeuntu=True
        )
        _age(binv / "claude", age)
        _run(tmp_path, binv, session=session)
        calls = (binv / "claude-argv.log").read_text().splitlines()
        assert "--version" in calls, "the stub was never asked for a version"
        assert not [c for c in calls if c.split()[:1] in (["update"], ["upgrade"])], (
            f"preflight ran an installing command: {calls}"
        )
        assert not (tmp_path / "exeuntu-argv.log").exists(), (
            "preflight ran exeuntu, whose update installs"
        )


class TestWhatItCannotMeasureItSays:
    @requires_bash
    def test_a_version_it_cannot_read(self, tmp_path: Path) -> None:
        binv = _stub_bin(tmp_path, claude="")
        (line,) = _lines(_run(tmp_path, binv))
        assert "reported no version" in line and "not determined" in line, line

    @requires_bash
    def test_claude_absent_from_path(self, tmp_path: Path) -> None:
        if _on_system_path("claude"):
            pytest.skip("this host has claude on the system PATH")
        result = _run(tmp_path, _stub_bin(tmp_path, claude=None))
        (line,) = _lines(result)
        assert "no claude on PATH" in line and "not determined" in line, line
        assert "plugin-connection check is skipped" in result.stdout, result.stdout
        assert result.returncode == 0, result.stdout
