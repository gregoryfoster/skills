"""Behavioral tests for the half-healed checkout (#185, following #176).

#176 fixed the *hook*: `git submodule update` without `--init` skips a
submodule that is absent from `.git/config` and **exits 0**. Two other places
carried the same silent skip.

1. `managing-skills/SKILL.md` documents the manual bulk update. A human
   following it got "success" and an unmoved pointer.
2. `doctor.sh` used "every symlink resolves" as a proxy for "the submodules
   are healthy". Those two conditions come apart in exactly the state #176
   was found in — vendored content present on disk, `.git/config` carrying
   no `submodule.*` entries — so the symlink probe passed, the doctor
   short-circuited before its `git submodule update --init --recursive`, and
   the repo stayed half-healed indefinitely.

Verified by execution before the fix was written: on a superproject whose
submodule section has been removed from `.git/config`, `git submodule update
--remote --merge` exits 0 with *no output at all* and moves nothing;
`--init --remote --merge` registers the path and merges.

Exercised end-to-end against throwaway git repos — the property that matters
is a runtime one (does the doctor actually reach its heal in this state).

Coverage:
- half-healed checkout, symlinks all resolve  → doctor inits, exit 0
- --check-only in that state                  → reports, changes nothing
- heal never refreshes (#100's pin filter)    → gitlink, not upstream head
- uninit submodule outside skills-vendor/     → out of scope, silent no-op
- healthy checkout                            → still the silent fast path
- SKILL.md teaches `--init --remote --merge`
- --help documents the second trigger
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "skills" / "managing-skills" / "scripts"
DOCTOR = SCRIPTS / "doctor.sh"
MS_SKILL = REPO_ROOT / "skills" / "managing-skills" / "SKILL.md"

SUBMODULE_PATH = "skills-vendor/acme-skills"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — same precaution as
    test_doctor_ssh_remediation. Pre-commit and other tooling can set
    GIT_INDEX_FILE etc., which would leak into the git calls inside the
    script and confuse them.

    Then one GIT_* var is put back deliberately. Since git 2.38
    (CVE-2022-39253) a submodule whose URL is a local path is refused with
    "transport 'file' not allowed", which is every submodule in these tests.
    It has to travel by environment rather than `git -c`: the doctor runs its
    own `git submodule update --init --recursive` and cannot be handed a flag,
    and a repo-local `protocol.file.allow` does not reach the clone, which is
    a separate process operating on a repo that does not exist yet.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "protocol.file.allow"
    env["GIT_CONFIG_VALUE_0"] = "always"
    return env


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Always `cwd=repo`, never a bare `git` against an ambient directory.

    A linked worktree shares `.git/config` with its main checkout, so a
    repo-creating git command without an explicit target reaches out of the
    worktree and writes the orchestrator's config (#189).
    """
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=60,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "doctor-test@example.invalid")
    _git(path, "config", "user.name", "doctor test")
    return path


def _upstream(tmp_path: Path) -> Path:
    """A vendor skills repo with one skill, at commit v1."""
    up = _init_repo(tmp_path / "upstream")
    (up / "skills" / "demo").mkdir(parents=True)
    (up / "skills" / "demo" / "SKILL.md").write_text("v1\n")
    _git(up, "add", "-A")
    _git(up, "commit", "-qm", "v1")
    return up


def _consumer(tmp_path: Path, upstream: Path) -> Path:
    """A consumer wired the managing-skills way: vendor submodule plus a
    skills/<name> symlink pointing through it."""
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "submodule", "add", "-q", str(upstream), SUBMODULE_PATH)
    _git(repo, "commit", "-qm", "add vendor submodule")
    (repo / "skills").mkdir(exist_ok=True)
    (repo / "skills" / "demo").symlink_to(f"../{SUBMODULE_PATH}/skills/demo")
    return repo


def _half_heal(repo: Path, path: str = SUBMODULE_PATH) -> None:
    """Reproduce #176's state: vendored content present on disk, nothing
    registered under `submodule.*` in `.git/config`."""
    _git(repo, "config", "--remove-section", f"submodule.{path}")


def _submodule_status(repo: Path) -> str:
    return _git(repo, "submodule", "status").stdout


def _uninitialized(repo: Path) -> list[str]:
    """Paths `git submodule status` still prefixes with '-'."""
    return [
        line[1:].split(" ", 1)[1].split(" ")[0]
        for line in _submodule_status(repo).splitlines()
        if line.startswith("-")
    ]


def _doctor(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(DOCTOR), "--no-preflight", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=120,
    )


@pytest.fixture
def half_healed(tmp_path: Path) -> Path:
    repo = _consumer(tmp_path, _upstream(tmp_path))
    _half_heal(repo)
    return repo


class TestGitReallySkipsAnUnregisteredSubmodule:
    """The premise both fixes rest on, asserted rather than assumed.

    Neither half of #185 is worth anything if git had changed this behaviour;
    the issue asserted it without running it.
    """

    def test_update_without_init_exits_zero_and_moves_nothing(self, half_healed):
        assert _uninitialized(half_healed) == [SUBMODULE_PATH]
        before = (half_healed / SUBMODULE_PATH / "skills" / "demo" / "SKILL.md").read_text()

        r = subprocess.run(
            ["git", "submodule", "update", "--remote", "--merge"],
            cwd=str(half_healed), capture_output=True, text=True,
            env=_clean_env(), timeout=60,
        )

        assert r.returncode == 0, r.stdout + r.stderr
        assert _uninitialized(half_healed) == [SUBMODULE_PATH], "git registered it"
        after = (half_healed / SUBMODULE_PATH / "skills" / "demo" / "SKILL.md").read_text()
        assert after == before

    def test_adding_init_registers_the_path(self, half_healed):
        r = subprocess.run(
            ["git", "submodule", "update", "--init", "--remote", "--merge"],
            cwd=str(half_healed), capture_output=True, text=True,
            env=_clean_env(), timeout=60,
        )

        assert r.returncode == 0, r.stdout + r.stderr
        assert _uninitialized(half_healed) == []


class TestSkillTeachesTheInitForm:
    """#185 part 1 — the instruction a human follows by hand, with no hook to
    blame when it reports success and moves nothing."""

    def test_bulk_update_snippet_passes_init(self):
        offenders = [
            f"{MS_SKILL.name}:{i}: {line.strip()}"
            for i, line in enumerate(MS_SKILL.read_text().splitlines(), 1)
            if "submodule update --remote" in line and "--init" not in line
        ]
        assert not offenders, (
            "a documented bulk update without --init silently skips every "
            "submodule missing from .git/config and exits 0:\n"
            + "\n".join(offenders)
        )


class TestDoctorHealsTheHalfHealedCheckout:
    """#185 part 2 — the doctor's own precondition.

    "Every symlink resolves" was standing in for "the submodules are healthy",
    and the half-healed checkout is precisely where the two disagree.
    """

    def test_symlinks_resolve_so_only_the_submodule_probe_can_fire(self, half_healed):
        """Guards the fixture, not the doctor: if the symlink dangled here,
        every test below would pass through the pre-existing heal path and
        prove nothing."""
        assert (half_healed / "skills" / "demo").is_symlink()
        assert (half_healed / "skills" / "demo").resolve().exists()

    def test_doctor_initializes_the_unregistered_submodule(self, half_healed):
        r = _doctor(half_healed)

        assert r.returncode == 0, r.stdout + r.stderr
        assert _uninitialized(half_healed) == [], (
            "doctor exited 0 leaving the repo half-healed:\n" + r.stderr
        )

    def test_doctor_says_what_it_is_repairing(self, half_healed):
        r = _doctor(half_healed)

        assert "submodule" in r.stderr.lower(), r.stderr
        assert "dangling symlinks detected" not in r.stderr, (
            "reported a symlink failure that did not happen:\n" + r.stderr
        )

    def test_check_only_reports_without_initializing(self, half_healed):
        r = _doctor(half_healed, "--check-only")

        assert SUBMODULE_PATH in r.stderr, r.stdout + r.stderr
        assert _uninitialized(half_healed) == [SUBMODULE_PATH], (
            "--check-only is contractually non-mutating and it initialized"
        )

    def test_an_uninitialized_submodule_alone_is_not_an_exit_code(self, half_healed):
        """Reported, never fatal — in either mode.

        Verified by execution: with `submodule.<name>.update = none`,
        `git submodule update --init --recursive` registers the path, prints
        "Skipping submodule", exits 0, and leaves `git submodule status`
        showing '-' permanently. This repo's own refresh hook names
        `update = none` as what operators reach for to hold a vendored skill
        still, so failing on the residue would block every Phase 1 preflight
        in such a consumer forever — over a checkout whose symlinks all
        resolve and whose skills are all reachable.
        """
        assert _doctor(half_healed, "--check-only").returncode == 0
        assert _doctor(half_healed).returncode == 0

    def test_heal_initializes_but_never_refreshes(self, tmp_path: Path):
        """#100's pin filter. Initializing a pinned submodule is fine —
        `--init` checks out the recorded gitlink, which is what a pin holds.
        Refreshing it is not, so the heal must never grow a `--remote`.
        """
        up = _upstream(tmp_path)
        repo = _consumer(tmp_path, up)
        _half_heal(repo)
        (up / "skills" / "demo" / "SKILL.md").write_text("v2\n")
        _git(up, "add", "-A")
        _git(up, "commit", "-qm", "v2")

        r = _doctor(repo)

        assert r.returncode == 0, r.stdout + r.stderr
        assert _uninitialized(repo) == []
        content = (repo / SUBMODULE_PATH / "skills" / "demo" / "SKILL.md").read_text()
        assert content == "v1\n", (
            "the doctor advanced a pointer instead of only initializing it"
        )
        # Scoped to the submodule: the fixture's skills/demo symlink is
        # deliberately uncommitted, so a whole-repo status is never clean.
        dirty = _git(repo, "status", "--porcelain", "--", SUBMODULE_PATH).stdout
        assert dirty.strip() == "", f"the doctor left a staged pointer move: {dirty}"

    def test_healthy_checkout_stays_on_the_silent_fast_path(self, tmp_path: Path):
        repo = _consumer(tmp_path, _upstream(tmp_path))

        r = _doctor(repo)

        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stderr.strip() == "", r.stderr

    def test_uninit_submodule_outside_skills_vendor_is_out_of_scope(self, tmp_path):
        """The doctor exists for the vendored-skill chain. Widening the probe
        to every submodule would make a preflight clone whatever heavy,
        deliberately-uninitialized submodule an unrelated repo carries."""
        repo = _consumer(tmp_path, _upstream(tmp_path))
        other = _init_repo(tmp_path / "other")
        (other / "README.md").write_text("other\n")
        _git(other, "add", "-A")
        _git(other, "commit", "-qm", "init")
        _git(repo, "submodule", "add", "-q", str(other), "vendor/other")
        _git(repo, "commit", "-qm", "add unrelated submodule")
        _half_heal(repo, "vendor/other")

        r = _doctor(repo)

        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stderr.strip() == "", r.stderr
        assert _uninitialized(repo) == ["vendor/other"], (
            "the doctor initialized a submodule outside skills-vendor/"
        )

    def test_no_submodules_at_all_is_still_a_silent_noop(self, tmp_path: Path):
        repo = _init_repo(tmp_path / "repo")
        (repo / "skills").mkdir()

        r = _doctor(repo)

        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stderr.strip() == "", r.stderr

    def test_help_documents_the_second_trigger(self):
        help_text = subprocess.run(
            ["bash", str(DOCTOR), "--help"],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        ).stdout

        assert "skills-vendor/" in help_text, help_text
        assert "uninitialized" in help_text.lower(), help_text
