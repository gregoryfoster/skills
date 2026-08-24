"""#222 — the SessionStart strip reads per-hook and writes per-group.

`install-hook.sh` decides *whether* a hook is registered by scanning every
command in every matcher group (`matching_commands`), and then *removes* the
registration by dropping whole matcher groups keyed on their **first** hook
only. Two granularities, one filter, and the answer is wrong in both directions
the moment a matcher group holds more than one hook:

- **Failure A — eviction.** The marker matches at index 0, so `map(select(...))`
  over `.hooks.SessionStart` deletes the entire group and every sibling hook
  registered beside it. Silent: the installer reports success, the evicted
  hook's symlink is still a valid file, and `.skills/doctor.sh` sees nothing
  wrong because only the registration is gone. This is what happened to
  `CannObserv/watcher`, which lost its daily submodule refresh to an
  `init-socraticode` install.
- **Failure B — duplication.** The marker matches at index ≥ 1, so the `[0]`
  probe never sees it, the group is retained, and the append writes a *second*
  registration. `is_registered` scans all indices, so the same run also prints
  `upgrading the registration to the canonical command form` while doing the
  opposite of collapsing.

Every fixture in `test_hook_installer_generic.py` and
`test_refresh_hook_install.py` builds one-hook groups, which is exactly why both
directions passed. So the fixture here — a **multi-hook matcher group** — is the
test, and the assertions are almost incidental to it.

A multi-hook group is not exotic. It is the natural shape when hooks were
registered by hand, or by any tooling predating `install-hook.sh`, and all three
hooks a cohort consumer ends up with land in the same `SessionStart` array.

Both write paths are covered, because they were the same filter: the merge strip
on the install path and the strip on `--uninstall`. So is the jq block
`managing-skills/SKILL.md` documents for a manual uninstall, which carried the
identical `[0]` — run verbatim, the way `TestManagingSkillsHookCommand` runs the
rest of that document's snippets, because a documented filter that evicts a
group-mate is the same defect with a slower fuse.
"""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MS_SCRIPTS = REPO_ROOT / "skills" / "managing-skills" / "scripts"
MS_SKILL = REPO_ROOT / "skills" / "managing-skills" / "SKILL.md"
MS_REFERENCES = REPO_ROOT / "skills" / "managing-skills" / "references"


def _documented_surface() -> list[str]:
    """Every file this skill publishes prose in: SKILL.md plus references/.

    A snippet under test may live in either, and moves between them when the
    ratchet forces a demotion. Callers searching for a documented block search
    all of it, so relocating one does not read as a behavioural change.
    """
    texts = [MS_SKILL.read_text()]
    texts += [p.read_text() for p in sorted(MS_REFERENCES.rglob("*.md"))]
    return texts
INSTALL_HOOK = MS_SCRIPTS / "install-hook.sh"
INSTALL_REFRESH = MS_SCRIPTS / "install-refresh.sh"
SOC_SCRIPTS = REPO_ROOT / "skills" / "init-socraticode" / "scripts"

REMINDER = "socraticode-reminder.sh"
HEALTH = "socraticode-health.sh"
REFRESH = "skills-submodule-update.sh"

SETTINGS_REL = ".claude/settings.json"

REMINDER_ARGS = (
    "--hook", REMINDER, "--skill", "init-socraticode",
    "--marker", "socraticode-prefetch", "--marker", "socraticode-reminder",
)
HEALTH_ARGS = (
    "--hook", HEALTH, "--skill", "init-socraticode",
    "--marker", "socraticode-health",
)

# The exact pair watcher carried, in the order it carried them: the reminder
# hook first, so the marker matches at index 0, and the refresh hook second, so
# it is the group-mate the strip took with it.
LEGACY_REMINDER_CMD = f"bash .claude/hooks/{REMINDER}"
LEGACY_REFRESH_CMD = f"bash .claude/hooks/{REFRESH}"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — pre-commit sets GIT_INDEX_FILE etc.,
    and a linked worktree shares .git/config with its main checkout, so a
    repo-creating git command that inherits them writes the wrong repo (#189)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _run(repo: Path, *args: str, script: Path = INSTALL_HOOK):
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=repo, capture_output=True, text=True, env=_clean_env(), timeout=30,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A consumer checkout vendoring both skills, no hooks wired."""
    r = tmp_path / "consumer"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True, env=_clean_env())
    for skill, names in (
        ("managing-skills", [REFRESH]),
        ("init-socraticode", [REMINDER, HEALTH]),
    ):
        vendor = r / "skills-vendor" / "acme-skills" / "skills" / skill / "scripts"
        vendor.mkdir(parents=True, exist_ok=True)
        src_dir = MS_SCRIPTS if skill == "managing-skills" else SOC_SCRIPTS
        for name in names:
            (vendor / name).write_text((src_dir / name).read_text())
    return r


def _settings(repo: Path) -> dict:
    return json.loads((repo / SETTINGS_REL).read_text())


def _groups(repo: Path) -> list[dict]:
    return _settings(repo).get("hooks", {}).get("SessionStart", [])


def _commands(repo: Path) -> list[str]:
    return [h.get("command", "") for e in _groups(repo) for h in e.get("hooks", [])]


def _seed_group(repo: Path, *commands: str) -> None:
    """ONE matcher group holding every command — the shape no other fixture in
    this suite builds, and the whole point of this file."""
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    (repo / SETTINGS_REL).write_text(json.dumps({
        "hooks": {"SessionStart": [{
            "matcher": ".*",
            "hooks": [
                {"type": "command", "command": c} for c in commands
            ],
        }]}
    }))


class TestRegisteringAHookDoesNotEvictItsGroupMates:
    """Failure A. The serious one: it removes a working capability, reports
    success, and leaves no artifact any checker can see."""

    def test_a_group_mate_at_index_1_survives_an_install(self, repo: Path):
        _seed_group(repo, LEGACY_REMINDER_CMD, LEGACY_REFRESH_CMD)
        r = _run(repo, *REMINDER_ARGS)
        assert r.returncode == 0, r.stderr
        assert LEGACY_REFRESH_CMD in _commands(repo), (
            "installing the reminder hook deleted the refresh hook's "
            f"registration — the whole matcher group went with it:\n"
            f"{json.dumps(_groups(repo), indent=2)}"
        )

    def test_a_group_mate_at_index_0_survives_an_install(self, repo: Path):
        """The mirror ordering. `[0]` makes the two orders behave differently,
        which is itself the tell that the filter is keyed on position."""
        _seed_group(repo, LEGACY_REFRESH_CMD, LEGACY_REMINDER_CMD)
        r = _run(repo, *REMINDER_ARGS)
        assert r.returncode == 0, r.stderr
        assert LEGACY_REFRESH_CMD in _commands(repo), _groups(repo)

    def test_an_unrelated_group_mate_survives(self, repo: Path):
        """Not every group-mate is another installer's hook. A hand-wired
        `bash .skills/doctor.sh` beside it is the commonest case of all."""
        _seed_group(repo, LEGACY_REMINDER_CMD, "bash .skills/doctor.sh")
        assert _run(repo, *REMINDER_ARGS).returncode == 0
        assert "bash .skills/doctor.sh" in _commands(repo), _groups(repo)

    def test_all_three_hooks_can_share_one_group(self, repo: Path):
        """The cohort's end state, reached from a hand-registered start: three
        hooks, three installers, one array. Installing each in turn must leave
        exactly three registrations."""
        _seed_group(repo, LEGACY_REMINDER_CMD, LEGACY_REFRESH_CMD)
        assert _run(repo, *REMINDER_ARGS).returncode == 0
        # Asserted mid-sequence, not only at the end: re-running the refresh
        # installer afterwards would restore what the first step deleted, so a
        # count taken only at the end passes over the eviction.
        assert LEGACY_REFRESH_CMD in _commands(repo), _groups(repo)
        assert _run(repo, *HEALTH_ARGS).returncode == 0
        assert LEGACY_REFRESH_CMD in _commands(repo), _groups(repo)
        assert _run(repo, script=INSTALL_REFRESH).returncode == 0
        cmds = _commands(repo)
        assert len(cmds) == 3, cmds
        for name in (REMINDER, HEALTH, REFRESH):
            assert len([c for c in cmds if name in c]) == 1, (name, cmds)


class TestReRegisteringANonFirstHookDoesNotDuplicateIt:
    """Failure B, the mirror. `is_registered` scans every index and says yes;
    the strip only ever reads index 0 and removes nothing; the append writes a
    second entry. The run announces an upgrade while producing the duplicate
    that the dedupe-then-append design exists to prevent."""

    def test_the_legacy_entry_is_collapsed_not_appended_to(self, repo: Path):
        _seed_group(repo, LEGACY_REMINDER_CMD, LEGACY_REFRESH_CMD)
        r = _run(repo, script=INSTALL_REFRESH)
        assert r.returncode == 0, r.stderr
        hits = [c for c in _commands(repo) if REFRESH in c]
        assert len(hits) == 1, (
            "the pre-#110 cwd-relative entry was left in place and a second "
            f"registration appended beside it:\n{hits}"
        )
        assert hits == [
            'bash "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/'
            'skills-submodule-update.sh"'
        ], hits

    def test_two_forms_of_the_same_hook_in_one_group_collapse(self, repo: Path):
        """A duplicate pair that ended up inside a single group rather than in
        two. Both match, so the strip must empty the group, and the group must
        then go rather than linger as `{"matcher": ".*", "hooks": []}`."""
        canonical = (
            'bash "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/'
            'socraticode-reminder.sh" # socraticode-prefetch'
        )
        _seed_group(repo, canonical, LEGACY_REMINDER_CMD)
        assert _run(repo, *REMINDER_ARGS).returncode == 0
        assert len(_commands(repo)) == 1, _groups(repo)
        assert _groups(repo) == [{
            "matcher": ".*",
            "hooks": [{"type": "command", "command": canonical}],
        }], _groups(repo)


class TestUninstallHasTheIdenticalDefect:
    """`--uninstall` shares the filter, so it shares both failures — and here
    eviction is worse, because the operator asked for exactly one hook to go."""

    def test_uninstalling_one_hook_leaves_its_group_mate_registered(
        self, repo: Path
    ):
        _seed_group(repo, LEGACY_REMINDER_CMD, LEGACY_REFRESH_CMD)
        r = _run(repo, *REMINDER_ARGS, "--uninstall")
        assert r.returncode == 0, r.stderr
        assert LEGACY_REFRESH_CMD in _commands(repo), (
            "--uninstall on a grouped hook removed its group-mate's "
            f"registration too:\n{json.dumps(_groups(repo), indent=2)}"
        )

    def test_uninstalling_a_non_first_hook_actually_removes_it(
        self, repo: Path
    ):
        """The `[0]` probe never sees index 1, so the strip is a no-op and
        `--uninstall` exits 0 having left the entry running."""
        _seed_group(repo, LEGACY_REFRESH_CMD, LEGACY_REMINDER_CMD)
        r = _run(repo, *REMINDER_ARGS, "--uninstall")
        assert r.returncode == 0, r.stderr
        assert not [c for c in _commands(repo) if REMINDER in c], (
            "--uninstall reported success and left the registration behind:\n"
            f"{json.dumps(_groups(repo), indent=2)}"
        )
        assert LEGACY_REFRESH_CMD in _commands(repo), _groups(repo)

    def test_a_group_emptied_by_uninstall_is_dropped(self, repo: Path):
        """Stripping at hook granularity must not leave hollow groups behind.
        An accumulating `{"hooks": []}` per uninstall is litter that the next
        reader has to decide is harmless."""
        _seed_group(repo, LEGACY_REMINDER_CMD)
        assert _run(repo, *REMINDER_ARGS, "--uninstall").returncode == 0
        assert _groups(repo) == [], _groups(repo)

    def test_a_group_that_was_already_empty_is_left_alone(self, repo: Path):
        """The other half of the same rule. Dropping every empty group would
        edit content this installer never wrote, which the script's own
        contract forbids — only groups this run emptied may go."""
        (repo / ".claude").mkdir(parents=True, exist_ok=True)
        (repo / SETTINGS_REL).write_text(json.dumps({
            "hooks": {"SessionStart": [
                {"matcher": "startup", "hooks": []},
                {"matcher": ".*", "hooks": [
                    {"type": "command", "command": LEGACY_REMINDER_CMD},
                ]},
            ]}
        }))
        assert _run(repo, *REMINDER_ARGS, "--uninstall").returncode == 0
        assert {"matcher": "startup", "hooks": []} in _groups(repo), _groups(repo)


class TestTheDocumentedUninstallFilterIsFixedToo:
    """`managing-skills` publishes the manual equivalent of `--uninstall` as a
    jq block, and it carried the same `[0]`. Run verbatim, for the reason
    `TestManagingSkillsHookCommand` runs the rest of that skill's snippets: a
    behavioural test that hardcodes what the doc *should* say cannot catch the
    doc saying something else.

    Searched across the skill's whole documented surface — SKILL.md plus its
    references/ — rather than SKILL.md alone. The claim under test is "the
    filter this skill publishes works", and *which file* publishes it is
    incidental: the block began in SKILL.md and moved to
    `references/auto-refresh-hook.md` when that file was curated under its
    ratchet. Binding the test to one path made a demotion look like a
    behavioural regression, which is the wrong signal from a suite that exists
    to catch the doc drifting from the script.
    """

    def _documented_block(self) -> str:
        blocks = [
            b for text in _documented_surface()
            for b in re.findall(r"```bash\n(.*?)```", text, re.DOTALL)
            if "jq " in b and REFRESH in b
        ]
        assert len(blocks) == 1, (
            "expected exactly one documented jq block naming "
            f"{REFRESH!r} across managing-skills' SKILL.md and references/, "
            f"found {len(blocks)}"
        )
        return blocks[0]

    def test_it_strips_the_hook_without_evicting_its_group_mate(
        self, repo: Path
    ):
        _seed_group(repo, LEGACY_REFRESH_CMD, "bash .skills/doctor.sh")
        r = subprocess.run(
            ["bash", "-c", self._documented_block()],
            cwd=repo, capture_output=True, text=True, env=_clean_env(),
            timeout=30,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "bash .skills/doctor.sh" in _commands(repo), (
            "the documented manual uninstall deleted an unrelated hook that "
            f"shared the matcher group:\n{json.dumps(_groups(repo), indent=2)}"
        )
        assert not [c for c in _commands(repo) if REFRESH in c], _groups(repo)

    def test_it_removes_the_hook_when_it_is_not_first_in_its_group(
        self, repo: Path
    ):
        _seed_group(repo, "bash .skills/doctor.sh", LEGACY_REFRESH_CMD)
        r = subprocess.run(
            ["bash", "-c", self._documented_block()],
            cwd=repo, capture_output=True, text=True, env=_clean_env(),
            timeout=30,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert not [c for c in _commands(repo) if REFRESH in c], (
            "the documented manual uninstall left the entry in place because "
            f"it was not first in its group:\n{json.dumps(_groups(repo), indent=2)}"
        )
