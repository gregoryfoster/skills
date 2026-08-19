"""One knob, two entry points, two right answers (#187).

`HEALTH_TIMEOUT_MS` bounds the same driver run from two callers with different
budgets, and the two usage blocks each documented only their own half:

  - `socraticode-health.sh --help` said *default 60000*, which is the number the
    hook exports at the call site.
  - `mcp-driver.mjs --help` said *default 120000*, which is the driver's own
    fallback — and justified it with "It runs from a SessionStart hook", a
    rationale belonging to the caller that overrides it, so the sentence
    explained a number that caller never uses.

Both statements were true in isolation and the pair was misleading, which did
not matter while the hook was the only invocation. [#177] made the driver a
documented direct path — SKILL.md Phase 6 and `references/socraticode-doc.md`
both hand a reader `mcp-driver.mjs health-check` to run themselves — so
`--help` on the driver alone now answers a reader whose ceiling really is
120000, while `--help` on the hook answers one whose ceiling really is 60000,
and neither told them the other existed.

The resolution was **not** to make the defaults agree. They are two budgets, not
one drifted number: 60000 is what a SessionStart hook can spend before it blocks
a session, and 120000 is what a health check run by hand — against a stack that
may still be starting Docker — is worth waiting for. Unifying at 60000 would
push the hook's constraint onto the only caller that does not have it; unifying
at 120000 would mean dropping the hook's export and letting a session stall for
two minutes. So the disagreement stands and each usage block names both numbers.

That is the invariant this file pins, because it is the one that rots: the next
editor who touches either number, or who "tidies" a usage block back down to its
own half, reintroduces exactly the reading #187 reported.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "skills" / "init-socraticode" / "scripts"
DRIVER = SCRIPTS / "mcp-driver.mjs"
HOOK = SCRIPTS / "socraticode-health.sh"

# The two budgets. Changing either is a deliberate act; this file makes it one
# that has to be made in the source, the help text, and here.
HOOK_MS = 60000
DIRECT_MS = 120000

requires_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is required to run mcp-driver.mjs --help",
)


def _clean_env(**extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("SOCRATICODE_DRIVER", "SOCRATICODE_PROBE_FILE",
              "HEALTH_TIMEOUT_MS", "SOCRATICODE_HEALTH_FORCE"):
        env.pop(k, None)
    env.update(extra)
    return env


def _help(*cmd: str) -> str:
    result = subprocess.run(
        [*cmd, "--help"], capture_output=True, text=True, timeout=60,
        env=_clean_env(),
    )
    assert result.returncode == 0, f"{cmd} --help exited {result.returncode}"
    return result.stdout


class TestTheCodeMeansWhatTheHelpSays:
    """Each side's documented default is the default it actually applies."""

    def test_the_hook_exports_the_number_it_advertises(self) -> None:
        src = HOOK.read_text()
        assert re.search(
            r'^export HEALTH_TIMEOUT_MS="\$\{HEALTH_TIMEOUT_MS:-%d\}"$' % HOOK_MS,
            src, re.M,
        ), (
            f"socraticode-health.sh no longer exports {HOOK_MS} as the default "
            "ceiling. If that is deliberate, update HOOK_MS here and both usage "
            "blocks — and check the new number against the contract that a "
            "SessionStart hook must never block a session."
        )

    def test_the_driver_falls_back_to_the_number_it_advertises(self) -> None:
        src = DRIVER.read_text()
        assert re.search(
            r"process\.env\.HEALTH_TIMEOUT_MS \|\| %d\b" % DIRECT_MS, src,
        ), (
            f"mcp-driver.mjs no longer falls back to {DIRECT_MS}. If that is "
            "deliberate, update DIRECT_MS here and both usage blocks."
        )

    def test_the_two_budgets_are_still_different(self) -> None:
        """A guard against 'fixing' #187 by unifying them.

        If a later change really does decide one number serves both callers,
        this test is the place that argument gets made — not a silent edit.
        """
        assert HOOK_MS != DIRECT_MS
        assert HOOK_MS < DIRECT_MS, (
            "the hook's ceiling must stay the tighter one: it runs at session "
            "start, where a bounded wait is the whole contract"
        )


class TestEachUsageBlockNamesBothNumbers:
    """The #187 defect exactly: a reader of one entry point gets one number."""

    @requires_node
    def test_driver_help_names_the_hook_override(self) -> None:
        text = _help("node", str(DRIVER))
        assert str(DIRECT_MS) in text, "the driver's own default is unstated"
        assert str(HOOK_MS) in text, (
            "mcp-driver.mjs --help states its 120000 default without saying the "
            "SessionStart hook exports 60000 — so a reader who reaches the "
            "driver through the hook is told a ceiling that never applies to "
            "them. That is #187. State the override."
        )
        assert "socraticode-health.sh" in text, (
            "the driver's help names an override without naming who sets it"
        )

    def test_hook_help_names_the_drivers_own_default(self) -> None:
        text = _help("bash", str(HOOK))
        assert str(HOOK_MS) in text, "the hook's exported ceiling is unstated"
        assert str(DIRECT_MS) in text, (
            "socraticode-health.sh --help states 60000 without saying it is a "
            "tightening of mcp-driver.mjs's own 120000 default — so a reader "
            "carries the hook's number to a direct run, where it is wrong."
        )

    @requires_node
    def test_the_driver_no_longer_justifies_its_default_by_the_hook(self) -> None:
        """The rationale belonged to the caller that overrides the number.

        "It runs from a SessionStart hook, so it must not hang a session" is the
        reason for 60000, not for 120000. Attached to 120000 it made the wrong
        number look considered.
        """
        text = _help("node", str(DRIVER))
        line = next(
            (ln for ln in text.splitlines() if "HEALTH_TIMEOUT_MS" in ln), None,
        )
        assert line is not None, "the driver's help no longer documents the knob"
        para = text[text.index(line):]
        para = para[:para.index("\n\n")] if "\n\n" in para else para
        assert not re.search(
            r"It runs from a SessionStart hook, so it must not hang", para,
        ), (
            "the 120000 default is again justified by the SessionStart hook, "
            "which overrides it to 60000 and is no longer the only caller (#177)"
        )


class TestTheOverrideActuallyReachesTheDriver:
    """The help is only true if the hook really exports it."""

    @requires_node
    def test_hook_hands_the_driver_60000(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q"],
                       check=True, capture_output=True, env=_clean_env())
        (repo / ".socraticodecontextartifacts.json").write_text('{"artifacts": []}')

        out = tmp_path / "seen.txt"
        stub = repo / "record-env.mjs"
        stub.write_text(
            "import { writeFileSync } from 'node:fs';\n"
            "writeFileSync(process.env.HEALTH_ENV_OUT, "
            "String(process.env.HEALTH_TIMEOUT_MS));\n"
            "process.exit(0);\n"
        )
        subprocess.run(
            ["bash", str(HOOK)], cwd=str(repo), capture_output=True, text=True,
            timeout=60,
            env=_clean_env(SOCRATICODE_DRIVER=str(stub), HEALTH_ENV_OUT=str(out)),
        )
        assert out.read_text() == str(HOOK_MS)

    @requires_node
    def test_an_operators_value_survives_the_hook(self, tmp_path: Path) -> None:
        """`:-` not `=`: the help promises an operator can widen the ceiling."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q"],
                       check=True, capture_output=True, env=_clean_env())
        (repo / ".socraticodecontextartifacts.json").write_text('{"artifacts": []}')

        out = tmp_path / "seen.txt"
        stub = repo / "record-env.mjs"
        stub.write_text(
            "import { writeFileSync } from 'node:fs';\n"
            "writeFileSync(process.env.HEALTH_ENV_OUT, "
            "String(process.env.HEALTH_TIMEOUT_MS));\n"
            "process.exit(0);\n"
        )
        subprocess.run(
            ["bash", str(HOOK)], cwd=str(repo), capture_output=True, text=True,
            timeout=60,
            env=_clean_env(SOCRATICODE_DRIVER=str(stub), HEALTH_ENV_OUT=str(out),
                           HEALTH_TIMEOUT_MS="300000"),
        )
        assert out.read_text() == "300000"
