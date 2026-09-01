"""#259 — a SessionStart entry carries a deliberate `timeout`, and a re-run keeps it.

`install-hook.sh` merged entries of this shape:

    {"type": "command",
     "command": "bash \\"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/socraticode-health.sh\\" # socraticode-health"}

No `timeout` key, so the harness default applied. Two consequences, and the
second is the one that bites:

1. **The health hook is the worst candidate for an implicit ceiling.** It shells
   out to `mcp-driver.mjs`, which starts the server via `npx -y socraticode` —
   4.0s measured warm on `CannObserv/cli`, a package download cold. And it
   stamps its once-per-UTC-day lock *before* doing the work, deliberately, so a
   transient failure does not re-run and re-log on every same-day session. A
   timeout kill therefore **consumes the day's attempt and reports nothing**,
   and the lock guarantees no retry until tomorrow. A hook that is silent when
   clean cannot be told from one that never finished — the ambiguity #179 is
   about, reached through the timeout instead of through the exit code.

2. **The dedupe-strip discarded a timeout the consumer added.** The merge is
   dedupe-then-append: it removes every entry matching the marker and appends
   one canonical entry rebuilt from constants. That is right for upgrading a
   stale command string, and it meant a consumer who added `"timeout": 120` by
   hand — on this installer's own advice, in the per-repo #167 issues — lost it
   on the next `install-hook.sh` run, with no warning. The repair was silently
   undone by the tool that prescribed it. `CannObserv/cli`'s
   `socraticode-reminder.sh` **had** `"timeout": 5` before an install and lost
   it to the rewrite: a regression from a value someone had chosen.

The resolution keeps the constants where #200 put them — a `--timeout N` flag
whose per-hook value lives in each `<hook>.install` manifest, not in a branch
inside the installer — and makes **preserve beat prescribe**: a value already on
the entry being replaced wins over the flag, and the run says so. Nothing in the
installer can tell a figure an operator chose from one a manifest supplied (both
arrive as `--timeout`), so a precedence rule that let the argument win would undo
the repair again for the only caller that matters.

What this file pins, and why each is a mechanism rather than a spelling:

- **Every hook a consumer installs names its own ceiling.** A manifest without
  one is back to the harness default, which is the defect.
- **The reminder hook's is tighter than the two network-touching hooks'.** It is
  one `echo`; the other two reach the network. Collapsing them to one number is
  the "unify the defaults" move `test_health_timeout_contract.py` refuses for
  the sibling knob, for the same reason: they are two budgets, not one drifted
  number.
- **A fresh install writes the flag's value as a JSON number**, not a string,
  and not at all when no `--timeout` was given — absent means "the harness
  default applies", which is a state a consumer may want.
- **A re-run preserves a differing registered value**, reports both numbers, and
  still reads as `unchanged` — an idempotent tool that announces a change it did
  not make is how a real change stops being noticed.
- **A re-run ADDS the value where the entry carries none**, which is the upgrade
  path for every consumer installed before this existed.
- **The strip does not evict a sibling hook's timeout**, which is #222's failure
  asked about the new key.
"""

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
INSTALL_HOOK = SKILLS_DIR / "managing-skills" / "scripts" / "install-hook.sh"

# Each hook a consumer ends up with, its vendoring skill, and the ceiling its
# manifest must name. The numbers are here so that changing one is a deliberate
# act made in two places, exactly as `test_health_timeout_contract.py` holds the
# two `HEALTH_TIMEOUT_MS` budgets.
HOOK_TIMEOUTS = {
    ("skills-submodule-update.sh", "managing-skills"): 120,
    ("socraticode-reminder.sh", "init-socraticode"): 5,
    ("socraticode-health.sh", "init-socraticode"): 120,
}

# The one hook that is pure local work. Everything else here reaches the
# network, and the split is the point — see the module docstring.
LOCAL_ONLY = ("socraticode-reminder.sh", "init-socraticode")

requires_jq = pytest.mark.skipif(
    shutil.which("jq") is None,
    reason="install-hook.sh edits settings.json with jq",
)


def _manifest(hook: str, skill: str) -> Path:
    return SKILLS_DIR / skill / "scripts" / (hook.removesuffix(".sh") + ".install")


def _manifest_args(hook: str, skill: str) -> list[str]:
    """The manifest's argument line, as `.skills/doctor.sh` reads it."""
    for line in _manifest(hook, skill).read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return shlex.split(stripped)
    raise AssertionError(f"{_manifest(hook, skill)} carries no argument line")


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — a linked worktree shares .git/config
    with its main checkout, so a fixture-creating git command that inherits
    them reaches out of the fixture and writes the wrong repo (#189)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _consumer(tmp_path: Path) -> Path:
    repo = tmp_path / "consumer"
    (repo / "skills-vendor/acme-skills/skills/demo/scripts").mkdir(parents=True)
    (repo / "skills-vendor/acme-skills/skills/demo/scripts/demo-hook.sh").write_text(
        "#!/usr/bin/env bash\nexit 0\n"
    )
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True,
                   capture_output=True, env=_clean_env(), timeout=60)
    return repo


def _install(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALL_HOOK), "--hook", "demo-hook.sh", "--skill", "demo",
         "--marker", "demo-hook", *args],
        cwd=str(repo), capture_output=True, text=True,
        env=_clean_env(), timeout=120,
    )


def _entries(repo: Path) -> list[dict]:
    settings = json.loads((repo / ".claude/settings.json").read_text())
    return [h for group in settings["hooks"]["SessionStart"]
            for h in group["hooks"]]


def _entry(repo: Path, marker: str = "demo-hook") -> dict:
    matches = [e for e in _entries(repo) if marker in e["command"]]
    assert len(matches) == 1, f"expected one {marker} entry, found {len(matches)}"
    return matches[0]


class TestEveryHookNamesItsOwnCeiling:
    """The constants stay in the manifests, and each one is a real figure."""

    @pytest.mark.parametrize(("hook", "skill"), sorted(HOOK_TIMEOUTS))
    def test_the_manifest_carries_a_timeout(self, hook: str, skill: str) -> None:
        args = _manifest_args(hook, skill)
        assert "--timeout" in args, (
            f"{_manifest(hook, skill).relative_to(REPO_ROOT)} names no "
            "--timeout, so install-hook.sh registers this hook with no ceiling "
            "and the harness default applies. That is #259 — and for a hook "
            "that stamps a once-per-day lock before doing its work, a kill "
            "consumes the day's attempt and reports nothing."
        )
        value = args[args.index("--timeout") + 1]
        assert value.isdigit() and int(value) > 0, (
            f"--timeout in {_manifest(hook, skill).name} is not a positive "
            f"whole number of seconds: {value!r}. It is written into "
            "settings.json as a JSON number."
        )
        assert int(value) == HOOK_TIMEOUTS[(hook, skill)], (
            f"{hook} now claims a {value}s ceiling; this file records "
            f"{HOOK_TIMEOUTS[(hook, skill)]}s. If the change is deliberate, "
            "make it here too — the figure is a budget with a reason, and the "
            "reason belongs beside both copies."
        )

    def test_the_local_hook_keeps_the_tighter_budget(self) -> None:
        """A guard against 'tidying' the three numbers into one.

        They are three budgets, not one drifted number: the reminder hook is a
        single `echo`, and the other two reach the network. Unifying upward
        gives a trivial hook a two-minute licence to hang a session start;
        unifying downward puts a local hook's budget on a `git submodule
        update --remote` that legitimately needs longer.
        """
        local = HOOK_TIMEOUTS[LOCAL_ONLY]
        networked = [v for k, v in HOOK_TIMEOUTS.items() if k != LOCAL_ONLY]
        assert networked, "the split this test describes no longer exists"
        assert all(local < n for n in networked), (
            "socraticode-reminder.sh's ceiling is no longer the tightest. It "
            "is one echo; the others reach the network. If one number really "
            "does serve all three, make that argument here rather than in a "
            "silent edit."
        )


@requires_jq
class TestTheInstallerWritesAndKeepsIt:
    """The flag reaches settings.json, and a re-run never takes it away."""

    def test_a_fresh_install_writes_a_json_number(self, tmp_path: Path) -> None:
        repo = _consumer(tmp_path)
        assert _install(repo, "--timeout", "120", "-q").returncode == 0
        entry = _entry(repo)
        assert entry["timeout"] == 120
        assert isinstance(entry["timeout"], int), (
            "the timeout was written as a string; Claude Code reads a number"
        )

    def test_no_flag_writes_no_key(self, tmp_path: Path) -> None:
        """Absent is a state, not a missing default.

        Writing some number for "no --timeout given" would invent a policy
        nobody chose, and would make this flag impossible to opt out of.
        """
        repo = _consumer(tmp_path)
        assert _install(repo, "-q").returncode == 0
        assert "timeout" not in _entry(repo)

    def test_a_rerun_preserves_a_value_the_consumer_chose(self, tmp_path: Path) -> None:
        """#259's actual finding: the repair undone by the tool prescribing it."""
        repo = _consumer(tmp_path)
        assert _install(repo, "--timeout", "120", "-q").returncode == 0
        settings = repo / ".claude/settings.json"
        data = json.loads(settings.read_text())
        data["hooks"]["SessionStart"][0]["hooks"][0]["timeout"] = 300
        settings.write_text(json.dumps(data, indent=2))

        result = _install(repo, "--timeout", "120")
        assert result.returncode == 0
        assert _entry(repo)["timeout"] == 300, (
            "the dedupe-strip discarded a timeout the consumer had set by hand "
            "and rebuilt the entry from constants — #259 exactly"
        )
        # stderr, and deliberately (CR round 1, finding 7): this is the one
        # line saying the run ignored an argument it was given, and through
        # log() it was suppressed by --quiet — for the automated caller least
        # likely to notice the difference any other way.
        assert "300" in result.stderr and "120" in result.stderr, (
            "the run kept a value differing from the one prescribed and did "
            "not say so; a silent preserve freezes a raised default forever "
            "with nothing to read"
        )
        quiet = _install(repo, "--timeout", "120", "-q")
        assert "300" in quiet.stderr, "--quiet swallowed the decision notice"
        assert "unchanged" in result.stdout, (
            "preserving a differing value must still read as unchanged — an "
            "idempotent tool that announces a change it did not make is how a "
            "real change stops being noticed"
        )

    def test_a_rerun_adds_the_ceiling_where_there_is_none(self, tmp_path: Path) -> None:
        """The upgrade path for every consumer installed before #259."""
        repo = _consumer(tmp_path)
        assert _install(repo, "-q").returncode == 0
        assert "timeout" not in _entry(repo)
        assert _install(repo, "--timeout", "5", "-q").returncode == 0
        assert _entry(repo)["timeout"] == 5

    def test_check_reports_a_missing_ceiling_as_repairable(self, tmp_path: Path) -> None:
        repo = _consumer(tmp_path)
        assert _install(repo, "-q").returncode == 0
        result = _install(repo, "--timeout", "5", "--check")
        assert result.returncode == 3, (
            "a registered entry with no timeout, where the hook prescribes one, "
            "is a form this installer repairs — --check must say so"
        )
        assert "timeout" in result.stdout

    def test_check_does_not_fail_on_a_deliberate_local_value(self, tmp_path: Path) -> None:
        """Reported, not red.

        There is nothing here for a re-run to repair — the installer preserves
        the value — and failing would push a consumer toward deleting a
        deliberate figure to get a green light.
        """
        repo = _consumer(tmp_path)
        assert _install(repo, "--timeout", "300", "-q").returncode == 0
        result = _install(repo, "--timeout", "120", "--check")
        assert result.returncode == 0
        assert "300" in result.stdout and "120" in result.stdout

    def test_a_siblings_timeout_survives_this_hooks_install(self, tmp_path: Path) -> None:
        """#222's failure, asked about the new key.

        The strip removes matching HOOKS rather than whole matcher groups, so a
        group holding several hooks keeps the ones this run does not own — and
        each keeps its own ceiling.
        """
        repo = _consumer(tmp_path)
        (repo / ".claude").mkdir(exist_ok=True)
        (repo / ".claude/settings.json").write_text(json.dumps({"hooks": {
            "SessionStart": [{"matcher": ".*", "hooks": [
                {"type": "command", "command": "bash .claude/hooks/other.sh",
                 "timeout": 60},
                {"type": "command",
                 "command": "bash .claude/hooks/demo-hook.sh # demo-hook",
                 "timeout": 90},
            ]}],
        }}, indent=2))

        assert _install(repo, "--timeout", "120", "-q").returncode == 0
        other = _entry(repo, "other.sh")
        assert other["timeout"] == 60, "a sibling hook's ceiling was rewritten"
        mine = _entry(repo)
        assert mine["timeout"] == 90, (
            "the hand-set 90 was replaced while the command string was upgraded"
        )
        assert "CLAUDE_PROJECT_DIR" in mine["command"], (
            "preserving the timeout must not also freeze the legacy command "
            "form — the upgrade is the other half of the same merge (#110)"
        )


class TestTheFlagRefusesWhatWouldBreakSettingsJson:
    """The one argument written unquoted, so its charset is the guard."""

    @pytest.mark.parametrize("bad", ["60s", "0", "-5", "1.5", "", "86401"])
    def test_a_non_duration_is_refused(self, tmp_path: Path, bad: str) -> None:
        repo = _consumer(tmp_path)
        result = _install(repo, "--timeout", bad)
        assert result.returncode == 1, (
            f"--timeout {bad!r} was accepted; it reaches settings.json as a "
            "JSON number, so a non-duration leaves the consumer with a file "
            "Claude Code cannot parse — worse than the missing timeout this "
            "flag exists to fix"
        )
        assert not (repo / ".claude/settings.json").exists(), (
            "a run that cannot finish must not start"
        )
