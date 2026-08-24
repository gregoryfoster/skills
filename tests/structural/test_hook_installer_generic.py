"""#200 — one hook installer, parameterised, rather than a fourth near-copy.

`install-refresh.sh` was 435 lines, and roughly 400 of them were the generic
two-artifact contract: the jq settings merge, the reader/writer drift fixes,
`--check`/`--uninstall`, and the four rounds of ordering hardening from #178.
Three hooks now want that mechanism — `skills-submodule-update.sh`,
`socraticode-reminder.sh` and `socraticode-health.sh` — and #179's implementing
agent refused to write the second copy on exactly that ground:

    An `install-health.sh` differs in two constants. Writing it means either
    copy-pasting that history — guaranteeing the two drift, which is the failure
    #179 is *about* — or generalizing.

So the mechanism moved to `install-hook.sh`, which takes the constants as
arguments, and `install-refresh.sh` became a wrapper that supplies refresh's.

What this file pins, and why each one is a mechanism rather than a spelling:

- **The generic installer honours the same two-artifact contract**, for a hook
  that is not the refresh hook. If it only worked for the hook it was extracted
  from, the extraction bought nothing.
- **Two hooks coexist in one `.claude/hooks/` and one settings.json.** That is
  the state every `init-socraticode` consumer lands in, and the dedupe-then-
  append merge is the step that could silently evict the sibling — a shared
  marker would make one hook's strip match the other's entry.
- **A hook's markers, not its basename, decide what counts as its
  registration.** The reminder hook's legacy installs name
  `socraticode-reminder` with no marker comment; the canonical form carries
  `# socraticode-prefetch`. Both must be recognised, and a re-run must upgrade
  rather than duplicate — the #110 lesson, inherited rather than re-learned.
- **The copy fallback is a flag, not a second code path in prose.** A consumer
  with no `skills-vendor/` tree has nothing to symlink at; `init-socraticode`
  documented that branch as prose for both its hooks.
- **A copy where a symlink is possible is reported, not called MISSING.** That
  is #179's silent drift, and `.skills/doctor.sh` is blind to it by
  construction (a copy is a valid regular file, not a dangling symlink).
- **`install-refresh.sh` still installs exactly what it installed before.**
  It is named by path in README.md, docs/SKILLS.md, managing-skills/SKILL.md,
  `doctor.sh`'s repair advice and in cohort repos' per-repo issues, so its
  path, its exit codes and the command string it registers are a contract.

`test_refresh_hook_install.py` keeps the end-to-end behaviour suite for the
refresh hook and is unchanged by the refactor — that it still passes against a
wrapper is the load-bearing evidence that the four hardening rounds were
inherited rather than re-litigated.
"""

import json
import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MS_SCRIPTS = REPO_ROOT / "skills" / "managing-skills" / "scripts"
INSTALL_HOOK = MS_SCRIPTS / "install-hook.sh"
INSTALL_REFRESH = MS_SCRIPTS / "install-refresh.sh"
MS_SKILL = REPO_ROOT / "skills" / "managing-skills" / "SKILL.md"
SOC_SCRIPTS = REPO_ROOT / "skills" / "init-socraticode" / "scripts"
POLICY_REF = (
    REPO_ROOT / "skills" / "init-socraticode" / "references"
    / "code-exploration-policy.md"
)

REMINDER = "socraticode-reminder.sh"
HEALTH = "socraticode-health.sh"
REFRESH = "skills-submodule-update.sh"

SETTINGS_REL = ".claude/settings.json"


def _documented_args(step_marker: str, end_marker: str) -> tuple[str, ...]:
    """The flags `init-socraticode` documents for one hook, read out of the
    reference rather than transcribed here.

    `TestManagingSkillsHookCommand` runs `managing-skills`' documented jq
    snippets verbatim for the same reason: a behavioural test that hardcodes
    what the doc *should* say cannot catch the doc saying something else. These
    two argument lists are the entire per-hook surface of #200's refactor, so
    they are the thing most worth binding to the document an agent will run.
    """
    body = POLICY_REF.read_text()
    step = body[body.index(step_marker):body.index(end_marker, body.index(step_marker))]
    block = re.search(r"```bash\n(.*?)```", step, re.DOTALL)
    assert block, f"{step_marker} carries no bash block to run"
    parts = shlex.split(block.group(1).replace("\\\n", " "))
    assert parts[0] == "bash", parts
    assert parts[1].endswith("install-hook.sh"), (
        f"{step_marker} must invoke the shared installer, not a hand-rolled "
        f"loop (#200): {parts[1]}"
    )
    return tuple(parts[2:])


REMINDER_ARGS = _documented_args("**Step A —", "**Step B —")
HEALTH_ARGS = _documented_args("**Step C —", "**It reports;")


def _without(args: tuple[str, ...], flag: str) -> tuple[str, ...]:
    return tuple(a for a in args if a != flag)


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


@pytest.fixture
def bare(tmp_path: Path) -> Path:
    """A consumer that does not vendor via managing-skills: no skills-vendor/
    tree, so there is nothing for a symlink to point at."""
    r = tmp_path / "bare"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True, env=_clean_env())
    return r


def _settings(repo: Path) -> dict:
    return json.loads((repo / SETTINGS_REL).read_text())


def _commands(repo: Path) -> list[str]:
    entries = _settings(repo).get("hooks", {}).get("SessionStart", [])
    return [h.get("command", "") for e in entries for h in e.get("hooks", [])]


def _seed(repo: Path, *commands: str) -> None:
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    (repo / SETTINGS_REL).write_text(json.dumps({
        "hooks": {"SessionStart": [
            {"matcher": ".*", "hooks": [{"type": "command", "command": c}]}
            for c in commands
        ]}
    }))


class TestItInstallsAHookItWasNotExtractedFrom:
    """The point of the generalisation: a second hook, no second script."""

    def test_both_artifacts_land(self, repo: Path):
        r = _run(repo, *REMINDER_ARGS)
        assert r.returncode == 0, r.stderr
        link = repo / ".claude" / "hooks" / REMINDER
        assert link.is_symlink(), r.stdout + r.stderr
        assert link.resolve().is_file()
        assert _commands(repo) == [
            'bash "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/socraticode-reminder.sh"'
            " # socraticode-prefetch"
        ]

    def test_the_symlink_target_is_relative(self, repo: Path):
        """An absolute target would break for every other checkout of the repo —
        worktrees, CI clones, and anyone else's machine."""
        _run(repo, *REMINDER_ARGS)
        target = os.readlink(repo / ".claude" / "hooks" / REMINDER)
        assert not os.path.isabs(target), target
        assert target.startswith("../../skills-vendor/"), target

    def test_a_rerun_is_idempotent(self, repo: Path):
        _run(repo, *REMINDER_ARGS)
        before = (repo / SETTINGS_REL).read_text()
        r = _run(repo, *REMINDER_ARGS)
        assert r.returncode == 0, r.stderr
        assert "unchanged" in r.stdout
        assert (repo / SETTINGS_REL).read_text() == before

    def test_check_reports_both_halves(self, repo: Path):
        r = _run(repo, *REMINDER_ARGS, "--check")
        assert r.returncode == 3, r.stdout
        assert "hook symlink:       MISSING" in r.stdout
        assert "SessionStart entry: MISSING" in r.stdout
        _run(repo, *REMINDER_ARGS)
        r = _run(repo, *REMINDER_ARGS, "--check")
        assert r.returncode == 0, r.stdout
        assert "SessionStart entry: yes" in r.stdout


class TestTwoHooksInOneDirectory:
    """Every `init-socraticode` consumer ends up here, and `managing-skills`
    consumers add a third. The merge is dedupe-then-append, so the strip is the
    step that could evict a sibling — which is why the reference doc insists the
    health hook's marker is distinct from the prefetch hook's."""

    def test_the_second_install_does_not_evict_the_first(self, repo: Path):
        assert _run(repo, *REMINDER_ARGS).returncode == 0
        assert _run(repo, *HEALTH_ARGS).returncode == 0
        cmds = _commands(repo)
        assert len(cmds) == 2, cmds
        assert any(REMINDER in c for c in cmds), cmds
        assert any(HEALTH in c for c in cmds), cmds

    def test_uninstalling_one_leaves_the_other(self, repo: Path):
        _run(repo, *REMINDER_ARGS)
        _run(repo, *HEALTH_ARGS)
        r = _run(repo, *REMINDER_ARGS, "--uninstall")
        assert r.returncode == 0, r.stderr
        assert not (repo / ".claude" / "hooks" / REMINDER).is_symlink()
        assert (repo / ".claude" / "hooks" / HEALTH).is_symlink()
        assert [c for c in _commands(repo) if HEALTH in c], _commands(repo)
        assert not [c for c in _commands(repo) if REMINDER in c]

    def test_one_hooks_check_does_not_answer_for_the_other(self, repo: Path):
        _run(repo, *REMINDER_ARGS)
        r = _run(repo, *HEALTH_ARGS, "--check")
        assert r.returncode == 3, r.stdout
        assert "SessionStart entry: MISSING" in r.stdout

    def test_the_refresh_hook_is_not_confused_for_a_socraticode_one(
        self, repo: Path
    ):
        """All three land in the same array. The refresh hook dedupes on its
        basename and the socraticode hooks on their own markers; a match across
        that boundary would make one install remove another."""
        _run(repo, *REMINDER_ARGS)
        _run(repo, *HEALTH_ARGS)
        assert _run(repo, script=INSTALL_REFRESH).returncode == 0
        assert len(_commands(repo)) == 3, _commands(repo)


class TestMarkersDecideWhatCountsAsARegistration:
    def test_a_legacy_alias_is_upgraded_not_duplicated(self, repo: Path):
        """The reminder hook's pre-#186 installs name the script file with no
        marker comment. Recognised — it does run — and normalised on the next
        install, which is #110's lesson inherited rather than re-learned."""
        _seed(repo, 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/socraticode-reminder.sh"')
        chk = _run(repo, *REMINDER_ARGS, "--check")
        assert "SessionStart entry: yes" in chk.stdout, chk.stdout

        r = _run(repo, *REMINDER_ARGS)
        assert r.returncode == 0, r.stderr
        assert "upgrading" in r.stdout, r.stdout
        assert _commands(repo) == [
            'bash "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/socraticode-reminder.sh"'
            " # socraticode-prefetch"
        ]

    def test_a_duplicate_pair_collapses_to_one(self, repo: Path):
        """A prior verbatim re-run of the prose left two entries. The reference
        doc asks for the extras to go; strip-then-append does it for free."""
        canonical = (
            'bash "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/socraticode-reminder.sh"'
            " # socraticode-prefetch"
        )
        _seed(repo, canonical, 'bash .claude/hooks/socraticode-reminder.sh')
        _run(repo, *REMINDER_ARGS)
        assert len(_commands(repo)) == 1, _commands(repo)

    def test_a_permissions_mention_is_not_a_registration(self, repo: Path):
        """The whole-file grep that made `--check` lie (#178 round 1) must stay
        fixed for every hook, not just the one it was found on."""
        (repo / ".claude").mkdir(parents=True, exist_ok=True)
        (repo / SETTINGS_REL).write_text(json.dumps({
            "permissions": {"allow": [
                "Bash(bash .claude/hooks/socraticode-reminder.sh)"
            ]}
        }))
        r = _run(repo, *REMINDER_ARGS, "--check")
        assert r.returncode == 3, r.stdout
        assert "SessionStart entry: MISSING" in r.stdout, r.stdout

    def test_a_marker_with_shell_or_json_metacharacters_is_refused(
        self, repo: Path
    ):
        """The markers reach a jq program as a constructed JSON array. Refusing
        anything outside the token charset is what keeps that construction from
        needing to be trusted."""
        r = _run(repo, "--hook", REMINDER, "--skill", "init-socraticode",
                 "--marker", 'a","b')
        assert r.returncode == 1, r.stdout
        assert "marker" in r.stderr.lower(), r.stderr


class TestTheCopyFallback:
    """`init-socraticode` documented this branch in prose for both its hooks:
    a consumer that does not vendor via `managing-skills` has no tree to point
    a symlink at."""

    def test_the_reference_asks_for_it(self):
        """Both documented commands pass it. Without the flag the fallback would
        have to come back as a second prose branch, which is what #200 removed."""
        assert "--copy-fallback" in REMINDER_ARGS, REMINDER_ARGS
        assert "--copy-fallback" in HEALTH_ARGS, HEALTH_ARGS

    def test_without_the_flag_it_refuses(self, bare: Path):
        r = _run(bare, *_without(REMINDER_ARGS, "--copy-fallback"))
        assert r.returncode == 1, r.stdout
        assert "no vendored" in r.stderr, r.stderr
        assert not (bare / ".claude").exists()

    def test_with_the_flag_it_copies_from_the_installers_own_tree(
        self, bare: Path
    ):
        r = _run(bare, *REMINDER_ARGS)
        assert r.returncode == 0, r.stdout + r.stderr
        hook = bare / ".claude" / "hooks" / REMINDER
        assert hook.is_file() and not hook.is_symlink()
        assert hook.read_text() == (SOC_SCRIPTS / REMINDER).read_text()
        assert os.access(hook, os.X_OK), "the copy must be executable"
        assert any(REMINDER in c for c in _commands(bare))

    def test_the_copy_says_it_is_frozen(self, bare: Path):
        """A copy freezes at install day and nothing detects it, so the one
        chance to say so is the run that creates it (#179)."""
        r = _run(bare, *REMINDER_ARGS)
        assert "copied" in r.stdout.lower(), r.stdout
        chk = _run(bare, *REMINDER_ARGS, "--check")
        assert chk.returncode == 0, chk.stdout
        assert "COPY" in chk.stdout, chk.stdout

    def test_a_copy_where_a_symlink_is_possible_is_reported(self, repo: Path):
        """#179's actual failure: a copy in a repo that vendors the source.
        `.skills/doctor.sh` cannot see it — a copy is a valid regular file, not
        a dangling symlink — so this check is the only thing that can."""
        hooks = repo / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / REMINDER).write_text((SOC_SCRIPTS / REMINDER).read_text())
        r = _run(repo, *REMINDER_ARGS, "--check")
        assert r.returncode == 3, r.stdout
        assert "COPY" in r.stdout, r.stdout
        assert "MISSING" not in r.stdout.split("SessionStart")[0], r.stdout

    def test_a_copy_is_replaced_by_the_symlink_on_a_re_run(self, repo: Path):
        """`ln -sfn` over a regular file, which is what upgrades a legacy
        hand-typed hook in place without a separate step."""
        hooks = repo / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / REMINDER).write_text("# stale\n")
        assert _run(repo, *REMINDER_ARGS).returncode == 0
        assert (hooks / REMINDER).is_symlink()

    def test_the_copy_does_not_write_through_an_existing_symlink(
        self, bare: Path, tmp_path: Path
    ):
        """`cp` follows a symlink and writes its target. With a dangling-or-not
        link already in `.claude/hooks/`, that would edit the vendored source
        instead of installing over the link."""
        hooks = bare / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        victim = tmp_path / "victim.sh"
        victim.write_text("# not the hook\n")
        (hooks / REMINDER).symlink_to(victim)
        assert _run(bare, *REMINDER_ARGS).returncode == 0
        assert victim.read_text() == "# not the hook\n", "wrote through the link"
        assert not (hooks / REMINDER).is_symlink()


class TestArgumentHandling:
    def test_help_exits_zero_without_a_hook(self):
        r = subprocess.run(
            ["bash", str(INSTALL_HOOK), "--help"],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert r.returncode == 0, r.stderr
        assert "--hook" in r.stdout

    def test_a_missing_hook_name_is_a_usage_error(self, repo: Path):
        r = _run(repo, "--skill", "init-socraticode")
        assert r.returncode == 1
        assert "--hook" in r.stderr, r.stderr

    def test_a_flag_without_its_value_is_a_usage_error(self, repo: Path):
        r = _run(repo, "--hook")
        assert r.returncode == 1
        assert "value" in r.stderr.lower(), r.stderr

    def test_a_hook_name_with_a_path_is_refused(self, repo: Path):
        """The name is joined into `.claude/hooks/` and into a vendor glob; a
        path there would install somewhere nobody looks."""
        r = _run(repo, "--hook", "../evil.sh", "--skill", "init-socraticode")
        assert r.returncode == 1, r.stdout
        assert not (repo / ".claude").exists()

    def test_an_unknown_argument_is_refused(self, repo: Path):
        """`doctor.sh` resolves the installer glob itself rather than printing
        it, precisely because extra matches arrive as arguments."""
        r = _run(repo, *REMINDER_ARGS, "--wat")
        assert r.returncode == 1
        assert "unknown argument" in r.stderr


CI_GATE_START = "**Where the vendor content is absent"
CI_GATE_END = "> **Duplicate-config trap.**"


def _ci_gate_window() -> str:
    """The section of the reference that documents checking an install where
    the vendor content is not checked out (#227, #228).

    Resolved per call rather than at import, so a document missing the section
    fails the tests that are about it instead of collapsing the whole module's
    collection."""
    body = POLICY_REF.read_text()
    assert CI_GATE_START in body, (
        f"the reference carries no {CI_GATE_START!r} section — the CI recipe "
        "#227 asks for has nowhere to live"
    )
    window = body[body.index(CI_GATE_START):]
    assert CI_GATE_END in window, (
        f"{CI_GATE_START!r} is not followed by {CI_GATE_END!r}; the section "
        "moved and these tests are reading the wrong span"
    )
    return window[:window.index(CI_GATE_END)]


def _ci_gate_args() -> tuple[str, ...]:
    return _documented_args(CI_GATE_START, CI_GATE_END)


def _uncheckout_the_vendor(repo: Path) -> None:
    """The submodule-less state `actions/checkout` and `git worktree add` both
    produce: the vendor directory is there and empty, the symlinks into it are
    not."""
    tree = repo / "skills-vendor" / "acme-skills"
    for path in sorted(tree.rglob("*"), reverse=True):
        path.unlink() if path.is_file() or path.is_symlink() else path.rmdir()
    tree.rmdir()


class TestCheckSeparatesShapeFromResolution:
    """#227 — `--check` could not gate CI, because a *correct* symlink install
    reports DANGLING in the checkout `init-project-fastapi` ships.

    Two decisions in this repo are individually sound and jointly produce it:
    `github-ci.md` omits `skills-vendor/` submodules from CI checkout on purpose
    ("nothing in lint/test needs them"), and `init-socraticode` installs its
    hooks as symlinks *into* `skills-vendor/` on purpose (#179, #186). So in CI
    every vendor symlink dangles and `is_linked` — which requires resolution,
    not merely shape — calls a correct install broken.

    The inversion is the part worth more than the exit code. Where the vendor
    content is absent, a **dangling symlink is the healthy state** and a **copy
    is the only variant that resolves**. Any check that verifies the install by
    resolving it passes on the copy this library argues against and fails on the
    symlink it prescribes. `--allow-unresolved` is that split made explicit:
    shape is checkable everywhere and carries the copy-vs-symlink guarantee;
    resolution is only checkable where the content exists.
    """

    def _installed_then_uncheckedout(self, repo: Path) -> None:
        assert _run(repo, *REMINDER_ARGS).returncode == 0
        _uncheckout_the_vendor(repo)

    def test_without_the_flag_a_correct_install_still_reports_dangling(
        self, repo: Path
    ):
        """Unchanged by default. On a workstation the vendor content SHOULD be
        there, and a link that does not resolve is a repair signal."""
        self._installed_then_uncheckedout(repo)
        r = _run(repo, *REMINDER_ARGS, "--check")
        assert r.returncode == 3, r.stdout
        assert "DANGLING" in r.stdout, r.stdout

    def test_the_report_says_the_shape_is_correct(self, repo: Path):
        """The two verdicts are printed separately even without the flag —
        an operator who cannot tell which half failed cannot act on either."""
        self._installed_then_uncheckedout(repo)
        r = _run(repo, *REMINDER_ARGS, "--check")
        assert "Shape is correct" in r.stdout, r.stdout
        assert "--allow-unresolved" in r.stdout, r.stdout

    def test_the_flag_accepts_an_unresolved_vendor_symlink(self, repo: Path):
        """The CI gate. Both halves of the contract are still asserted; only
        the half that cannot be answered here is skipped."""
        self._installed_then_uncheckedout(repo)
        r = _run(repo, *REMINDER_ARGS, "--check", "--allow-unresolved")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_the_flag_does_not_accept_an_absolute_target(self, repo: Path):
        """An absolute symlink resolves on the machine that made it and nowhere
        else. No submodule checkout fixes that, so the flag must not cover it."""
        _run(repo, *REMINDER_ARGS)
        link = repo / ".claude" / "hooks" / REMINDER
        link.unlink()
        link.symlink_to("/nowhere/acme/socraticode-reminder.sh")
        _uncheckout_the_vendor(repo)
        r = _run(repo, *REMINDER_ARGS, "--check", "--allow-unresolved")
        assert r.returncode == 3, r.stdout
        assert "skills-vendor" in r.stdout, r.stdout

    def test_the_flag_does_not_accept_a_target_outside_the_vendor(
        self, repo: Path
    ):
        _run(repo, *REMINDER_ARGS)
        link = repo / ".claude" / "hooks" / REMINDER
        link.unlink()
        link.symlink_to(f"../../vendor-elsewhere/{REMINDER}")
        _uncheckout_the_vendor(repo)
        r = _run(repo, *REMINDER_ARGS, "--check", "--allow-unresolved")
        assert r.returncode == 3, r.stdout

    def test_the_flag_does_not_excuse_a_link_that_misses_a_present_source(
        self, repo: Path
    ):
        """The vendor IS checked out and the link still does not resolve, so
        "the content is not here" is not the explanation. Excusing this would
        make the flag mean "never mind the symlink", which is not the split."""
        _run(repo, *REMINDER_ARGS)
        link = repo / ".claude" / "hooks" / REMINDER
        link.unlink()
        link.symlink_to(
            f"../../skills-vendor/other-skills/skills/init-socraticode/"
            f"scripts/{REMINDER}"
        )
        r = _run(repo, *REMINDER_ARGS, "--check", "--allow-unresolved")
        assert r.returncode == 3, r.stdout

    def test_the_flag_reports_a_copy_rather_than_accepting_it(self, repo: Path):
        """The inversion, caught. With the vendor uncheckedout a copy is the
        one variant that RESOLVES, so every resolution-based check passes on
        exactly the install #179 argues against. The flag says vendor content
        may be absent, which is precisely why absence can no longer be read as
        "this repo vendors nothing to link at"."""
        hooks = repo / ".claude" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / REMINDER).write_text((SOC_SCRIPTS / REMINDER).read_text())
        _uncheckout_the_vendor(repo)
        r = _run(repo, *REMINDER_ARGS, "--check", "--allow-unresolved")
        assert r.returncode == 3, r.stdout
        assert "COPY" in r.stdout, r.stdout

    def test_the_flag_still_gates_the_registration(self, repo: Path):
        """It relaxes resolution and nothing else. A hook file with no
        SessionStart entry never runs, in CI as anywhere."""
        _run(repo, *REMINDER_ARGS)
        (repo / SETTINGS_REL).write_text("{}")
        _uncheckout_the_vendor(repo)
        r = _run(repo, *REMINDER_ARGS, "--check", "--allow-unresolved")
        assert r.returncode == 3, r.stdout
        assert "SessionStart entry: MISSING" in r.stdout, r.stdout

    def test_the_flag_still_gates_a_missing_hook_file(self, repo: Path):
        r = _run(repo, *REMINDER_ARGS, "--check", "--allow-unresolved")
        assert r.returncode == 3, r.stdout
        assert "hook symlink:       MISSING" in r.stdout, r.stdout

    def test_the_flag_is_refused_outside_check(self, repo: Path):
        """It changes what `--check` tolerates and nothing about an install.
        Accepting it silently on an install run would imply it did."""
        r = _run(repo, *REMINDER_ARGS, "--allow-unresolved")
        assert r.returncode == 1, r.stdout
        assert "--allow-unresolved requires --check" in r.stderr, r.stderr
        assert not (repo / ".claude" / "hooks" / REMINDER).exists()


class TestCheckReportsHowManyRegistrations:
    """#222's third suggestion, and the state its strip could leave behind.

    `--check` reported `yes` for one entry and for two, so a repo carrying a
    stranded duplicate read as healthy — and a hook registered twice runs twice
    per session. The reader already scans every index, so the count costs
    nothing; only the report was throwing it away."""

    def test_one_entry_is_reported_as_one(self, repo: Path):
        _run(repo, *REMINDER_ARGS)
        r = _run(repo, *REMINDER_ARGS, "--check")
        assert r.returncode == 0, r.stdout
        assert "SessionStart entry: yes (1 entry" in r.stdout, r.stdout

    def test_two_entries_are_not_reported_as_yes(self, repo: Path):
        canonical = (
            'bash "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/'
            'socraticode-reminder.sh" # socraticode-prefetch'
        )
        _seed(repo, canonical, canonical)
        r = _run(repo, *REMINDER_ARGS, "--check")
        assert r.returncode == 3, r.stdout
        assert "SessionStart entry: 2 entries" in r.stdout, r.stdout
        assert "SessionStart entry: yes" not in r.stdout, r.stdout

    def test_the_duplicate_report_names_the_repair(self, repo: Path):
        canonical = (
            'bash "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/'
            'socraticode-reminder.sh" # socraticode-prefetch'
        )
        _seed(repo, canonical, canonical)
        r = _run(repo, *REMINDER_ARGS, "--check")
        assert "install-hook.sh --hook socraticode-reminder.sh" in r.stdout, (
            r.stdout
        )


class TestTheReferenceDocumentsTheCiRecipe:
    """#227's second half. archiver rediscovered the shape-vs-resolution split
    by hand and paid for it once; the point of writing it down is that the next
    consumer does not.

    Run verbatim, like Step A and Step C, because a doc that prescribes a CI
    gate has to be a gate that passes — and the whole failure being documented
    is a check reporting a correct install as broken."""

    def test_the_documented_gate_asks_for_both_flags(self):
        args = _ci_gate_args()
        assert "--check" in args, args
        assert "--allow-unresolved" in args, args

    def test_the_documented_gate_passes_on_a_submodule_less_checkout(
        self, repo: Path
    ):
        """The exact state `actions/checkout` produces, against an install this
        installer made minutes earlier."""
        args = _ci_gate_args()
        install = _without(_without(args, "--check"), "--allow-unresolved")
        assert _run(repo, *install).returncode == 0
        _uncheckout_the_vendor(repo)
        r = _run(repo, *args)
        assert r.returncode == 0, r.stdout + r.stderr

    def test_it_states_the_inversion_rather_than_only_the_flag(self):
        """A flag an operator can copy is not the same as knowing why their own
        `hook.resolve().is_file()` assertion passes on the install this library
        argues against."""
        window = _ci_gate_window().lower()
        assert "copy" in window, window
        assert "shape" in window, window
        assert "resolv" in window, window

    def test_it_warns_off_the_wrong_repair(self):
        """The tempting fix is `submodules: recursive` in CI, which buys a
        passing check by undoing the checkout decision that made the skip
        worth having."""
        assert "submodules: recursive" in _ci_gate_window()


class TestTheFirstSessionCostIsWrittenDown:
    """#228 — a vendor-symlinked hook does not merely fail a check in a
    submodule-less checkout, it fails to RUN, with rc=127.

    Prose only, deliberately. The alternative on the table was a self-guarding
    registered command (`[ -f "$0" ] || exit 0`), which converts the error into
    silence — and for `socraticode-health.sh`, a hook designed to be silent when
    clean, silence is exactly the state #179 identifies as dangerous. A hook
    that is silent when healthy cannot afford a second way of being silent.

    So what is owed is the sentence, in both skills that prescribe the layout:
    the first session in a fresh clone or worktree errors, `.skills/doctor.sh`
    repairs it, and the repair lands for the NEXT session — because Claude Code
    runs an event's matching hooks **in parallel**, so no position in the
    `SessionStart` array puts the doctor ahead of what it heals.

    That last clause is the load-bearing one and it is a fact about Claude Code,
    not about this repo: "When an event fires, Claude Code runs all matching
    hooks in parallel" — https://code.claude.com/docs/en/hooks-guide, which also
    says the completion order is non-deterministic. Neither of these two skills
    currently claims ordering helps; these tests keep it that way, since the
    tempting repair for an operator who reads only the rc=127 half is to shuffle
    the array.
    """

    ORDERING_MYTHS = (
        "first in the SessionStart array",
        "first in the array",
        "place the doctor first",
        "order the doctor",
        "run the doctor first",
        "sequentially in array order",
    )

    def test_the_reference_states_the_first_session_failure(self):
        window = _ci_gate_window()
        assert "127" in window, window
        assert ".skills/doctor.sh" in window, window

    def test_the_reference_states_that_hooks_run_in_parallel(self):
        window = _ci_gate_window().lower()
        assert "parallel" in window, window

    def test_managing_skills_states_it_too(self):
        """Its refresh hook is the third vendor symlink in the same
        `.claude/hooks/`, and it fails identically. A note in one skill's
        reference does not reach the consumer who installed the other."""
        body = MS_SKILL.read_text()
        assert "127" in body, "managing-skills/SKILL.md does not mention rc=127"
        assert "parallel" in body.lower(), (
            "managing-skills/SKILL.md does not say hooks run in parallel, so a "
            "reader is still free to think reordering the array would help"
        )

    @pytest.mark.parametrize(
        "doc", [POLICY_REF, MS_SKILL], ids=lambda p: p.name
    )
    def test_neither_skill_implies_that_ordering_helps(self, doc: Path):
        body = doc.read_text().lower()
        found = [m for m in self.ORDERING_MYTHS if m.lower() in body]
        assert not found, (
            f"{doc.name} implies the SessionStart array's order affects when a "
            f"hook runs; Claude Code runs matching hooks in parallel: {found}"
        )


class TestInstallRefreshIsStillItself:
    """Named by path in README.md, docs/SKILLS.md, managing-skills/SKILL.md,
    doctor.sh's repair advice, and in every per-repo cohort issue filed for
    #167. The wrapper keeps that path working; these pin what it must produce.

    The full behavioural suite is `test_refresh_hook_install.py`, unchanged by
    the refactor — that it still passes is the evidence the hardening rounds
    were inherited rather than re-implemented."""

    def test_it_registers_the_same_command_as_before(self, repo: Path):
        r = _run(repo, script=INSTALL_REFRESH)
        assert r.returncode == 0, r.stderr
        assert _commands(repo) == [
            'bash "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/skills-submodule-update.sh"'
        ], "the registered command is a contract with every installed consumer"

    def test_it_still_speaks_in_its_own_name(self, repo: Path):
        """Its messages are quoted in per-repo repair issues, and `doctor.sh`
        tells operators to run `install-refresh.sh` by name."""
        r = _run(repo, script=INSTALL_REFRESH)
        assert "install-refresh:" in r.stdout, r.stdout

    def test_it_delegates_rather_than_carrying_a_copy(self):
        """The whole point of #200. A wrapper that grew its own jq merge back
        would be the fourth near-copy this issue exists to prevent."""
        body = INSTALL_REFRESH.read_text()
        assert "install-hook.sh" in body
        assert "jq " not in body, (
            "install-refresh.sh is carrying settings-merge logic again; the "
            "merge lives in install-hook.sh so one set of hardening rounds "
            "serves every hook (#200, #178)"
        )
        assert len(body.splitlines()) < 80, (
            "install-refresh.sh is meant to be a thin wrapper over "
            f"install-hook.sh; it is {len(body.splitlines())} lines"
        )
