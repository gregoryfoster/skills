"""#224 — the doctor checks the registration of EVERY installed hook, and each
skill declares its own repair line.

`check_refresh_registration()` knew the right thing — a hook symlink without a
`SessionStart` registration is a real defect, silent by construction, because
the missing half is the half that would have run (#167). It was hardcoded to
`skills-submodule-update.sh`. The two `init-socraticode` hooks that land in the
same `.claude/hooks/` of the same consumer got no equivalent check, so a repo
with three hooks installed and zero registered had exactly one of the three
reported.

`socraticode-health.sh` is the worst hook to lose that way: it is **silent when
clean by design**, so "installed, unregistered, never runs" and "installed,
registered, nothing to report" produce byte-identical observable behaviour. The
repo that most needs the check is the one that cannot tell it stopped. Paired
with #222 — which deletes a registration silently — the two are a complete
silent-failure loop.

The repair line is the part that resists generalizing, because each hook needs
`install-hook.sh` with its own `--hook`/`--skill`/`--marker` constants. A table
inside `doctor.sh` was rejected: it needs a `doctor.sh` edit every time a skill
adds a hook. Instead each skill ships a one-line `<hook>.install` manifest
beside the script, holding that hook's `install-hook.sh` arguments — the
constants next to the hook they belong to, where #200 already moved them.

What this file pins, and why each one is a mechanism rather than a spelling:

- **Every unregistered hook is named, not just the first.** The defect was a
  loop that did not exist; a test that installs one hook proves nothing about
  the one that was skipped.
- **The repair line is the manifest, verbatim.** Read from the shipped file
  rather than transcribed here, so a manifest edit cannot drift from what the
  doctor prints without this failing.
- **The printed repair line actually repairs it.** Executed, then the doctor is
  re-run. A repair line that is merely plausible is how an operator ends up
  pasting a command that exits 1 and concluding the warning was noise.
- **The manifests agree with the install commands the skills document.** They
  are a transcription of `install-hook.sh`'s argument list, and nothing else in
  the tree would notice them going stale — a renamed flag conflicts with no
  file, because the manifests are new files and the rename is elsewhere.
- **Who is NOT warned about.** A dangling symlink (the symlink scan owns it), a
  project-authored regular file, and a manifest-less vendored hook registered
  under some other event. The existing check earned its `[ -L ]` guard for this
  reason: nagging the group that is fine trains everyone to ignore the group
  that is not.
- **The exit code stays advisory.** Phase 1 preflights invoke the doctor with
  `|| exit 1`. Whether a wiring gap SHOULD gate a review is a separate call
  from whether it is detected; this pins today's answer so a change to it is
  deliberate.

Keep this list current — it is the file's index.
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
MANAGING_SCRIPTS = SKILLS_DIR / "managing-skills" / "scripts"
SOCRATICODE_SCRIPTS = SKILLS_DIR / "init-socraticode" / "scripts"
DOCTOR = MANAGING_SCRIPTS / "doctor.sh"
INSTALL_HOOK = MANAGING_SCRIPTS / "install-hook.sh"
INSTALL_REFRESH = MANAGING_SCRIPTS / "install-refresh.sh"
POLICY_REF = (
    SKILLS_DIR / "init-socraticode" / "references" / "code-exploration-policy.md"
)

VENDOR_REL = "skills-vendor/acme-skills/skills"

# The three hooks that land in one consumer's .claude/hooks/, each with the
# skill that vendors it and the file whose install command its manifest
# transcribes. That last column is the whole point of the parametrization: the
# manifest is a copy of an argument list that lives somewhere else, and this is
# the only thing in the tree that would notice the two coming apart.
HOOKS = [
    ("skills-submodule-update.sh", "managing-skills", INSTALL_REFRESH),
    ("socraticode-reminder.sh", "init-socraticode", POLICY_REF),
    ("socraticode-health.sh", "init-socraticode", POLICY_REF),
]

# Flags that belong to a WRAPPER rather than to the hook. --label renames the
# voice the installer speaks in and --note appends prose after a successful
# install; neither changes which artifacts land, and a manifest is pasted at
# install-hook.sh directly, which is the name it would then have to speak in.
COSMETIC_FLAGS = {"--label", "--note"}

# Flags that consume the following token. Everything else is a bare switch.
VALUE_FLAGS = {"--hook", "--skill", "--marker", "--label", "--note"}


def _skill_scripts(skill: str) -> Path:
    return SKILLS_DIR / skill / "scripts"


def _manifest_path(hook: str, skill: str) -> Path:
    return _skill_scripts(skill) / (hook.removesuffix(".sh") + ".install")


def _manifest_args(hook: str, skill: str) -> list[str]:
    """The manifest's argument line, as the doctor reads it: the first line
    that is neither blank nor a comment."""
    path = _manifest_path(hook, skill)
    assert path.is_file(), (
        f"{path.relative_to(REPO_ROOT)} does not exist, so .skills/doctor.sh "
        "has no repair line to print for a hook it can now see is "
        "unregistered."
    )
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return shlex.split(stripped)
    raise AssertionError(f"{path} carries no argument line, only comments")


def _invocation_tokens(text: str, hook: str) -> list[str]:
    """The install-hook.sh invocation for `hook`, as a flat token list.

    Backslash-continuations are joined first so a command spread over five
    lines is one line. Split on whitespace rather than with shlex: the only
    multi-word value is install-refresh.sh's --note, whose quoted body runs
    past a real newline and would leave shlex with an unbalanced quote. The
    caller truncates at --note anyway.
    """
    for line in text.replace("\\\n", " ").splitlines():
        if "install-hook.sh" in line and f"--hook {hook}" in line:
            tokens = line.split()
            return tokens[tokens.index("--hook") :]
    raise AssertionError(f"no install-hook.sh invocation for {hook} found")


def _functional_pairs(tokens: list[str]) -> set[str]:
    """Flag-and-value pairs, dropping the cosmetic ones, as comparable strings.

    Truncates at the first cosmetic flag rather than skipping it: --note's
    value is prose that whitespace-splitting has already shredded, and it is
    always last in the invocations this compares.
    """
    pairs: set[str] = set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if not token.startswith("--"):
            i += 1
            continue
        if token in COSMETIC_FLAGS:
            break
        if token in VALUE_FLAGS and i + 1 < len(tokens):
            pairs.add(f"{token} {tokens[i + 1]}")
            i += 2
        else:
            pairs.add(token)
            i += 1
    return pairs


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — a linked worktree shares .git/config
    with its main checkout, so a fixture-creating git command that inherits
    them reaches out of the fixture and writes the wrong repo (#189)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=str(repo), check=True,
        capture_output=True, text=True, env=_clean_env(), timeout=60,
    )


def _doctor(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(DOCTOR), "--no-preflight"],
        cwd=str(repo), capture_output=True, text=True,
        env=_clean_env(), timeout=120,
    )


def _vendor(repo: Path, skill: str) -> Path:
    path = repo / VENDOR_REL / skill / "scripts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _link(repo: Path, hook: str, skill: str) -> Path:
    link = repo / ".claude" / "hooks" / hook
    link.symlink_to(f"../../{VENDOR_REL}/{skill}/scripts/{hook}")
    return link


@pytest.fixture
def consumer(tmp_path: Path) -> Path:
    """A consumer carrying all three hooks as resolving symlinks and no
    settings.json at all — the strongest form of unregistered, and the exact
    state the issue's demonstration was taken from."""
    repo = tmp_path / "consumer"
    (repo / ".claude" / "hooks").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")

    shutil.copy2(INSTALL_HOOK, _vendor(repo, "managing-skills") / INSTALL_HOOK.name)
    for hook, skill, _ in HOOKS:
        vendor = _vendor(repo, skill)
        shutil.copy2(_skill_scripts(skill) / hook, vendor / hook)
        manifest = _manifest_path(hook, skill)
        if manifest.is_file():
            shutil.copy2(manifest, vendor / manifest.name)
        _link(repo, hook, skill)
    return repo


def _warned_hooks(stderr: str) -> set[str]:
    """The hooks the doctor named as installed-but-unregistered."""
    return {
        line.split(".claude/hooks/", 1)[1].split(" ", 1)[0]
        for line in stderr.splitlines()
        if ".claude/hooks/" in line and "does not register it" in line
    }


class TestEveryInstalledHookIsChecked:
    """The bug was a loop that did not exist. One of three hooks reported is
    indistinguishable from three of three when you only ever install one."""

    def test_all_three_unregistered_hooks_are_named(self, consumer: Path):
        result = _doctor(consumer)
        assert _warned_hooks(result.stderr) == {h for h, _, _ in HOOKS}, result.stderr

    def test_the_health_hook_is_named(self, consumer: Path):
        """Called out separately because it is the one the issue is about.
        socraticode-health.sh is silent when clean by design, so an
        unregistered copy is observationally identical to a healthy one — no
        other signal in the system can distinguish them."""
        result = _doctor(consumer)
        assert "socraticode-health.sh" in _warned_hooks(result.stderr), result.stderr

    def test_a_registered_hook_is_not_named(self, consumer: Path):
        """Per-hook granularity. A check that warned about all three whenever
        any one was missing would be as useless as one that warned about one."""
        installed = subprocess.run(
            ["bash", str(consumer / VENDOR_REL / "managing-skills" / "scripts"
                         / "install-hook.sh"),
             *_manifest_args("socraticode-health.sh", "init-socraticode")],
            cwd=str(consumer), capture_output=True, text=True,
            env=_clean_env(), timeout=60,
        )
        assert installed.returncode == 0, installed.stderr
        result = _doctor(consumer)
        assert _warned_hooks(result.stderr) == {
            "skills-submodule-update.sh",
            "socraticode-reminder.sh",
        }, result.stderr

    def test_a_permissions_entry_is_not_a_registration(self, consumer: Path):
        """The whole-file grep that CR finding 1 removed from the old check
        must not come back through the new loop. `permissions.allow` naming a
        hook is what the fewer-permission-prompts skill writes, and it runs
        nothing."""
        (consumer / ".claude" / "settings.json").write_text(json.dumps({
            "permissions": {
                "allow": ["Bash(bash .claude/hooks/socraticode-health.sh)"]
            }
        }))
        result = _doctor(consumer)
        assert "socraticode-health.sh" in _warned_hooks(result.stderr), result.stderr

    def test_the_exit_code_stays_advisory(self, consumer: Path):
        """Three hooks unregistered and the doctor still exits 0. Phase 1
        preflights gate on this with `|| exit 1`, and #224 scoped itself to
        detection; making a wiring gap fail a review is a separate call with a
        separate blast radius across every consumer's review gate."""
        assert _doctor(consumer).returncode == 0


class TestTheRepairLineComesFromTheManifest:
    """The reason a manifest exists rather than a table in doctor.sh."""

    def _repair_lines(self, stderr: str) -> list[str]:
        return [
            line.split("doctor:", 1)[1].strip()
            for line in stderr.splitlines()
            if line.strip().startswith("doctor:") and "install-hook.sh" in line
        ]

    def test_each_hook_gets_its_own_manifest_arguments(self, consumer: Path):
        result = _doctor(consumer)
        lines = self._repair_lines(result.stderr)
        for hook, skill, _ in HOOKS:
            args = " ".join(_manifest_args(hook, skill))
            assert any(line.endswith(args) for line in lines), (
                f"no repair line ending in the {hook} manifest's arguments "
                f"({args}); the doctor printed:\n{result.stderr}"
            )

    def test_the_repair_line_names_the_vendored_installer(self, consumer: Path):
        """Resolved, not printed as a glob. `bash skills-vendor/*/…` passes
        every extra match as an argument to the first, so the
        paste-under-pressure path would fail on any repo vendoring a second
        skills repo — the reason the old refresh line resolved its own."""
        result = _doctor(consumer)
        for line in self._repair_lines(result.stderr):
            assert "*" not in line, line
            installer = shlex.split(line)[1]
            assert (consumer / installer).is_file(), f"{installer}\n{result.stderr}"

    def test_the_printed_repair_line_actually_repairs_it(self, consumer: Path):
        """Executed, not merely read. A repair line that exits 1 teaches the
        operator that the warning above it was noise."""
        for line in self._repair_lines(_doctor(consumer).stderr):
            repair = subprocess.run(
                shlex.split(line), cwd=str(consumer), capture_output=True,
                text=True, env=_clean_env(), timeout=60,
            )
            assert repair.returncode == 0, f"{line}\n{repair.stderr}"
        result = _doctor(consumer)
        assert _warned_hooks(result.stderr) == set(), result.stderr

    def test_a_vendored_hook_with_no_manifest_still_gets_reported(
        self, consumer: Path
    ):
        """A skill that ships no manifest must not fall out of the check
        entirely — that is the failure mode #224 is about, reintroduced one
        level up. It loses the exact command, not the warning."""
        (consumer / VENDOR_REL / "init-socraticode" / "scripts"
         / "socraticode-health.install").unlink()
        result = _doctor(consumer)
        assert "socraticode-health.sh" in _warned_hooks(result.stderr), result.stderr
        assert not any(
            "socraticode-health.sh" in line
            for line in self._repair_lines(result.stderr)
        ), result.stderr


class TestWhoIsNotWarnedAbout:
    """The old check's `[ -L ]` guard was reasoned, not incidental: nagging a
    consumer that is fine is how the warning that matters gets skimmed past."""

    def test_a_dangling_hook_is_left_to_the_symlink_scan(self, consumer: Path):
        """Two diagnoses for one file is worse than one. The dangling scan
        already names it, with the repair that actually applies."""
        (consumer / VENDOR_REL / "init-socraticode" / "scripts"
         / "socraticode-health.sh").unlink()
        result = _doctor(consumer)
        assert "socraticode-health.sh" not in _warned_hooks(result.stderr), result.stderr

    def test_a_project_authored_hook_is_not_nagged(self, consumer: Path):
        """A regular file in .claude/hooks/ was written by the project, not
        installed by a skill, and nothing here knows what should register it."""
        (consumer / ".claude" / "hooks" / "format-on-write.sh").write_text(
            "#!/usr/bin/env bash\nexit 0\n"
        )
        result = _doctor(consumer)
        assert "format-on-write.sh" not in _warned_hooks(result.stderr), result.stderr

    def test_a_manifest_less_hook_registered_elsewhere_is_not_nagged(
        self, consumer: Path
    ):
        """Hooks in .claude/hooks/ fire on other events — this script's own
        header describes one running on every Edit|Write|MultiEdit. Without a
        manifest nothing declares which event a hook wants, so only 'registered
        under no event at all' is a defensible complaint."""
        (consumer / VENDOR_REL / "init-socraticode" / "scripts"
         / "socraticode-health.install").unlink()
        (consumer / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {
                "PostToolUse": [{
                    "matcher": "Edit",
                    "hooks": [{
                        "type": "command",
                        "command": "bash .claude/hooks/socraticode-health.sh",
                    }],
                }]
            }
        }))
        result = _doctor(consumer)
        assert "socraticode-health.sh" not in _warned_hooks(result.stderr), result.stderr

    def test_a_manifested_hook_registered_elsewhere_is_nagged(
        self, consumer: Path
    ):
        """The other side of that line. A manifest says install-hook.sh
        installed this, and install-hook.sh writes SessionStart and nothing
        else — so an entry under another event is not the registration this
        hook needs, and reporting it as one would be the #167 lie."""
        (consumer / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {
                "PostToolUse": [{
                    "matcher": "Edit",
                    "hooks": [{
                        "type": "command",
                        "command": "bash .claude/hooks/socraticode-health.sh",
                    }],
                }]
            }
        }))
        result = _doctor(consumer)
        assert "socraticode-health.sh" in _warned_hooks(result.stderr), result.stderr


class TestTheManifestsMatchTheDocumentedInstalls:
    """A manifest is a transcription of an argument list that lives elsewhere,
    and a flag renamed in install-hook.sh conflicts with no file here — the
    manifests are new, the rename is somewhere else. This is the check that
    turns that silent edge into a failing test."""

    @pytest.mark.parametrize(
        ("hook", "skill", "source"), HOOKS, ids=[h for h, _, _ in HOOKS]
    )
    def test_the_manifest_matches_the_documented_command(
        self, hook: str, skill: str, source: Path
    ):
        documented = _functional_pairs(_invocation_tokens(source.read_text(), hook))
        declared = _functional_pairs(_manifest_args(hook, skill))
        assert declared == documented, (
            f"{_manifest_path(hook, skill).relative_to(REPO_ROOT)} and "
            f"{source.relative_to(REPO_ROOT)} disagree about how {hook} is "
            "installed. The manifest is what .skills/doctor.sh prints as the "
            "repair, so the two drifting means the doctor hands operators a "
            "command that installs something other than what the skill "
            "documents."
        )

    @pytest.mark.parametrize(
        ("hook", "skill"), [(h, s) for h, s, _ in HOOKS],
        ids=[h for h, _, _ in HOOKS],
    )
    def test_every_manifest_flag_is_one_install_hook_accepts(
        self, hook: str, skill: str
    ):
        """The rename half of the same edge. install-hook.sh parses its flags
        in a `case`, so an accepted flag is one with a `--flag)` arm."""
        accepted = INSTALL_HOOK.read_text()
        for token in _manifest_args(hook, skill):
            if token.startswith("--"):
                assert f"{token})" in accepted, (
                    f"{_manifest_path(hook, skill).relative_to(REPO_ROOT)} "
                    f"passes {token}, which install-hook.sh does not parse — "
                    "it would exit 1 on 'unknown argument' the moment an "
                    "operator pasted the doctor's repair line."
                )

    @pytest.mark.parametrize(
        ("hook", "skill"), [(h, s) for h, s, _ in HOOKS],
        ids=[h for h, _, _ in HOOKS],
    )
    def test_the_manifest_sits_beside_the_hook_it_installs(
        self, hook: str, skill: str
    ):
        """The manifest is found by name from the hook symlink's own target,
        so its location is load-bearing rather than conventional."""
        manifest = _manifest_path(hook, skill)
        assert (manifest.parent / hook).is_file(), (
            f"{manifest.relative_to(REPO_ROOT)} has no {hook} beside it"
        )
        args = _manifest_args(hook, skill)
        assert args[args.index("--hook") + 1] == hook, (
            f"{manifest.relative_to(REPO_ROOT)} installs a different hook than "
            "the one it is named for"
        )
