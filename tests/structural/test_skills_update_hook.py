"""Behavioral tests for the auto-refresh hook's commit scope (issue #86).

The hook installs `.skills/doctor.sh` on every session but historically only
staged `skills-vendor/`, so the file it had just written stayed untracked
forever. Four of twelve audited consumers had been reinstalling a doctor for
weeks that had never once been committed — leaving their fresh worktrees and
CI clones with no doctor and a silently short-circuiting Phase 1 preflight.

Run end-to-end against throwaway repos with a shimmed `git submodule`, because
what matters is runtime behaviour: which paths get staged, whether an untracked
file is noticed at all, and whether operator config gets swept in alongside.

Coverage:
- untracked .skills/doctor.sh                → committed (the #86 case)
- modified tracked .skills/doctor.sh         → committed
- operator config (.skills/plans_dir)        → never staged
- unrelated dirty work                       → never absorbed
- nothing changed                            → no empty commit
- no .skills/doctor.sh at all                → unaffected, still exits 0
- commit message names what actually changed
- non-main branch                            → installs but does not commit
- `git status` fails                         → logged with git's own stderr,
                                               commit skipped, scratch cleaned
- `git commit` fails                         → index unstaged, install kept
- ...and the unstage fails (a held
  index.lock)                                → still-staged paths named on
                                               stderr, with the command (#311)
- ...and the reset exits 0 but unstages
  nothing                                    → still reported: the index is
                                               read back, not the exit status
- ...and the index cannot be read back       → reported as unchecked

Pushing what it commits (issue #293) gets its own fixture, `remote_repo`,
because the `repo` fixture has no upstream at all — a configuration the
reconcile step returns on immediately, so none of the push behaviour is
reachable there. These run against a real bare remote over the `file`
transport, since what matters is whether a push was actually accepted:
- a commit the hook makes                    → pushed, checkout not ahead
- a commit stranded by an earlier run        → pushed at the next session
- push fails                                 → commit rolled back
- push fails with unrelated dirty work       → that work survives (NOT --hard)
- push fails                                 → refreshed content stays on disk
- push fails                                 → reported on stderr, not only $LOG
- push fails                                 → no second attempt in the same run
- push fails and its unstage fails           → reported after the rollback (#311)
- an operator's unpushed commit              → never rolled back
- an operator's unpushed commit              → never published, nothing committed
- a mix of theirs and ours                   → reported, all of it left alone
- diverged main                              → rollback stays on our own history
- no upstream configured                     → silent no-op
- work staged before the session             → not absorbed, not published
- a gitignored .skills/                      → submodule bump still commits
- a log the hook cannot read                 → refuses, and commits nothing
- a merge inside @{u}..HEAD                  → refuses, and commits nothing

Submodule pins (issue #100) get their own fixture, `pinned_repo`, because the
property under test is which pointers actually move — a shimmed `git submodule`
cannot show that. Those tests build real superproject/submodule pairs over the
`file` transport and let the hook run the real update:
- no pin file                                → every submodule refreshes
- pinned submodule                           → pointer does not move
- unpinned sibling                           → still refreshes
- pin survives the auto-commit step
- honoured pin is logged
- pin naming an unknown submodule            → reported, refresh refused
- malformed pin line                         → reported, refresh refused
- every submodule pinned                     → no update runs at all
- recorded pointer past the pin              → drift reported
- unresolvable pin target                    → reported, hold still applied
- comments/blank lines only                  → treated as no pins
- SKILLS_PIN_FILE overrides the file location
- the pin file itself is never staged

Uninitialized submodules (issue #176) reuse `pinned_repo` for the same reason:
whether a pointer moved is the only honest evidence. `git submodule update`
skips an unregistered submodule and exits 0, so the hook reported success
forever and never advanced anything:
- deinitialized submodules                   → initialized and refreshed
- a pin over a deinitialized submodule       → still held, sibling still moves
- skills-vendor/ with no registered
  submodules at all                          → reported, not a bare header
- a path still uninitialized after the
  refresh                                    → reported to log and stderr

Keep this list current — it is the file's index, and it undercounted for two
rounds while tests were added around it.
"""

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
HOOK = SCRIPTS / "skills-submodule-update.sh"
DOCTOR = SCRIPTS / "doctor.sh"
INSTALLER = SCRIPTS / "install-doctor.sh"

VENDOR_REL = "skills-vendor/acme-skills/skills/managing-skills/scripts"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — pre-commit and other tooling set
    GIT_INDEX_FILE etc., which would leak into the hook's git calls."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    # The hook commits; give it an identity that doesn't depend on the
    # developer's global gitconfig being present.
    env.update(
        {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
    )
    return env


def _git(
    repo: Path,
    *args: str,
    check: bool = True,
    env_extra: dict | None = None,
) -> subprocess.CompletedProcess:
    env = _clean_env()
    env.update(env_extra or {})
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A consumer repo on main with a vendored skills tree, one commit deep.

    `git submodule` is shimmed to a silent success: the hook's real submodule
    update needs a network remote, and none of these tests are about that.
    Every other git invocation reaches real git.
    """
    repo = tmp_path / "repo"
    (repo / VENDOR_REL).mkdir(parents=True)
    shutil.copy2(DOCTOR, repo / VENDOR_REL / "doctor.sh")
    shutil.copy2(INSTALLER, repo / VENDOR_REL / "install-doctor.sh")
    (repo / VENDOR_REL / "install-doctor.sh").chmod(0o755)
    (repo / "README.md").write_text("consumer\n")

    _git(repo.parent, "init", "-b", "main", "-q", str(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")

    _shim_dir(repo).mkdir()
    _write_git_shim(repo)
    return repo


def _shim_dir(repo: Path) -> Path:
    """Shim location derived from the repo path rather than carried on it —
    Path instances reject attribute assignment."""
    return repo.parent / "bin"


def _write_git_shim(
    repo: Path, extra_arms: str = "", submodule_body: str = "exit 0"
) -> None:
    """Install a fake `git` on the hook's PATH.

    `submodule` is always intercepted with a silent success — the hook's real
    submodule update needs a network remote and no test here is about that.
    `submodule_body` replaces that body for the tests that are about what git
    reports back from a submodule call (#176). `extra_arms` injects further
    subcommand interceptions (each a complete `if` statement) ahead of the
    delegation to real git, so a test can make a specific subcommand fail
    without restating the base shim.
    """
    real_git = shutil.which("git") or "/usr/bin/git"
    shim = _shim_dir(repo) / "git"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$1" = "submodule" ]; then\n{submodule_body}\nfi\n'
        f"{extra_arms}"
        f'exec {real_git} "$@"\n'
    )
    shim.chmod(0o755)


def _run_hook(repo: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = _clean_env()
    env["PATH"] = f"{_shim_dir(repo)}:{env.get('PATH', '/usr/bin:/bin')}"
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", str(HOOK)], cwd=repo, capture_output=True, text=True, env=env
    )


def _head_message(repo: Path) -> str:
    return _git(repo, "log", "-1", "--pretty=%s").stdout.strip()


def _commit_count(repo: Path) -> int:
    return int(_git(repo, "rev-list", "--count", "HEAD").stdout.strip())


def _tracked(repo: Path, path: str) -> bool:
    return _git(repo, "ls-files", "--error-unmatch", path, check=False).returncode == 0


class TestDoctorGetsCommitted:
    def test_untracked_doctor_is_committed(self, repo):
        """The #86 case: the hook installs the doctor, so it exists but has
        never been tracked. A `git diff HEAD` guard would not even see it."""
        assert not (repo / ".skills").exists()

        result = _run_hook(repo)

        assert result.returncode == 0, result.stderr
        assert _tracked(repo, ".skills/doctor.sh"), (
            "the hook installed the doctor but left it untracked — this is "
            "exactly the state that left 4 of 12 consumers with no doctor in CI"
        )
        assert (repo / ".skills" / "doctor.sh").read_text() == DOCTOR.read_text()

    def test_stale_tracked_doctor_is_committed(self, repo):
        skills = repo / ".skills"
        skills.mkdir()
        stale = DOCTOR.read_text().replace('VERSION="', 'VERSION="stale-', 1)
        (skills / "doctor.sh").write_text(stale)
        (skills / "doctor.sh").chmod(0o755)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "add stale doctor")
        before = _commit_count(repo)

        result = _run_hook(repo)

        assert result.returncode == 0, result.stderr
        assert _commit_count(repo) == before + 1
        assert (skills / "doctor.sh").read_text() == DOCTOR.read_text()

    def test_working_tree_is_clean_afterwards(self, repo):
        """The end-to-end property: nothing the hook touched is left dangling."""
        _run_hook(repo)

        status = _git(repo, "status", "--porcelain").stdout
        assert status == "", f"hook left the tree dirty: {status!r}"


class TestCommitScopeIsNarrow:
    """Matching diff scope to add scope is the invariant that keeps unrelated
    work out of an automated commit. Widening to `.skills/` would break it."""

    def test_operator_config_is_never_staged(self, repo):
        skills = repo / ".skills"
        skills.mkdir()
        (skills / "plans_dir").write_text("docs/notes\n")
        (skills / "worktree_root").write_text("/tmp/wt\n")

        result = _run_hook(repo)

        assert result.returncode == 0, result.stderr
        assert _tracked(repo, ".skills/doctor.sh")
        for cfg in ("plans_dir", "worktree_root"):
            assert not _tracked(repo, f".skills/{cfg}"), (
                f".skills/{cfg} is operator config — the hook must never "
                "commit it. Staging `.skills/` wholesale would."
            )
            assert (skills / cfg).exists(), "and it must be left in place"

    def test_unrelated_dirty_work_is_not_absorbed(self, repo):
        (repo / "README.md").write_text("local edit in flight\n")
        (repo / "scratch.py").write_text("untracked\n")

        _run_hook(repo)

        # Asserted via status, not via `git show HEAD` — the latter passes
        # vacuously whenever the hook makes no commit at all, which is the
        # state the pre-#86 hook was in for this fixture.
        status = _git(repo, "status", "--porcelain").stdout
        assert " M README.md" in status, (
            "the in-flight edit must still be uncommitted after the hook runs"
        )
        assert "?? scratch.py" in status, "the untracked file must stay untracked"
        assert (repo / "README.md").read_text() == "local edit in flight\n"

    def test_no_empty_commit_when_nothing_changed(self, repo):
        _run_hook(repo)
        settled = _commit_count(repo)

        # The lock MUST be cleared before the second run. The first run stamps
        # it with today's UTC date, so a second run would exit at the lock
        # check and never reach the commit block — making this assertion pass
        # no matter what the commit logic does.
        lock = repo / ".git" / "skills-update.lock"
        assert lock.exists(), "first run should have stamped the once-daily lock"
        lock.unlink()
        log_before = (repo / ".git" / "skills-update.log").read_text()

        _run_hook(repo)

        log_after = (repo / ".git" / "skills-update.log").read_text()
        assert log_after != log_before, (
            "second run must actually reach the update/commit block — if the "
            "log is unchanged it exited early and this test proves nothing"
        )
        assert _commit_count(repo) == settled, "no empty commit"
        assert "commit skills update:" not in log_after[len(log_before) :], (
            "the commit block should not even have been entered on a clean tree"
        )

    def test_consumer_without_a_doctor_is_unaffected(self, repo):
        """A consumer whose vendor tree ships no installer must not error —
        `git add` on a path that isn't there would."""
        (repo / VENDOR_REL / "install-doctor.sh").unlink()
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "drop installer")
        before = _commit_count(repo)

        result = _run_hook(repo)

        assert result.returncode == 0, result.stderr
        assert not (repo / ".skills" / "doctor.sh").exists()
        assert _commit_count(repo) == before


class TestStatusFailureIsDiagnosable:
    """The status check drives the commit branch. A git that fails for an
    unexpected reason must not read as "nothing to commit" — that would
    silently stop this hook committing forever with no trace anywhere."""

    def test_failure_is_logged_and_skipped(self, repo):
        _write_git_shim(
            repo,
            extra_arms=(
                'if [ "$1" = "status" ]; then '
                'echo "fatal: simulated index corruption" >&2; exit 128; fi\n'
            ),
        )
        before = _commit_count(repo)

        result = _run_hook(repo)

        assert result.returncode == 0, "the hook must never block a session"
        log = (repo / ".git" / "skills-update.log").read_text()
        assert "git status failed (rc=128)" in log
        assert "simulated index corruption" in log, (
            "git's own stderr must reach the log — the rc alone doesn't say why"
        )
        assert _commit_count(repo) == before, "must skip the commit, not guess"
        assert not (repo / ".git" / "skills-status.err").exists(), (
            "the stderr scratch file must be cleaned up"
        )


class TestFailedCommitLeavesNoResidue:
    """`git add` may stage a previously untracked .skills/doctor.sh. Leaving a
    file the operator never touched sitting in their index is worse than
    leaving the commit undone — the next run retries cleanly either way."""

    def test_failed_commit_unstages(self, repo):
        _write_git_shim(
            repo,
            extra_arms=(
                'if [ "$1" = "commit" ]; then '
                'echo "shim: commit refused" >&2; exit 1; fi\n'
            ),
        )

        result = _run_hook(repo)

        assert result.returncode == 0, "the hook must never block a session"
        staged = _git(repo, "diff", "--cached", "--name-only").stdout
        assert staged == "", f"index left dirty after a failed commit: {staged!r}"
        assert (repo / ".skills" / "doctor.sh").exists(), (
            "the working-tree install must survive — only the staging is undone"
        )
        assert "still staged" not in result.stderr, (
            f"an unstage that worked must not be reported as one that did not:\n"
            f"{result.stderr}"
        )


class TestAFailedUnstageIsReported:
    """#311 — the unstage is read back from the index, never assumed.

    CannObserv/power-map was found with both of the hook's paths staged beneath
    its own "commit failed — unstaging" line. The reset's exit status was
    discarded and its stderr went only to $LOG, so a reset that failed looked,
    from anywhere a session reads, exactly like one that worked. The cause is
    still unknown, which is why these pin the outcome rather than a cause: a
    reset refused by a lock, a reset that exits 0 having changed nothing, and an
    index that cannot be read back at all.
    """

    COMMIT_REFUSED = (
        'if [ "$1" = "commit" ]; then echo "shim: commit refused" >&2; exit 1; fi\n'
    )

    def test_a_reset_refused_by_a_held_lock_is_reported(self, repo):
        """The issue's leading hypothesis, with real git: another process's
        index.lock outlives the failed commit, so the reset exits 128."""
        _write_git_shim(
            repo,
            extra_arms=(
                'if [ "$1" = "commit" ]; then : > .git/index.lock; '
                'echo "shim: commit refused" >&2; exit 1; fi\n'
            ),
        )

        result = _run_hook(repo)

        assert result.returncode == 0, "the hook must never block a session"
        assert _git(repo, "diff", "--cached", "--name-only").stdout.strip() == (
            ".skills/doctor.sh"
        ), "the fixture should reproduce the observed state: the path still staged"
        assert ".skills/doctor.sh still staged after a failed commit" in (
            result.stderr
        ), f"the stranded path was not reported on stderr:\n{result.stderr}"
        assert "git reset -q -- .skills/doctor.sh" in result.stderr, (
            f"the report should carry the command that clears it:\n{result.stderr}"
        )
        log = _log_text(repo)
        assert "index.lock" in log, f"git's own reason must reach the log:\n{log}"

    def test_the_index_is_read_back_not_the_reset_status(self, repo):
        """A reset that exits 0 having unstaged nothing. A check on the exit
        status passes here; only reading the index catches it. The issue's
        other hypothesis, something re-staging AFTER the reset, is past any
        check the hook can make, and _unstage says so."""
        _write_git_shim(
            repo,
            extra_arms=self.COMMIT_REFUSED
            + 'if [ "$1" = "reset" ] && [ "$3" = "--" ]; then exit 0; fi\n',
        )

        result = _run_hook(repo)

        assert result.returncode == 0
        assert ".skills/doctor.sh still staged after a failed commit" in (
            result.stderr
        ), f"a reset that did nothing passed as one that worked:\n{result.stderr}"

    def test_an_index_that_cannot_be_read_back_is_reported(self, repo):
        """A failed read is not an empty one. Taken as "nothing staged", it
        would be the silence this check exists to end."""
        _write_git_shim(
            repo,
            extra_arms=self.COMMIT_REFUSED
            + 'if [ "$1" = "reset" ]; then : > .git/reset-ran; fi\n'
            'if [ "$1" = "diff" ] && [ -e .git/reset-ran ]; then '
            'echo "fatal: simulated index read failure" >&2; exit 128; fi\n',
        )

        result = _run_hook(repo)

        assert result.returncode == 0
        assert "could not check the index after a failed commit" in result.stderr, (
            result.stderr
        )
        assert "still staged after" not in result.stderr, result.stderr
        assert "simulated index read failure" in _log_text(repo)


class TestCommitMessageNamesWhatChanged:
    def test_doctor_only_refresh(self, repo):
        """Nothing moved in skills-vendor/ (submodule is shimmed), so the
        message must not claim a submodule update."""
        _run_hook(repo)

        assert _head_message(repo) == "chore: refresh .skills/doctor.sh", (
            f"got {_head_message(repo)!r}"
        )

    def test_both_changed(self, repo):
        """Simulate a pointer bump landing alongside the doctor install by
        dirtying a tracked file under skills-vendor/."""
        (repo / VENDOR_REL / "doctor.sh").write_text(
            DOCTOR.read_text() + "\n# vendor moved\n"
        )

        _run_hook(repo)

        assert _head_message(repo) == (
            "chore: update skills submodules and refresh .skills/doctor.sh"
        ), f"got {_head_message(repo)!r}"

    def test_submodule_only(self, repo):
        skills = repo / ".skills"
        skills.mkdir()
        shutil.copy2(DOCTOR, skills / "doctor.sh")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "doctor already current")
        (repo / VENDOR_REL / "install-doctor.sh").write_text(
            INSTALLER.read_text() + "\n# vendor moved\n"
        )

        _run_hook(repo)

        assert _head_message(repo) == "chore: update skills submodules", (
            f"got {_head_message(repo)!r}"
        )


class TestBranchGating:
    def test_feature_branch_installs_but_does_not_commit(self, repo):
        """The install is the working-tree repair and runs everywhere; the
        commit is main-only, as it was before #86."""
        _git(repo, "checkout", "-qb", "feature/x")
        before = _commit_count(repo)

        result = _run_hook(repo)

        assert result.returncode == 0, result.stderr
        assert (repo / ".skills" / "doctor.sh").exists(), (
            "the working-tree install must still happen off main"
        )
        assert _commit_count(repo) == before, "no auto-commit off main"
        assert not _tracked(repo, ".skills/doctor.sh")


# --------------------------------------------------------------------------
# Submodule pins (#100)
#
# Everything above shims `git submodule` away, because those tests are about
# staging scope. A pin is about which pointers move, which only real
# submodules can demonstrate — so the fixtures below build throwaway
# superproject/submodule pairs and let the hook run the real update.
# --------------------------------------------------------------------------

# `git submodule` refuses the `file` transport by default since git 2.38
# (CVE-2022-39253). Local throwaway upstreams need it re-allowed — for the
# fixture's own git calls and for the hook's, which clones and fetches here.
FILE_TRANSPORT = {"GIT_ALLOW_PROTOCOL": "file"}

VENDOR_A = "skills-vendor/acme-skills"
VENDOR_B = "skills-vendor/obra-superpowers"


def _gitlink(repo: Path, path: str) -> str:
    """The commit the superproject records for a submodule, from HEAD.

    This — not the submodule's checked-out HEAD — is what an auto-commit
    would move and what a hold has to keep still."""
    return _git(repo, "rev-parse", f"HEAD:{path}").stdout.strip()


def _write_pin(repo: Path, text: str, name: str = "skills-pin") -> Path:
    skills = repo / ".skills"
    skills.mkdir(exist_ok=True)
    pin = skills / name
    pin.write_text(text)
    return pin


def _log_text(repo: Path) -> str:
    log = repo / ".git" / "skills-update.log"
    return log.read_text() if log.exists() else ""


@pytest.fixture
def pinned_repo(tmp_path: Path):
    """A consumer repo with two real skills-vendor/ submodules, each recorded
    one commit behind its upstream, so a refresh visibly moves a pointer.

    No pin file is written — each test writes the one it needs.
    """
    from types import SimpleNamespace

    upstreams = {}
    for name, rel in (("acme", VENDOR_A), ("obra", VENDOR_B)):
        up = tmp_path / f"up-{name}"
        _git(tmp_path, "init", "-q", "-b", "main", str(up))
        (up / "f.txt").write_text(f"{name} one\n")
        _git(up, "add", "-A")
        _git(up, "commit", "-qm", f"{name} c1")
        upstreams[rel] = up

    repo = tmp_path / "repo"
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    (repo / "README.md").write_text("consumer\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    for rel, up in upstreams.items():
        _git(repo, "submodule", "add", "-q", str(up), rel, env_extra=FILE_TRANSPORT)
    _git(repo, "commit", "-qm", "vendor submodules")

    before = {rel: _gitlink(repo, rel) for rel in upstreams}

    after = {}
    for rel, up in upstreams.items():
        (up / "f.txt").write_text("two\n")
        _git(up, "commit", "-qam", "c2")
        after[rel] = _git(up, "rev-parse", "HEAD").stdout.strip()

    assert before[VENDOR_A] != after[VENDOR_A]
    assert before[VENDOR_A] != before[VENDOR_B], (
        "the two submodules must be distinguishable by sha or the assertions "
        "below prove nothing"
    )

    # Empty: the pin tests want real git, but _run_hook always prepends it.
    _shim_dir(repo).mkdir()
    return SimpleNamespace(path=repo, before=before, after=after, upstreams=upstreams)


def _run_pin_hook(fixture) -> subprocess.CompletedProcess:
    result = _run_hook(fixture.path, env_extra=FILE_TRANSPORT)
    assert result.returncode == 0, (
        f"the hook must never block a session: {result.stderr}"
    )
    return result


class TestPinlessBehaviourIsUnchanged:
    def test_every_submodule_refreshes_without_a_pin_file(self, pinned_repo):
        """The baseline the pin has to preserve for unpinned submodules."""
        _run_pin_hook(pinned_repo)

        for rel in (VENDOR_A, VENDOR_B):
            assert _gitlink(pinned_repo.path, rel) == pinned_repo.after[rel], (
                f"{rel} should have refreshed to its remote HEAD"
            )

    def test_comments_and_blank_lines_are_not_pins(self, pinned_repo):
        """A pin file with no entries must not accidentally hold anything —
        the empty pathspec that would produce is the dangerous shape."""
        _write_pin(pinned_repo.path, "# nothing held right now\n\n   \n")

        _run_pin_hook(pinned_repo)

        for rel in (VENDOR_A, VENDOR_B):
            assert _gitlink(pinned_repo.path, rel) == pinned_repo.after[rel]


class TestPinHoldsOneSubmodule:
    def test_pinned_pointer_does_not_move(self, pinned_repo):
        _write_pin(pinned_repo.path, f"{VENDOR_A} {pinned_repo.before[VENDOR_A]}\n")

        _run_pin_hook(pinned_repo)

        assert _gitlink(pinned_repo.path, VENDOR_A) == pinned_repo.before[VENDOR_A], (
            "the held submodule's recorded pointer moved — the hold ended "
            "silently, which is exactly issue #100"
        )

    def test_unpinned_sibling_still_refreshes(self, pinned_repo):
        """The whole point: per-submodule granularity, not an all-or-nothing
        pause of the hook."""
        _write_pin(pinned_repo.path, f"{VENDOR_A} {pinned_repo.before[VENDOR_A]}\n")

        _run_pin_hook(pinned_repo)

        assert _gitlink(pinned_repo.path, VENDOR_B) == pinned_repo.after[VENDOR_B], (
            "holding one submodule must not stop the others refreshing"
        )

    def test_honoured_pin_is_logged(self, pinned_repo):
        """A pin that is silently honoured is a second silent behaviour; the
        log line is what makes a stale hold visible."""
        _write_pin(pinned_repo.path, f"{VENDOR_A} {pinned_repo.before[VENDOR_A]}\n")

        _run_pin_hook(pinned_repo)

        log = _log_text(pinned_repo.path)
        assert "pin honoured" in log and VENDOR_A in log, (
            f"no honoured-pin line naming {VENDOR_A} in the log:\n{log}"
        )

    def test_pin_file_is_never_staged(self, pinned_repo):
        """`.skills/skills-pin` is operator config, like plans_dir — the hook
        writes commits, it does not own this file."""
        _write_pin(pinned_repo.path, f"{VENDOR_A} {pinned_repo.before[VENDOR_A]}\n")

        _run_pin_hook(pinned_repo)

        assert not _tracked(pinned_repo.path, ".skills/skills-pin")

    def test_pin_file_location_is_overridable(self, pinned_repo):
        """Three-step knob resolution (AGENTS.md): env var wins over the
        committed file."""
        _write_pin(pinned_repo.path, f"{VENDOR_B} {pinned_repo.before[VENDOR_B]}\n")
        _write_pin(
            pinned_repo.path,
            f"{VENDOR_A} {pinned_repo.before[VENDOR_A]}\n",
            name="skills-pin.override",
        )

        result = _run_hook(
            pinned_repo.path,
            env_extra={
                **FILE_TRANSPORT,
                "SKILLS_PIN_FILE": ".skills/skills-pin.override",
            },
        )

        assert result.returncode == 0, result.stderr
        assert _gitlink(pinned_repo.path, VENDOR_A) == pinned_repo.before[VENDOR_A]
        assert _gitlink(pinned_repo.path, VENDOR_B) == pinned_repo.after[VENDOR_B], (
            "the env var must override the committed pin file, not merge with it"
        )


class TestPinSurvivesTheAutoCommit:
    """A pin honoured during the update but clobbered by the commit step is
    not a pin. The commit stages `skills-vendor/` wholesale unless the pinned
    paths are removed from its scope."""

    def test_drifted_checkout_is_not_committed(self, pinned_repo):
        repo = pinned_repo.path
        sub = repo / VENDOR_A
        # Someone ran `git submodule update --remote` by hand: the checkout is
        # ahead of the recorded pointer, so `git add skills-vendor/` would
        # commit the bump the pin exists to prevent.
        _git(sub, "fetch", "-q", "origin", env_extra=FILE_TRANSPORT)
        _git(sub, "checkout", "-q", pinned_repo.after[VENDOR_A])
        assert " M " in _git(repo, "status", "--porcelain").stdout

        _write_pin(repo, f"{VENDOR_A} {pinned_repo.before[VENDOR_A]}\n")
        _run_pin_hook(pinned_repo)

        assert _gitlink(repo, VENDOR_A) == pinned_repo.before[VENDOR_A], (
            "the auto-commit absorbed the pinned submodule's drift — the "
            "update honoured the pin and the commit step undid it"
        )
        committed = _git(repo, "show", "--name-only", "--pretty=", "HEAD").stdout
        assert VENDOR_A not in committed, (
            f"pinned path appears in the hook's commit:\n{committed}"
        )

    def test_drift_is_reported(self, pinned_repo):
        """The pin arriving *after* the pointer already moved past it is the
        real-world case (the hold ended, then someone wrote the pin). Not
        updating cannot restore it — only an operator can — so the hook must
        say the hold is not in effect rather than imply it is."""
        repo = pinned_repo.path
        sub = repo / VENDOR_A
        _git(sub, "fetch", "-q", "origin", env_extra=FILE_TRANSPORT)
        _git(sub, "checkout", "-q", pinned_repo.after[VENDOR_A])
        _git(repo, "add", "--", VENDOR_A)
        _git(repo, "commit", "-qm", "bump landed before the pin was written")
        # Pin the older commit — present in the checkout, so it resolves.
        _write_pin(repo, f"{VENDOR_A} {pinned_repo.before[VENDOR_A]}\n")

        result = _run_pin_hook(pinned_repo)

        assert "pin drift" in _log_text(repo), _log_text(repo)
        assert VENDOR_A in result.stderr, (
            f"drift must reach the operator, not only the log: {result.stderr!r}"
        )

    def test_unresolvable_target_is_reported_but_still_holds(self, pinned_repo):
        """A target the submodule checkout cannot resolve — an uninitialised
        submodule, a commit not yet fetched — must not refuse the refresh:
        the hold on movement is applied either way, and refusing would strand
        every sibling on a fresh clone. Report it and carry on."""
        repo = pinned_repo.path
        _write_pin(repo, f"{VENDOR_A} v9.9.9-does-not-exist\n")

        result = _run_pin_hook(pinned_repo)

        assert "pin unverified" in _log_text(repo), _log_text(repo)
        assert VENDOR_A in result.stderr
        assert _gitlink(repo, VENDOR_A) == pinned_repo.before[VENDOR_A], (
            "the hold must still be applied"
        )
        assert _gitlink(repo, VENDOR_B) == pinned_repo.after[VENDOR_B], (
            "an unverifiable target must not refuse the sibling's refresh"
        )


class TestUnhonourablePinRefusesTheRefresh:
    """A pin the hook cannot apply means the operator believes they have a
    hold they do not have. Refusing the refresh for the run is the only
    outcome that cannot silently end an experiment arm."""

    def test_unknown_submodule_is_reported(self, pinned_repo):
        _write_pin(pinned_repo.path, "skills-vendor/not-vendored abc1234\n")

        result = _run_pin_hook(pinned_repo)

        log = _log_text(pinned_repo.path)
        assert "not-vendored" in log, log
        assert "not-vendored" in result.stderr, result.stderr

    def test_unknown_submodule_holds_every_pointer(self, pinned_repo):
        """A typo'd path leaves the real path unpinned; refreshing it would be
        the exact silent bump the pin was written to stop."""
        _write_pin(pinned_repo.path, "skills-vendor/not-vendored abc1234\n")

        _run_pin_hook(pinned_repo)

        for rel in (VENDOR_A, VENDOR_B):
            assert _gitlink(pinned_repo.path, rel) == pinned_repo.before[rel], (
                "a pin the hook could not honour must stop the refresh, not "
                "be skipped past"
            )

    def test_malformed_line_is_reported_and_refuses(self, pinned_repo):
        _write_pin(pinned_repo.path, f"{VENDOR_A}\n")

        result = _run_pin_hook(pinned_repo)

        assert "malformed" in _log_text(pinned_repo.path).lower()
        assert result.stderr.strip(), "a malformed pin file must reach stderr"
        for rel in (VENDOR_A, VENDOR_B):
            assert _gitlink(pinned_repo.path, rel) == pinned_repo.before[rel]

    def test_every_submodule_pinned_runs_no_update(self, pinned_repo):
        """An empty pathspec is not "nothing" to `git submodule update` — it
        is *everything*. Verified: `git submodule update --remote --merge --`
        with no paths refreshes every submodule."""
        _write_pin(
            pinned_repo.path,
            f"{VENDOR_A} {pinned_repo.before[VENDOR_A]}\n"
            f"{VENDOR_B} {pinned_repo.before[VENDOR_B]}\n",
        )

        _run_pin_hook(pinned_repo)

        for rel in (VENDOR_A, VENDOR_B):
            assert _gitlink(pinned_repo.path, rel) == pinned_repo.before[rel], (
                f"{rel} moved although every submodule was pinned — the "
                "pathspec collapsed to empty and git updated everything"
            )


# --------------------------------------------------------------------------
# Uninitialized submodules (#176)
#
# `git submodule update --remote --merge` skips a submodule that is not
# registered in .git/config, prints "not initialized", and exits **0**. The
# hook's `if !` guard passes, nothing is committed, and the day's lock — which
# is stamped before the update, deliberately — is already consumed. Found in
# a consumer checkout that had been "succeeding" this way for days.
# --------------------------------------------------------------------------


def _deinit(repo: Path) -> None:
    """Drop every submodule's .git/config registration, leaving the gitlinks
    in HEAD and the (now empty) directories on disk.

    This is the half-healed state from #176: `git submodule status` prefixes
    every path with '-', and the doctor does not repair it because its own
    init is gated on a dangling `skills/*` symlink."""
    _git(repo, "submodule", "deinit", "-f", "--all", "-q")
    assert not _git(repo, "config", "--get-regexp", r"^submodule\.", check=False).stdout


class TestUninitializedSubmodulesStillRefresh:
    def test_deinitialized_submodules_are_initialized_and_refreshed(self, pinned_repo):
        """The #176 case. Without `--init` git skips both submodules, says so
        on stdout, and exits 0 — so the hook reports success forever and never
        advances a pointer."""
        _deinit(pinned_repo.path)

        _run_pin_hook(pinned_repo)

        for rel in (VENDOR_A, VENDOR_B):
            assert _gitlink(pinned_repo.path, rel) == pinned_repo.after[rel], (
                f"{rel} did not refresh from an uninitialized checkout — the "
                f"log said:\n{_log_text(pinned_repo.path)}"
            )

    def test_init_stays_behind_the_pin_filter(self, pinned_repo):
        """`--init` must not become a back door around a pin: a pinned path is
        absent from the pathspec, so it is neither initialized nor refreshed,
        while its uninitialized sibling still gets both."""
        _deinit(pinned_repo.path)
        _write_pin(pinned_repo.path, f"{VENDOR_A} {pinned_repo.before[VENDOR_A]}\n")

        _run_pin_hook(pinned_repo)

        assert _gitlink(pinned_repo.path, VENDOR_A) == pinned_repo.before[VENDOR_A], (
            "the held submodule's pointer moved — `--init` refreshed a path "
            "the pin had removed from the pathspec"
        )
        assert _gitlink(pinned_repo.path, VENDOR_B) == pinned_repo.after[VENDOR_B], (
            "the unpinned sibling must still initialize and refresh"
        )


class TestNothingRefreshedReadsAsAProblem:
    """The skip was indistinguishable from success in the log's *structure*:
    a header line, two lines of git's output, no verdict. Whatever the cause,
    a refresh that moved nothing because nothing was there to move has to read
    as a problem — that is what makes the state findable without a repro."""

    def test_no_registered_submodules_is_reported(self, repo):
        """`skills-vendor/` full of content that is not tracked as submodules:
        the pathspec matches nothing, git exits 0, and the hook can never
        advance a pointer here. Say so instead of logging a bare header."""
        assert not (repo / ".gitmodules").exists(), (
            "fixture precondition: the vendored tree is committed as plain files"
        )

        result = _run_hook(repo)

        assert result.returncode == 0, result.stderr
        log = _log_text(repo)
        assert "no registered skills-vendor/ submodules" in log, (
            f"nothing in the log distinguishes this from a successful refresh:\n{log}"
        )
        assert "skills-vendor/" in result.stderr, (
            f"the operator sees stderr, not .git/skills-update.log: {result.stderr!r}"
        )

    def test_still_uninitialized_after_the_refresh_is_reported(self, repo):
        """Belt and braces for the shape of the bug rather than its one known
        cause: if git ever again reports a path as uninitialized *after* the
        refresh, the hook must not let that pass as success."""
        (repo / ".gitmodules").write_text(
            '[submodule "acme-skills"]\n'
            "\tpath = skills-vendor/acme-skills\n"
            "\turl = https://example.invalid/acme-skills.git\n"
        )
        _write_git_shim(
            repo,
            submodule_body=(
                'if [ "$2" = "status" ]; then\n'
                '  echo "-1111111111111111111111111111111111111111 '
                'skills-vendor/acme-skills"\n'
                "  exit 0\n"
                "fi\n"
                "echo \"Submodule path 'skills-vendor/acme-skills' not initialized\"\n"
                "exit 0\n"
            ),
        )

        result = _run_hook(repo)

        assert result.returncode == 0, result.stderr
        log = _log_text(repo)
        assert "still uninitialized" in log, (
            f"a refresh that left a submodule uninitialized logged nothing "
            f"that reads as a problem:\n{log}"
        )
        assert "skills-vendor/acme-skills" in log, log
        assert "skills-vendor/acme-skills" in result.stderr, result.stderr


# ------------------------------------------------------------------- #293
# A commit that lands locally and is never pushed is functionally untracked
# for every consumer but the machine that wrote it. On CannObserv/replicator,
# whose systemd unit refuses to start a checkout carrying unpushed commits,
# one pointer bump from this hook stranded the deployed service twice in two
# weeks. These tests are about what the remote ends up holding, so they use a
# real bare remote over the `file` transport rather than a shim — a shimmed
# push that "succeeds" would pass every one of them while proving nothing.


@pytest.fixture
def remote_repo(tmp_path: Path) -> Path:
    """A consumer repo on main tracking a real bare remote.

    `repo` has no upstream, which the reconcile step treats as a legitimate
    configuration and returns on at once — so the push path is unreachable
    there and every existing test in this file is unaffected by #293.
    """
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", "-q", str(origin))

    repo = tmp_path / "work"
    (repo / VENDOR_REL).mkdir(parents=True)
    shutil.copy2(DOCTOR, repo / VENDOR_REL / "doctor.sh")
    shutil.copy2(INSTALLER, repo / VENDOR_REL / "install-doctor.sh")
    (repo / VENDOR_REL / "install-doctor.sh").chmod(0o755)
    (repo / "README.md").write_text("consumer\n")

    _git(repo.parent, "init", "-b", "main", "-q", str(repo))
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "push", "-q", "-u", "origin", "main")

    _shim_dir(repo).mkdir()
    _write_git_shim(repo)
    return repo


def _ahead(repo: Path) -> int:
    """Commits on main that the upstream has not been told about."""
    out = _git(repo, "rev-list", "--count", "@{u}..HEAD", check=False).stdout.strip()
    return int(out) if out.isdigit() else -1


def _origin_subjects(repo: Path) -> list[str]:
    origin = repo.parent / "origin.git"
    out = _git(origin, "log", "--format=%s", "main", check=False).stdout
    return [line for line in out.split("\n") if line]


def _break_remote(repo: Path) -> None:
    """Point origin at a path that does not exist, so a push fails the way an
    unreachable remote or a missing credential does — non-fatally, at push
    time, after the commit has already been made."""
    _git(repo, "remote", "set-url", "origin", str(repo.parent / "gone.git"))


def _hook_commit(repo: Path, subject: str = "chore: update skills submodules") -> None:
    """A commit indistinguishable from one an earlier run of this hook made."""
    (repo / "skills-vendor" / "acme-skills" / "marker").write_text("bumped\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", subject)


class TestCommitsGetPushed:
    def test_a_commit_it_makes_is_pushed(self, remote_repo):
        """The hook installs and commits the doctor (#86). That commit has to
        reach the remote, or it is untracked for everyone but this machine."""
        result = _run_hook(remote_repo)

        assert result.returncode == 0, result.stderr
        assert _tracked(remote_repo, ".skills/doctor.sh")
        assert _ahead(remote_repo) == 0, (
            "the hook committed and left the commit unpushed — the state that "
            "stranded replicator's service for 56 minutes"
        )
        assert any("doctor" in s for s in _origin_subjects(remote_repo)), (
            f"nothing reached the remote: {_origin_subjects(remote_repo)}"
        )

    def test_a_commit_stranded_by_an_earlier_run_is_pushed(self, remote_repo):
        """The reconcile pass runs ahead of the once-per-day lock, so a
        checkout left diverged by a previous run — a push killed by the hook's
        timeout, or a vendored copy from before #293 — heals at the next
        session rather than the next UTC day."""
        _hook_commit(remote_repo)
        assert _ahead(remote_repo) == 1

        result = _run_hook(remote_repo)

        assert result.returncode == 0, result.stderr
        assert _ahead(remote_repo) == 0, (
            "a commit stranded before this run was still stranded after it"
        )
        assert "chore: update skills submodules" in _origin_subjects(remote_repo)

    def test_the_lock_does_not_gate_the_retry(self, remote_repo):
        """Same-day second session: the lock skips the refresh, but a stranded
        commit must still be reconciled. Gating the retry behind the lock would
        make the wait for recovery a whole UTC day."""
        _run_hook(remote_repo)  # stamps .git/skills-update.lock
        _hook_commit(remote_repo)

        result = _run_hook(remote_repo)

        assert result.returncode == 0, result.stderr
        assert (remote_repo / ".git" / "skills-update.lock").exists()
        assert _ahead(remote_repo) == 0, "the day lock swallowed the push retry"


class TestFailedPushRollsBack:
    def test_the_commit_is_rolled_back(self, remote_repo):
        """Rolling back is what keeps the never-diverged property. Leaving the
        commit is the failure mode; it is silent, and it persists."""
        _break_remote(remote_repo)

        result = _run_hook(remote_repo)

        assert result.returncode == 0, result.stderr
        assert _ahead(remote_repo) == 0, (
            "a push that failed left the checkout ahead of its upstream"
        )

    def test_unrelated_dirty_work_survives(self, remote_repo):
        """The regression test for `git reset --hard HEAD~1`, which #293
        proposed. `--hard` is whole-tree: this hook's add-scope discipline is a
        property of `git add` and constrains it not at all, so an uncommitted
        edit anywhere in the checkout is discarded. Measured before the fix —
        the file below was reverted to its committed content."""
        (remote_repo / "README.md").write_text("OPERATOR WORK IN PROGRESS\n")
        _break_remote(remote_repo)

        result = _run_hook(remote_repo)

        assert result.returncode == 0, result.stderr
        assert (
            remote_repo / "README.md"
        ).read_text() == "OPERATOR WORK IN PROGRESS\n", (
            "the rollback discarded an uncommitted edit the hook never staged"
        )

    def test_the_refreshed_content_stays_on_disk(self, remote_repo):
        """Only the recorded pointer reverts. The doctor this run installed is
        still there, so the skills keep working and the next session retries
        from a working tree that already holds the refresh."""
        _break_remote(remote_repo)

        _run_hook(remote_repo)

        assert (remote_repo / ".skills" / "doctor.sh").exists(), (
            "the rollback took the installed doctor with it"
        )

    def test_it_is_reported_on_stderr_not_only_the_log(self, remote_repo):
        """$LOG is a file nobody reads until something has already gone wrong,
        which is why #293 rejects log-a-warning as the whole fix. Every other
        non-fatal failure in this hook also reaches stderr."""
        _break_remote(remote_repo)

        result = _run_hook(remote_repo)

        assert "could not push" in result.stderr, (
            f"a failed push was invisible to the operator:\n{result.stderr}"
        )

    def test_it_does_not_retry_within_the_same_run(self, remote_repo):
        """A rollback leaves the refreshed content dirty, so the commit step
        would otherwise re-stage it, re-commit it and re-attempt the push just
        refused — two network waits inside a 120s ceiling, and the same warning
        twice."""
        _break_remote(remote_repo)

        result = _run_hook(remote_repo)

        assert result.stderr.count("could not push") == 1, (
            f"the run attempted the refused push more than once:\n{result.stderr}"
        )
        assert _ahead(remote_repo) == 0

    def test_an_unstage_that_fails_after_the_rollback_is_reported(self, remote_repo):
        """The rollback's unstage is the commit step's failure path in another
        place, and it discarded the reset's status the same way (#311). The
        soft reset is left to work; only the pathspec reset after it fails."""
        _break_remote(remote_repo)
        _write_git_shim(
            remote_repo,
            extra_arms=(
                'if [ "$1" = "reset" ] && [ "$3" = "--" ]; then '
                'echo "fatal: simulated index.lock" >&2; exit 128; fi\n'
            ),
        )

        result = _run_hook(remote_repo)

        assert result.returncode == 0, result.stderr
        assert _ahead(remote_repo) == 0, "the rollback itself must still happen"
        warning = ".skills/doctor.sh still staged after a rolled-back push"
        assert warning in result.stderr, result.stderr
        assert result.stderr.index("could not push") < result.stderr.index(warning), (
            f"the warning belongs after the rollback it qualifies:\n{result.stderr}"
        )


class TestOperatorCommitsAreUntouchable:
    def test_an_operator_commit_is_never_rolled_back(self, remote_repo):
        """The authorship guard, not the choice of reset mode, is what makes
        rolling back safe in general."""
        (remote_repo / "mine.txt").write_text("unshared\n")
        _git(remote_repo, "add", "-A")
        _git(remote_repo, "commit", "-qm", "feat: my own work")
        _break_remote(remote_repo)

        result = _run_hook(remote_repo)

        assert result.returncode == 0, result.stderr
        assert _head_message(remote_repo) == "feat: my own work", (
            "the hook rolled back a commit it did not write"
        )

    def test_an_operator_commit_is_never_published(self, remote_repo):
        """A push is a push of the whole branch. Committing a bump on top of
        work the operator has not shared and pushing it would publish their
        work for them — a larger overreach than the stranding being fixed, so
        the run commits nothing instead."""
        (remote_repo / "mine.txt").write_text("unshared\n")
        _git(remote_repo, "add", "-A")
        _git(remote_repo, "commit", "-qm", "feat: unshared work")

        result = _run_hook(remote_repo)

        assert result.returncode == 0, result.stderr
        assert "feat: unshared work" not in _origin_subjects(remote_repo), (
            "the hook published a commit the operator had chosen not to share"
        )
        assert _head_message(remote_repo) == "feat: unshared work", (
            "the hook added a commit on top of work it could not share"
        )
        assert "cannot share" in _log_text(remote_repo)

    def test_purely_operator_commits_pass_in_silence(self, remote_repo):
        """Working unpushed on a local main is normal in plenty of repos. A
        stderr line at every session start there would train the reader to
        ignore the one channel the stranding case depends on."""
        (remote_repo / "mine.txt").write_text("unshared\n")
        _git(remote_repo, "add", "-A")
        _git(remote_repo, "commit", "-qm", "feat: my own work")

        result = _run_hook(remote_repo)

        assert "unpushed" not in result.stderr, result.stderr

    def test_a_mix_is_reported_and_left_alone(self, remote_repo):
        """The hook's own bump stranded behind a commit it must not touch. It
        cannot fix that from here, so it says so where someone will see it."""
        _hook_commit(remote_repo)
        (remote_repo / "mine.txt").write_text("unshared\n")
        _git(remote_repo, "add", "-A")
        _git(remote_repo, "commit", "-qm", "feat: my own work")

        result = _run_hook(remote_repo)

        assert result.returncode == 0, result.stderr
        assert _ahead(remote_repo) == 2, "the hook touched a history it does not own"
        assert "did not write" in result.stderr, result.stderr
        assert result.stderr.count("did not write") == 1, (
            f"the same finding was reported twice in one run:\n{result.stderr}"
        )


class TestReconcileEdgeCases:
    def test_diverged_main_rolls_back_onto_its_own_history(self, remote_repo):
        """Resetting to @{u} instead of HEAD~N would move HEAD onto the
        remote's tree while the working tree stayed on ours, so every file the
        remote had added would read as deleted-by-us. A sibling workflow
        pushing `chore: weekly context measurement` to main makes this the
        expected steady state on an unattended VM, not a corner case."""
        origin = remote_repo.parent / "origin.git"
        other = remote_repo.parent / "other"
        _git(remote_repo.parent, "clone", "-q", str(origin), str(other))
        (other / "measure.txt").write_text("weekly\n")
        _git(other, "add", "-A")
        _git(other, "commit", "-qm", "chore: weekly context measurement")
        _git(other, "push", "-q", "origin", "main")

        _hook_commit(remote_repo)
        _git(remote_repo, "fetch", "-q", "origin")

        result = _run_hook(remote_repo)

        assert result.returncode == 0, result.stderr
        assert _ahead(remote_repo) == 0, "our side was not rolled back"
        porcelain = _git(remote_repo, "status", "--porcelain").stdout
        assert " D measure.txt" not in porcelain, (
            f"the rollback made the remote's own file read as deleted:\n{porcelain}"
        )

    def test_no_upstream_is_a_silent_no_op(self, remote_repo):
        """A remote-less checkout is a configuration, not a fault: there is
        nothing to be ahead of, so there is nothing to say."""
        _git(remote_repo, "branch", "--unset-upstream")
        _git(remote_repo, "remote", "remove", "origin")

        result = _run_hook(remote_repo)

        assert result.returncode == 0, result.stderr
        assert "push" not in result.stderr.lower(), result.stderr
        assert _head_message(remote_repo).startswith("chore:"), (
            "the hook stopped committing when there was no remote to push to"
        )


class TestCommitScope:
    """What the commit is allowed to sweep up. The hook's add scope was always
    narrow, but `git commit` with no pathspec commits the whole INDEX — so
    anything the operator had staged before the session began went into the
    hook's commit under the hook's own message. That was a local wart while the
    hook only committed. Since it pushes (#293), it publishes."""

    def test_pre_staged_operator_work_is_not_absorbed(self, remote_repo):
        """Measured before the fix: a file the operator had staged and not
        committed reached the remote inside `chore: update skills submodules`."""
        (remote_repo / "secret.txt").write_text("staged, deliberately not shared\n")
        _git(remote_repo, "add", "secret.txt")

        result = _run_hook(remote_repo)

        assert result.returncode == 0, result.stderr
        committed = _git(
            remote_repo, "show", "--stat", "--format=", "--name-only", "HEAD"
        ).stdout
        assert "secret.txt" not in committed, (
            f"the hook's commit absorbed work it never staged:\n{committed}"
        )
        origin = remote_repo.parent / "origin.git"
        assert (
            _git(origin, "cat-file", "-e", "main:secret.txt", check=False).returncode
            != 0
        ), "the hook published work the operator had only staged"
        assert (
            _git(remote_repo, "diff", "--cached", "--name-only").stdout.strip()
            == "secret.txt"
        ), "the operator's index did not survive the hook's commit"

    def test_a_gitignored_skills_dir_still_gets_its_submodule_bump(self, remote_repo):
        """The regression guard on how that scope is expressed. `git commit --
        <path>` fails outright on a path git does not know, and
        `.skills/doctor.sh` is exactly that where a consumer gitignores
        `.skills/` — the `git add` leaves it unstaged there by design. Scoping
        the commit to the hook's whole path list made the commit fail for those
        consumers and stranded the submodule bump with it, which is the hard
        failure the `|| true` on the add exists to avoid."""
        (remote_repo / ".gitignore").write_text(".skills/\n")
        _git(remote_repo, "add", "-A")
        _git(remote_repo, "commit", "-qm", "chore: ignore .skills")
        _git(remote_repo, "push", "-q", "origin", "main")
        (remote_repo / VENDOR_REL / "doctor.sh").write_text("# bumped\n")

        result = _run_hook(remote_repo)

        assert result.returncode == 0, result.stderr
        assert _head_message(remote_repo) == "chore: update skills submodules", (
            "the gitignored doctor took the submodule bump down with it"
        )
        assert _ahead(remote_repo) == 0
        assert not _tracked(remote_repo, ".skills/doctor.sh")


class TestRefusalsBlockTheCommitToo:
    """Every refusal inside the reconcile has to stop the commit step as well.
    A run that concludes it cannot share a commit and then makes one has
    manufactured the stranding #293 exists to prevent — call site 2 only
    refuses it again, and it sits there until an operator intervenes."""

    def test_a_log_it_cannot_read_refuses_and_commits_nothing(self, remote_repo):
        """The guard fails closed, and closed means no new commit either. With
        `git log` failing, the subject read returns nothing; scoring that as
        "every one of them is mine" would publish an operator's unshared work,
        and committing on top of it would strand a bump behind theirs."""
        (remote_repo / "mine.txt").write_text("unshared\n")
        _git(remote_repo, "add", "-A")
        _git(remote_repo, "commit", "-qm", "feat: my own work")
        _write_git_shim(
            remote_repo, extra_arms='if [ "$1" = "log" ]; then exit 128; fi\n'
        )

        result = _run_hook(remote_repo)

        assert result.returncode == 0, result.stderr
        assert "feat: my own work" not in _origin_subjects(remote_repo), (
            "an unreadable log let the hook publish a commit it could not verify"
        )
        assert _head_message(remote_repo) == "feat: my own work", (
            "the hook committed on top of a range it had just refused to read"
        )
        assert _ahead(remote_repo) == 1

    def test_a_merge_in_the_range_refuses_and_commits_nothing(self, remote_repo):
        """`HEAD~N` counts first-parent steps, so a merge in the range makes the
        rollback arithmetic wrong and the reconcile refuses. That refusal has to
        reach the commit step for the same reason as any other.

        The MERGE carries a hook subject, which is what makes this a test of the
        merge refusal at all: with an ordinary `Merge branch 'side'` subject the
        `unknown > 0` branch fires first and this branch never runs — the shape
        that let an earlier version of this test pass with the fix removed."""
        _git(remote_repo, "checkout", "-q", "-b", "side")
        (remote_repo / "side.txt").write_text("side\n")
        _git(remote_repo, "add", "-A")
        _git(remote_repo, "commit", "-qm", "chore: update skills submodules")
        _git(remote_repo, "checkout", "-q", "main")
        _git(
            remote_repo,
            "merge",
            "-q",
            "--no-ff",
            "-m",
            "chore: update skills submodules",
            "side",
        )
        before = _commit_count(remote_repo)

        result = _run_hook(remote_repo)

        assert result.returncode == 0, result.stderr
        assert _commit_count(remote_repo) == before, (
            "the hook added a commit to a range it had refused to reconcile"
        )
        assert not _tracked(remote_repo, ".skills/doctor.sh")
        assert "refusing to roll back" in _log_text(remote_repo), (
            "the merge refusal never ran — another branch caught this first"
        )
