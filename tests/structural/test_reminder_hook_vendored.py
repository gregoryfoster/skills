"""#186 — the prefetch hook needs a source file, and a symlink install.

`.claude/hooks/socraticode-reminder.sh` had no source file anywhere in this
repo. It was rendered from prose in
`skills/init-socraticode/references/code-exploration-policy.md`, so every
consumer's copy was whatever the installing agent typed that day.

That is strictly worse than the *copy* #179 rejected for the sibling
`socraticode-health.sh`. A copy at least starts as a byte-for-byte snapshot of
a known version and only drifts afterwards; a prose-rendered hook does not even
have that guarantee, and it carries the identical "it carries no per-project
state" justification that #179 established argues **for** the symlink.

So the fix is #179's shape, reused rather than reinvented: vendor
`scripts/socraticode-reminder.sh`, symlink it into `.claude/hooks/`, keep the
copy as the no-`skills-vendor/` fallback.

What this file pins, and why each one is a mechanism rather than a spelling:

- **The vendored script prints exactly what the prose printed.** The extraction
  is only safe if it is behaviour-preserving; the one line the hook emits is
  its entire product, and `docs/SOCRATICODE.md`'s copy of the same `select:`
  query is what an operator runs by hand when the hook did not fire. Two copies
  that must agree, so the agreement is asserted rather than maintained by
  attention.
- **The install step is a symlink with a copy fallback.** The mirror of
  `test_socraticode_graph_yield.py::TestHookIsInstalled`, which pins the same
  property for the health hook one Step down the same document. Both hooks land
  in the same `.claude/hooks/` of the same consumer; installing them by
  opposite mechanisms is the defect #179 was filed for.
- **`.skills/doctor.sh` really does cover the new hook.** #186 asserts the
  symlink "inherits" #99's dangling-symlink self-heal for free. That claim is
  the load-bearing half of choosing a symlink over a copy, and it is asserted
  here by *running* the doctor against a fixture whose reminder hook dangles,
  not by reading its SCAN_DIRS.
- **The hook never blocks a session.** A SessionStart hook that fails closed
  takes the session with it. The prose version had no `set -euo pipefail` at
  all, so this file's version is the first that *could* abort; the ERR-trap
  backstop is what keeps the degrade at "noisier reporting" rather than "no
  session", and it is exercised against a genuinely failing write.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "init-socraticode"
SCRIPT = SKILL_DIR / "scripts" / "socraticode-reminder.sh"
POLICY_REF = SKILL_DIR / "references" / "code-exploration-policy.md"
DOC_REF = SKILL_DIR / "references" / "socraticode-doc.md"
SKILL_MD = SKILL_DIR / "SKILL.md"
DOCTOR = REPO_ROOT / "skills" / "managing-skills" / "scripts" / "doctor.sh"

# The dedupe token the settings.json merge scans for, duplicated into the
# script's own header so the two cannot be reasoned about separately.
PREFETCH_MARKER = "socraticode-prefetch"

# The prefetch query itself, matched from wherever it appears rather than
# spelled out here — a third transcription of a 600-byte string in the test
# that exists to stop transcriptions diverging would be self-defeating.
_SELECT_RE = re.compile(r"select:mcp__plugin_socraticode_socraticode__[\w,]+")


def _run(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=30,
        **kwargs,
    )


class TestTheScriptIsVendored:
    """A hook with no source file is not a version of anything."""

    def test_it_exists(self) -> None:
        assert SCRIPT.exists(), (
            "skills/init-socraticode/scripts/socraticode-reminder.sh is missing "
            "— without a source file the hook is whatever the installing agent "
            "typed that day (#186)"
        )

    def test_it_is_executable(self) -> None:
        """The copy fallback `chmod +x`s it; the symlink inherits this mode."""
        assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable"

    def test_it_carries_the_dedupe_marker(self) -> None:
        assert PREFETCH_MARKER in SCRIPT.read_text(), (
            f"the script must carry the `{PREFETCH_MARKER}` marker, the same "
            "token the settings.json merge dedupes on"
        )


class TestBehaviourIsPreserved:
    """The extraction is only safe if the hook still prints the same thing."""

    def test_it_prints_exactly_one_line(self) -> None:
        result = _run()
        assert result.returncode == 0, result.stderr
        lines = result.stdout.splitlines()
        assert len(lines) == 1, (
            "the hook's entire product is one line of session context; "
            f"got {len(lines)}:\n{result.stdout}"
        )

    def test_the_line_leads_with_the_marker(self) -> None:
        assert _run().stdout.startswith(f"{PREFETCH_MARKER}:"), _run().stdout

    def test_it_names_toolsearch_and_the_preference(self) -> None:
        """The two instructions the line exists to give."""
        out = _run().stdout
        assert "ToolSearch" in out, out
        assert "Prefer codebase_search over grep" in out, out

    def test_the_prefetch_query_matches_the_overflow_doc(self) -> None:
        """`docs/SOCRATICODE.md` is what an operator runs when the hook did not
        fire. If the two drift, one of them loads a tool set the other does not
        and the failure is a validation error on a deferred schema."""
        from_script = _SELECT_RE.search(_run().stdout)
        assert from_script, f"no `select:` query in the hook's output:\n{_run().stdout}"
        from_doc = _SELECT_RE.search(DOC_REF.read_text())
        assert from_doc, f"no `select:` query in references/{DOC_REF.name}"
        assert from_script.group(0) == from_doc.group(0), (
            "the hook and references/socraticode-doc.md disagree about the "
            "ToolSearch prefetch query. Both are transcribed into consumers; "
            "they must name the same tools.\n"
            f"  hook: {from_script.group(0)}\n"
            f"  doc:  {from_doc.group(0)}"
        )

    def test_the_policy_reference_no_longer_inlines_a_script_body(self) -> None:
        """The prose that *was* the script is what #186 replaced.

        Leaving it behind would give a re-run two sources of truth, which is
        the state the issue describes.
        """
        step = _step_a()
        assert "#!/usr/bin/env bash" not in step, (
            "Step A still inlines a shebang — the reminder script is vendored "
            f"at scripts/{SCRIPT.name} now and must be installed, not "
            f"retyped (#186).\n---\n{step}"
        )
        assert "select:mcp__plugin_socraticode" not in step, (
            "Step A still inlines the prefetch query, so a consumer's hook is "
            "still a transcription rather than the vendored file (#186)"
        )


def _step_a() -> str:
    """Step A of the policy reference — where the install is actually written.

    Sliced the way `test_socraticode_graph_yield._health_hook_install_step`
    slices Step C, so both installs are read out of the document the same way.
    """
    body = POLICY_REF.read_text()
    start = body.index("**Step A —")
    return body[start:body.index("**Step B —", start)]


class TestItIsInstalledLikeItsSibling:
    """#179's shape, reused. Two hooks, one `.claude/hooks/`, one mechanism —
    and since #200 that is literally one script: `managing-skills`'
    `install-hook.sh`, which Step A and Step C invoke with different constants.
    What the installer *does* is pinned behaviourally in
    `test_hook_installer_generic.py`, against the very argument list parsed out
    of these steps; what this class pins is that the document still asks for it.
    """

    def test_step_a_runs_the_shared_installer(self) -> None:
        step = _step_a()
        assert "install-hook.sh" in step, (
            "Step A must install through managing-skills' shared installer, not "
            "a hand-rolled loop: a second implementation is the fourth "
            f"near-copy #200 exists to prevent.\n---\n{step}"
        )
        assert "--hook socraticode-reminder.sh" in step, (
            "Step A must name the hook it installs in the command it gives"
        )

    def test_step_a_still_states_the_symlink_rule(self) -> None:
        """The rule survives the move into a script. An agent reading Step A has
        to know a copy is the fallback and not the mechanism, or the first
        environment where the installer copies looks like a normal install."""
        step = _step_a()
        assert "ln -s" in step, (
            "Step A must say it symlinks the vendored script into "
            "skills-vendor/, the way Step C installs the health hook and "
            f"managing-skills installs its refresh hook (#186, #179).\n---\n{step}"
        )
        assert "skills-vendor/" in step, (
            "the symlink target must be derived from the vendor directory "
            "actually found, not a hand-substituted <owner>-<repo>"
        )

    def test_the_copy_survives_as_the_fallback(self) -> None:
        """A consumer that does not vendor via managing-skills has no
        `skills-vendor/` tree and so nothing to point at."""
        step = _step_a()
        assert "copy" in step.lower(), (
            f"the copy must survive as the fallback (#186, #179).\n---\n{step}"
        )

    def test_step_a_links_the_vendored_source(self) -> None:
        """A relative link, so `test_relative_links` proves the file is there."""
        assert f"../scripts/{SCRIPT.name}" in _step_a(), (
            "Step A must link the vendored script it installs, or a reader has "
            "no way to find the source from the install instruction"
        )

    def test_skill_md_does_not_contradict_the_reference(self) -> None:
        """The contradiction between SKILL.md and the reference is what let one
        cohort repo end up with one hook of each kind in the same directory."""
        body = SKILL_MD.read_text()
        idx = body.index(".claude/hooks/socraticode-reminder.sh")
        window = body[max(0, idx - 500):idx + 500]
        assert "symlink" in window.lower(), (
            "SKILL.md Phase 3 must describe the reminder hook as a symlink "
            f"install, matching the reference (#186).\n---\n{window}"
        )


class TestItNeverBlocksASession:
    """A SessionStart hook that fails closed takes the session with it."""

    def test_help_exits_zero_with_output(self) -> None:
        result = _run("--help")
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip(), "--help produced nothing on stdout"

    def test_an_unknown_argument_is_not_fatal(self) -> None:
        """Claude Code passes no arguments today. A future one that does must
        get the reminder, not a usage error."""
        result = _run("--some-future-flag")
        assert result.returncode == 0, result.stderr
        assert PREFETCH_MARKER in result.stdout, result.stdout

    def test_a_failed_write_degrades_to_stderr_rather_than_a_bad_exit(self) -> None:
        """The one realistic failure: stdout is closed or full.

        Under `set -euo pipefail` — which the prose version did not have — that
        is an errexit abort. The ERR-trap backstop turns it into a noisier
        report and a zero exit, which is the contract for this hook class.
        """
        result = subprocess.run(
            ["bash", "-c", f'bash "$1" 1>&-', "_", str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            "the hook exited non-zero when its stdout write failed; a "
            f"SessionStart hook must never fail closed.\n{result.stderr}"
        )
        assert "socraticode-reminder:" in result.stderr, (
            "the failure degraded silently. A hook that cannot do its job must "
            f"say so on stderr.\n{result.stderr}"
        )


def _git(repo: Path, *args: str) -> None:
    """`env -u GIT_DIR -u GIT_WORK_TREE` by construction (docs/STYLE.md).

    A linked worktree shares `.git/config` with its main checkout, so a
    repo-creating git command that inherits the orchestrator's GIT_* vars
    reaches out of the fixture and writes the wrong repo (#189).
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(
        ["git", *args], cwd=str(repo), check=True,
        capture_output=True, text=True, env=env, timeout=60,
    )


def _doctor(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["bash", str(DOCTOR), "--no-preflight", *args],
        cwd=str(repo), capture_output=True, text=True, env=env, timeout=120,
    )


@pytest.fixture
def consumer(tmp_path: Path) -> Path:
    """A consumer repo carrying a *resolving* reminder-hook symlink."""
    repo = tmp_path / "repo"
    (repo / ".claude" / "hooks").mkdir(parents=True)
    vendor = repo / "skills-vendor" / "acme-skills" / "skills" / "init-socraticode" / "scripts"
    vendor.mkdir(parents=True)
    (vendor / SCRIPT.name).write_text(SCRIPT.read_text())
    (repo / ".claude" / "hooks" / SCRIPT.name).symlink_to(
        f"../../skills-vendor/acme-skills/skills/init-socraticode/scripts/{SCRIPT.name}"
    )
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "reminder-test@example.invalid")
    _git(repo, "config", "user.name", "reminder test")
    return repo


class TestDoctorCoversTheSymlinkedHook:
    """#186 claims the symlink "inherits" #99's self-heal for free.

    Asserted by running the doctor, because that claim is the reason to prefer
    a symlink to a copy at all — and because a `SCAN_DIRS` entry is not proof
    that a *hook* symlink reaches the reporting path.
    """

    def test_a_healthy_hook_symlink_is_silent(self, consumer: Path) -> None:
        result = _doctor(consumer, "--check-only")
        assert result.returncode == 0, (
            f"the doctor flagged a resolving hook symlink:\n{result.stderr}"
        )

    def test_a_dangling_hook_symlink_is_reported(self, consumer: Path) -> None:
        """The state a consumer lands in after a fresh `git worktree add` or a
        shallow clone: the vendor tree is not there, the symlink is."""
        link = consumer / ".claude" / "hooks" / SCRIPT.name
        link.unlink()
        link.symlink_to(
            f"../../skills-vendor/acme-skills/skills/init-socraticode/scripts/{SCRIPT.name}"
        )
        target = consumer / "skills-vendor" / "acme-skills"
        for path in sorted(target.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()

        result = _doctor(consumer, "--check-only")
        assert result.returncode != 0, (
            "the doctor exited 0 on a dangling reminder-hook symlink — #186's "
            "'it inherits the self-heal for free' would be false and the "
            f"symlink install would have no advantage over a copy.\n{result.stdout}"
        )
        assert SCRIPT.name in result.stderr, (
            "the doctor must name the broken hook; a report that does not "
            f"identify the file is not actionable.\n{result.stderr}"
        )

    def test_a_copy_is_invisible_to_the_same_scan(self, consumer: Path) -> None:
        """The control, and the whole argument for the symlink.

        A copy of the same hook, equally stale, is a perfectly valid regular
        file the doctor can never see. Asserting the negative is what keeps
        someone from "simplifying" the install back to a copy on the grounds
        that the doctor would catch it.
        """
        link = consumer / ".claude" / "hooks" / SCRIPT.name
        link.unlink()
        link.write_text(SCRIPT.read_text())
        target = consumer / "skills-vendor" / "acme-skills"
        for path in sorted(target.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()

        result = _doctor(consumer, "--check-only")
        assert result.returncode == 0, (
            "the doctor now reports something about a plain copied hook; if "
            "that is deliberate, this test documents the old behaviour and "
            f"should be rewritten rather than deleted.\n{result.stderr}"
        )
