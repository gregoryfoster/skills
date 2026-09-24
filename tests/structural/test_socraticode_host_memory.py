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
- **#331.** On a host where sessions sit at -1000, `--prefer` reaches only a
  `choom`'d launch, and a dry run's badness column is printed before the skip
  that makes it so; on a host with swap, `-m` alone waits for swap to run out.

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
import shlex
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
            passed
            and "reserves up to 384 MiB" in passed[0]
            and "reserves up to 256 MiB" in passed[0]
        ), lines

    @requires_bash
    def test_siblings_summing_past_their_grant_are_named(self, tmp_path: Path) -> None:
        """Each within 512M, both together 768M: the kernel shares the 512M.

        `effective_protection()` in mm/page_counter.c: when the children's used
        claims exceed the parent's effective protection, each gets
        `protected * parent_effective / siblings_protected`. Checking each claim
        against its grant alone printed "a.service keeps 384 MiB, b.service
        keeps 384 MiB" under a ✓ here.
        """
        lines, _ = _read(
            _host(
                tmp_path,
                {
                    "system.slice": str(512 * MIB),
                    "system.slice/a.service": str(384 * MIB),
                    "system.slice/b.service": str(384 * MIB),
                },
            )
        )
        warned = _marked(lines, WARN)
        assert len(warned) == 1, lines
        for part in ("system.slice", "512 MiB", "768 MiB", "a.service", "b.service"):
            assert part in warned[0], f"the warning must name {part!r}: {warned}"
        assert not _marked(lines, PASS), lines
        assert not any("keeps 384" in ln for ln in lines), lines

    @requires_bash
    def test_a_nested_slices_children_are_summed_too(self, tmp_path: Path) -> None:
        lines, _ = _read(
            _host(
                tmp_path,
                {
                    "system.slice": str(1024 * MIB),
                    "system.slice/app.slice": str(512 * MIB),
                    "system.slice/app.slice/x.service": str(384 * MIB),
                    "system.slice/app.slice/y.service": str(384 * MIB),
                },
            )
        )
        warned = _marked(lines, WARN)
        assert len(warned) == 1, lines
        assert "under app.slice" in warned[0] and "768 MiB" in warned[0], warned
        assert "512 MiB app.slice grants" in warned[0], warned

    @requires_bash
    def test_a_lone_claim_over_its_grant_is_warned_once(self, tmp_path: Path) -> None:
        """One claimant over its grant is the clamp warning, not also a sum."""
        lines, _ = _read(
            _host(
                tmp_path,
                {
                    "system.slice": str(128 * MIB),
                    "system.slice/a.service": str(256 * MIB),
                },
            )
        )
        assert len(_marked(lines, WARN)) == 1, lines

    @requires_bash
    def test_a_unit_two_slices_down_is_read(self, tmp_path: Path) -> None:
        """The walk once stopped one slice below system.slice.

        A unit in a slice inside a slice, clamped to 0 there, got a ✓ reading
        "nothing under it claims MemoryLow=" — #307's failure, reported as its
        absence, one level further down than the templated case.
        """
        lines, _ = _read(
            _host(
                tmp_path,
                {
                    "system.slice": str(1024 * MIB),
                    "system.slice/app.slice": str(1024 * MIB),
                    "system.slice/app.slice/app-worker.slice": "0",
                    "system.slice/app.slice/app-worker.slice/worker@1.service": str(
                        256 * MIB
                    ),
                },
            )
        )
        warned = _marked(lines, WARN)
        assert len(warned) == 1, lines
        assert "app.slice/app-worker.slice/worker@1.service" in warned[0], warned
        assert "app-worker.slice grants 0 MiB" in warned[0], (
            f"the warning must name the slice that clamps it: {warned}"
        )
        assert not any("nothing under" in ln for ln in lines), lines

    @requires_bash
    def test_a_granted_nested_chain_passes(self, tmp_path: Path) -> None:
        lines, _ = _read(
            _host(
                tmp_path,
                {
                    "system.slice": str(1024 * MIB),
                    "system.slice/app.slice": str(512 * MIB),
                    "system.slice/app.slice/app-worker.slice": str(256 * MIB),
                    "system.slice/app.slice/app-worker.slice/worker@1.service": str(
                        256 * MIB
                    ),
                },
            )
        )
        assert not _marked(lines, WARN), lines
        passed = _marked(lines, PASS)
        assert passed and "worker@1.service" in passed[0], lines

    @requires_bash
    def test_the_depth_bound_is_named_not_dropped(self, tmp_path: Path) -> None:
        """Past the bound nothing is read, so nothing may be called absent."""
        tree = {"system.slice": str(1024 * MIB)}
        path = "system.slice"
        for n in range(8):
            path += f"/n{n}.slice"
            tree[path] = str(1024 * MIB)
        tree[f"{path}/deep.service"] = str(256 * MIB)
        lines, _ = _read(_host(tmp_path, tree))
        warned = _marked(lines, WARN)
        assert any("not measured past" in ln and "n5.slice" in ln for ln in warned), (
            lines
        )
        assert not any("nothing under" in ln for ln in lines), lines

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

    # The templated case again, with the option systemd mounts cgroup2 with
    # where the kernel has it. address-validator's clamp was measured on a bare
    # `rw` mount, which the test above without the option still holds.
    RECURSIVEPROT = "rw,nsdelegate,memory_recursiveprot"

    @requires_bash
    def test_recursiveprot_makes_a_zero_slice_a_share_not_a_clamp(
        self, tmp_path: Path
    ) -> None:
        """#307 CR 43: under a granting parent, a slice at 0 passes down a share.

        effective_protection()'s recursive branch gives a child that claims
        less than its parent affords a share of the parent's unclaimed
        protection in proportion to its unprotected usage, "without requiring
        explicit downward propagation into leaf cgroups". The walk passed down
        min(grant, memory.low) regardless, and told this host the unit keeps
        at most 0 MiB.
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
                opts=self.RECURSIVEPROT,
            )
        )
        warned = _marked(lines, WARN)
        assert len(warned) == 1, lines
        assert "postgresql@16-main.service" in warned[0], warned
        assert "at most 0 MiB" not in warned[0], (
            "under memory_recursiveprot a slice granting 0 below a 1024 MiB "
            f"system.slice is not a clamp to 0: {warned}"
        )
        for part in ("usage", "up to 384 MiB", "1024 MiB system.slice grants"):
            assert part in warned[0], f"the warning must say {part!r}: {warned}"

    @requires_bash
    def test_the_share_is_bounded_by_the_siblings_claims(self, tmp_path: Path) -> None:
        """The unclaimed part is the grant less what the siblings claim."""
        lines, _ = _read(
            _host(
                tmp_path,
                {
                    "system.slice": str(512 * MIB),
                    "system.slice/a.service": str(384 * MIB),
                    "system.slice/system-postgresql.slice": "0",
                    "system.slice/system-postgresql.slice/postgresql@16-main.service": str(
                        384 * MIB
                    ),
                },
                opts=self.RECURSIVEPROT,
            )
        )
        warned = _marked(lines, WARN)
        assert len(warned) == 1, lines
        assert "up to 128 MiB" in warned[0], warned
        assert "384 MiB its siblings claim" in warned[0], warned

    @requires_bash
    def test_siblings_claiming_the_whole_grant_leave_no_share(
        self, tmp_path: Path
    ) -> None:
        """Nothing unclaimed, nothing to share: the static reading is the clamp."""
        lines, _ = _read(
            _host(
                tmp_path,
                {
                    "system.slice": str(512 * MIB),
                    "system.slice/a.service": str(512 * MIB),
                    "system.slice/system-postgresql.slice": "0",
                    "system.slice/system-postgresql.slice/postgresql@16-main.service": str(
                        384 * MIB
                    ),
                },
                opts=self.RECURSIVEPROT,
            )
        )
        warned = _marked(lines, WARN)
        assert len(warned) == 1, lines
        assert "at most 0 MiB" in warned[0], warned
        assert "system-postgresql.slice grants 0 MiB" in warned[0], warned

    # The option only ADDS: effective_protection()'s recursive branch computes
    # ep = min(usage, claim) and then adds the unclaimed share to it, so what a
    # chain of grants reserves is reserved with the option too (#307 CR 66).
    # CR 43 walked the share in the grant's place, and every unit below a slice
    # granting less than its parent read as "not a reservation".
    @requires_bash
    @pytest.mark.parametrize(
        ("slice_low", "claim"),
        [(384, 384), (256, 128)],
        ids=["every-link-granted", "claim-within-the-slice"],
    )
    def test_recursiveprot_leaves_a_granted_chain_reserved(
        self, tmp_path: Path, slice_low: int, claim: int
    ) -> None:
        """address-validator's fixed chain, 1G / 384M / 384M, is host-memory.md's
        own remedy. With the option it read as unprotected, and the hint sent
        the operator to grant slices that were granted."""
        lines, _ = _read(
            _host(
                tmp_path,
                {
                    "system.slice": str(1024 * MIB),
                    "system.slice/system-postgresql.slice": str(slice_low * MIB),
                    "system.slice/system-postgresql.slice/postgresql@16-main.service": str(
                        claim * MIB
                    ),
                },
                opts=self.RECURSIVEPROT,
            )
        )
        assert not _marked(lines, WARN), lines
        assert not _marked(lines, HINT), lines
        passed = _marked(lines, PASS)
        assert len(passed) == 1, lines
        assert f"reserves up to {claim} MiB" in passed[0], passed
        assert "with memory_recursiveprot" in passed[0], passed

    @requires_bash
    def test_recursiveprot_keeps_the_slices_own_grant_reserved(
        self, tmp_path: Path
    ) -> None:
        """A 512M claim under a 256M slice reserves the 256M, and may keep a
        share above it. It read as reserving nothing."""
        lines, _ = _read(
            _host(
                tmp_path,
                {
                    "system.slice": str(1024 * MIB),
                    "system.slice/foo.slice": str(256 * MIB),
                    "system.slice/foo.slice/a.service": str(512 * MIB),
                },
                opts=self.RECURSIVEPROT,
            )
        )
        warned = _marked(lines, WARN)
        assert len(warned) == 1, lines
        for part in (
            "reserves only 256 MiB",
            "its foo.slice grants 256 MiB",
            "usage-dependent share of up to 512 MiB",
            "1024 MiB system.slice grants",
        ):
            assert part in warned[0], f"the warning must say {part!r}: {warned}"
        assert "not a reservation either" not in warned[0], warned

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

    def test_the_doc_states_the_walks_real_depth(self) -> None:
        """host-memory.md once said preflight "runs the same walk" at two levels."""
        found = re.search(r"^PROTECTION_DEPTH=(\d+)$", PREFLIGHT.read_text(), re.M)
        assert found, "preflight.sh no longer sets PROTECTION_DEPTH"
        words = {4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}
        depth = words.get(int(found.group(1)), found.group(1))
        text = " ".join(HOST_MEMORY.read_text().split())
        assert f"through nested slices {depth} levels deep" in text, (
            "host-memory.md must state how deep preflight's walk goes — "
            f"PROTECTION_DEPTH is {found.group(1)}"
        )

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


def _env_file_value(raw: str) -> str:
    """A double-quoted `EnvironmentFile=` value as systemd 255 reads it.

    src/basic/env-file.c: the quotes go, a backslash before one of
    `"`, `\\`, `` ` `` or `$` yields that character, and any other backslash
    is kept along with the character after it.
    """
    assert raw.startswith('"') and raw.endswith('"'), raw
    out, escaped = [], False
    for c in raw[1:-1]:
        if escaped:
            out.append(c if c in '"\\`$' else "\\" + c)
            escaped = False
        elif c == "\\":
            escaped = True
        else:
            out.append(c)
    return "".join(out)


def _systemd_split(value: str) -> list[str]:
    """An unquoted `$VAR` in `ExecStart=`, split as systemd 255 splits it.

    replace_env_argv() in src/basic/env-util.c calls strv_split_full(...,
    WHITESPACE, EXTRACT_RELAX|EXTRACT_UNQUOTE), so extract_first_word() in
    src/basic/extract-word.c: whitespace separates, single and double quotes
    group and are removed, and a backslash — quoted or not — is dropped and the
    character after it kept literally. #303 read this as a plain whitespace
    split with no quoting; the quoting is real, and so is the lost backslash.
    """
    words: list[str] = []
    word: list[str] = []
    quote, escaped, started = None, False, False
    for c in value:
        if escaped:
            word.append(c)
            escaped = False
        elif quote:
            if c == quote:
                quote = None
            elif c == "\\":
                escaped = True
            else:
                word.append(c)
        elif c in "'\"":
            quote, started = c, True
        elif c == "\\":
            escaped, started = True, True
        elif c in " \t\n\r":
            if started:
                words.append("".join(word))
                word, started = [], False
        else:
            word.append(c)
            started = True
    if started:
        words.append("".join(word))
    return words


class TestTheDocsSnippetsWorkAsWritten:
    """The reference's commands are executed and parsed, not only read."""

    @staticmethod
    def _earlyoom_value() -> str:
        line = next(
            ln
            for block in _fenced(HOST_MEMORY.read_text(), "sh")
            for ln in block.splitlines()
            if ln.startswith("EARLYOOM_ARGS=")
        )
        return line.split("=", 1)[1]

    @classmethod
    def _earlyoom_args(cls) -> list[str]:
        """What systemd hands earlyoom for Debian's unquoted `$EARLYOOM_ARGS`."""
        return _systemd_split(_env_file_value(cls._earlyoom_value()))

    def test_the_split_is_modelled_as_systemd_splits(self) -> None:
        """Quotes group and vanish; a backslash vanishes and its character stays."""
        raw = "\"--prefer '^(npm exec)' --avoid ^a\\.b$\""
        assert _systemd_split(_env_file_value(raw)) == [
            "--prefer",
            "^(npm exec)",
            "--avoid",
            "^a.b$",
        ]

    def test_the_earlyoom_traps_name_the_backslash(self) -> None:
        """The doc's list of silent misconfigurations says what the split does."""
        text = HOST_MEMORY.read_text()
        found = re.search(
            r"(\w+) ways it silently runs something other than what you wrote:"
            r"\n\n((?:- .*\n(?:  .*\n)*)+)",
            text,
        )
        assert found, "host-memory.md's list of earlyoom traps moved or was reworded"
        traps = re.findall(r"^- \*\*(.+?)\*\*", found.group(2), re.M)
        count = {"three": 3, "four": 4, "five": 5, "six": 6}[found.group(1).lower()]
        assert count == len(traps), (found.group(1), traps)
        assert any("backslash" in t.lower() for t in traps), traps
        assert "no shell quoting" not in " ".join(text.split()), (
            "systemd's split of $EARLYOOM_ARGS honours quotes "
            "(EXTRACT_RELAX|EXTRACT_UNQUOTE); the doc must not say otherwise"
        )

    def test_no_regex_carries_a_backslash(self) -> None:
        """`\\.` reaches earlyoom as `.`, a regex that matches any character."""
        value = self._earlyoom_value()
        assert "\\" not in value, (
            "systemd's split of $EARLYOOM_ARGS drops a backslash and keeps the "
            f"character after it, silently changing the regex: {value}"
        )

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

    def test_each_host_is_named_with_what_was_measured_on_it(self) -> None:
        """#307 CR 31: "corroborated on a fourth" hid two single-host findings.

        The templated-slice clamp and the -1000 reading with no `exe-init`
        were measured on address-validator and nowhere else, and a reader
        weighing either needs to know that.
        """
        text = " ".join(HOST_MEMORY.read_text().split())
        start = text.index("## A production service on the same host")
        intro = text[start : text.index("### 1.", start)]
        assert "corroborated on a fourth" not in intro, intro
        for host in ("broker", "notifier", "wslcb-licensing-tracker"):
            assert host in intro, f"{host} is not named: {intro}"
        on_av = intro[intro.index("address-validator") :]
        assert "templated-slice clamp" in on_av and "exe-init" in on_av, (
            f"address-validator's own findings must be attributed to it: {intro}"
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


def _section_four() -> str:
    text = HOST_MEMORY.read_text()
    start = text.index("### 4.")
    return text[start:]


class TestTheEarlyKillerFollowsTheHostClass:
    """#331: what earlyoom does turns on §1's reading, and so does its config.

    Two cohort hosts at -1000 installed the one configuration §4 gave and
    documented it as preferring dev tooling, which earlyoom never selects
    there; one pinned a `--prefer` floor of 300 in its tests, read off a dry
    run's badness column, which is printed before the -1000 skip. And every
    host that ran it had no swap, which hid that `-m` waits for swap too.
    """

    @staticmethod
    def _args() -> list[str]:
        return TestTheDocsSnippetsWorkAsWritten._earlyoom_args()

    def test_memory_alone_decides_on_a_host_with_swap(self) -> None:
        """earlyoom needs memory AND swap below their minimums to act.

        The package default is `-s 10`, so on replicator (4 G swap) `-m 12,6`
        alone waited for ~3.7 GB paged out. `-s 100` alone is not the fix:
        SIGKILL's swap figure defaults to half the SIGTERM one, so it still
        waits for swap to be half used.
        """
        args = self._args()
        assert "-s" in args, (
            "the configuration leaves swap at the package's `-s 10`: on a host "
            f"with swap, `-m` then waits until swap is ~90% used (#331): {args}"
        )
        assert args[args.index("-s") + 1] == "100,100", (
            "both swap figures must be 100 for memory alone to decide — a bare "
            f"`-s 100` leaves SIGKILL's at 50 (#331): {args}"
        )

    def test_the_dry_run_cannot_kill(self) -> None:
        """The reproduction is offered as safe: every earlyoom it runs is --dryrun."""
        runs = []
        for block in _fenced(HOST_MEMORY.read_text(), "bash"):
            for line in block.replace("\\\n", " ").splitlines():
                words = shlex.split(line, comments=True)
                if any(w.endswith("/earlyoom") for w in words):
                    runs.append(words)
        assert runs, "host-memory.md no longer shows how to dry-run earlyoom"
        for words in runs:
            assert "--dryrun" in words, (
                f"an earlyoom run in host-memory.md can send a signal: {words}"
            )

    def test_the_dry_run_prints_the_verdict_lines(self) -> None:
        """The badness column is pre-skip; only the verdict lines are evidence."""
        block = next(
            b for b in _fenced(HOST_MEMORY.read_text(), "bash") if "--dryrun" in b
        )
        assert "^sending" in block and "^pid" in block, (
            "the dry run must keep the `sending` line and the `pid` rows, where "
            f"`<--- new victim` is marked (#331)\n{block}"
        )
        prose = " ".join(_section_four().split())
        assert "new victim" in prose and "never the badness column" in prose, (
            "a -1000 `--prefer` match prints badness 300 in a dry run and is "
            "never taken; §4 must say to read the verdict, not the score"
        )

    def test_the_minus_1000_host_is_told_what_prefer_reaches(self) -> None:
        row = next(
            ln for ln in _section_four().splitlines() if ln.startswith("| **-1000**")
        )
        assert "choom -n 500" in row, row
        assert "decline" in row, (
            "declining earlyoom at -1000 is a legitimate outcome and the row "
            f"must say so (#331): {row}"
        )


# Options of systemd-run's that take a value, as a separate word.
SYSTEMD_RUN_VALUED = {
    "-p",
    "--property",
    "-E",
    "--setenv",
    "-H",
    "--host",
    "-M",
    "--machine",
    "-u",
    "--unit",
    "--description",
    "--slice",
}


def _systemd_run(argv: list[str]) -> tuple[list[str], list[str]]:
    """systemd-run's options, and the command it runs.

    It stops at the first word that is not an option: v255's optstring
    starts with `+`, and main's parser is OPTION_PARSER_STOP_AT_FIRST_NONOPTION.
    A `--` ends them early and is consumed, so `… -- choom` and `… choom`
    run the same command.
    """
    assert argv[0] == "systemd-run", argv
    i, opts = 1, []
    while i < len(argv):
        word = argv[i]
        if word == "--":
            i += 1
            break
        if not word.startswith("-"):
            break
        if word in SYSTEMD_RUN_VALUED:
            opts += argv[i : i + 2]
            i += 2
        else:
            opts.append(word)
            i += 1
    return opts, argv[i:]


def _choom(argv: list[str]) -> tuple[dict[str, str], list[str]]:
    """choom's options, and the command it runs.

    util-linux choom.c parses with getopt_long("hn:p:V") — no `+`, so GNU
    getopt permutes: until a `--`, every option-looking word is choom's
    wherever it sits. `choom -n 500 npm install --prefix …` is an error, not
    an install.
    """
    assert argv[0] == "choom", argv
    opts: dict[str, str] = {}
    rest: list[str] = []
    i = 1
    while i < len(argv):
        word = argv[i]
        if word == "--":
            rest += argv[i + 1 :]
            break
        if word in ("-n", "-p"):
            opts[word] = argv[i + 1]
            i += 2
            continue
        assert not word.startswith("-"), f"choom rejects {word!r}: {argv}"
        rest.append(word)
        i += 1
    return opts, rest


def _host_capacity(mem_kb: int) -> list[str]:
    """preflight.sh's host-capacity block, run for a host of `mem_kb`.

    Lifted between its sentinels, as the memory-protection block is, because
    the script reads total memory from /proc/meminfo or sysctl and no suite
    host is small enough to reach the hints.
    """
    body = PREFLIGHT.read_text()
    start = body.index("# >>> host-capacity\n")
    end = body.index("# <<< host-capacity\n")
    helpers = [
        ln for ln in body.splitlines() if re.match(r"^(pass|warn|hint)\(\) \{", ln)
    ]
    program = (
        "set -euo pipefail\n"
        + "\n".join(helpers)
        + f"\nMEM_KB={mem_kb}\nSC_PIN_DIR=/home/u/.socraticode/pin\n"
        + body[start:end]
    )
    result = subprocess.run(
        [shutil.which("bash") or "/bin/bash", "-c", program],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


class TestTheCappedInstallCanBeKilled:
    """#307 CR 51: CR 1's -1000 lever reaches the capped pre-install too.

    At oom_score_adj -1000 no killer takes a process, so a MemoryMax= cap on
    one stalls it rather than killing it — row U's capped scope runs its
    command under `choom -n 500` for that reason. The capped pre-install
    preflight prints and host-memory.md shows did not, and preflight's
    shared-host hint stopped at the service side on every host.
    """

    @staticmethod
    def _preflight_command() -> str:
        lines = _host_capacity(2 * 1024 * 1024)
        line = next((ln for ln in lines if "Pre-install once under a cap" in ln), "")
        assert "systemd-run" in line, lines
        return line[line.index("systemd-run") :]

    @staticmethod
    def _doc_command() -> str:
        block = next(
            b for b in _fenced(HOST_MEMORY.read_text(), "bash") if "systemd-run" in b
        )
        joined = block.replace("\\\n", " ")
        return next(ln for ln in joined.splitlines() if ln.startswith("systemd-run"))

    @staticmethod
    def _row_u_command() -> str:
        row = next(
            ln
            for ln in TROUBLESHOOTING.read_text().splitlines()
            if ln.startswith("| **U**")
        )
        found = re.search(r"`(systemd-run [^`]*)`", row)
        assert found, row
        return found.group(1)

    @requires_bash
    @pytest.mark.parametrize("where", ["preflight", "host-memory.md"])
    def test_the_capped_install_runs_under_choom(self, where: str) -> None:
        cmd = self._preflight_command() if where == "preflight" else self._doc_command()
        opts, command = _systemd_run(shlex.split(cmd))
        assert "MemoryMax=1536M" in opts, cmd
        assert command and command[0] == "choom", (
            f"{where}'s capped install runs {command[:1]}, not choom — at "
            f"oom_score_adj -1000 the cap stalls it rather than killing it\n{cmd}"
        )
        adj, install = _choom(command)
        assert adj == {"-n": "500"}, cmd
        assert install[:3] == ["npm", "install", "--prefix"], install

    @requires_bash
    def test_every_capped_scope_is_composed_alike(self) -> None:
        """Row U's scope, preflight's hint and the doc's block: one shape."""
        shapes = set()
        for cmd in (
            self._row_u_command(),
            self._preflight_command(),
            self._doc_command(),
        ):
            words = shlex.split(cmd)
            assert "choom" in words, f"a capped scope without choom: {cmd}"
            at = words.index("choom")
            shapes.add((words[at - 1] == "--", tuple(words[at : at + 4])))
        assert len(shapes) == 1, shapes

    @requires_bash
    def test_the_shared_host_hint_names_choom_at_minus_1000(self) -> None:
        lines = _host_capacity(2 * 1024 * 1024)
        at_1000 = [ln for ln in lines if "-1000" in ln]
        assert at_1000, lines
        assert any("choom -n 500" in ln for ln in at_1000), (
            "where sessions sit at -1000 nothing on the service's side makes "
            f"one killable; the hint must name the session's own lever\n{at_1000}"
        )

    @requires_bash
    def test_a_host_with_room_gets_no_hint(self) -> None:
        lines = _host_capacity(8 * 1024 * 1024)
        assert len(lines) == 1 and "Host memory 8.0 GiB" in lines[0], lines
