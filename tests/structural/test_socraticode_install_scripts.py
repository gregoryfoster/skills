"""Preflight names the pin's install scripts npm >= 11.20 skipped (#606).

npm 11.20 runs a dependency's install script only once the project's
`allowScripts` approves it. In the pin `init-socraticode` prescribes
(`npm install --save-exact --prefix ~/.socraticode/pin socraticode@<version>`)
that is 18 packages at socraticode 1.16.2 — sixteen `@ast-grep/lang-*`,
`@parcel/watcher` and `tree-sitter-gdscript` — every one transitive. npm warns
once, on stderr, at install, and nothing reports it after. The parsers and the
watcher load prebuilds where the platform has one; a platform without one
loses that parser or the watcher with no error anywhere.

So preflight reads `npm install-scripts ls --json` in the pin and names what is
pending, as a warning: nothing is approved, and no host that passes today
fails. Measured on npm 11.20.0 (2026-11-17), the shapes these fakes copy:

- `ls` exits 0 whether or not anything is pending, so the JSON decides;
- `{"allowScripts": [{"name", "changes": [{"key", "change": "pending"}]}]}`,
  and `{"allowScripts": []}` when clean, or after `deny --all`;
- npm 11.5.2 answers `Unknown command: "install-scripts"` and exits 1.

The block is run alone, as `test_socraticode_session_pin.py` runs
launch-pins, with a fake `npm` on PATH and the real `node` that parses it.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "skills" / "init-socraticode"
PREFLIGHT = SKILL / "scripts" / "preflight.sh"
HOST_MEMORY = SKILL / "references" / "host-memory.md"

BLOCK = "pin-install-scripts"

requires_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to parse npm's JSON"
)

# The 1.16.2 pin's pending set, as `npm install-scripts ls` listed it.
AST_GREP = [
    "bash", "c", "cpp", "csharp", "dart", "elixir", "go", "java", "kotlin",
    "lua", "php", "python", "ruby", "rust", "scala", "swift",
]  # fmt: skip
PENDING = [f"@ast-grep/lang-{x}@0.0.7" for x in AST_GREP] + [
    "@parcel/watcher@2.6.0",
    "tree-sitter-gdscript@6.1.0",
]


def _listing(keys: list[str]) -> str:
    def name(key: str) -> str:
        return key.rsplit("@", 1)[0]

    return json.dumps(
        {
            "allowScripts": [
                {"name": name(k), "changes": [{"key": k, "change": "pending"}]}
                for k in keys
            ]
        },
        indent=2,
    )


def _block() -> str:
    body = PREFLIGHT.read_text()
    start = body.index(f"# >>> {BLOCK}\n")
    end = body.index(f"# <<< {BLOCK}\n")
    return body[start:end]


def _helpers() -> str:
    """pass/fail/warn/hint, and version_ge — what the block calls."""
    body = PREFLIGHT.read_text()
    lines = [
        ln for ln in body.splitlines() if re.match(r"^(pass|fail|warn|hint)\(\) \{", ln)
    ]
    m = re.search(r"^version_ge\(\) \{\n.*?^\}\n", body, re.S | re.M)
    assert m, "preflight.sh no longer defines version_ge()"
    return "\n".join(lines) + "\n" + m.group(0)


def _fake_npm(
    tmp_path: Path,
    version: str,
    stdout: str = "",
    rc: int = 0,
    stderr: str = "",
) -> Path:
    """An `npm` that logs its argv, prints `version` for --version, and answers
    `install-scripts ...` with `stdout`/`stderr`/`rc`; npm below 11.20 does not
    know the command, as the real 11.5.2 does not."""
    binv = tmp_path / "bin"
    binv.mkdir()
    (tmp_path / "out.json").write_text(stdout)
    (tmp_path / "err.txt").write_text(stderr)
    older = version.startswith(("10.", "11.5.", "11.19."))
    script = f"""#!/bin/sh
printf '%s\\n' "$*" >> "{tmp_path}/npm.log"
if [ "$1" = "--version" ]; then echo "{version}"; exit 0; fi
if [ "$1" = "install-scripts" ]; then
  if [ {"1" if older else "0"} = 1 ]; then
    echo 'Unknown command: "install-scripts"' >&2; exit 1
  fi
  cat "{tmp_path}/out.json"; cat "{tmp_path}/err.txt" >&2; exit {rc}
fi
exit 0
"""
    npm = binv / "npm"
    npm.write_text(script)
    npm.chmod(0o755)
    return binv


def _run(tmp_path: Path, binv: Path | None, pin_ver: str = "1.16.2"):
    pin = tmp_path / "pin"
    program = (
        "set -euo pipefail\nFAIL=0\n"
        + _helpers()
        + f"SC_PIN_VER={json.dumps(pin_ver)}\nSC_PIN_DIR={json.dumps(str(pin))}\n"
        + _block()
        + 'echo "FAIL=$FAIL"\n'
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("npm_config_")}
    if binv is not None:
        env["PATH"] = f"{binv}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        [shutil.which("bash") or "/bin/bash", "-c", program],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[-1] == "FAIL=0", (
        f"the block set FAIL — a host that passes today must not fail: {lines}"
    )
    log = tmp_path / "npm.log"
    return lines[:-1], (log.read_text().splitlines() if log.exists() else [])


def _warnings(lines: list[str]) -> list[str]:
    return [ln for ln in lines if "•" in ln]


@requires_node
class TestPendingScriptsAreNamed:
    def test_the_measured_pin_gives_one_warning_naming_them(
        self, tmp_path: Path
    ) -> None:
        binv = _fake_npm(tmp_path, "11.20.0", _listing(PENDING))
        lines, _ = _run(tmp_path, binv)
        warns = _warnings(lines)
        assert len(warns) == 1, lines
        w = warns[0]
        assert "18" in w, w
        for name in ("@ast-grep/lang-*", "@parcel/watcher", "tree-sitter-gdscript"):
            assert name in w, f"{name} not named: {w}"
        assert "16" in w, f"the grouped scope must carry its count: {w}"

    def test_it_reads_the_pin_offline_as_json(self, tmp_path: Path) -> None:
        binv = _fake_npm(tmp_path, "11.20.0", _listing(PENDING))
        _, log = _run(tmp_path, binv)
        reads = [ln for ln in log if ln.startswith("install-scripts")]
        assert len(reads) == 1, log
        argv = reads[0].split()
        assert argv[:2] == ["install-scripts", "ls"], argv
        assert "--json" in argv and "--offline" in argv, argv
        assert argv[argv.index("--prefix") + 1] == str(tmp_path / "pin"), argv

    def test_the_hints_record_a_review_and_never_approve(self, tmp_path: Path) -> None:
        binv = _fake_npm(tmp_path, "11.20.0", _listing(PENDING))
        lines, log = _run(tmp_path, binv)
        hints = [ln for ln in lines if "→" in ln]
        text = "\n".join(hints)
        assert f"npm install-scripts deny --all --prefix {tmp_path / 'pin'}" in text, (
            hints
        )
        assert "prebuild" in text, hints
        assert "host-memory.md" in text, hints
        assert not any("approve" in ln for ln in log), (
            f"npm was asked to approve: {log}"
        )
        assert "install-scripts approve" not in text, (
            "the hint must not prescribe approving: that runs node-gyp builds "
            f"the skill would then own — {hints}"
        )

    def test_a_short_list_is_named_in_full(self, tmp_path: Path) -> None:
        binv = _fake_npm(
            tmp_path, "11.21.3", _listing(["@parcel/watcher@2.6.0", "x@1.0.0"])
        )
        lines, _ = _run(tmp_path, binv)
        (w,) = _warnings(lines)
        assert "@parcel/watcher" in w and " x" in w and "2 packages" in w, w

    def test_later_npm_majors_are_read_too(self, tmp_path: Path) -> None:
        binv = _fake_npm(tmp_path, "12.2.2", _listing(["@parcel/watcher@2.6.0"]))
        lines, _ = _run(tmp_path, binv)
        assert len(_warnings(lines)) == 1, lines


@requires_node
class TestNothingToSay:
    def test_a_reviewed_pin_is_silent(self, tmp_path: Path) -> None:
        """`{"allowScripts": []}` — clean, or after `deny --all`."""
        binv = _fake_npm(tmp_path, "11.20.0", json.dumps({"allowScripts": []}))
        lines, log = _run(tmp_path, binv)
        assert lines == [], lines
        assert any(ln.startswith("install-scripts") for ln in log), log

    def test_older_npm_is_not_asked(self, tmp_path: Path) -> None:
        """npm 11.5.2 has no such command; it runs every install script."""
        binv = _fake_npm(tmp_path, "11.5.2")
        lines, log = _run(tmp_path, binv)
        assert lines == [], lines
        assert not any(ln.startswith("install-scripts") for ln in log), log

    def test_no_pin_runs_nothing(self, tmp_path: Path) -> None:
        binv = _fake_npm(tmp_path, "11.20.0", _listing(PENDING))
        lines, log = _run(tmp_path, binv, pin_ver="")
        assert lines == [] and log == [], (lines, log)

    def test_an_unreadable_npm_version_is_not_guessed(self, tmp_path: Path) -> None:
        binv = _fake_npm(tmp_path, "not-a-version", _listing(PENDING))
        lines, log = _run(tmp_path, binv)
        assert lines == [], lines
        assert not any(ln.startswith("install-scripts") for ln in log), log


@requires_node
class TestAFailedReadIsSaidNotGuessed:
    """npm >= 11.20 and a pin, but the listing could not be read: a warning
    that says nothing was measured, with npm's own words — never silence,
    which would read as a reviewed pin, and never a failure."""

    def test_npm_exiting_non_zero(self, tmp_path: Path) -> None:
        binv = _fake_npm(
            tmp_path, "11.20.0", "", rc=1, stderr="npm error code EBROKEN\nmore\n"
        )
        lines, _ = _run(tmp_path, binv)
        (w,) = _warnings(lines)
        assert "not measured" in w and "EBROKEN" in w, w

    def test_output_that_is_not_the_listing(self, tmp_path: Path) -> None:
        binv = _fake_npm(tmp_path, "11.20.0", "not json at all")
        lines, _ = _run(tmp_path, binv)
        (w,) = _warnings(lines)
        assert "not measured" in w, w


class TestTheDocSaysIt:
    def test_host_memory_names_the_default_and_the_review(self) -> None:
        doc = HOST_MEMORY.read_text()
        for needle in (
            "11.20",
            "npm install-scripts ls --prefix",
            "npm install-scripts deny --all --prefix",
            "prebuild",
            "#606",
        ):
            assert needle in doc, f"host-memory.md does not say {needle!r}"
