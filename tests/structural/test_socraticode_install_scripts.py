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


def _run(
    tmp_path: Path,
    binv: Path | None,
    pin_ver: str = "1.16.2",
    pin_name: str = "pin",
):
    pin = tmp_path / pin_name
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
        assert "18 packages in the pin" in w, w
        assert "have install scripts allowScripts has not reviewed" in w, w
        assert "skipped" not in w, (
            "ls reflects the policy, not what ran: a pin built by an older npm "
            f"whose scripts did run lists the same way (CR 2478) — {w}"
        )
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
        pin = tmp_path / "pin"
        assert f'npm install-scripts deny --all --prefix "{pin}"' in text, hints
        assert "by name" in text and "later versions" in text, (
            f"deny --all records names, so it covers later versions (CR 2477): {hints}"
        )
        assert "re-pin" in text and "load" in text, (
            f"the load check is re-run after every re-pin (CR 2477): {hints}"
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

    def test_only_a_scoped_family_collapses(self, tmp_path: Path) -> None:
        """CR 2479: node-pty, node-sass and node-expat share a stem and
        nothing else; `@scope/prefix-*` is a family, `node-*` is not."""
        keys = ["node-pty@1", "node-sass@9", "node-expat@2"] + [
            f"@x/lang-{c}@1" for c in "abc"
        ]
        binv = _fake_npm(tmp_path, "11.20.0", _listing(keys))
        lines, _ = _run(tmp_path, binv)
        (w,) = _warnings(lines)
        assert "@x/lang-* (3)" in w, w
        assert "node-*" not in w, w
        for name in ("node-pty", "node-sass", "node-expat"):
            assert name in w, w

    def test_the_tail_is_counted_in_packages(self, tmp_path: Path) -> None:
        """CR 2479: "and N more" counts packages, not list entries. Nine
        singletons and a family of three sort as ten entries; the last two
        hold four packages."""
        keys = [f"@a{i}/x@1" for i in range(1, 10)] + [f"@b/lang-{c}@1" for c in "abc"]
        binv = _fake_npm(tmp_path, "11.20.0", _listing(keys))
        lines, _ = _run(tmp_path, binv)
        (w,) = _warnings(lines)
        assert "12 packages" in w and "and 4 more" in w, w

    def test_the_full_list_is_one_command_away(self, tmp_path: Path) -> None:
        binv = _fake_npm(tmp_path, "11.20.0", _listing(PENDING))
        lines, _ = _run(tmp_path, binv)
        pin = tmp_path / "pin"
        assert any(
            "→" in ln and f'npm install-scripts ls --prefix "{pin}"' in ln
            for ln in lines
        ), lines

    def test_every_listed_name_counts(self, tmp_path: Path) -> None:
        """CR 2474: `ls` lists only what allowScripts has not reviewed, so an
        entry is counted by its name, whatever its changes say."""
        out = json.dumps(
            {"allowScripts": [{"name": "a"}, {"name": "b", "changes": []}]}
        )
        binv = _fake_npm(tmp_path, "11.20.0", out)
        lines, _ = _run(tmp_path, binv)
        (w,) = _warnings(lines)
        assert "2 packages" in w and "a, b" in w, w

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

    def test_the_release_before_is_not_asked(self, tmp_path: Path) -> None:
        """CR 2481: 11.19.x is below the floor — no read, no warning."""
        binv = _fake_npm(tmp_path, "11.19.9", _listing(PENDING))
        lines, log = _run(tmp_path, binv)
        assert lines == [], lines
        assert not any(ln.startswith("install-scripts") for ln in log), log

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
        """Exit 0 with stdout that is not JSON (CR 2481)."""
        binv = _fake_npm(tmp_path, "11.20.0", "not json at all")
        lines, log = _run(tmp_path, binv)
        (w,) = _warnings(lines)
        assert "not measured" in w, w
        assert len([ln for ln in log if ln.startswith("install-scripts")]) == 1, log

    def test_a_listing_of_nothing_recognisable(self, tmp_path: Path) -> None:
        """CR 2474: entries with no name are not a clean pin."""
        out = json.dumps({"allowScripts": [{"package": "a"}, 7]})
        binv = _fake_npm(tmp_path, "11.20.0", out)
        lines, _ = _run(tmp_path, binv)
        (w,) = _warnings(lines)
        assert "not measured" in w, w

    def test_npm_json_error_is_quoted_not_its_warning(self, tmp_path: Path) -> None:
        """CR 2473: npm prints `npm warn` lines before its error — an
        always-auth .npmrc and EGLOBAL, reproduced on 11.20.0. The --json
        error on stdout names it; npm is read once."""
        err = {
            "error": {
                "code": "EGLOBAL",
                "summary": "`npm install-scripts` does not work for global installs",
                "detail": "",
            }
        }
        binv = _fake_npm(
            tmp_path,
            "11.20.0",
            json.dumps(err),
            rc=1,
            stderr='npm warn Unknown user config "always-auth".\n'
            "npm error code EGLOBAL\n"
            "npm error `npm install-scripts` does not work for global installs\n",
        )
        lines, log = _run(tmp_path, binv)
        (w,) = _warnings(lines)
        assert (
            "EGLOBAL: `npm install-scripts` does not work for global installs" in w
        ), w
        assert "always-auth" not in w, w
        assert len([ln for ln in log if ln.startswith("install-scripts")]) == 1, log

    def test_without_json_the_first_npm_error_line_is_quoted(
        self, tmp_path: Path
    ) -> None:
        """CR 2473: no JSON on stdout — stderr's first `npm error` line, past
        any `npm warn` ahead of it."""
        binv = _fake_npm(
            tmp_path,
            "11.20.0",
            "",
            rc=1,
            stderr="npm warn something first\nnpm error code EBROKEN\nmore\n",
        )
        lines, log = _run(tmp_path, binv)
        (w,) = _warnings(lines)
        assert "npm error code EBROKEN" in w and "something first" not in w, w
        assert len([ln for ln in log if ln.startswith("install-scripts")]) == 1, log


@requires_node
class TestCopyableCommandsQuoteThePin:
    """CR 2482: a hint is copied whole, and a pin path can hold a space."""

    def test_the_hints_quote_a_pin_with_a_space(self, tmp_path: Path) -> None:
        binv = _fake_npm(tmp_path, "11.20.0", _listing(PENDING))
        lines, _ = _run(tmp_path, binv, pin_name="pin with space")
        pin = tmp_path / "pin with space"
        hints = "\n".join(ln for ln in lines if "→" in ln)
        assert f'--prefix "{pin}"' in hints, hints
        assert f"--prefix {pin}" not in hints, hints

    def test_no_hint_in_preflight_leaves_the_pin_unquoted(self) -> None:
        body = PREFLIGHT.read_text()
        loose = [
            ln.strip()
            for ln in body.splitlines()
            if "--prefix $SC_PIN_DIR" in ln or "--prefix ${SC_PIN_DIR" in ln
        ]
        assert not loose, loose


class TestTheDocSaysIt:
    def test_host_memory_names_the_default_and_the_review(self) -> None:
        doc = HOST_MEMORY.read_text()
        for needle in (
            "11.20",
            "npm install-scripts ls --prefix",
            "npm install-scripts deny --all --prefix",
            "prebuild",
            "#606",
            "by name",
            "every re-pin",
        ):
            assert needle in doc, f"host-memory.md does not say {needle!r}"

    def test_the_swap_reading_keeps_its_date(self) -> None:
        """CR 2475: replicator's 4 G of swap was a reading at #331, and the
        date is what squares it with co-replicator's no swap (#330)."""
        text = " ".join(HOST_MEMORY.read_text().split())
        assert "4 G swap when #331 measured it" in text, (
            "host-memory.md lost when replicator's swap was measured"
        )
