"""Row U's host side: a reservation that takes effect, and an early killer that runs.

`init-socraticode` tells a host that runs a production service beside agent
sessions to give that service `MemoryLow=` and `OOMScoreAdjust=` and to run
earlyoom (row U, #295). Two cohort rollouts found the advice producing settings
that report themselves as applied and do nothing:

- **#307.** cgroup v2 caps a unit's effective protection at what every
  ancestor grants, and `system.slice` ships `memory.low` 0. On
  `CannObserv/wslcb-licensing-tracker` a unit at `MemoryLow=256M` was protected
  by nothing while `systemctl show`, the unit's own `memory.low`, a clean
  `daemon-reload` and a healthy service all agreed it worked. On
  `CannObserv/address-validator` a templated unit stayed unprotected one slice
  deeper, under a `system.slice` grant that was working.
- **#303, #307.** Debian's earlyoom unit expands `$EARLYOOM_ARGS` unquoted, so a
  space inside a regex splits it; the regexes match `comm`, truncated to 15
  characters, so a `$`-anchored `--prefer` never matches the server.

This file holds both halves to behaviour rather than wording. `preflight.sh`'s
reading is lifted out of the script and run against fixture cgroup trees —
every branch, including the ones a macOS suite host can never reach through the
script itself, since its only input is the mountinfo file it is handed. The
reference doc's verification snippet and earlyoom configuration are executed
and parsed the way systemd and earlyoom will, because the #307 thread showed
both a proposed verification and a proposed drop-in (an inline `#` comment,
which systemd reads as part of the value) that would have failed as written.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from .test_socraticode_node_gate import _env, _stub_toolchain

SKILL = Path(__file__).resolve().parents[2] / "skills" / "init-socraticode"
PREFLIGHT = SKILL / "scripts" / "preflight.sh"
HOST_MEMORY = SKILL / "references" / "host-memory.md"
TROUBLESHOOTING = SKILL / "references" / "troubleshooting.md"

requires_bash = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash is required to run preflight.sh"
)

MIB = 1024 * 1024
CALL = "memory_protection /proc/self/mountinfo"


def _lifted() -> str:
    """preflight.sh's memory-protection block, with its output helpers.

    Between the script's own sentinels, so a reader of preflight.sh sees where
    the lifted program starts and stops. The one live call is dropped — the
    test makes its own, with a fixture — and asserted present first, so a
    renamed entry point fails here rather than leaving the script calling
    something the tests never ran.
    """
    body = PREFLIGHT.read_text()
    start = body.index("# >>> memory-protection\n")
    end = body.index("# <<< memory-protection\n")
    region = body[start:end]
    assert region.count(f"\n{CALL}\n") == 1, (
        f"preflight.sh no longer calls `{CALL}` inside its memory-protection "
        "block, so nothing below exercises what the script runs"
    )
    helpers = [
        ln for ln in body.splitlines() if re.match(r"^(pass|warn|hint)\(\) \{", ln)
    ]
    assert len(helpers) == 3, helpers
    return (
        "set -euo pipefail\nFAIL=0\n"
        + "\n".join(helpers)
        + "\n"
        + region.replace(f"\n{CALL}\n", "\n")
        + '\nmemory_protection "$1"\necho "FAIL=$FAIL"\n'
    )


def _host(
    tmp_path: Path,
    tree: dict[str, str],
    *,
    opts: str = "rw,nsdelegate",
    cgroup2: bool = True,
    root_name: str = "cg",
) -> Path:
    """A mountinfo naming a fixture cgroup root, and `memory.low` files under it."""
    root = tmp_path / root_name
    root.mkdir()
    for rel, low in tree.items():
        (root / rel).mkdir(parents=True, exist_ok=True)
        (root / rel / "memory.low").write_text(f"{low}\n")
    mountpoint = str(root).replace(" ", "\\040")
    lines = [
        "22 1 0:21 / /proc rw,nosuid,nodev,noexec,relatime shared:12 - proc proc rw"
    ]
    if cgroup2:
        lines.append(
            f"29 28 0:26 / {mountpoint} rw,relatime shared:7 - cgroup2 cgroup2 {opts}"
        )
    else:
        lines.append(
            f"30 28 0:27 / {mountpoint}/memory rw,relatime shared:8 - cgroup cgroup rw,memory"
        )
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text("\n".join(lines) + "\n")
    return mountinfo


def _read(mountinfo: Path, path: str | None = None) -> tuple[list[str], str]:
    """Run the lifted reading; return its output lines, and the whole stdout.

    `path` replaces PATH for the run, to take tools away from it.
    """
    env = dict(os.environ) if path is None else {**os.environ, "PATH": path}
    result = subprocess.run(
        [shutil.which("bash") or "/bin/bash", "-c", _lifted(), "memory-protection"]
        + [str(mountinfo)],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert result.returncode == 0, (
        f"the memory-protection reading exited {result.returncode} — it is "
        f"advisory and must never end preflight\n{result.stdout}\n{result.stderr}"
    )
    assert result.stdout.rstrip().endswith("FAIL=0"), (
        "the memory-protection reading set FAIL — it is advisory and must "
        f"never fail preflight\n{result.stdout}"
    )
    lines = [ln for ln in result.stdout.splitlines() if not ln.startswith("FAIL=")]
    return lines, result.stdout


def _marked(lines: list[str], marker: str) -> list[str]:
    return [ln for ln in lines if marker in ln]


WARN, PASS, HINT = "•", "✓", "→"


class TestPreflightReadsTheWholeChain:
    """#307 suggestion 1, and the #307 comment's correction to it."""

    @requires_bash
    def test_not_linux_is_said_not_skipped(self, tmp_path: Path) -> None:
        lines, _ = _read(tmp_path / "no-such-mountinfo")
        assert any("not measured" in ln and "not Linux" in ln for ln in lines), lines

    @requires_bash
    def test_no_cgroup2_is_said_not_skipped(self, tmp_path: Path) -> None:
        lines, _ = _read(_host(tmp_path, {}, cgroup2=False))
        assert any(
            "not measured" in ln and "cgroup2 is not mounted" in ln for ln in lines
        ), lines

    @requires_bash
    def test_no_system_slice_is_said_not_skipped(self, tmp_path: Path) -> None:
        """A container's own cgroup, or a host without systemd."""
        lines, _ = _read(_host(tmp_path, {"init.scope": "0"}))
        assert any("not measured" in ln and "system.slice" in ln for ln in lines), lines

    @requires_bash
    def test_a_stock_host_gets_the_reading_not_a_warning(self, tmp_path: Path) -> None:
        """Nothing claims protection: the consequence is said, nothing is accused.

        system.slice ships memory.low 0 on every systemd host, so warning on it
        alone would fire on every Linux run — the cry-wolf shape preflight's
        own shared-host hint is written to avoid.
        """
        lines, _ = _read(
            _host(tmp_path, {"system.slice": "0", "system.slice/cron.service": "0"})
        )
        assert not _marked(lines, WARN), lines
        assert any(
            PASS in ln and "nothing under system.slice claims" in ln for ln in lines
        )
        assert any(HINT in ln and "inert" in ln for ln in lines), (
            "#307's consequence — a MemoryLow= given here would be inert "
            f"without a parent grant — must still be said: {lines}"
        )

    @requires_bash
    def test_the_wslcb_unit_is_named_as_clamped(self, tmp_path: Path) -> None:
        lines, _ = _read(
            _host(
                tmp_path,
                {
                    "system.slice": "0",
                    "system.slice/wslcb-web.service": str(256 * MIB),
                },
            )
        )
        warned = _marked(lines, WARN)
        assert len(warned) == 1, lines
        assert "wslcb-web.service" in warned[0], warned
        assert "256 MiB" in warned[0] and "at most 0 MiB" in warned[0], warned
        assert "system.slice grants 0 MiB" in warned[0], warned

    @requires_bash
    def test_a_templated_unit_is_clamped_one_slice_deeper(self, tmp_path: Path) -> None:
        """The #307 comment's case: a working system.slice grant is not enough.

        A preflight that printed only system.slice's memory.low would have said
        "fine" on address-validator while postgres sat unprotected.
        """
        lines, _ = _read(
            _host(
                tmp_path,
                {
                    "system.slice": str(1024 * MIB),
                    "system.slice/system-postgresql.slice": "0",
                    "system.slice/system-postgresql.slice/postgresql@16-main.service": str(
                        384 * MIB
                    ),
                },
            )
        )
        warned = _marked(lines, WARN)
        assert len(warned) == 1, lines
        assert "postgresql@16-main.service" in warned[0], warned
        assert "system-postgresql.slice grants 0 MiB" in warned[0], (
            f"the warning must name the slice that clamps it, not system.slice: {warned}"
        )

    @requires_bash
    def test_the_repaired_chain_passes(self, tmp_path: Path) -> None:
        """1G / 384M / 384M — address-validator after its second drop-in."""
        lines, _ = _read(
            _host(
                tmp_path,
                {
                    "system.slice": str(1024 * MIB),
                    "system.slice/system-postgresql.slice": str(384 * MIB),
                    "system.slice/system-postgresql.slice/postgresql@16-main.service": str(
                        384 * MIB
                    ),
                    "system.slice/wslcb-web.service": str(256 * MIB),
                },
            )
        )
        assert not _marked(lines, WARN), lines
        passed = _marked(lines, PASS)
        assert (
            passed and "keeps 384 MiB" in passed[0] and "keeps 256 MiB" in passed[0]
        ), lines

    @requires_bash
    def test_recursiveprot_does_not_rescue_a_zero_parent(self, tmp_path: Path) -> None:
        """#307 read memory_recursiveprot as an escape hatch; the kernel does not.

        `effective_protection()` in mm/page_counter.c scales a child's claim by
        its parent's effective protection before the recursive branch is ever
        reached, so a parent at 0 leaves the child at 0 with the option on.
        """
        lines, _ = _read(
            _host(
                tmp_path,
                {"system.slice": "0", "system.slice/wslcb-web.service": str(256 * MIB)},
                opts="rw,nsdelegate,memory_recursiveprot",
            )
        )
        assert len(_marked(lines, WARN)) == 1, lines
        assert any("with memory_recursiveprot" in ln for ln in lines), lines

    @requires_bash
    def test_max_is_no_limit(self, tmp_path: Path) -> None:
        lines, _ = _read(
            _host(
                tmp_path,
                {
                    "system.slice": "max",
                    "system.slice/wslcb-web.service": str(256 * MIB),
                },
            )
        )
        assert not _marked(lines, WARN), lines

    @requires_bash
    def test_a_missing_tool_is_not_read_as_no_cgroup2(self, tmp_path: Path) -> None:
        """The mount is parsed with builtins; only the memory.low reads use cat.

        test_socraticode_external_store.py runs preflight on a PATH of six
        tools. There an awk-based parse came back empty and would have said
        "cgroup2 is not mounted" on a host where it is — a false fact where
        "not measured" is the truth.
        """
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        lines, _ = _read(_host(tmp_path, {"system.slice": "0"}), path=str(empty))
        assert not any("cgroup2 is not mounted" in ln for ln in lines), lines
        assert any("not measured" in ln and "system.slice" in ln for ln in lines), lines

    @requires_bash
    def test_a_space_in_the_mount_point_is_decoded(self, tmp_path: Path) -> None:
        """mountinfo writes a space as \\040; the reading must follow it."""
        lines, _ = _read(
            _host(
                tmp_path,
                {"system.slice": "0", "system.slice/wslcb-web.service": str(256 * MIB)},
                root_name="cg root",
            )
        )
        assert len(_marked(lines, WARN)) == 1, lines


class TestPreflightRunsTheReading:
    """The lifted block is only evidence if the script runs it."""

    @requires_bash
    def test_this_host_gets_a_memory_protection_line(self, tmp_path: Path) -> None:
        binv = _stub_toolchain(tmp_path, "v22.11.0", "1.14.0")
        result = subprocess.run(
            ["bash", str(PREFLIGHT)],
            capture_output=True,
            text=True,
            timeout=120,
            env=_env(binv),
            cwd=str(tmp_path),
        )
        lines = [ln for ln in result.stdout.splitlines() if "Memory protection" in ln]
        assert lines, (
            "preflight printed no memory-protection line — where it cannot "
            f"measure it must say so, never skip\n{result.stdout}"
        )
        if not os.path.exists("/proc/self/mountinfo"):
            assert "not measured" in lines[0], lines
        assert result.returncode == 0, (
            "an advisory reading changed preflight's verdict on a host the "
            f"stubbed toolchain passes\n{result.stdout}"
        )


def _fenced(text: str, lang: str) -> list[str]:
    return re.findall(rf"^```{lang}\n(.*?)^```", text, re.S | re.M)


class TestTheDocsSnippetsWorkAsWritten:
    """The reference's commands are executed and parsed, not only read."""

    @staticmethod
    def _earlyoom_args() -> list[str]:
        line = next(
            ln
            for block in _fenced(HOST_MEMORY.read_text(), "sh")
            for ln in block.splitlines()
            if ln.startswith("EARLYOOM_ARGS=")
        )
        value = line.split("=", 1)[1]
        assert value.startswith('"') and value.endswith('"'), line
        # What systemd hands earlyoom for an unquoted `$EARLYOOM_ARGS`: the
        # EnvironmentFile's quotes removed, then split on whitespace, no shell.
        return value[1:-1].split()

    def test_no_regex_is_split_by_the_unquoted_expansion(self) -> None:
        args = self._earlyoom_args()
        for flag in ("--prefer", "--avoid"):
            i = args.index(flag)
            after = args[i + 2] if i + 2 < len(args) else None
            assert after is None or after.startswith("-"), (
                f"{flag}'s regex becomes more than one argument under Debian's "
                f"unquoted $EARLYOOM_ARGS (#303): {args}"
            )

    def test_prefer_matches_the_session_by_its_truncated_comm(self) -> None:
        args = self._earlyoom_args()
        prefer = args[args.index("--prefer") + 1]
        avoid = args[args.index("--avoid") + 1]
        assert not prefer.endswith("$"), (
            "a $-anchored --prefer never matches `npm exec socrat`, the "
            f"15-character comm of `npm exec socraticode@latest` (#307): {prefer}"
        )
        for comm in ("npm exec socrat", "MainThread", "claude"):
            assert re.search(prefer, comm), f"--prefer {prefer} misses {comm!r}"
            assert not re.search(avoid, comm), f"--avoid {avoid} shields {comm!r}"

    def test_no_ini_value_carries_an_inline_comment(self) -> None:
        """systemd reads `#` as a comment only at the start of a line.

        `MemoryLow=512M   # >= the sum…`, as #307 wrote it, sets the value to
        the whole remainder of the line.
        """
        for block in _fenced(HOST_MEMORY.read_text(), "ini"):
            for ln in block.splitlines():
                if "=" in ln and not ln.lstrip().startswith(("#", ";")):
                    assert "#" not in ln, f"inline comment in a unit setting: {ln!r}"

    @staticmethod
    def _walk(tmp_path: Path, control_group: str, tree: dict[str, str]) -> str:
        snippet = next(
            b for b in _fenced(HOST_MEMORY.read_text(), "bash") if "ControlGroup" in b
        )
        fs = tmp_path / "fs"
        for rel, low in tree.items():
            (fs / rel).mkdir(parents=True, exist_ok=True)
            (fs / rel / "memory.low").write_text(f"{low}\n")
        for line in ("unit=<unit>", "fs=/sys/fs/cgroup"):
            assert f"\n{line}\n" in f"\n{snippet}", (
                f"the verification snippet no longer opens with `{line}`, which "
                "is where this test points it at a fixture"
            )
        program = snippet.replace("unit=<unit>", "unit=fixture.service").replace(
            "fs=/sys/fs/cgroup", f"fs={fs}"
        )
        binv = tmp_path / "bin"
        binv.mkdir()
        (binv / "systemctl").write_text(f"#!/bin/sh\necho '{control_group}'\n")
        (binv / "systemctl").chmod(0o755)
        result = subprocess.run(
            ["bash", "-c", program],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "PATH": f"{binv}{os.pathsep}{os.environ['PATH']}"},
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    @requires_bash
    def test_the_walk_reaches_a_templated_units_implicit_slice(
        self, tmp_path: Path
    ) -> None:
        """The two-level `min(unit, parent)` the issue proposed reads 384 MiB here."""
        out = self._walk(
            tmp_path,
            "/system.slice/system-postgresql.slice/postgresql@16-main.service",
            {
                "system.slice": str(1024 * MIB),
                "system.slice/system-postgresql.slice": "0",
                "system.slice/system-postgresql.slice/postgresql@16-main.service": str(
                    384 * MIB
                ),
            },
        )
        assert "at most 0 MiB" in out and "3 levels" in out, out

    @requires_bash
    def test_the_walk_reads_a_plain_unit(self, tmp_path: Path) -> None:
        out = self._walk(
            tmp_path,
            "/system.slice/wslcb-web.service",
            {
                "system.slice": str(512 * MIB),
                "system.slice/wslcb-web.service": str(256 * MIB),
            },
        )
        assert "at most 256 MiB" in out and "2 levels" in out, out

    @requires_bash
    def test_a_stopped_unit_is_not_reported_as_unlimited(self, tmp_path: Path) -> None:
        """No ControlGroup means nothing was read — not `max`."""
        out = self._walk(tmp_path, "", {"system.slice": "0"})
        assert "no memory.low read" in out and "max" not in out, out


class TestTheOomPremiseIsConditional:
    """#303: the -1000 inheritance is measured on some hosts, not all."""

    def test_row_u_gives_the_check_rather_than_the_premise(self) -> None:
        row = next(
            ln
            for ln in TROUBLESHOOTING.read_text().splitlines()
            if ln.startswith("| **U**")
        )
        assert "cat /proc/<pid>/oom_score_adj" in row, row
        assert "exe.dev session processes inherit" not in row, (
            "row U still states the -1000 inheritance as true of every exe.dev "
            "host; notifier's sessions sit at 0 (#303)"
        )

    def test_the_actions_stand_either_way(self) -> None:
        text = " ".join(HOST_MEMORY.read_text().split())
        assert "The service-side actions below are the same either way." in text, (
            "a reader who measures 0 must be told not to skip the reservation "
            "and OOMScoreAdjust= (#303)"
        )

    def test_no_killer_is_promised_a_minus_1000_session(self) -> None:
        """earlyoom skips oom_score_adj -1000 exactly as the kernel does.

        `kill.c`, v1.7 and master: "Skip processes with oom_score_adj = -1000,
        like the kernel oom killer would." The -1000 row once said the
        service's OOMScoreAdjust= "lets earlyoom take the session first" there
        — a promise nothing on the service's side can keep, on the hosts where
        the service is most exposed. What does work is the session's own score.
        """
        for doc, marker in ((HOST_MEMORY, "| **-1000**"), (TROUBLESHOOTING, "| **U**")):
            row = next(
                ln for ln in doc.read_text().splitlines() if ln.startswith(marker)
            )
            assert "take the session first" not in row, row
            assert "earlyoom" in row and "skips a -1000 process" in row, (
                f"{doc.name} must say earlyoom cannot take a -1000 session: {row}"
            )
            assert "choom -n 500" in row, (
                f"{doc.name} must name the lever that works at -1000 — raising "
                f"the session's own score: {row}"
            )
