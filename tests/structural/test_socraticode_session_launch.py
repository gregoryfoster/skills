"""The session's pin is observed on the process table, not inferred (#332).

#327 made the plugin session pinnable with `SOCRATICODE_SPEC`, and every check
that said it WAS pinned worked the answer out rather than reading it: preflight
and `health-check` expanded the plugin's definition against their own
environment. A settings `env` block reaches every child of a session — the
Bash tool, hooks, the driver — whether or not it reached the plugin's launch,
and on CannObserv/watcher, notifier and address-validator (Claude Code 2.1.280,
VS Code) it did not:

    $ ps -eo pid,ppid,args | grep '[n]pm exec socraticode'
     971250  971194 npm exec socraticode@latest     # 971194 = the session's claude
    $ tr '\\0' '\\n' </proc/971250/environ | grep SOCRATICODE_SPEC
    SOCRATICODE_SPEC=socraticode@1.14.0

preflight printed "✓ Plugin session launches socraticode 1.14.0 … no launch
installs", and `health-check` skipped the pin drift because "the plugin's spec
is fixed". Both now read the session's server off the process table: the
npx-style child of the nearest `claude` above the check.

These tests build that tree for real. A stand-in `claude` — a script, so its
argv names it the way an npm-installed one's does — launches a child whose
argv reads `npm exec <spec>`, waits until the table shows it, then runs the
check beneath itself. Nothing is mocked between the check and `ps`.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from .test_socraticode_graph_yield import (
    DRIVER,
    HEALTH_OK,
    STATUS_CLEAN,
    STUB_SERVER,
    _clean_env,
    _graph_built_by,
    _plugin_config,
)
from .test_socraticode_session_pin import _block, _helpers
from .test_socraticode_session_pin import _report as _launch_pins

requires_tree = pytest.mark.skipif(
    shutil.which("node") is None
    or shutil.which("ps") is None
    or shutil.which("bash") is None,
    reason="node, ps and bash are needed to build and read a session's tree",
)

LIVE = {
    "command": "npx",
    "args": ["-y", "--prefer-online", "${SOCRATICODE_SPEC:-socraticode@latest}"],
}
PINNED = "socraticode@1.14.0"
REPLIES = {
    "codebase_health": HEALTH_OK,
    "codebase_status": STATUS_CLEAN,
    "codebase_graph_status": _graph_built_by("1.14.0"),
}

# The stand-in session. `exec -a` gives the child the argv npm gives the
# plugin's npx launch, so the table reads exactly as it did on the hosts.
FAKE_CLAUDE = """#!/bin/bash
bash -c "exec -a 'npm exec $FAKE_SERVER_SPEC' sleep 60" &
srv=$!
for _ in $(seq 200); do
  case "$(ps -o args= -p "$srv" 2>/dev/null)" in "npm exec "*) break ;; esac
  sleep 0.05
done
"$@"
rc=$?
kill "$srv" 2>/dev/null
exit "$rc"
"""


def _claude(tmp_path: Path) -> Path:
    """A script named `claude`, so the table shows `/bin/bash …/claude …`."""
    path = tmp_path / "session" / "claude"
    path.parent.mkdir()
    path.write_text(FAKE_CLAUDE)
    path.chmod(0o755)
    return path


def _npm_stub(tmp_path: Path, latest: str) -> str:
    """A PATH whose `npm view socraticode version` answers `latest`, offline."""
    bindir = tmp_path / "npm-stub"
    bindir.mkdir()
    (bindir / "npm").write_text(f"#!/bin/sh\necho {latest}\n")
    (bindir / "npm").chmod(0o755)
    return f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"


def _pin(tmp_path: Path, version: str) -> Path:
    """A pinned pre-install whose server is the scripted stub."""
    pkg = tmp_path / "pin" / "node_modules" / "socraticode"
    (pkg / "dist").mkdir(parents=True)
    (pkg / "dist" / "index.js").write_text(STUB_SERVER)
    (pkg / "package.json").write_text(
        json.dumps({"name": "socraticode", "version": version, "type": "module"})
    )
    return tmp_path / "pin"


def _health_check(
    tmp_path: Path, *, server_spec: str | None, pinned: str | None = None, **env: str
) -> dict:
    """health-check under a session whose server launched as `server_spec`.

    `server_spec=None` runs it outside any session. `pinned` launches the check
    from a pinned pre-install at that version rather than SOCRATICODE_ENTRY.
    """
    project = tmp_path / "repo"
    project.mkdir()
    replies = tmp_path / "replies.json"
    replies.write_text(json.dumps(REPLIES))
    launch = {"SOCRATICODE_PIN_DIR": str(tmp_path / "no-pin")}
    if pinned:
        launch = {"SOCRATICODE_PIN_DIR": str(_pin(tmp_path, pinned))}
    else:
        stub = tmp_path / "stub-server.mjs"
        stub.write_text(STUB_SERVER)
        launch["SOCRATICODE_ENTRY"] = str(stub)
    command = ["node", str(DRIVER), "health-check", str(project)]
    extra = {
        "STUB_REPLIES": str(replies),
        "HEALTH_TIMEOUT_MS": "30000",
        "CLAUDE_CONFIG_DIR": str(_plugin_config(tmp_path, LIVE, "1.14.0")),
        **launch,
        **env,
    }
    if server_spec is not None:
        command = [str(_claude(tmp_path)), *command]
        extra.update(CLAUDECODE="1", FAKE_SERVER_SPEC=server_spec)
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=90, env=_clean_env(**extra)
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"health-check produced no JSON\n{result.stdout}\n{result.stderr}")


class TestHealthCheckReadsTheLaunch:
    @requires_tree
    def test_the_variable_that_missed_the_launch_is_a_defect(
        self, tmp_path: Path
    ) -> None:
        """watcher's session, rebuilt: the variable here, @latest at the launch."""
        report = _health_check(
            tmp_path, server_spec="socraticode@latest", SOCRATICODE_SPEC=PINNED
        )
        session = report["sessionServer"]
        assert session["basis"].startswith("observed:"), session
        assert session["version"] is None, (
            "the session's server was seen launched as socraticode@latest, which "
            f"fixes no version — reading 1.14.0 off the definition is #332\n{session}"
        )
        missed = [f for f in report["findings"] if "reached this process" in f]
        assert missed and not missed[0].startswith("note: "), report["findings"]
        assert "socraticode@latest" in missed[0], missed
        assert report["healthy"] is False, report

    @requires_tree
    def test_a_launch_carrying_the_pin_is_read_as_pinned(self, tmp_path: Path) -> None:
        report = _health_check(tmp_path, server_spec=PINNED, SOCRATICODE_SPEC=PINNED)
        session = report["sessionServer"]
        assert session["version"] == "1.14.0", session
        assert session["basis"].startswith("observed:"), session
        assert not [f for f in report["findings"] if "reached this process" in f]

    @requires_tree
    def test_outside_a_session_the_version_is_said_to_be_inferred(
        self, tmp_path: Path
    ) -> None:
        report = _health_check(tmp_path, server_spec=None, SOCRATICODE_SPEC=PINNED)
        session = report["sessionServer"]
        assert session["inferred"] is True, session
        assert session["basis"].startswith(
            "inferred from this process's environment"
        ), f"a version expanded from the check's own environment must say so\n{session}"

    @requires_tree
    def test_an_inferred_fix_does_not_skip_the_pin_drift(self, tmp_path: Path) -> None:
        """Item 3: "with the variable set to the pin's version … nothing to measure"."""
        report = _health_check(
            tmp_path,
            server_spec=None,
            pinned="1.13.2",
            SOCRATICODE_SPEC="socraticode@1.13.2",
            PATH=_npm_stub(tmp_path, "1.14.0"),
        )
        drift = report["pinDrift"]
        assert drift is not None, (
            "a pinned driver beside a session pinned only by this process's "
            "environment was not measured — the skip #332 removes"
        )
        assert (
            drift["observed"] is False and drift["floatingSpec"] == "socraticode@latest"
        ), drift
        note = [f for f in report["findings"] if "NOT observed" in f]
        assert note and note[0].startswith("note: "), report["findings"]

    @requires_tree
    def test_an_observed_floating_launch_is_measured_against_the_pin(
        self, tmp_path: Path
    ) -> None:
        report = _health_check(
            tmp_path,
            server_spec="socraticode@latest",
            pinned="1.13.2",
            SOCRATICODE_SPEC="socraticode@1.13.2",
            PATH=_npm_stub(tmp_path, "1.14.0"),
        )
        drift = report["pinDrift"]
        assert drift == {
            "pinned": "1.13.2",
            "floatingSpec": "socraticode@latest",
            "resolves": "1.14.0",
            "observed": True,
        }, drift
        assert any("two different feature releases" in f for f in report["findings"]), (
            report["findings"]
        )


def _plugin_launch(tmp_path: Path, *, server_spec: str | None, spec: str) -> dict:
    """preflight's plugin-launch block, run under a session or outside one."""
    program = (
        "set -euo pipefail\n"
        + _helpers()
        + '\nresolve() { R_VAL="${!1:-}" R_SRC="the environment"; }\n'
        + f"ROOT={json.dumps(str(tmp_path))}\n"
        + f"SC_DRIVER_PATH={json.dumps(str(DRIVER))}\n"
        + _block("plugin-launch")
        + 'printf "%s|%s|%s|%s" "$SC_PLUGIN_FIXED" "$SC_SEEN_SPEC" "$SC_SEEN_FIXED" "$SC_SEEN_WHY"\n'
    )
    command = ["bash", "-c", program]
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("SOCRATICODE_SPEC", "CLAUDECODE") and not k.startswith("GIT_")
    }
    env.update(
        CLAUDE_CONFIG_DIR=str(_plugin_config(tmp_path, LIVE, "1.14.0")),
        SOCRATICODE_SPEC=spec,
    )
    if server_spec is not None:
        command = [str(_claude(tmp_path)), *command]
        env.update(CLAUDECODE="1", FAKE_SERVER_SPEC=server_spec)
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=60, env=env
    )
    assert result.returncode == 0, result.stderr
    fixed, seen, seen_fixed, why = result.stdout.split("|")
    return {"fixed": fixed, "seen": seen, "seen_fixed": seen_fixed, "why": why}


class TestPreflightReadsTheLaunch:
    @requires_tree
    def test_the_launch_is_read_not_the_expansion(self, tmp_path: Path) -> None:
        got = _plugin_launch(tmp_path, server_spec="socraticode@latest", spec=PINNED)
        assert got["fixed"] == "1.14.0", got
        assert got["seen"] == "socraticode@latest" and got["seen_fixed"] == "", (
            "the definition expanded to 1.14.0 in this shell; the session's "
            f"server launched @latest, and that is what must be read\n{got}"
        )

    @requires_tree
    def test_a_pinned_launch_reads_its_version(self, tmp_path: Path) -> None:
        got = _plugin_launch(tmp_path, server_spec=PINNED, spec=PINNED)
        assert got["seen"] == PINNED and got["seen_fixed"] == "1.14.0", got

    @requires_tree
    def test_outside_a_session_nothing_is_seen_and_it_says_why(
        self, tmp_path: Path
    ) -> None:
        got = _plugin_launch(tmp_path, server_spec=None, spec=PINNED)
        assert got["seen"] == "" and got["why"] == "outside a Claude Code session", got


PINNED_STATE = {
    "SC_PLUGIN_FIXED": "1.14.0",
    "SC_SPEC_VAR": "SOCRATICODE_SPEC",
    "SC_SPEC": PINNED,
    "SC_SPEC_SRC": ".claude/settings.json",
}


class TestPreflightNeverPassesAnUnobservedPin:
    def test_the_missed_launch_is_named_with_the_channel_that_reaches_it(
        self,
    ) -> None:
        lines = _launch_pins(
            **PINNED_STATE,
            SC_SEEN_SPEC="socraticode@latest",
            SC_SEEN_PIDS="42284",
            session={"CLAUDECODE": "1", "SOCRATICODE_SPEC": PINNED},
        )
        assert "✓" not in "\n".join(lines), lines
        assert "'socraticode@latest' (pid 42284)" in lines[0], lines
        assert "reached this shell but not the launch" in lines[0], lines
        assert "claudeCode.environmentVariables" in lines[1], lines
        assert "restart" in lines[2], lines

    def test_an_unobserved_pin_is_never_a_pass(self) -> None:
        lines = _launch_pins(**PINNED_STATE)
        assert len(lines) == 1 and "✓" not in lines[0], lines
        assert (
            "A session carrying SOCRATICODE_SPEC launches socraticode 1.14.0"
            in lines[0]
        )
        assert "not observed: outside a Claude Code session" in lines[0], lines

    def test_a_cold_npx_tree_is_named_with_a_capped_warm_up(self) -> None:
        """The first launch of a new exact spec installs (address-validator)."""
        lines = _launch_pins(
            **PINNED_STATE,
            SC_SEEN_SPEC=PINNED,
            SC_SEEN_PIDS="42284",
            warmed=("socraticode@latest", "socraticode"),
        )
        assert "✓" in lines[0], lines
        assert "No npx cache tree" in lines[1] and "socraticode@1.14.0" in lines[1], (
            lines
        )
        assert "choom -n 500 -- npm exec" in lines[2], lines
        assert "--package=socraticode@1.14.0" in lines[2], lines

    def test_a_warm_tree_is_silent(self) -> None:
        lines = _launch_pins(**PINNED_STATE, SC_SEEN_SPEC=PINNED, SC_SEEN_PIDS="1")
        assert len(lines) == 1 and "✓" in lines[0], lines
