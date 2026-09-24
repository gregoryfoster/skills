"""The plugin session can be pinned, and preflight reports both pins (#327).

#295 pinned the driver's launches and wrote down, as a known limitation, that
the session could not be: "Claude Code cannot override a plugin's MCP command,
so the plugin keeps launching `@latest`." Upstream `0c33776` (2026-09-20)
refuted it for this plugin: Claude Code's manifest became
`.claude-plugin/mcp.json`, which launches
`npx -y --prefer-online ${SOCRATICODE_SPEC:-socraticode@latest}`, so a repo's
settings env block pins the session too. Measured on `co-replicator` off the
process table: `npm exec socraticode@1.14.0`.

Two traps make the claim easy to re-derive wrongly, and this file pins both:

- **Three manifests, one live.** Both root manifests still hardcode `@latest`;
  only the one `plugin.json` names reads the variable. Reading a root file
  "confirms" the limitation.
- **The variable arrived after the 1.14.0 release with no version bump.** A
  plugin cache labelled `1.14.0` can predate it and ignore the variable, so
  preflight has to say so rather than report the session pinned.

Preflight's two blocks are lifted between their sentinels and run against a
written config tree, as the host-capacity block is in
test_socraticode_host_memory.py: no claude CLI, no network, no real plugin.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "skills" / "init-socraticode"
DRIVER = SKILL / "scripts" / "mcp-driver.mjs"
PREFLIGHT = SKILL / "scripts" / "preflight.sh"
HOST_MEMORY = SKILL / "references" / "host-memory.md"
TROUBLESHOOTING = SKILL / "references" / "troubleshooting.md"

requires_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to read the plugin"
)

LIVE = "${SOCRATICODE_SPEC:-socraticode@latest}"


def _block(name: str) -> str:
    body = PREFLIGHT.read_text()
    start = body.index(f"# >>> {name}\n")
    end = body.index(f"# <<< {name}\n")
    return body[start:end]


def _helpers() -> str:
    body = PREFLIGHT.read_text()
    return "\n".join(
        ln for ln in body.splitlines() if re.match(r"^(pass|warn|hint)\(\) \{", ln)
    )


def _run(program: str, env: dict) -> subprocess.CompletedProcess:
    base = {
        k: v
        for k, v in os.environ.items()
        if k not in ("SOCRATICODE_SPEC", "CLAUDECODE", "CLAUDE_CONFIG_DIR")
        and not k.startswith("GIT_")
    }
    result = subprocess.run(
        [shutil.which("bash") or "/bin/bash", "-c", program],
        capture_output=True,
        text=True,
        timeout=60,
        env={**base, **env},
    )
    assert result.returncode == 0, result.stderr
    return result


def _plugin_tree(tmp_path: Path, live: str) -> Path:
    """A config dir holding one plugin version in upstream's current layout.

    `live` is what the manifest plugin.json names launches with. The root
    manifests always hardcode @latest, as upstream's do.
    """
    config = tmp_path / "claude"
    version = config / "plugins" / "cache" / "socraticode" / "socraticode" / "1.14.0"
    (version / ".claude-plugin").mkdir(parents=True)

    def definition(spec: str) -> str:
        return json.dumps(
            {
                "mcpServers": {
                    "socraticode": {
                        "command": "npx",
                        "args": ["-y", "--prefer-online", spec],
                    }
                }
            }
        )

    (version / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"version": "1.14.0", "mcpServers": "./.claude-plugin/mcp.json"})
    )
    (version / ".claude-plugin" / "mcp.json").write_text(definition(live))
    for root in ("mcp.json", ".mcp.json"):
        (version / root).write_text(definition("socraticode@latest"))
    return config


def _read(tmp_path: Path, live: str, spec: str | None) -> tuple[str, str, str]:
    """preflight's plugin-launch block: (fixed, floats, spec variable)."""
    program = (
        "set -euo pipefail\n"
        + _helpers()
        + '\nresolve() { R_VAL="${!1:-}" R_SRC="the environment"; }\n'
        + f"ROOT={json.dumps(str(tmp_path))}\n"
        + f"SC_DRIVER_PATH={json.dumps(str(DRIVER))}\n"
        + _block("plugin-launch")
        + 'printf "%s|%s|%s" "$SC_PLUGIN_FIXED" "$SC_PLUGIN_FLOATS" "$SC_SPEC_VAR"\n'
    )
    env = {"CLAUDE_CONFIG_DIR": str(_plugin_tree(tmp_path, live))}
    if spec is not None:
        env["SOCRATICODE_SPEC"] = spec
    return tuple(_run(program, env).stdout.split("|"))


class TestPreflightReadsTheLiveManifest:
    @requires_node
    def test_unset_the_session_floats_and_the_variable_is_named(
        self, tmp_path: Path
    ) -> None:
        assert _read(tmp_path, LIVE, None) == (
            "",
            "socraticode@latest",
            "SOCRATICODE_SPEC",
        )

    @requires_node
    def test_set_it_pins_the_session(self, tmp_path: Path) -> None:
        assert _read(tmp_path, LIVE, "socraticode@1.14.0") == (
            "1.14.0",
            "",
            "SOCRATICODE_SPEC",
        )

    @requires_node
    def test_an_empty_value_is_not_a_pin(self, tmp_path: Path) -> None:
        """Empty expands to an empty argument, not the default, in Claude Code
        and in the driver alike (#309) — a broken launch, never a pinned one."""
        assert _read(tmp_path, LIVE, "")[0] == ""

    @requires_node
    def test_a_build_that_predates_the_variable_names_none(
        self, tmp_path: Path
    ) -> None:
        """The "1.14.0" that hardcodes its spec: set or not, nothing reads it."""
        assert _read(tmp_path, "socraticode@latest", "socraticode@1.14.0") == (
            "",
            "socraticode@latest",
            "",
        )


def _report(
    *,
    session: dict | None = None,
    warmed: tuple[str, ...] | None = None,
    **variables: str,
) -> list[str]:
    """preflight's launch-pins block, for the given resolved state.

    `session` is the process environment (CLAUDECODE, SOCRATICODE_SPEC); every
    other keyword is a shell variable the block reads. `warmed` is the specs an
    npx cache tree holds — by default the one the definition fixes, so a test
    about something else is not also a cold-cache test (#332).
    """
    defaults = {
        "SC_PLUGIN_FIXED": "",
        "SC_PLUGIN_FLOATS": "",
        "SC_SPEC_VAR": "",
        "SC_SPEC": "",
        "SC_SPEC_SRC": "",
        "SC_PIN_VER": "",
        "SC_PIN_DIR": "/home/u/.socraticode/pin",
        "MEM_KB": str(36 * 1024 * 1024),
        "SC_SEEN_SPEC": "",
        "SC_SEEN_PIDS": "",
        "SC_SEEN_WHY": "outside a Claude Code session",
    }
    state = {**defaults, **variables}
    if warmed is None:
        fixed = state["SC_PLUGIN_FIXED"]
        warmed = (f"socraticode@{fixed}",) if fixed else ()
    program = (
        "set -euo pipefail\n"
        + _helpers()
        + "\n"
        + "".join(f"{k}={json.dumps(v)}\n" for k, v in state.items())
        + _block("launch-pins")
    )
    with tempfile.TemporaryDirectory() as cache:
        for i, spec in enumerate(warmed):
            tree = Path(cache) / "_npx" / f"tree{i}"
            tree.mkdir(parents=True)
            (tree / "package.json").write_text(
                json.dumps({"_npx": {"packages": [spec]}, "dependencies": {}})
            )
        env = {"npm_config_cache": cache, **(session or {})}
        return _run(program, env).stdout.splitlines()


class TestPreflightReportsBothPins:
    def test_both_pinned_to_one_version_passes(self) -> None:
        lines = _report(
            SC_PLUGIN_FIXED="1.14.0",
            SC_SPEC_VAR="SOCRATICODE_SPEC",
            SC_SPEC="socraticode@1.14.0",
            SC_SPEC_SRC=".claude/settings.json",
            SC_PIN_VER="1.14.0",
            SC_SEEN_SPEC="socraticode@1.14.0",
            SC_SEEN_PIDS="42284",
        )
        assert len(lines) == 1 and "✓" in lines[0], lines
        assert "no launch installs" in lines[0], lines
        assert "observed" in lines[0] and "42284" in lines[0], (
            f"the pass must say the launch was seen, and which server: {lines}"
        )

    def test_two_pinned_versions_are_named(self) -> None:
        lines = _report(SC_PLUGIN_FIXED="1.14.0", SC_PIN_VER="1.13.2")
        assert "disagree" in lines[0], lines

    def test_a_pinned_driver_beside_a_floating_session_is_half_done(self) -> None:
        """The issue's point 2: pinning the driver alone reads as done."""
        lines = _report(
            SC_PLUGIN_FLOATS="socraticode@latest",
            SC_SPEC_VAR="SOCRATICODE_SPEC",
            SC_PIN_VER="1.14.0",
        )
        assert "still installs" in lines[0], lines
        assert "SOCRATICODE_SPEC=socraticode@1.14.0" in lines[1], lines
        assert "claudeCode.environmentVariables" in lines[1], (
            "the hint must name a channel that reaches the launch — the settings "
            f"env block alone missed it on three hosts (#332): {lines[1]}"
        )

    def test_a_variable_the_plugin_ignores_is_said_to_be_ignored(self) -> None:
        lines = _report(
            SC_PLUGIN_FLOATS="socraticode@latest",
            SC_SPEC="socraticode@1.14.0",
            SC_SPEC_SRC="the environment",
        )
        assert "never reads it" in lines[0], lines
        assert "process table" in lines[1] and "claude mcp list" not in lines[1], (
            "`claude mcp list` from a session shell reports what a launch WITH "
            f"the shell's environment runs, not what launched (#332): {lines[1]}"
        )
        assert "claude plugin update" in lines[1], lines

    def test_a_pinned_driver_beside_a_build_that_cannot_pin_says_update(
        self,
    ) -> None:
        lines = _report(SC_PLUGIN_FLOATS="socraticode@latest", SC_PIN_VER="1.14.0")
        assert "still installs" in lines[0], lines
        assert "update the plugin" in lines[1], lines

    def test_a_small_host_with_nothing_pinned_is_told(self) -> None:
        lines = _report(
            SC_PLUGIN_FLOATS="socraticode@latest",
            SC_SPEC_VAR="SOCRATICODE_SPEC",
            MEM_KB=str(2 * 1024 * 1024),
        )
        assert "under 4 GiB" in lines[0], lines

    @pytest.mark.parametrize(
        "state",
        [
            pytest.param({}, id="no-plugin"),
            pytest.param(
                {
                    "SC_PLUGIN_FLOATS": "socraticode@latest",
                    "SC_SPEC_VAR": "SOCRATICODE_SPEC",
                },
                id="floating-on-a-roomy-host",
            ),
        ],
    )
    def test_the_shipped_default_on_a_roomy_host_is_silent(self, state: dict) -> None:
        assert _report(**state) == []

    def test_a_declared_value_this_session_lacks_says_restart(self) -> None:
        lines = _report(
            SC_PLUGIN_FIXED="1.14.0",
            SC_SPEC_VAR="SOCRATICODE_SPEC",
            SC_SPEC="socraticode@1.14.0",
            SC_SPEC_SRC=".claude/settings.json",
            session={"CLAUDECODE": "1"},
        )
        assert "does not carry it" in lines[0], lines
        assert "Restart" in lines[1], lines


class TestTheDocsNoLongerSayItCannotBeDone:
    SOURCES = (HOST_MEMORY, TROUBLESHOOTING, PREFLIGHT, DRIVER)

    @pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
    def test_the_refuted_claim_is_gone(self, path: Path) -> None:
        text = re.sub(r"\s+", " ", path.read_text())
        assert "cannot override a plugin's MCP" not in text, (
            f"{path.name} still says Claude Code cannot override the plugin's "
            "command. For this plugin it can: SOCRATICODE_SPEC pins the "
            "session's launch (#327)."
        )

    def test_host_memory_names_the_variable_and_the_live_manifest(self) -> None:
        text = HOST_MEMORY.read_text()
        assert '"name": "SOCRATICODE_SPEC", "value": "socraticode@' in text, (
            "host-memory.md must show the setting that pins the session where "
            "Claude Code starts (#332)"
        )
        assert ".claude-plugin/mcp.json" in text, (
            "host-memory.md must name the one live manifest — reading a root "
            "one is how #295 concluded the session could not be pinned"
        )
        assert "ps -eo pid,ppid,args" in text, (
            "host-memory.md must say to read the launched command off the "
            "process table, not a manifest"
        )

    def test_row_u_pins_both_launches(self) -> None:
        row = next(
            ln
            for ln in TROUBLESHOOTING.read_text().splitlines()
            if ln.startswith("| **U**")
        )
        assert "SOCRATICODE_SPEC" in row, row
