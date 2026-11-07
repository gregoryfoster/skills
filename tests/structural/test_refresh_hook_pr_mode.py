"""#560 — with `.skills/merge_mode` `pr`, the refresh hook proposes its bump as ONE PR.

A consumer that protects its default branch with a PR-only ruleset and no
bypass refuses the hook's push, and the hook rolls the bump back. Decided on
#560 (comment 6605837550): read #342's knob, no new one. With `pr`, the hook
pushes `skills/submodule-refresh` and keeps one PR open, which later sessions
update. Absent or `direct`: today's behaviour, byte for byte.

The mechanism (managing-skills references/auto-refresh-hook/pr-mode.md):
- the refresh runs in place as today, under the in-progress marker; the bump
  is recorded in a commit built on `@{u}` in a private index, and the content
  goes back to the recorded pointer BEFORE any network call, so local `main`
  never moves and the checkout's content always equals its pointer;
- `gh` is asked for the branch's PRs and `git ls-remote` for its tip; the push
  is `--force-with-lease` against that tip; a PR is created only when none is
  open;
- a refusal, an absent or unauthenticated `gh` — anything that stops it — is
  reported once and not retried: the run ends, and the day is spent.

Every fixture repo is built with an explicit path and a scrubbed `GIT_*`
environment (#189). `gh` is a fake on PATH; the remote is a local bare repo
whose pre-receive hook stands in for the ruleset. Not available here: a real
no-bypass ruleset, a real `gh`, a real VS Code session.
"""

import copy
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests.structural import merge_mode_layouts as layouts
from tests.structural.test_cadence_merge_mode import (
    CASES,
    NOT_TEXT,
    _merge_mode_sh,
    _not_text,
)
from tests.utils.refresh_hook_consumer import (
    DOCTOR_PATH,
    HOOK,
    INSTALLER,
    MS_SCRIPTS,
    MSG_SUB,
    VENDOR,
    _vendor_commit,
    build,
    clean_env,
    content,
    finish_hook,
    git,
    gitlink,
    lock,
    log_text,
    origin_gitlink,
    run_hook,
    staged,
    start_hook,
    today,
    write_shim,
)

PR_BRANCH = "skills/submodule-refresh"
MARKER = ".git/skills-update.staging"
PR_INDEX = ".git/skills-update.pr-index"

FAKE_GH = r"""#!/usr/bin/env bash
# A stand-in for gh. Logs every call to $S/calls. `pr list` prints $S/prs, one
# PR per line as the hook's --jq shapes it — `<number> <STATE> <head oid>` —
# with an OPEN PR's head read live from origin, as GitHub reports it.
# `pr create` records an OPEN PR. $S/list_err or $S/create_err make that call
# fail with the file's text; $S/kill_create kills the run's process group at
# `pr create`, once, the way the VS Code extension's shutdown does (#555).
S="@STATE@"
# `auth token` is the preflight's offline check (#576), logged apart from the
# calls that reach GitHub: $S/no_login makes it fail, as with no stored login.
if [ "$1 $2" = "auth token" ]; then
  printf '%s\n' "$*" >>"$S/auth"
  [ ! -f "$S/no_login" ] || exit 1
  echo stored-token
  exit 0
fi
printf '%s\n' "$*" >>"$S/calls"
printf '%s\n' "${GH_TOKEN:-}" >>"$S/tokens"
tip() { "@GIT@" ls-remote origin "refs/heads/skills/submodule-refresh" | cut -f1; }
case "$1 $2" in
  "pr list")
    [ ! -f "$S/list_err" ] || { cat "$S/list_err" >&2; exit 1; }
    [ -f "$S/prs" ] || exit 0
    while read -r n s oid; do
      if [ "$s" = OPEN ]; then oid=$(tip); fi
      echo "$n $s $oid"
    done <"$S/prs"
    exit 0 ;;
  "pr create")
    if [ -f "$S/kill_create" ]; then rm -f "$S/kill_create"; kill -KILL 0; sleep 5; fi
    [ ! -f "$S/create_err" ] || { cat "$S/create_err" >&2; exit 1; }
    n=$(( $( (cat "$S/prs" 2>/dev/null || true) | wc -l) + 7 ))
    echo "$n OPEN $(tip)" >>"$S/prs"
    echo "https://github.com/o/r/pull/$n"
    exit 0 ;;
esac
echo "fake gh: unhandled: $*" >&2
exit 64
"""

GH013 = (
    "#!/usr/bin/env bash\n"
    "while read -r _ _ ref; do\n"
    '  if [ "$ref" = @REF@ ] || [ @REF@ = all ]; then\n'
    '    echo x >>"@COUNT@"\n'
    '    echo "error: GH013: Repository rule violations found for $ref." >&2\n'
    '    echo "Review all repository rules at https://github.com/o/r/rules" >&2\n'
    '    echo "" >&2\n'
    '    echo "- Changes must be made through a pull request." >&2\n'
    "    exit 1\n"
    "  fi\n"
    "done\n"
)


# --- the rig -----------------------------------------------------------------


def _gh(c) -> Path:
    """Installs the fake gh in the hook's PATH; returns its state dir."""
    state = c.path.parent / "ghstate"
    state.mkdir(exist_ok=True)
    fake = c.bindir / "gh"
    # Real git by path: the hook's PATH carries a shim that kills or holds.
    real_git = shutil.which("git") or "/usr/bin/git"
    fake.write_text(FAKE_GH.replace("@STATE@", str(state)).replace("@GIT@", real_git))
    fake.chmod(0o755)
    return state


def _calls(state: Path) -> list[str]:
    f = state / "calls"
    return f.read_text().splitlines() if f.exists() else []


def _creates(state: Path) -> list[str]:
    return [line for line in _calls(state) if line.startswith("pr create")]


def _commit_knob(c, text: str) -> None:
    """The knob, committed and shared — as a consumer adopting it would."""
    (c.path / ".skills").mkdir(exist_ok=True)
    (c.path / ".skills" / "merge_mode").write_text(text)
    git(c.path, "add", ".skills/merge_mode")
    git(c.path, "commit", "-qm", "chore: merge_mode", "--", ".skills/merge_mode")
    git(c.path, "push", "-q", "origin", "main")


def _rule(c, ref: str = "refs/heads/main") -> Path:
    """A no-bypass rule on `ref` (or every ref, `all`), as a server hook that
    refuses the way GitHub does. Returns the file counting refused pushes."""
    count = c.path.parent / f"pushes-{ref.replace('/', '_')}"
    hook = c.origin / "hooks" / "pre-receive"
    hook.write_text(GH013.replace("@COUNT@", str(count)).replace("@REF@", ref))
    hook.chmod(0o755)
    return count


def _pushes(count: Path) -> int:
    return count.read_text().count("x") if count.exists() else 0


def _origin(c, rev: str) -> str:
    r = git(c.origin, "rev-parse", "--verify", "-q", rev, check=False)
    return r.stdout.strip()


def _branch_gitlink(c) -> str:
    return _origin(c, f"{PR_BRANCH}:{VENDOR}")


def _new_day(c) -> None:
    lock(c).unlink(missing_ok=True)


def _upstream_moves(c, tag: str = "c3") -> str:
    return _vendor_commit(c.up, c.v2 + f"# fixture: {tag}\n", f"vendor {tag}")


def _assert_content_matches_pointer(c) -> None:
    assert content(c) == gitlink(c), (
        f"the vendored checkout holds {content(c)[:7]} while main records "
        f"{gitlink(c)[:7]} — the content is ahead of the pointer"
    )


def _run(c, path: str | None = None) -> subprocess.CompletedProcess:
    """A session start with a chosen PATH (the gh-absent case)."""
    if path is None:
        return run_hook(c)
    env = clean_env()
    env["PATH"] = path
    proc = subprocess.Popen(
        ["bash", str(HOOK)],
        cwd=c.path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    return finish_hook(proc)


def _path_without_gh(c) -> str:
    """The hook's PATH with every directory's `gh` hidden: a directory of
    links to everything else on PATH, first match wins."""
    tools = c.path.parent / "tools"
    tools.mkdir()
    for d in os.environ.get("PATH", "/usr/bin:/bin").split(os.pathsep):
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name == "gh" or (tools / name).exists() or (tools / name).is_symlink():
                continue
            src = Path(d) / name
            try:
                runnable = src.is_file() and os.access(src, os.X_OK)
            except OSError:  # a root-only entry in /usr/sbin
                runnable = False
            if runnable:
                (tools / name).symlink_to(src)
    return f"{c.bindir}{os.pathsep}{tools}"


@pytest.fixture
def pr_consumer(tmp_path):
    c = build(tmp_path)
    _commit_knob(c, "pr\n")
    c.gh = _gh(c)
    c.main0 = _origin(c, "main")
    c.head0 = git(c.path, "rev-parse", "HEAD").stdout.strip()
    return c


def _main_never_moved(c) -> None:
    assert _origin(c, "main") == c.main0, "the default branch moved"
    assert git(c.path, "rev-parse", "HEAD").stdout.strip() == c.head0, (
        "local main moved"
    )


# --- #560's "Done when", verbatim -------------------------------------------


class TestTheIssuesReproduction:
    def test_with_merge_mode_pr_a_sessions_refresh_lands_as_a_pr_update_not_a_rollback_loop(
        self, pr_consumer
    ):
        """Done when: "With `merge_mode` `pr` and a no-bypass PR-only rule on
        the default branch, a session's refresh lands as a PR update instead
        of a rollback loop." Run 1 opens the PR; run 2, the next day, updates
        the same PR; the default branch and local main never move, and the
        content equals the recorded pointer after each run."""
        c = pr_consumer
        main_pushes = _rule(c)

        first = run_hook(c)

        assert first.returncode == 0, first.stderr
        assert "could not push" not in first.stderr, first.stderr
        assert "rolled" not in first.stderr, first.stderr
        _main_never_moved(c)
        _assert_content_matches_pointer(c)
        assert content(c) == c.before
        assert _pushes(main_pushes) == 0, "the hook pushed at the default branch"
        assert _branch_gitlink(c) == c.after
        assert _origin(c, f"{PR_BRANCH}~1") == c.main0, (
            "the PR's commit must sit on the default branch's tip"
        )
        creates = _creates(c.gh)
        assert len(creates) == 1, _calls(c.gh)
        assert f"--head {PR_BRANCH}" in creates[0] and "--base main" in creates[0]
        # The doctor that rides the commit is the one the new pointer ships
        # (#299); the checkout keeps the one its own pointer ships.
        assert git(c.origin, "show", f"{PR_BRANCH}:{DOCTOR_PATH}").stdout == c.v2
        assert (c.path / DOCTOR_PATH).read_text() == c.v1

        _new_day(c)
        c3 = _upstream_moves(c)
        second = run_hook(c)

        assert second.returncode == 0, second.stderr
        assert "could not push" not in second.stderr, second.stderr
        _main_never_moved(c)
        _assert_content_matches_pointer(c)
        assert content(c) == c.before
        assert _pushes(main_pushes) == 0
        assert _branch_gitlink(c) == c3, "the same PR's branch was not updated"
        assert _origin(c, f"{PR_BRANCH}~1") == c.main0
        assert len(_creates(c.gh)) == 1, "a second PR was opened"
        assert lock(c).read_text().strip() == today()


# --- absent or direct: today's behaviour ------------------------------------


class TestAbsentOrDirectIsToday:
    @pytest.mark.parametrize("knob", [None, "direct\n"])
    def test_no_gh_and_the_bump_is_pushed_to_main_as_before(self, tmp_path, knob):
        c = build(tmp_path)
        if knob is not None:
            _commit_knob(c, knob)
        state = _gh(c)

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        assert _calls(state) == [], "a direct run invoked gh"
        assert origin_gitlink(c) == c.after == gitlink(c) == content(c)
        assert git(c.path, "log", "-1", "--format=%s").stdout.strip() in (
            MSG_SUB,
            "chore: update skills submodules and refresh .skills/doctor.sh",
        )
        assert _origin(c, PR_BRANCH) == ""
        assert not (c.path / PR_INDEX).exists()
        assert "merge_mode" not in log_text(c)

    def test_a_ruleset_refusal_names_the_rule_and_the_remedy(self, tmp_path):
        """Under a PR-only rule `direct` is refused with GH013 — the
        wordpress case (#560's premise correction). Everything `direct` does
        is unchanged; the stderr line says which rule refused it and that
        `merge_mode` `pr` is the remedy."""
        c = build(tmp_path)
        count = _rule(c)

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert "could not push" in result.stderr, result.stderr
        assert "rolled 1 commit(s) back" in result.stderr, result.stderr
        assert "GH013" in result.stderr, result.stderr
        assert "Changes must be made through a pull request" in result.stderr
        assert ".skills/merge_mode" in result.stderr and " pr" in result.stderr
        assert _pushes(count) == 1
        _assert_content_matches_pointer(c)
        assert content(c) == c.before

    def test_any_other_refusal_says_what_it_said_before(self, tmp_path):
        c = build(tmp_path)
        git(c.path, "remote", "set-url", "origin", str(c.path.parent / "gone.git"))

        result = run_hook(c)

        assert "could not push" in result.stderr
        assert "merge_mode" not in result.stderr
        assert "GH013" not in result.stderr


# --- the inline reader holds merge-mode.sh's grammar ------------------------


def _reader_source() -> str:
    m = re.search(r"^_read_merge_mode\(\) \{\n.*?^\}\n", HOOK.read_text(), re.M | re.S)
    assert m, "the hook has no _read_merge_mode() at column 0"
    return m.group(0)


def _read_mode(cwd: Path, env: dict | None = None) -> tuple[str, str]:
    script = (
        "set -euo pipefail\n"
        + _reader_source()
        + '_read_merge_mode\nprintf "%s\\n%s" "$MERGE_MODE" "$MERGE_MODE_ERR"\n'
    )
    r = subprocess.run(
        ["bash", "-c", script],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=clean_env() if env is None else env,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    mode, _, err = r.stdout.partition("\n")
    return mode, err


class TestTheReaderHoldsMergeModeShsGrammar:
    @pytest.mark.parametrize("text", CASES, ids=[repr(c) for c in CASES])
    def test_it_answers_as_merge_mode_sh_does(self, tmp_path, text):
        repo = tmp_path / "r"
        git(tmp_path, "init", "-q", "-b", "main", str(repo))
        if text is not None:
            (repo / ".skills").mkdir()
            (repo / ".skills" / "merge_mode").write_text(text)
        want_rc, want = _merge_mode_sh(repo)
        mode, err = _read_mode(repo)
        if want_rc == 0:
            assert (mode, err) == (want, "")
        else:
            assert mode == "unusable", (text, mode)
            assert ".skills/merge_mode" in err

    @pytest.mark.parametrize("kind", NOT_TEXT)
    def test_it_refuses_what_merge_mode_sh_refuses(self, tmp_path, kind):
        """The states no text can write (CR 1793)."""
        repo = tmp_path / "r"
        git(tmp_path, "init", "-q", "-b", "main", str(repo))
        _not_text(repo, kind)
        assert _merge_mode_sh(repo)[0] == 2, "fixture: merge-mode.sh accepts it"
        mode, err = _read_mode(repo)
        assert mode == "unusable", (kind, mode)
        assert ".skills/merge_mode" in err

    def test_outside_a_git_checkout_it_is_unusable(self, tmp_path):
        """The hook itself exits before reading the knob there (no git dir),
        so this pins the reader alone: a failed `git worktree list` is a
        refusal, never `direct`."""
        bare = tmp_path / "not-a-repo"
        bare.mkdir()
        assert _merge_mode_sh(bare)[0] == 2
        mode, err = _read_mode(bare)
        assert mode == "unusable", mode
        assert ".skills/merge_mode" in err

    def test_it_reads_the_primary_checkout(self, tmp_path):
        """An untracked knob is absent from a linked worktree (#559's bug)."""
        repo = tmp_path / "r"
        git(tmp_path, "init", "-q", "-b", "main", str(repo))
        (repo / "README.md").write_text("x\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "init")
        (repo / ".skills").mkdir()
        (repo / ".skills" / "merge_mode").write_text("pr\n")
        wt = tmp_path / "wt"
        git(repo, "worktree", "add", "-q", "-b", "feature/x", str(wt))
        assert _merge_mode_sh(wt) == (0, "pr")
        assert _read_mode(wt) == ("pr", "")

    # #584: in a bare primary and a submodule, the first list entry is a git
    # dir, and the reader read it as the checkout: `direct`, in silence, and
    # the hook pushed to main in a repo that asked for review.

    @pytest.mark.parametrize("layout", sorted(layouts.LAYOUTS))
    @pytest.mark.parametrize("text", ["pr\n", "PR\n"], ids=["pr", "PR"])
    def test_it_reads_the_primary_in_each_layout(self, tmp_path, layout, text):
        checkout = layouts.LAYOUTS[layout](tmp_path, text)
        want = (0, "pr") if text == "pr\n" else (2, "")
        assert _merge_mode_sh(checkout) == want, "fixture: merge-mode.sh disagrees"
        mode, err = _read_mode(checkout)
        if want[0] == 0:
            assert (mode, err) == ("pr", ""), "read as direct"
        else:
            assert mode == "unusable", mode
            assert ".skills/merge_mode" in err

    @pytest.mark.parametrize("layout", sorted(layouts.LAYOUTS))
    def test_an_inherited_git_dir_does_not_answer(self, tmp_path, layout):
        """CR 1895: an inherited GIT_DIR beats `-C`, so the submodule's
        entry named itself as the work tree and the read said `direct`."""
        checkout = layouts.LAYOUTS[layout](tmp_path, "pr\n")
        env = clean_env()
        env["GIT_DIR"] = layouts.git(checkout, "rev-parse", "--absolute-git-dir")
        assert _read_mode(checkout, env) == ("pr", "")

    @pytest.mark.parametrize("layout", sorted(layouts.LAYOUTS))
    def test_an_inherited_git_work_tree_does_not_answer(self, tmp_path, layout):
        """CR 1903: an inherited GIT_WORK_TREE beats the submodule's
        core.worktree, so its entry named this linked checkout, whose
        committed knob says `direct`."""
        checkout = layouts.LAYOUTS[layout](tmp_path, "pr\n")
        env = clean_env()
        env["GIT_WORK_TREE"] = str(checkout)
        assert _read_mode(checkout, env) == ("pr", "")

    def test_a_primary_git_cannot_open_is_unusable(self, tmp_path):
        """Only the primary is refused ("dubious ownership"): unusable, with
        git's reason, never a fallback to this checkout or the raw path."""
        repo = tmp_path / "r"
        git(tmp_path, "init", "-q", "-b", "main", str(repo))
        (repo / "README.md").write_text("x\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "init")
        (repo / ".skills").mkdir()
        (repo / ".skills" / "merge_mode").write_text("pr\n")
        wt = tmp_path / "wt"
        git(repo, "worktree", "add", "-q", "-b", "feature/x", str(wt))
        mode, err = _read_mode(wt, layouts.different_owner(clean_env(), wt))
        assert mode == "unusable", mode
        assert "dubious ownership" in err, err
        assert str(repo.resolve()) in err, err

    # CR 1892: a primary whose .git is a pointer file lists its store, which
    # names no work tree. #584 made that unusable from the primary itself,
    # where the hook said "no refresh" daily on a repo with no knob at all.

    @pytest.mark.parametrize(
        ("text", "want"), [(None, "direct"), ("pr\n", "pr")], ids=["absent", "pr"]
    )
    def test_a_separate_git_dir_primary_reads_its_own_knob(self, tmp_path, text, want):
        primary, _ = layouts.separate_git_dir(tmp_path, text)
        assert _read_mode(primary) == (want, "")

    @pytest.mark.parametrize("text", [None, "pr\n"], ids=["absent", "pr"])
    def test_its_linked_worktree_is_unusable_and_says_why(self, tmp_path, text):
        _, linked = layouts.separate_git_dir(tmp_path, text)
        mode, err = _read_mode(linked)
        assert mode == "unusable", mode
        assert layouts.SEPARATE_GIT_DIR_HINT in err, err
        assert "primary checkout" in err, err

    def test_its_store_git_cannot_open_is_never_the_fallback(self, tmp_path):
        _, linked = layouts.separate_git_dir(tmp_path, "pr\n")
        mode, err = _read_mode(linked, layouts.different_owner(clean_env(), linked))
        assert mode == "unusable", mode
        assert "dubious ownership" in err, err
        assert layouts.SEPARATE_GIT_DIR_HINT not in err, err


# --- the PR, kept to one ------------------------------------------------------


class TestOnePr:
    def test_a_day_with_the_same_bump_pushes_nothing_and_opens_nothing(
        self, pr_consumer
    ):
        c = pr_consumer
        assert run_hook(c).returncode == 0
        tip = _origin(c, PR_BRANCH)
        _new_day(c)

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert _origin(c, PR_BRANCH) == tip, "an unchanged bump was re-pushed"
        assert len(_creates(c.gh)) == 1
        _assert_content_matches_pointer(c)

    def test_a_quiet_day_makes_no_network_call_past_the_submodule_fetch(
        self, pr_consumer
    ):
        """Nothing upstream since main recorded it: no gh, no ls-remote."""
        c = pr_consumer
        git(c.path, "submodule", "update", "--remote", "--merge", "--", VENDOR)
        (c.path / DOCTOR_PATH).write_text(c.v2)
        git(c.path, "add", VENDOR, DOCTOR_PATH)
        git(c.path, "commit", "-qm", "manual bump")
        git(c.path, "push", "-q", "origin", "main")

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert _calls(c.gh) == []
        assert _origin(c, PR_BRANCH) == ""
        assert lock(c).read_text().strip() == today()

    def test_a_human_commit_on_the_open_prs_branch_is_left_alone(self, pr_consumer):
        """A bump that needs a repo-side config change (#550's case) is fixed
        on the PR itself. Replacing the branch would destroy that fix."""
        c = pr_consumer
        assert run_hook(c).returncode == 0
        human = c.path.parent / "human"
        git(c.path.parent, "clone", "-q", "-b", PR_BRANCH, str(c.origin), str(human))
        (human / "config.txt").write_text("the knob the new skills read\n")
        git(human, "add", "config.txt")
        git(human, "commit", "-qm", "fix: config for the new skills")
        git(human, "push", "-q", "origin", PR_BRANCH)
        theirs = _origin(c, PR_BRANCH)
        _new_day(c)
        _upstream_moves(c)

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert _origin(c, PR_BRANCH) == theirs, "the human's commit was replaced"
        assert PR_BRANCH in result.stderr, result.stderr
        assert len(_creates(c.gh)) == 1
        _assert_content_matches_pointer(c)

    def test_a_closed_pr_is_not_reopened_for_the_same_bump(self, pr_consumer):
        """Closed unmerged is a human's no to that bump; the next upstream
        change is proposed again (the pin file is how to hold one)."""
        c = pr_consumer
        assert run_hook(c).returncode == 0
        prs = c.gh / "prs"
        n, _, oid = prs.read_text().split()
        prs.write_text(f"{n} CLOSED {_origin(c, PR_BRANCH)}\n")
        _new_day(c)

        quiet = run_hook(c)

        assert quiet.returncode == 0, quiet.stderr
        assert len(_creates(c.gh)) == 1, "a declined bump was proposed again"

        _new_day(c)
        c3 = _upstream_moves(c)
        again = run_hook(c)

        assert again.returncode == 0, again.stderr
        assert len(_creates(c.gh)) == 2
        assert _branch_gitlink(c) == c3

    def test_a_merged_pr_not_yet_pulled_gets_no_bump(self, pr_consumer):
        """The default branch records a newer pointer than local main: a
        checkout that is behind on the hook's paths gets no bump."""
        c = pr_consumer
        other = c.path.parent / "other"
        git(c.path.parent, "clone", "-q", str(c.origin), str(other))
        git(other, "submodule", "update", "-q", "--init", "--remote", "--", VENDOR)
        git(other, "add", VENDOR)
        git(other, "commit", "-qm", MSG_SUB)
        git(other, "push", "-q", "origin", "main")

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert _creates(c.gh) == []
        assert _origin(c, PR_BRANCH) == ""
        assert "pull" in result.stderr, result.stderr
        _assert_content_matches_pointer(c)
        assert git(c.path, "rev-parse", "HEAD").stdout.strip() == c.head0

    def test_an_operators_unpushed_commit_is_not_carried(self, pr_consumer):
        c = pr_consumer
        (c.path / "mine.txt").write_text("unshared\n")
        git(c.path, "add", "mine.txt")
        git(c.path, "commit", "-qm", "feat: my own work", "--", "mine.txt")
        mine = git(c.path, "rev-parse", "HEAD").stdout.strip()

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert _branch_gitlink(c) == c.after
        assert _origin(c, f"{PR_BRANCH}~1") == c.main0
        assert _origin(c, f"{PR_BRANCH}:mine.txt") == ""
        assert git(c.path, "rev-parse", "HEAD").stdout.strip() == mine
        _assert_content_matches_pointer(c)


# --- reported once, never retried --------------------------------------------


class TestReportedOnce:
    def test_gh_absent(self, pr_consumer):
        c = pr_consumer
        (c.bindir / "gh").unlink()
        path = _path_without_gh(c)

        first = _run(c, path)

        assert first.returncode == 0, first.stderr
        assert "gh" in first.stderr and "merge_mode" in first.stderr, first.stderr
        assert _origin(c, PR_BRANCH) == ""
        _main_never_moved(c)
        _assert_content_matches_pointer(c)
        assert lock(c).read_text().strip() == today()

        later = _run(c, path)
        assert later.stderr == "", "reported again the same day"

    def test_a_token_github_rejects(self, pr_consumer):
        """gh has a token (the fake's stored login) and GitHub refuses it. A
        host with no token at all never reaches `gh pr list`: the preflight
        refuses it (test_refresh_hook_pr_gh_auth.py, #576)."""
        c = pr_consumer
        (c.gh / "list_err").write_text(
            "To get started with GitHub CLI, please run:  gh auth login\n"
        )

        first = run_hook(c)

        assert first.returncode == 0, first.stderr
        assert "gh auth login" in first.stderr, first.stderr
        lists = [x for x in _calls(c.gh) if x.startswith("pr list")]
        assert len(lists) == 1, _calls(c.gh)
        assert _origin(c, PR_BRANCH) == ""
        _assert_content_matches_pointer(c)

        later = run_hook(c)
        assert later.stderr == ""
        assert len(_calls(c.gh)) == 1, "gh was asked again the same day"

    def test_a_rule_on_the_pr_branch_too(self, pr_consumer):
        c = pr_consumer
        count = _rule(c, "all")

        first = run_hook(c)

        assert first.returncode == 0, first.stderr
        assert "GH013" in first.stderr, first.stderr
        assert "Changes must be made through a pull request" in first.stderr
        assert PR_BRANCH in first.stderr
        assert _pushes(count) == 1, "the refusal was retried"
        assert _creates(c.gh) == []
        _main_never_moved(c)
        _assert_content_matches_pointer(c)

        later = run_hook(c)
        assert later.stderr == ""
        assert _pushes(count) == 1

    def test_an_unusable_knob_is_never_direct(self, tmp_path):
        c = build(tmp_path)
        _commit_knob(c, "PR\n")
        state = _gh(c)
        count = _rule(c)

        first = run_hook(c)

        assert first.returncode == 0, first.stderr
        assert ".skills/merge_mode" in first.stderr, first.stderr
        assert _pushes(count) == 0, "an unusable knob pushed to main"
        assert _calls(state) == []
        assert origin_gitlink(c) == c.before
        _assert_content_matches_pointer(c)
        assert lock(c).read_text().strip() == today()

        later = run_hook(c)
        assert later.stderr == ""


# --- a kill anywhere converges ------------------------------------------------


class TestAKillAnywhereConverges:
    @pytest.mark.parametrize(
        "when",
        [
            '[ "$1" = read-tree ]',  # after the update, the content ahead
            '[ "$1" = ls-remote ]',  # after the restore, mid-network
            '[ "$1" = push ]',  # at the push
        ],
        ids=["after-update", "mid-network", "at-push"],
    )
    def test_the_next_session_opens_exactly_one_pr(self, pr_consumer, when):
        c = pr_consumer
        write_shim(c, kill_when=when)
        c.kill_flag.write_text("")

        killed = run_hook(c)

        assert killed.returncode < 0, "the fixture never fired"
        assert not lock(c).exists(), "a killed run spent the day"
        write_shim(c)

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert len(_creates(c.gh)) == 1
        assert _branch_gitlink(c) == c.after
        _main_never_moved(c)
        _assert_content_matches_pointer(c)
        assert content(c) == c.before
        assert (c.path / DOCTOR_PATH).read_text() == c.v1
        assert not (c.path / MARKER).exists()
        assert not (c.path / PR_INDEX).exists()
        assert git(c.path, "status", "--porcelain").stdout == ""

    def test_killed_between_the_push_and_the_pr(self, pr_consumer):
        c = pr_consumer
        (c.gh / "kill_create").write_text("")

        assert run_hook(c).returncode < 0
        pushed = _origin(c, PR_BRANCH)
        assert pushed, "the fixture fired before the push"

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert _origin(c, PR_BRANCH) == pushed, "the same bump was pushed again"
        assert len((c.gh / "prs").read_text().splitlines()) == 1
        _assert_content_matches_pointer(c)

    def test_a_second_session_leaves_a_pr_run_in_flight_alone(self, pr_consumer):
        c = pr_consumer
        # Held after the restore and the base's fetch, before gh and the
        # push: the marker must cover the rest of the run.
        write_shim(c, hold_when='[ "$1" = commit-tree ]')
        c.kill_flag.write_text("")
        first = start_hook(c)
        deadline = time.monotonic() + 60
        while not c.held.exists():
            assert time.monotonic() < deadline, "the first run never reached the hold"
            time.sleep(0.05)

        second = run_hook(c)

        assert second.returncode == 0, second.stderr
        assert "another refresh is in flight" in log_text(c)
        assert _calls(c.gh) == [], "the second session reached gh"
        c.release.write_text("")
        assert finish_hook(first).returncode == 0
        assert len(_creates(c.gh)) == 1
        _assert_content_matches_pointer(c)


# --- an earlier direct run's leftovers ----------------------------------------


class TestReconcileInPrMode:
    def test_an_unpushed_hook_commit_is_rolled_back_not_pushed(self, pr_consumer):
        """A bump a `direct` run committed and never pushed, then the repo
        moved to `pr`. Pushing it is what the rule refuses; it is rolled back
        and the PR path redoes the bump in the same run."""
        c = pr_consumer
        count = _rule(c)
        git(c.path, "submodule", "update", "--remote", "--merge", "--", VENDOR)
        git(c.path, "add", VENDOR)
        git(c.path, "commit", "-qm", MSG_SUB, "--", VENDOR)

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert _pushes(count) == 0
        _main_never_moved(c)
        _assert_content_matches_pointer(c)
        assert content(c) == c.before
        assert _branch_gitlink(c) == c.after
        assert len(_creates(c.gh)) == 1

    def test_two_sessions_rolling_back_together_roll_back_once(self, pr_consumer):
        """Both sessions reach this pass ahead of the in-progress marker. A
        relative `reset --soft HEAD~1` run by each would take main one commit
        behind its upstream — the knob's own commit, the operator's."""
        c = pr_consumer
        git(c.path, "submodule", "update", "--remote", "--merge", "--", VENDOR)
        git(c.path, "add", VENDOR)
        git(c.path, "commit", "-qm", MSG_SUB, "--", VENDOR)
        write_shim(c, hold_when='[ "$1" = update-ref ]')
        c.kill_flag.write_text("")
        first = start_hook(c)
        deadline = time.monotonic() + 60
        while not c.held.exists():
            assert time.monotonic() < deadline, "the first run never reached the hold"
            time.sleep(0.05)

        second = run_hook(c)
        c.release.write_text("")
        assert finish_hook(first).returncode == 0

        assert second.returncode == 0, second.stderr
        _main_never_moved(c)
        _assert_content_matches_pointer(c)
        assert len(_creates(c.gh)) == 1

    def test_one_parked_after_the_guards_read_the_range_rolls_back_nothing(
        self, pr_consumer
    ):
        """#566: the swap's expected HEAD was read after the guards, so a
        session parked between them took the other's rollback for its own
        range — and swapped one commit further back, onto the operator's."""
        c = pr_consumer
        git(c.path, "submodule", "update", "--remote", "--merge", "--", VENDOR)
        git(c.path, "add", VENDOR)
        git(c.path, "commit", "-qm", MSG_SUB, "--", VENDOR)
        write_shim(
            c,
            hold_when='[ "$1" = rev-list ] && [ "$2" = --count ] && [ "$3" = --merges ]',
        )
        c.kill_flag.write_text("")
        first = start_hook(c)
        deadline = time.monotonic() + 60
        while not c.held.exists():
            assert time.monotonic() < deadline, "the first run never reached the hold"
            time.sleep(0.05)

        second = run_hook(c)
        c.release.write_text("")
        assert finish_hook(first).returncode == 0

        assert second.returncode == 0, second.stderr
        _main_never_moved(c)
        _assert_content_matches_pointer(c)
        assert "rolling back 1 commit(s) this hook made on main failed" in (
            log_text(c)
        ), log_text(c)


# --- a staged leftover the hook did not mark (CR 1791) -----------------------


class TestAnUnmarkedStagedBumpInPrMode:
    """A checkout left staged by a hook from before #555 (hook paths staged,
    no marker) is not the heal's to undo, because a human's own `git add
    skills-vendor/<v>` looks the same. In `direct` mode the first refresh
    commits it through its own pathspec; `pr` mode never commits here, so the
    prose's "the first refresh … commits it" was false there, and the restore
    logged "restored … to the recorded pointer" while the content stayed on
    the staged bump. The next `git commit` on main absorbs it."""

    def _leftover(self, c) -> None:
        git(c.path / VENDOR, "fetch", "-q", "origin")
        git(c.path / VENDOR, "checkout", "-q", c.after)
        git(c.path, "add", VENDOR)

    def test_it_is_named_once_with_the_reset_and_left_staged(self, pr_consumer):
        """The reviewer's reproduction."""
        c = pr_consumer
        self._leftover(c)

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert staged(c) == [VENDOR], "an unmarked staged bump was unstaged"
        assert result.stderr.count(f"git reset -q -- {VENDOR}") == 1, result.stderr
        assert "no in-progress marker" in result.stderr, result.stderr
        assert len(_creates(c.gh)) == 1, "the PR path stopped proposing"
        _main_never_moved(c)

        again = run_hook(c)

        assert again.stderr == "", "said again behind a spent day's lock"

    def test_the_restore_names_the_pointer_it_restored_to(self, pr_consumer):
        """Content goes back to the pointer the INDEX records, the staged
        bump, which may be a human's, and the log says which."""
        c = pr_consumer
        self._leftover(c)

        run_hook(c)

        assert content(c) == c.after
        log = log_text(c)
        assert f"HEAD records {c.before[:7]}" in log, log
        assert f"{VENDOR} to the recorded pointer" not in log, log

    def test_with_nothing_staged_it_names_heads_pointer(self, pr_consumer):
        c = pr_consumer

        result = run_hook(c)

        assert result.stderr == "", result.stderr
        assert f"{c.before[:7]}, the pointer HEAD and the index both record" in (
            log_text(c)
        ), log_text(c)


# --- the doctor report after a restore (CR 1794) -----------------------------


class TestTheDoctorReportAfterARestore:
    """`_restore_content` is a third caller of `_install_doctor`, and in `pr`
    mode always the run's last, so the EXIT trap reports the restore's
    install. When the restored pointer's installer is broken but the bump's
    worked, the tree holds the doctor call site 2 installed from the bump,
    and "left as it was" says the run did not change it."""

    def test_a_failed_reinstall_does_not_say_left_as_it_was(self, pr_consumer):
        c = pr_consumer
        scripts = c.up / MS_SCRIPTS
        (scripts / "install-doctor.sh").write_text("#!/usr/bin/env bash\nexit 1\n")
        broken = _vendor_commit(c.up, c.v1 + "# fixture: broken\n", "broken")
        git(c.path / VENDOR, "fetch", "-q", "origin")
        git(c.path / VENDOR, "checkout", "-q", broken)
        git(c.path, "add", VENDOR)
        git(c.path, "commit", "-qm", "chore: vendor at a broken installer")
        git(c.path, "push", "-q", "origin", "main")
        shutil.copy2(INSTALLER, scripts / "install-doctor.sh")
        bumped_doctor = c.v2 + "# fixture: fixed\n"
        _vendor_commit(c.up, bumped_doctor, "fixed")

        result = run_hook(c)

        assert result.returncode == 0, result.stderr
        assert content(c) == broken, "the content did not go back"
        assert (c.path / DOCTOR_PATH).read_text() == bumped_doctor, (
            "fixture: call site 2 should have installed the bump's doctor"
        )
        assert "could not" in result.stderr and DOCTOR_PATH in result.stderr, (
            result.stderr
        )
        assert "left as it was" not in result.stderr, (
            "the run replaced the doctor and could not put it back, and "
            f"said it had left it as it was:\n{result.stderr}"
        )
        assert "restored pointer" in result.stderr, result.stderr


def _second_clone(c, tmp_path):
    """Another machine's clone of the same consumer, made before any PR, so
    the hook's PR commits were never in its object store."""
    b = tmp_path / "work-b"
    git(tmp_path, "clone", "-q", "--recurse-submodules", str(c.origin), str(b))
    git(b, "config", "core.hooksPath", str(b / ".git" / "hooks"))
    other = copy.copy(c)
    other.path = b
    return other


def _decline(c, *, keep_branch: bool, pull_ref: bool = True) -> str:
    """The open PR closed unmerged, as GitHub records it: `refs/pull/<n>/head`
    on the base repo keeps its head, whether or not the branch is deleted.

    The head is re-made on the remote with the same tree, parent and message
    but another date — the same bump, written by another clone. Without that,
    a second clone running in the same second builds a byte-identical commit
    (commit-tree, same tree, parent, identity and timestamp), already has the
    "missing" head, and never exercises the fetch: measured on Linux."""
    prs = c.gh / "prs"
    n, _, _ = prs.read_text().split()
    made_here = _origin(c, PR_BRANCH)
    env = clean_env()
    env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = "2001-01-01T00:00:00Z"
    head = subprocess.run(
        [
            "git",
            "commit-tree",
            f"{made_here}^{{tree}}",
            "-p",
            f"{made_here}^",
            "-m",
            git(c.origin, "log", "-1", "--format=%B", made_here).stdout,
        ],
        cwd=c.origin,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    git(c.origin, "update-ref", f"refs/heads/{PR_BRANCH}", head)
    prs.write_text(f"{n} CLOSED {head}\n")
    if pull_ref:
        git(c.origin, "update-ref", f"refs/pull/{n}/head", head)
    if not keep_branch:
        git(c.origin, "update-ref", "-d", f"refs/heads/{PR_BRANCH}")
    return n


class TestADeclineMadeElsewhere:
    """CR 1802: the declined-bump check compared the closed PR's head with
    this run's commit, and a head not in this clone's object store — the PR
    was proposed from another clone, or gc pruned it after the branch was
    deleted — compared as "not the same", so a declined bump was proposed
    again. The head is fetched from `refs/pull/<n>/head` first."""

    def test_a_second_clone_does_not_propose_a_declined_bump(
        self, pr_consumer, tmp_path
    ):
        """The reviewer's reproduction: the branch kept, the PR closed, and a
        clone that never saw the PR's commit."""
        c = pr_consumer
        other = _second_clone(c, tmp_path)
        assert run_hook(c).returncode == 0
        _decline(c, keep_branch=True)

        result = run_hook(other)

        assert result.returncode == 0, result.stderr
        assert len(_creates(c.gh)) == 1, "a declined bump was proposed again"
        assert "closed unmerged" in log_text(other), log_text(other)

    def test_the_branch_deleted_after_closing(self, pr_consumer, tmp_path):
        c = pr_consumer
        other = _second_clone(c, tmp_path)
        assert run_hook(c).returncode == 0
        _decline(c, keep_branch=False)

        result = run_hook(other)

        assert result.returncode == 0, result.stderr
        assert len(_creates(c.gh)) == 1, "a declined bump was proposed again"
        assert _origin(c, PR_BRANCH) == "", "the declined bump was pushed again"

    def test_a_head_that_cannot_be_fetched_proposes_nothing_this_run(
        self, pr_consumer, tmp_path
    ):
        """Unable to tell, the run proposes nothing and says so once: a
        proposal a human already closed is a visible write, and the next
        day's run checks again."""
        c = pr_consumer
        other = _second_clone(c, tmp_path)
        assert run_hook(c).returncode == 0
        n = _decline(c, keep_branch=False, pull_ref=False)

        result = run_hook(other)

        assert result.returncode == 0, result.stderr
        assert len(_creates(c.gh)) == 1
        assert result.stderr.count(f"PR #{n}") == 1, result.stderr + log_text(other)
        assert "declined" in result.stderr, result.stderr
        assert lock(other).read_text().strip() == today()
        _assert_content_matches_pointer(other)
