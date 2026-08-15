"""Behavioral tests for install-refresh.sh and the doctor's half-install warning
(issue #167).

The auto-refresh hook's contract is TWO artifacts — the symlink at
`.claude/hooks/skills-submodule-update.sh` and the SessionStart registration in
`.claude/settings.json` — and only the second makes it run. Four of twelve
audited consumers carried the first without the second: symlink present and
tracked, registration absent, so nothing ever bumped their vendored pointer.
All four sat at one commit for over a week while the cohort moved through four
skill versions.

Nothing detected it, because a half-installed hook is silent by construction —
the missing half is the half that would have run. The install was also the only
one of the pair that was prose rather than a script; `install-doctor.sh` has
been a script since the beginning and has no comparable failure population.

Run end-to-end against throwaway repos, because what matters is runtime
behaviour on the exact broken state: whether a repair preserves the operator's
other hooks and keys, and whether the doctor speaks up without changing its
exit code.

Coverage — install-refresh.sh:
- virgin repo                                 → both artifacts installed
- --check on a virgin repo                    → exit 3, both reported MISSING
- --check when installed                      → exit 0
- the #167 half-install                       → --check exit 3, symlink OK
- repairing a half-install                    → preserves unrelated SessionStart
                                                entries and unrelated top-level
                                                keys
- pre-existing entry in the old cwd-relative
  form (#110)                                 → recognised, not duplicated
- re-run                                      → idempotent, reports unchanged
- dangling symlink                            → --check exit 3, reported as
                                                DANGLING rather than installed
- --uninstall                                 → removes both halves, leaves
                                                other hooks intact
- no skills-vendor/                           → exit 1, nothing written
- not a git repo                              → exit 1
- the symlink target is relative and resolves

Coverage — doctor.sh:
- half-installed hook   → warns, names install-refresh.sh, still exits 0
- fully installed hook  → silent about the hook
- no symlink at all     → silent (never nag a consumer that declined the hook)

Keep this list current — it is the file's index.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "managing-skills"
    / "scripts"
)
INSTALL_REFRESH = SCRIPTS / "install-refresh.sh"
DOCTOR = SCRIPTS / "doctor.sh"
HOOK_SRC = SCRIPTS / "skills-submodule-update.sh"

VENDOR_REL = "skills-vendor/acme-skills/skills/managing-skills/scripts"
HOOK_REL = ".claude/hooks/skills-submodule-update.sh"
SETTINGS_REL = ".claude/settings.json"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — pre-commit sets GIT_INDEX_FILE etc.,
    which would leak into the script's git calls."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _path_without_jq(tmp_path: Path) -> Path:
    """A PATH carrying the tools the script needs and no jq, to exercise the
    degraded paths without touching the developer's environment."""
    bin_dir = tmp_path / "nojq-bin"
    bin_dir.mkdir(exist_ok=True)
    for tool in ("bash", "git", "sed", "grep", "awk", "readlink", "mkdir",
                 "ln", "rm", "mv", "cat", "printf", "command"):
        found = shutil.which(tool)
        if found:
            target = bin_dir / tool
            if not target.exists():
                target.symlink_to(found)
    return bin_dir


def _run(repo: Path, script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=30,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A consumer checkout with the skill vendored but no hook wired."""
    r = tmp_path / "consumer"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True, env=_clean_env())
    vendor = r / VENDOR_REL
    vendor.mkdir(parents=True)
    (vendor / "skills-submodule-update.sh").write_text(HOOK_SRC.read_text())
    return r


def _half_install(repo: Path, settings: dict | None = None) -> None:
    """The exact #167 state: symlink present, registration absent."""
    hooks = repo / ".claude" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "skills-submodule-update.sh").symlink_to(
        Path("../..") / VENDOR_REL / "skills-submodule-update.sh"
    )
    if settings is not None:
        (repo / SETTINGS_REL).write_text(json.dumps(settings))


def _settings(repo: Path) -> dict:
    return json.loads((repo / SETTINGS_REL).read_text())


def _commands(repo: Path) -> list[str]:
    entries = _settings(repo).get("hooks", {}).get("SessionStart", [])
    return [h.get("command", "") for e in entries for h in e.get("hooks", [])]


class TestInstallRefresh:
    def test_a_virgin_repo_gets_both_artifacts(self, repo: Path):
        r = _run(repo, INSTALL_REFRESH)
        assert r.returncode == 0, r.stderr
        assert (repo / HOOK_REL).is_symlink()
        assert (repo / HOOK_REL).resolve().is_file()
        assert any("skills-submodule-update.sh" in c for c in _commands(repo))

    def test_check_on_a_virgin_repo_reports_both_missing(self, repo: Path):
        r = _run(repo, INSTALL_REFRESH, "--check")
        assert r.returncode == 3
        assert "hook symlink:       MISSING" in r.stdout
        assert "SessionStart entry: MISSING" in r.stdout

    def test_check_passes_once_installed(self, repo: Path):
        _run(repo, INSTALL_REFRESH)
        r = _run(repo, INSTALL_REFRESH, "--check")
        assert r.returncode == 0, r.stdout
        assert "SessionStart entry: yes" in r.stdout

    def test_the_half_install_is_caught(self, repo: Path):
        """The #167 population: the symlink is right there, so only the
        registration half distinguishes working from frozen."""
        _half_install(repo)
        r = _run(repo, INSTALL_REFRESH, "--check")
        assert r.returncode == 3
        assert "hook symlink:       .claude/hooks" in r.stdout
        assert "SessionStart entry: MISSING" in r.stdout
        assert "frozen" in r.stdout

    def test_repairing_a_half_install_preserves_other_config(self, repo: Path):
        """What the four repos actually had: an unrelated doctor hook wired by
        hand. A repair that clobbers it trades one silent breakage for another."""
        _half_install(
            repo,
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": ".*",
                            "hooks": [
                                {"type": "command", "command": "bash .skills/doctor.sh"}
                            ],
                        }
                    ]
                },
                "permissions": {"allow": ["Bash(ls:*)"]},
            },
        )
        r = _run(repo, INSTALL_REFRESH)
        assert r.returncode == 0, r.stderr
        cmds = _commands(repo)
        assert "bash .skills/doctor.sh" in cmds
        assert any("skills-submodule-update.sh" in c for c in cmds)
        assert _settings(repo)["permissions"] == {"allow": ["Bash(ls:*)"]}

    def test_the_old_cwd_relative_form_is_not_duplicated(self, repo: Path):
        """An install predating #110 is a real registration written differently.
        Matching the whole command instead of the script path would append a
        second entry and leave the first unremovable by the uninstall filter."""
        _half_install(
            repo,
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": ".*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "bash .claude/hooks/skills-submodule-update.sh",
                                }
                            ],
                        }
                    ]
                }
            },
        )
        r = _run(repo, INSTALL_REFRESH)
        assert r.returncode == 0, r.stderr
        hits = [c for c in _commands(repo) if "skills-submodule-update.sh" in c]
        assert len(hits) == 1, hits

    def test_a_legacy_entry_is_upgraded_not_left_alone(self, repo: Path):
        """`--check` accepts the legacy cwd-relative form because it does run,
        but the install path must still normalise it. Answering both questions
        with one substring test made a re-run a no-op on exactly the repos
        carrying the undocumented cwd assumption (#110) — usa-wa among them."""
        _half_install(
            repo,
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": ".*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "bash .claude/hooks/skills-submodule-update.sh",
                                }
                            ],
                        }
                    ]
                }
            },
        )
        # A legacy entry is a working hook, so --check must not call it broken.
        chk = _run(repo, INSTALL_REFRESH, "--check")
        assert "SessionStart entry: yes" in chk.stdout

        r = _run(repo, INSTALL_REFRESH)
        assert r.returncode == 0, r.stderr
        assert "upgrading" in r.stdout
        assert _commands(repo) == [
            'bash "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/skills-submodule-update.sh"'
        ]

    def test_a_permissions_mention_is_not_a_registration(self, repo: Path):
        """The basename appears in settings.json for reasons that are not
        registrations — a `permissions.allow` Bash entry is the common one, and
        fewer-permission-prompts writes exactly that shape. A whole-file grep
        called it registered, so --check exited 0 saying `yes` on a repo whose
        SessionStart was empty: the #167 failure reproduced inside the tool
        built to detect it (CR finding 1)."""
        _half_install(
            repo,
            {
                "permissions": {
                    "allow": ["Bash(bash .claude/hooks/skills-submodule-update.sh)"]
                }
            },
        )
        r = _run(repo, INSTALL_REFRESH, "--check")
        assert r.returncode == 3, r.stdout
        assert "SessionStart entry: MISSING" in r.stdout, r.stdout

        # And the repair must leave the permissions entry alone.
        assert _run(repo, INSTALL_REFRESH).returncode == 0
        assert _settings(repo)["permissions"]["allow"] == [
            "Bash(bash .claude/hooks/skills-submodule-update.sh)"
        ]
        assert len(_commands(repo)) == 1

    def test_a_wrong_event_is_not_a_registration(self, repo: Path):
        """Same class: registered under PostToolUse rather than SessionStart is
        a hook that never runs at session start."""
        _half_install(
            repo,
            {
                "hooks": {
                    "PostToolUse": [
                        {
                            "matcher": ".*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "bash .claude/hooks/skills-submodule-update.sh",
                                }
                            ],
                        }
                    ]
                }
            },
        )
        r = _run(repo, INSTALL_REFRESH, "--check")
        assert r.returncode == 3, r.stdout
        assert "SessionStart entry: MISSING" in r.stdout

    def test_a_rerun_is_idempotent(self, repo: Path):
        _run(repo, INSTALL_REFRESH)
        before = (repo / SETTINGS_REL).read_text()
        r = _run(repo, INSTALL_REFRESH)
        assert r.returncode == 0
        assert "unchanged" in r.stdout
        assert (repo / SETTINGS_REL).read_text() == before

    def test_a_dangling_symlink_is_not_reported_as_installed(self, repo: Path):
        """Reporting a dangling link as present sends the operator looking
        anywhere but at the submodule."""
        _half_install(repo)
        (repo / VENDOR_REL / "skills-submodule-update.sh").unlink()
        r = _run(repo, INSTALL_REFRESH, "--check")
        assert r.returncode == 3
        assert "DANGLING" in r.stdout

    def test_uninstall_removes_both_halves(self, repo: Path):
        _half_install(
            repo,
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": ".*",
                            "hooks": [
                                {"type": "command", "command": "bash .skills/doctor.sh"}
                            ],
                        }
                    ]
                }
            },
        )
        _run(repo, INSTALL_REFRESH)
        r = _run(repo, INSTALL_REFRESH, "--uninstall")
        assert r.returncode == 0, r.stderr
        assert not (repo / HOOK_REL).exists()
        assert not (repo / HOOK_REL).is_symlink()
        assert _commands(repo) == ["bash .skills/doctor.sh"]

    def test_uninstall_without_jq_fails_loudly_rather_than_half_finishing(
        self, tmp_path: Path, repo: Path
    ):
        """Routing the registration test through jq made a jq-less --uninstall
        remove the symlink, skip the strip, and exit 0 — leaving an entry that
        runs bash on a path that no longer exists, every session start. A silent
        half-UNINSTALL, the mirror of the half-install this script exists for
        (CR finding 7)."""
        _run(repo, INSTALL_REFRESH)
        env = _clean_env()
        env["PATH"] = str(_path_without_jq(tmp_path))
        r = subprocess.run(
            ["bash", str(INSTALL_REFRESH), "--uninstall"],
            cwd=repo, capture_output=True, text=True, env=env, timeout=30,
        )
        assert r.returncode != 0, (
            "exited 0 having removed only the symlink:\n" + r.stdout + r.stderr
        )
        assert "jq" in r.stderr, r.stderr
        # And it must not have claimed success for the half it did not do.
        assert "removed the SessionStart entry" not in r.stdout
        # Nothing removed at all: a machine that cannot finish must not start,
        # so there is no partial state to reason about.
        assert (repo / HOOK_REL).is_symlink(), r.stdout + r.stderr
        assert len(_commands(repo)) == 1

    def test_uninstall_without_jq_still_works_with_no_settings_file(
        self, tmp_path: Path, repo: Path
    ):
        """jq is only needed to strip a registration. With no settings.json
        there is nothing to strip, so removing the symlink must still work."""
        _half_install(repo)
        assert not (repo / SETTINGS_REL).exists()
        env = _clean_env()
        env["PATH"] = str(_path_without_jq(tmp_path))
        r = subprocess.run(
            ["bash", str(INSTALL_REFRESH), "--uninstall"],
            cwd=repo, capture_output=True, text=True, env=env, timeout=30,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert not (repo / HOOK_REL).is_symlink()

    def test_an_unparseable_settings_file_is_not_reported_as_missing(
        self, repo: Path
    ):
        """MISSING would advise re-running the installer, which dies on the same
        parse error (CR finding 10)."""
        _half_install(repo)
        (repo / SETTINGS_REL).write_text("{not json,,,")
        r = _run(repo, INSTALL_REFRESH, "--check")
        assert r.returncode == 3
        assert "UNREADABLE" in r.stdout, r.stdout
        assert "MISSING —" not in r.stdout

    # A settings.json whose FIRST value parses and whose trailer does not. jq
    # emits the leading value's result before erroring, so this is the input
    # that made hook_command return non-zero WITH output — and the installer
    # claim a registration it had not written (CR findings 11, 12).
    TRAILING_GARBAGE = '{"permissions":{"allow":[]}}\n,,,garbage\n'

    def test_install_against_unparseable_settings_fails_loudly(self, repo: Path):
        (repo / ".claude").mkdir(exist_ok=True)
        (repo / SETTINGS_REL).write_text(self.TRAILING_GARBAGE)
        r = _run(repo, INSTALL_REFRESH)
        assert r.returncode != 0, r.stdout + r.stderr
        assert "registered the SessionStart entry" not in r.stdout, (
            "claimed a registration it did not write:\n" + r.stdout
        )
        assert "nothing was changed" in r.stderr, r.stderr
        assert "skills-submodule-update" not in (repo / SETTINGS_REL).read_text()

    def test_a_failed_rewrite_leaves_no_temp_file(self, repo: Path):
        """`git add -A` would otherwise pick up .claude/settings.json.tmp."""
        (repo / ".claude").mkdir(exist_ok=True)
        (repo / SETTINGS_REL).write_text(self.TRAILING_GARBAGE)
        _run(repo, INSTALL_REFRESH)
        assert not (repo / ".claude" / "settings.json.tmp").exists(), sorted(
            p.name for p in (repo / ".claude").iterdir()
        )

    def test_uninstall_against_unparseable_settings_changes_nothing(
        self, repo: Path
    ):
        """Discovering the file is unreadable after the symlink is gone leaves
        the half-state the need_jq ordering exists to prevent."""
        _run(repo, INSTALL_REFRESH)
        good = (repo / SETTINGS_REL).read_text()
        (repo / SETTINGS_REL).write_text(good + ",,,broken")
        r = _run(repo, INSTALL_REFRESH, "--uninstall")
        assert r.returncode != 0, r.stdout + r.stderr
        assert "removed the SessionStart entry" not in r.stdout, r.stdout
        assert (repo / HOOK_REL).is_symlink(), "symlink was removed anyway"

    def test_it_refuses_without_a_vendored_hook(self, tmp_path: Path):
        bare = tmp_path / "bare"
        bare.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=bare, check=True, env=_clean_env())
        r = _run(bare, INSTALL_REFRESH)
        assert r.returncode == 1
        assert "no vendored" in r.stderr
        assert not (bare / ".claude").exists()

    def test_it_refuses_outside_a_git_repo(self, tmp_path: Path):
        d = tmp_path / "nogit"
        d.mkdir()
        r = _run(d, INSTALL_REFRESH)
        assert r.returncode == 1
        assert "not inside a git repository" in r.stderr

    def test_the_symlink_target_is_relative(self, repo: Path):
        """An absolute target would break for every other checkout of the repo —
        worktrees, CI clones, and anyone else's machine."""
        _run(repo, INSTALL_REFRESH)
        target = os.readlink(repo / HOOK_REL)
        assert not os.path.isabs(target), target
        assert target.startswith("../../")


class TestDoctorReportsAHalfInstall:
    """The doctor is the one code path that still runs in a repo whose refresh
    hook does not — via a reviewing-*/shipping-* preflight, or a SessionStart
    entry of its own, which is exactly what the four #167 repos had."""

    def _doctor(self, repo: Path) -> subprocess.CompletedProcess:
        installed = repo / ".skills" / "doctor.sh"
        installed.parent.mkdir(parents=True, exist_ok=True)
        installed.write_text(DOCTOR.read_text())
        installed.chmod(0o755)
        return _run(repo, installed)

    def test_it_warns_without_changing_its_exit_code(self, repo: Path):
        """Phase 1 preflights invoke the doctor with `|| exit 1`, so a wiring
        gap must not block a review."""
        _half_install(repo)
        r = self._doctor(repo)
        assert r.returncode == 0, r.stderr
        assert "does not register it" in r.stderr
        assert "install-refresh.sh" in r.stderr

    def test_it_is_silent_when_the_hook_is_fully_installed(self, repo: Path):
        _run(repo, INSTALL_REFRESH)
        r = self._doctor(repo)
        assert r.returncode == 0
        assert "does not register it" not in r.stderr

    def test_a_permissions_mention_does_not_silence_it(self, repo: Path):
        """The doctor carried the same whole-file grep, so it stayed quiet on
        exactly the half-installed repos it was added for (CR finding 1)."""
        _half_install(
            repo,
            {
                "permissions": {
                    "allow": ["Bash(bash .claude/hooks/skills-submodule-update.sh)"]
                }
            },
        )
        r = self._doctor(repo)
        assert r.returncode == 0, r.stderr
        assert "does not register it" in r.stderr, r.stderr

    def test_it_is_silent_when_the_hook_was_never_installed(self, repo: Path):
        """A consumer that declined the hook is not broken. Nagging that group
        trains everyone to ignore the warning that matters."""
        r = self._doctor(repo)
        assert r.returncode == 0
        assert "does not register it" not in r.stderr
