"""#550 — a bump the hook cannot keep is undone whole: pointer, content and doctor.

Seen on CannObserv/wslcb-licensing-tracker (2026-10-29): the refresh merged the
vendored submodule forward, committed, and had its push rejected — local `main`
was one commit behind `origin`. The rollback reverted the recorded pointer and
left the refreshed content checked out. That content carried #480, which
refuses a knob grammar the repo's committed config still used, so the deploy
checkout's vendored skill refused the repo's own config until a human synced.

The comment above `_reconcile_unpushed` said the rollback leaves the content
"so the skills themselves keep working either way". That holds only while an
update is backward-compatible with the consumer's repo-side config.

Decided (2026-11-03), option 1: on rollback, the vendored checkout goes back
to the recorded pointer too. Two corrections to the decision as written, each
pinned below:
- plain `git submodule update -- <path>` is not enough. Under a configured
  `submodule.<name>.update` of merge, rebase or none it exits 0 and leaves the
  newer content checked out (measured, git 2.54); `--checkout` restores it.
- a rollback alone does not hold the invariant. A run that cannot share a
  commit used to refresh anyway and skip only the commit, so the content
  moved ahead of the pointer again in the same run (a rollback at session
  start), or every day (main carrying an operator's unpushed commit). A run
  that cannot commit now does not refresh.

`.skills/doctor.sh` rides the bump, so it rolls back with it: the restored
vendored installer writes the doctor the recorded pointer ships, whether the
doctor was tracked before the bump or not.

Coverage:
- a push rejected non-fast-forward (the issue's run, verbatim)
                                      → content == pointer, doctor back where
                                        it was (tracked and untracked before)
- a configured `update = merge`       → still restored
- a stranded commit whose push fails at session start, with the day unspent
                                      → the same run does not re-advance it
- main carries an operator's unpushed commit
                                      → no refresh, content stays at pointer
- a killed run's staging, then a run that cannot redo the bump
                                      → staging undone, content at pointer
- unrelated dirty work, and an edit inside the vendored checkout
                                      → survive the restore (never forced)
- a restore git refuses               → stderr says the content is ahead
"""

import pytest

from tests.utils.refresh_hook_consumer import (
    DOCTOR_PATH,
    MS_SCRIPTS,
    MSG_SUB,
    VENDOR,
    ahead,
    build,
    content,
    git,
    gitlink,
    lock,
    origin_gitlink,
    run_hook,
    staged,
    today,
    write_shim,
)

AFTER_ADD = '[ "$1" = diff ] && [ "$2" = --cached ] && [ "$3" = --quiet ]'


def _origin_moves_ahead(c) -> None:
    """Another writer lands on origin/main — the weekly context measurement,
    in the issue — so this checkout's next push is rejected non-fast-forward."""
    other = c.path.parent / "other"
    git(c.path.parent, "clone", "-q", str(c.origin), str(other))
    (other / "measurement.md").write_text("weekly\n")
    git(other, "add", "measurement.md")
    git(other, "commit", "-qm", "chore: weekly context measurement")
    git(other, "push", "-q", "origin", "main")


def _operator_commit(c) -> None:
    (c.path / "mine.txt").write_text("unshared\n")
    git(c.path, "add", "mine.txt")
    git(c.path, "commit", "-qm", "feat: my own work", "--", "mine.txt")


def _stranded_bump(c) -> None:
    """A bump an earlier run committed and never pushed (a push killed by the
    harness, or refused), with the day still unspent."""
    git(c.path, "submodule", "update", "--remote", "--merge", "--", VENDOR)
    git(c.path, "add", VENDOR)
    git(c.path, "commit", "-qm", MSG_SUB, "--", VENDOR)
    assert content(c) == c.after == gitlink(c)


def _doctor_status(c) -> str:
    return git(c.path, "status", "--porcelain", "--", DOCTOR_PATH).stdout.strip()


def _assert_content_matches_pointer(c) -> None:
    assert content(c) == gitlink(c) == c.before, (
        f"the vendored checkout holds {content(c)[:7]} while the recorded "
        f"pointer is {gitlink(c)[:7]} — the content is ahead of the pointer, "
        "so the repo's config may not match the skills that read it"
    )


class TestTheIssuesReproduction:
    @pytest.mark.parametrize("doctor_tracked", [True, False])
    def test_a_rejected_push_leaves_content_and_pointer_equal(
        self, tmp_path, doctor_tracked
    ):
        """Done when: after a failed push, the checkout's vendored content
        and its recorded pointer agree — and the doctor is back where it was."""
        c = build(tmp_path, doctor_tracked=doctor_tracked)
        _origin_moves_ahead(c)

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert "could not push" in result.stderr, result.stderr
        assert ahead(c) == 0
        _assert_content_matches_pointer(c)
        assert (c.path / DOCTOR_PATH).read_text() == c.v1, (
            "the doctor the refused bump installed is still in place"
        )
        if doctor_tracked:
            assert _doctor_status(c) == "", _doctor_status(c)
        else:
            assert _doctor_status(c) == f"?? {DOCTOR_PATH}", _doctor_status(c)
        assert staged(c) == []


class TestTheRestore:
    def test_a_configured_update_mode_does_not_stop_it(self, tmp_path):
        """`git submodule update -- <path>` honours `update = merge`, merges
        the older recorded commit into the newer checkout — already contained
        — and exits 0 with nothing restored. `--checkout` overrides it."""
        c = build(tmp_path)
        git(c.path, "config", f"submodule.{VENDOR}.update", "merge")
        _origin_moves_ahead(c)

        run_hook(c)

        _assert_content_matches_pointer(c)

    def test_the_same_run_does_not_refresh_it_forward_again(self, tmp_path):
        """A stranded bump's push fails at session start, and the day is
        unspent. The rollback restores the content; the refresh that follows
        must not then move it ahead of the pointer it cannot commit."""
        c = build(tmp_path)
        _stranded_bump(c)
        _origin_moves_ahead(c)
        assert not lock(c).exists()

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert ahead(c) == 0
        _assert_content_matches_pointer(c)
        assert lock(c).read_text().strip() == today(), (
            "a run that ends spends the day, refused or not"
        )

    def test_unpushed_operator_work_means_no_refresh(self, tmp_path):
        """Main carries the operator's own unpushed commit, so this run will
        not commit (#293). It used to refresh anyway — the content moved,
        every day, while the pointer could not."""
        c = build(tmp_path)
        _operator_commit(c)

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        _assert_content_matches_pointer(c)
        assert (c.path / DOCTOR_PATH).read_text() == c.v1

    def test_a_killed_runs_bump_is_undone_when_the_run_cannot_redo_it(self, tmp_path):
        """#555's heal unstages a killed run's bump. When the session that
        heals it cannot redo the bump, the content it left goes back too."""
        c = build(tmp_path)
        write_shim(c, kill_when=AFTER_ADD)
        c.kill_flag.write_text("")
        assert run_hook(c).returncode < 0
        write_shim(c)
        assert content(c) == c.after
        _operator_commit(c)

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert staged(c) == []
        _assert_content_matches_pointer(c)
        assert (c.path / DOCTOR_PATH).read_text() == c.v1
        assert _doctor_status(c) == ""


class TestTheRestoreIsBounded:
    def test_unrelated_dirty_work_survives(self, tmp_path):
        c = build(tmp_path)
        (c.path / "README.md").write_text("OPERATOR WORK IN PROGRESS\n")
        _origin_moves_ahead(c)

        run_hook(c)

        _assert_content_matches_pointer(c)
        assert (c.path / "README.md").read_text() == "OPERATOR WORK IN PROGRESS\n"

    def test_an_edit_inside_the_vendored_checkout_survives(self, tmp_path):
        """Never forced: a local edit to a file the two commits share is
        carried across the checkout, as a plain `git checkout` carries it."""
        c = build(tmp_path)
        edited = c.path / VENDOR / MS_SCRIPTS / "install-doctor.sh"
        edited.write_text(edited.read_text() + "# local edit\n")
        _origin_moves_ahead(c)

        run_hook(c)

        _assert_content_matches_pointer(c)
        assert edited.read_text().endswith("# local edit\n")

    def test_a_restore_git_refuses_is_said_plainly(self, tmp_path):
        """The issue's other acceptable outcome: where the content cannot be
        put back, the session hears that it is ahead of the pointer."""
        c = build(tmp_path)
        write_shim(c)
        shim = c.bindir / "git"
        text = shim.read_text().split("\n", 1)
        shim.write_text(
            text[0] + "\n"
            'case " $* " in *" --checkout "*) '
            'echo "fatal: simulated refusal" >&2; exit 1 ;; esac\n' + text[1]
        )
        _origin_moves_ahead(c)

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert content(c) == c.after and gitlink(c) == c.before
        assert "ahead of the recorded pointer" in result.stderr, result.stderr
        assert origin_gitlink(c) == c.before
