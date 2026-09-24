"""The daily health hook caps its own launch where the host can cap (#330).

`socraticode-health.sh` runs `mcp-driver.mjs health-check` from SessionStart,
once per UTC day: the one SocratiCode launch nobody is watching. On
co-replicator (3.82 GiB, no swap, a production co-tenant)
CannObserv/replicator#99 measured it as the only uncapped launcher on the host
— the #295 shape. Row U's capped scope existed only as prose and as
invocations each repo copied into its own docs.

Where the cap lives is what the issue's first trap decides. `install-hook.sh`
dedupes on the `# socraticode-health` marker and rebuilds the command from its
constants, keeping only `timeout` (#259), so replicator's wrapper in
`.claude/settings.json` (replicator `fb73b74..fba4cd9`) is erased, silently, by
the next `init-socraticode` re-run. The hook is a symlink into the vendored
skill, so the cap goes there and survives every re-run.

The other four traps are each a test class here:

- **The probe must pass the payload's properties** (trap 2). A bare probe
  succeeds where they are unsupported; the real call then fails with the
  uncapped branch behind it, and the hook fails closed. The hook runs both
  through one function, and `TestTheProbeIsTheCall` holds them to one prefix.
- **`capped || uncapped` is not the fix** (trap 3): it re-runs, uncapped, the
  process the cap just killed. `TestACapKillIsReportedAsSuch` counts runs.
- **choom** (trap 4): at oom_score_adj -1000 a cap stalls instead of killing.
- **Not every host can cap** (trap 5), and the ones that cannot must hear
  nothing: `TestAHostThatCannotCap`.

Stubs stand in for `systemd-run`, `choom` and `systemctl`, and for the driver:
no server, no Docker, no network, and no real scope — except
`TestARealCapKills`, which runs only where user systemd can cap a scope, and
is the acceptance's "a stub that exceeds a tiny MemoryMax".
"""

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

# The module, not its Test class: a `Test*` name imported here would be
# collected, and run, a second time as this module's own.
from . import test_socraticode_host_memory as host_memory
from .test_socraticode_graph_yield import HOOK, _clean_env, _repo, requires_node
from .test_socraticode_host_memory import _choom, _systemd_run

SEP = "\x1f"
FINDINGS_HEADER = "findings from today's once-per-day check"
CAP_LINE = "stopped by its memory cap"

# Each stub records its argv, one call per line, fields split by SEP, then
# behaves as the real tool does on a host that can cap: systemd-run and choom
# run their command, systemctl answers from the environment.
SYSTEMD_RUN_STUB = r"""#!/usr/bin/env bash
{ printf '%s\x1f' systemd-run "$@"; printf '\n'; } >>"$STUB_LOG"
if [ -n "${STUB_RUN_FAIL:-}" ]; then
  echo "Failed to connect to bus: No medium found" >&2
  exit 1
fi
while [ $# -gt 0 ]; do
  case "$1" in
    --user | --scope | -q | --quiet | --unit=*) shift ;;
    -p)
      for bad in ${STUB_REJECT_PROPS:-}; do
        case "$2" in "$bad"=*) echo "Unknown assignment: $2" >&2; exit 1 ;; esac
      done
      shift 2 ;;
    --) shift; break ;;
    -*) echo "stub systemd-run: unexpected option $1" >&2; exit 64 ;;
    *) break ;;
  esac
done
exec "$@"
"""

CHOOM_STUB = r"""#!/usr/bin/env bash
{ printf '%s\x1f' choom "$@"; printf '\n'; } >>"$STUB_LOG"
[ "$1" = -n ] && shift 2
[ "$1" = -- ] && shift
exec "$@"
"""

# `show -p MemoryCurrent` answers a byte count, as for a scope whose memory
# systemd accounts, or STUB_MEMORY_CURRENT — "[not set]" where it has no
# memory controller and would not enforce a MemoryMax=.
#
# `show -p Result` answers "success" for the first STUB_RESULT_AFTER queries,
# with the scope still deactivating, then STUB_SCOPE_RESULT: systemd records an
# OOM kill asynchronously, so the hook has to wait for a scope winding down.
SYSTEMCTL_STUB = r"""#!/usr/bin/env bash
{ printf '%s\x1f' systemctl "$@"; printf '\n'; } >>"$STUB_LOG"
case "$*" in
  *"-p Result"*)
    n=$(grep -c 'p.Result' "$STUB_LOG" || true)
    if [ "$n" -le "${STUB_RESULT_AFTER:-0}" ]; then echo success
    else echo "${STUB_SCOPE_RESULT:-success}"; fi ;;
  *"-p ActiveState"*)
    n=$(grep -c 'p.Result' "$STUB_LOG" || true)
    if [ "$n" -le "${STUB_RESULT_AFTER:-0}" ]; then echo deactivating
    else echo "${STUB_SCOPE_STATE:-inactive}"; fi ;;
  *"-p MemoryCurrent"*) echo "${STUB_MEMORY_CURRENT:-1503232}" ;;
esac
exit 0
"""

# The driver: counts its runs, prints what it is told, exits how it is told.
DRIVER_STUB = """import fs from 'node:fs';
fs.appendFileSync(process.env.STUB_RUNS, 'run\\n');
process.stderr.write(process.env.STUB_STDERR || '');
process.exit(Number(process.env.STUB_EXIT || 0));
"""


class Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.repo = _repo(tmp_path)
        self.bin = tmp_path / "stub-bin"
        self.bin.mkdir()
        for name, body in (
            ("systemd-run", SYSTEMD_RUN_STUB),
            ("choom", CHOOM_STUB),
            ("systemctl", SYSTEMCTL_STUB),
        ):
            path = self.bin / name
            path.write_text(body)
            path.chmod(0o755)
        self.driver = tmp_path / "stub-driver.mjs"
        self.driver.write_text(DRIVER_STUB)
        self.calls_log = tmp_path / "calls.log"
        self.runs_log = tmp_path / "runs.log"
        self.calls_log.touch()
        self.runs_log.touch()

    def run(self, *, stubs: bool = True, **env: str) -> subprocess.CompletedProcess:
        path = os.environ.get("PATH", "")
        if stubs:
            path = f"{self.bin}{os.pathsep}{path}"
        return subprocess.run(
            ["bash", str(HOOK)],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(
                SOCRATICODE_HEALTH_FORCE="1",
                SOCRATICODE_DRIVER=str(self.driver),
                STUB_LOG=str(self.calls_log),
                STUB_RUNS=str(self.runs_log),
                PATH=path,
                **env,
            ),
        )

    def calls(self, program: str) -> list[list[str]]:
        rows = [ln.split(SEP)[:-1] for ln in self.calls_log.read_text().splitlines()]
        return [row for row in rows if row and row[0] == program]

    def runs(self) -> int:
        return len(self.runs_log.read_text().splitlines())

    def hook_log(self) -> str:
        log = self.repo / ".git" / "socraticode-health.log"
        return log.read_text() if log.exists() else ""


def _split(call: list[str]) -> tuple[list[str], dict[str, str], list[str]]:
    """systemd-run's options minus the unit name, choom's, and the payload."""
    opts, command = _systemd_run(call)
    opts = [o for o in opts if not o.startswith("--unit=")]
    choom_opts, payload = _choom(command)
    return opts, choom_opts, payload


def _unit(call: list[str]) -> str:
    return next(w for w in call if w.startswith("--unit="))[len("--unit=") :]


def _props(opts: list[str]) -> list[str]:
    return [opts[i + 1] for i, w in enumerate(opts) if w == "-p"]


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


class TestTheProbeIsTheCall:
    """Trap 2: one prefix for both, so a probe cannot drop a property."""

    @requires_node
    def test_the_probe_and_the_payload_share_one_prefix(self, harness: Harness) -> None:
        result = harness.run()
        assert result.returncode == 0, result.stderr
        probe, payload = harness.calls("systemd-run")
        p_opts, p_choom, p_cmd = _split(probe)
        c_opts, c_choom, c_cmd = _split(payload)
        assert p_opts == c_opts, (
            "the probe and the payload reached systemd-run with different "
            f"options — a probe that drops a property succeeds where the call "
            f"then fails, and the hook fails closed (#330 trap 2)\n"
            f"  probe:   {p_opts}\n  payload: {c_opts}"
        )
        assert p_choom == c_choom == {"-n": "500"}, (p_choom, c_choom)
        assert p_cmd[:2] == ["sh", "-c"], p_cmd
        assert c_cmd[0] == "node" and "health-check" in c_cmd, c_cmd

    @requires_node
    def test_the_probe_asks_whether_its_own_scope_is_accounted(
        self, harness: Harness
    ) -> None:
        """Accepted is not enforced: systemd takes a MemoryMax= it has no
        controller for. The probe asks about its own scope, not the payload's,
        which does not exist yet."""
        harness.run()
        probe, _ = harness.calls("systemd-run")
        asked = [c for c in harness.calls("systemctl") if "MemoryCurrent" in c]
        assert [c[-1] for c in asked] == [f"{_unit(probe)}.scope"], (
            "the probe should ask systemd once whether it accounts the probe "
            f"scope's memory: {asked}"
        )

    @requires_node
    def test_a_cap_without_memory_asks_nothing_of_it(self, harness: Harness) -> None:
        """A CPU-only cap is not refused over a controller it never uses."""
        harness.run(
            SOCRATICODE_HEALTH_CAP="CPUQuota=50%", STUB_MEMORY_CURRENT="[not set]"
        )
        probe, _ = harness.calls("systemd-run")
        assert _split(probe)[2] == ["true"], probe
        assert harness.runs() == 1

    @requires_node
    def test_the_default_properties_are_row_us(self, harness: Harness) -> None:
        """One cap, stated once in prose and once in code, and they agree."""
        harness.run()
        (_, payload) = harness.calls("systemd-run")
        row_u, _ = _systemd_run(
            shlex.split(host_memory.TestTheCappedInstallCanBeKilled._row_u_command())
        )
        assert _props(_split(payload)[0]) == _props(row_u), (
            "the hook's default scope and troubleshooting.md row U's disagree"
        )

    @requires_node
    def test_the_payload_runs_under_its_own_named_scope(self, harness: Harness) -> None:
        """Named, so the hook can ask that scope how it ended — and distinct
        from the probe's, so the question is about the payload."""
        harness.run()
        probe, payload = harness.calls("systemd-run")
        assert _unit(payload).startswith("socraticode-health-"), payload
        assert _unit(probe) != _unit(payload), (probe, payload)

    def test_the_help_quotes_the_default_it_applies(self) -> None:
        """--help spells the default out twice; the code holds it once."""
        default = re.search(r'^CAP_DEFAULT="([^"]*)"$', HOOK.read_text(), re.M)
        assert default, "no CAP_DEFAULT assignment in socraticode-health.sh"
        usage = subprocess.run(
            ["bash", str(HOOK), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        for word in default.group(1).split():
            assert usage.count(word) >= 2, (
                f"--help's Behaviour and Env entries should both quote {word!r}, "
                "the default the hook applies (CR 8)"
            )

    def test_the_hook_invokes_systemd_run_in_one_place(self) -> None:
        """The behavioural test covers today's code; this covers the next
        edit, which would add a second hand-written invocation."""
        sites = [
            ln
            for ln in HOOK.read_text().splitlines()
            if ln.lstrip().startswith("systemd-run ")
        ]
        assert len(sites) == 1, (
            "socraticode-health.sh should reach systemd-run through one "
            f"function, the probe and the payload alike; found {sites}"
        )


class TestAHostThatCannotCap:
    """Trap 5: uncapped, as before, and silent about it."""

    @requires_node
    def test_no_user_bus_runs_uncapped_and_says_nothing(self, harness: Harness) -> None:
        result = harness.run(STUB_RUN_FAIL="1")
        assert result.returncode == 0, result.stderr
        assert result.stdout == "", (
            "a host that cannot cap heard about it — every session on it "
            f"would, daily (#330 trap 5): {result.stdout!r}"
        )
        assert harness.runs() == 1, "the check did not run uncapped"
        assert not harness.calls("choom"), "the payload went through the cap"
        assert "memory cap unavailable" in harness.hook_log(), harness.hook_log()
        assert "Failed to connect to bus" in harness.hook_log(), (
            "the log says the probe failed but not why (CR 5)"
        )

    @requires_node
    def test_unsupported_properties_run_uncapped_too(self, harness: Harness) -> None:
        """Replicator's first wrapper: user systemd, but no cpu delegation."""
        result = harness.run(STUB_REJECT_PROPS="CPUQuota")
        assert result.returncode == 0, result.stderr
        assert result.stdout == "", result.stdout
        assert len(harness.calls("systemd-run")) == 1, (
            "the payload was launched through a scope the probe had already "
            "shown cannot be created"
        )
        assert harness.runs() == 1
        assert "Unknown assignment: CPUQuota=100%" in harness.hook_log(), (
            "a refused property logs like a missing bus, so an operator cannot "
            f"tell their cap was rejected (CR 5)\n{harness.hook_log()}"
        )

    @requires_node
    def test_a_cap_systemd_would_not_enforce_runs_uncapped(
        self, harness: Harness
    ) -> None:
        """cgroup v1, or no memory controller delegated: the properties are
        accepted, exit 0, and bind nothing. Measured on systemd 255 — a 320 MB
        payload outlived MemoryMax=64M — so "capped" in the log would be false.
        """
        result = harness.run(STUB_MEMORY_CURRENT="[not set]")
        assert result.returncode == 0, result.stderr
        assert result.stdout == "", result.stdout
        assert len(harness.calls("systemd-run")) == 1, (
            "the payload was launched under a cap the probe had found systemd "
            "would not enforce"
        )
        assert harness.runs() == 1
        log = harness.hook_log()
        assert "memory cap unavailable" in log and "MemoryCurrent=[not set]" in log, log
        assert "capped: scope" not in log, log

    @requires_node
    def test_findings_still_reach_the_session(self, harness: Harness) -> None:
        result = harness.run(
            STUB_RUN_FAIL="1",
            STUB_EXIT="1",
            STUB_STDERR="  - graph yield LOW — 3 edge(s) across 374 files\n",
        )
        assert FINDINGS_HEADER in result.stdout, result.stdout
        assert "graph yield LOW" in result.stdout, result.stdout

    @requires_node
    def test_off_never_reaches_systemd_run(self, harness: Harness) -> None:
        result = harness.run(SOCRATICODE_HEALTH_CAP="off")
        assert result.stdout == "", result.stdout
        assert not harness.calls("systemd-run")
        assert harness.runs() == 1

    @requires_node
    @pytest.mark.skipif(
        shutil.which("systemd-run") is not None,
        reason="needs a host with no systemd-run at all, like macOS",
    )
    def test_a_host_without_systemd_is_untouched(self, harness: Harness) -> None:
        result = harness.run(stubs=False)
        assert result.stdout == "", result.stdout
        assert harness.runs() == 1
        assert "cap" not in harness.hook_log().lower(), harness.hook_log()


class TestACapKillIsReportedAsSuch:
    """Neither silence, nor "defects found", nor "could not run" — and once."""

    @requires_node
    def test_a_kill_says_it_was_the_cap(self, harness: Harness) -> None:
        result = harness.run(STUB_EXIT="137", STUB_SCOPE_RESULT="oom-kill")
        assert result.returncode == 0, result.stderr
        assert f"{CAP_LINE} (MemoryMax=1536M)" in result.stdout, result.stdout
        assert "not a clean result" in result.stdout, result.stdout
        assert "FAILED TO RUN" not in result.stdout, (
            "a check the cap stopped was reported as one that could not run — "
            f"those call for opposite responses (#330)\n{result.stdout}"
        )
        assert FINDINGS_HEADER not in result.stdout, result.stdout

    @requires_node
    def test_it_is_not_re_run_uncapped(self, harness: Harness) -> None:
        """Trap 3: `capped || uncapped` would undo the cap on the host it
        was protecting."""
        harness.run(STUB_EXIT="137", STUB_SCOPE_RESULT="oom-kill")
        assert harness.runs() == 1, (
            f"the driver ran {harness.runs()} times after its cap killed it "
            "(#330 trap 3)"
        )
        assert "not re-run uncapped" in harness.hook_log(), harness.hook_log()

    @requires_node
    def test_a_scope_still_winding_down_is_waited_for(self, harness: Harness) -> None:
        """systemd records the kill asynchronously: an answer read too early
        would call a cap kill a crash."""
        result = harness.run(
            STUB_EXIT="137", STUB_SCOPE_RESULT="oom-kill", STUB_RESULT_AFTER="3"
        )
        assert CAP_LINE in result.stdout, result.stdout

    @requires_node
    def test_its_own_failed_scope_is_reset(self, harness: Harness) -> None:
        harness.run(STUB_EXIT="137", STUB_SCOPE_RESULT="oom-kill")
        (_, payload) = harness.calls("systemd-run")
        resets = [c for c in harness.calls("systemctl") if "reset-failed" in c]
        assert resets and resets[0][-1] == f"{_unit(payload)}.scope", resets

    @requires_node
    def test_a_crash_under_the_cap_is_still_a_crash(self, harness: Harness) -> None:
        result = harness.run(STUB_EXIT="137", STUB_SCOPE_RESULT="success")
        assert "FAILED TO RUN" in result.stdout, result.stdout
        assert CAP_LINE not in result.stdout, result.stdout

    @requires_node
    def test_findings_under_the_cap_print_as_before(self, harness: Harness) -> None:
        result = harness.run(
            STUB_EXIT="1",
            STUB_STDERR="  - graph yield LOW — 3 edge(s) across 374 files\n",
        )
        assert FINDINGS_HEADER in result.stdout, result.stdout
        assert CAP_LINE not in result.stdout, result.stdout

    @requires_node
    def test_a_clean_capped_run_is_silent(self, harness: Harness) -> None:
        result = harness.run()
        assert result.stdout == "", result.stdout
        asked = [c for c in harness.calls("systemctl") if "MemoryCurrent" not in c]
        assert not asked, (
            "a clean run has no failure to explain, and asked the scope anyway"
        )

    @requires_node
    def test_a_custom_cap_reaches_both_calls_and_the_report(
        self, harness: Harness
    ) -> None:
        cap = "MemoryMax=64M MemorySwapMax=0"
        result = harness.run(
            SOCRATICODE_HEALTH_CAP=cap, STUB_EXIT="137", STUB_SCOPE_RESULT="oom-kill"
        )
        for call in harness.calls("systemd-run"):
            assert _props(_split(call)[0]) == cap.split(), call
        assert f"{CAP_LINE} (MemoryMax=64M)" in result.stdout, result.stdout


def _why_it_cannot_cap() -> str | None:
    """Why this host cannot run the real test, or None if it can.

    Called from the test body, never from a decorator: a `skipif` argument runs
    at import, so every collection of the structural suite on a Linux host
    would create a real scope, and a user bus slower than the timeout would
    raise at import and turn the whole module — and the commit gate — red.

    Asks what the hook asks: not only whether systemd takes the cap, but
    whether it accounts the scope's memory. Where it has no memory controller
    it takes MemoryMax= and enforces nothing, and this test's payload would be
    allocating against the host itself.
    """
    if shutil.which("systemd-run") is None or shutil.which("choom") is None:
        return "no systemd-run or choom here"
    unit = f"socraticode-cap-test-{os.getpid()}"
    try:
        probe = subprocess.run(
            [
                "systemd-run",
                "--user",
                "--scope",
                "-q",
                f"--unit={unit}",
                "-p",
                "MemoryMax=64M",
                "-p",
                "MemorySwapMax=0",
                "choom",
                "-n",
                "500",
                "--",
                "systemctl",
                "--user",
                "show",
                "-p",
                "MemoryCurrent",
                "--value",
                f"{unit}.scope",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"the capability probe did not finish: {exc}"
    if probe.returncode != 0:
        return f"user systemd cannot cap a scope here: {probe.stderr.strip()}"
    if not probe.stdout.strip().isdigit():
        return (
            "user systemd accepts MemoryMax= here but accounts no memory for "
            f"the scope (MemoryCurrent={probe.stdout.strip()!r}), so it would "
            "not enforce it — cgroup v1, or no memory controller delegated"
        )
    return None


class TestARealCapKills:
    """The acceptance's own test: a real scope, a tiny MemoryMax, a payload
    that exceeds it. Runs only where user systemd can cap a scope, which is
    no macOS host and no CI runner without linger."""

    @requires_node
    def test_a_payload_over_its_cap_is_killed_and_said_so(
        self, harness: Harness
    ) -> None:
        why = _why_it_cannot_cap()
        if why:
            pytest.skip(why)
        # Bounded at 8x the cap: if the cap does not hold after all, the
        # payload stops at 512 MB and the assertion below says so, instead of
        # allocating until the kernel OOM killer picks something on this host.
        harness.driver.write_text(
            "import fs from 'node:fs';\n"
            "fs.appendFileSync(process.env.STUB_RUNS, 'run\\n');\n"
            "const hog = [];\n"
            "for (let i = 0; i < 64; i++) hog.push(Buffer.alloc(8 * 1024 * 1024, 1));\n"
            "process.stderr.write('survived 512 MB under the cap\\n');\n"
        )
        result = harness.run(
            stubs=False, SOCRATICODE_HEALTH_CAP="MemoryMax=64M MemorySwapMax=0"
        )
        assert result.returncode == 0, result.stderr
        assert "survived 512 MB" not in harness.hook_log(), (
            "the payload allocated 512 MB under MemoryMax=64M and was not "
            "stopped: this host accepts the cap without enforcing it, and the "
            f"probe did not notice\n{harness.hook_log()}"
        )
        assert f"{CAP_LINE} (MemoryMax=64M)" in result.stdout, (
            f"stdout: {result.stdout!r}\nlog:\n{harness.hook_log()}"
        )
        assert harness.runs() == 1, "the killed check was re-run"
        assert result.stderr == "", (
            "bash's job notice for the killed payload reached the hook's "
            f"stderr instead of its log: {result.stderr!r}"
        )
        # This run's own unit, from the hook's log: a glob would also match the
        # scopes of real sessions' daily checks on the same host.
        found = re.search(r"capped: scope (\S+\.scope)", harness.hook_log())
        assert found, harness.hook_log()
        left = subprocess.run(
            ["systemctl", "--user", "list-units", "--all", found.group(1)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert found.group(1) not in left.stdout, (
            f"the killed check's scope outlived its payload:\n{left.stdout}"
        )
