"""Flag-position parity across the using-git-worktrees scripts (#262).

The four scripts in `skills/using-git-worktrees/scripts/` carried three
different argument conventions, and the two that disagreed most each
mis-diagnosed the other's habit by naming the wrong token:

- `destroy --force <branch>` read '--force' AS the branch (a blind positional
  `$1` with no shape check), shifted past it, and handed the real branch to the
  unknown-flag arm. The error named the one argument that was correct.
- `create <branch> --new` dropped the trailing flag in silence; the failure
  surfaced as git's `fatal: invalid reference: <branch>`.
- `--help` was recognised only as `$1` in both. On create that was
  side-effecting: `create <existing-branch> --help` provisioned a worktree and
  printed its path instead of printing help.
- `worktree-list.sh` ignored unrecognised arguments entirely and exited 0, so a
  `--porcelian` typo silently produced human-readable output.
- `audit-worktree-zombies.sh` reported a bare word as an "unknown flag".

`--force` is the routine destroy invocation for any repo with submodules
(`git worktree remove` refuses those without it), so the destroy direction was
hit on ordinary use, not at an edge.

These tests own the PARITY rather than any one script's behaviour: divergence
between siblings is the defect that recurs.

**Every flag exercised here is load-bearing, and each has a control test
asserting the command FAILS without it.** An earlier version of this file
parametrized position over flags that were inert in the fixture — the branch
was already merged and the worktree already clean — so all of it passed with
`--force` neutered to a no-op. A parity test that only proves `<branch>` parsed
would have shipped a silent `--force` regression, which is the original bug's
user-visible symptom (the worktree stays in place) with a green suite.

No API calls. Self-contained: each test gets a fresh tmp repo.
"""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "using-git-worktrees"
    / "scripts"
)
CREATE = SCRIPTS / "worktree-create.sh"
DESTROY = SCRIPTS / "worktree-destroy.sh"
LIST = SCRIPTS / "worktree-list.sh"
AUDIT = SCRIPTS / "audit-worktree-zombies.sh"


def _scrubbed() -> dict:
    """Env without inherited GIT_* vars.

    An inherited GIT_DIR outranks both `git -C` and the process cwd, and git
    exports it to every hook — so under pre-commit a throwaway fixture would
    address the real repo (docs/STYLE.md, #189).
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run git against the fixture. check=True so setup failures raise HERE.

    Provisioning used to go through worktree-create.sh unchecked, which meant a
    create regression surfaced as a destroy assertion ("flag-first destroy must
    work") — the same misdiagnosis-by-wrong-token that #262 is about, rebuilt
    inside the test that guards it.
    """
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=_scrubbed(),
    )


def _run(script: Path, repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = _scrubbed()
    env["WORKTREE_ROOT"] = str(repo / ".worktrees")
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=env,
    )


def _worktree_paths(repo: Path) -> list:
    """Registered worktree paths, main checkout included."""
    return [
        line[len("worktree ") :]
        for line in _git(repo, "worktree", "list", "--porcelain").stdout.splitlines()
        if line.startswith("worktree ")
    ]


def _provision(repo: Path, branch: str) -> Path:
    """Register a worktree for `branch` with git directly, not via create.sh.

    destroy.sh resolves by branch through git's registry, so the leaf name is
    immaterial; using the slug scheme keeps it consistent with the constructed
    fallback path.
    """
    path = repo / ".worktrees" / branch.replace("/", "-")
    _git(repo, "worktree", "add", str(path), branch)
    return path


def _dirty(worktree: Path) -> None:
    """Make git refuse removal without --force.

    `git worktree remove` on a worktree with modified tracked files exits 128
    with 'contains modified or untracked files, use --force to delete it'.
    This is what makes --force observable.
    """
    (worktree / "README.md").write_text("modified in the worktree\n")


def _ordered(branch: str, flag: list, position: str) -> list:
    """Build an argv with `flag` before or after `<branch>`."""
    return [*flag, branch] if position == "before" else [branch, *flag]


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """A repo with both a merged and an unmerged branch.

    `merged` sits on main's commit (trivially an ancestor, Iron Law passes).
    `unmerged` is one commit ahead of main, so the Iron Law REFUSES it unless
    --descoped is honoured — which is what makes that flag observable.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("initial\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")

    _git(repo, "branch", "merged")

    _git(repo, "checkout", "-q", "-b", "unmerged")
    (repo / "ahead.txt").write_text("ahead\n")
    _git(repo, "add", "ahead.txt")
    _git(repo, "commit", "-m", "ahead of main")
    _git(repo, "checkout", "-q", "main")

    # A local-only integration branch at `unmerged`'s commit, mirroring a
    # multi-agent orchestration: the worker branch is an ancestor of batch/x
    # but NOT of main, which is the case --base exists to serve.
    _git(repo, "branch", "batch/x", "unmerged")

    (repo / ".worktrees").mkdir()
    return repo


# --- The two filed repros --------------------------------------------------


def test_destroy_accepts_force_before_branch(tmp_repo: Path):
    """`destroy --force <branch>` must not read '--force' as the branch.

    The filed repro: the error named 'feat/some-branch', the one token that was
    correct, and the worktree stayed in place. The worktree is dirtied first so
    this also proves --force reached `git worktree remove`.
    """
    worktree = _provision(tmp_repo, "merged")
    _dirty(worktree)
    result = _run(DESTROY, tmp_repo, "--force", "merged")
    assert result.returncode == 0, (
        f"flag-first destroy must work, got {result.returncode}\nstderr: {result.stderr}"
    )
    assert "unknown flag 'merged'" not in result.stderr, (
        "the branch must never be reported as a flag"
    )
    assert str(worktree) not in _worktree_paths(tmp_repo)


def test_create_accepts_new_after_branch(tmp_repo: Path):
    """`create <branch> --new` must create the branch, not drop the flag."""
    result = _run(CREATE, tmp_repo, "feat/trailing", "--new")
    assert result.returncode == 0, (
        f"trailing --new must be honoured, got {result.returncode}\n"
        f"stderr: {result.stderr}"
    )
    assert "invalid reference" not in result.stderr
    assert "feat/trailing" in _git(tmp_repo, "branch", "--list", "feat/trailing").stdout


# --- Controls: each flag below is proven load-bearing before parity is tested


def test_dirty_worktree_refuses_without_force(tmp_repo: Path):
    """Control for --force: without it, a dirty worktree must NOT be removed."""
    worktree = _provision(tmp_repo, "merged")
    _dirty(worktree)
    result = _run(DESTROY, tmp_repo, "merged")
    assert result.returncode == 2, (
        f"a dirty worktree must refuse removal without --force, "
        f"got {result.returncode}\nstderr: {result.stderr}"
    )
    assert str(worktree) in _worktree_paths(tmp_repo), "the worktree must survive"


def test_unmerged_branch_refuses_without_descoped(tmp_repo: Path):
    """Control for --descoped: the Iron Law must refuse an unmerged branch."""
    _provision(tmp_repo, "unmerged")
    result = _run(DESTROY, tmp_repo, "unmerged")
    assert result.returncode == 1, (
        f"expected Iron Law exit 1, got {result.returncode}\nstderr: {result.stderr}"
    )


def test_create_refuses_nonexistent_branch_without_new(tmp_repo: Path):
    """Control for --new: without it, a nonexistent branch must fail."""
    result = _run(CREATE, tmp_repo, "feat/nope")
    assert result.returncode == 2, (
        f"expected exit 2 without --new, got {result.returncode}\n"
        f"stderr: {result.stderr}"
    )


# --- Parity: the same flag, either side of <branch>, same effect ------------


@pytest.mark.parametrize("position", ["before", "after"])
def test_force_removes_dirty_worktree_in_either_position(tmp_repo: Path, position: str):
    """--force must take EFFECT from either position, not merely parse."""
    worktree = _provision(tmp_repo, "merged")
    _dirty(worktree)
    result = _run(DESTROY, tmp_repo, *_ordered("merged", ["--force"], position))
    assert result.returncode == 0, (
        f"--force {position} <branch> must remove a dirty worktree, "
        f"got {result.returncode}\nstderr: {result.stderr}"
    )
    assert str(worktree) not in _worktree_paths(tmp_repo)


@pytest.mark.parametrize("position", ["before", "after"])
def test_descoped_overrides_iron_law_in_either_position(tmp_repo: Path, position: str):
    """--descoped must take EFFECT from either position."""
    worktree = _provision(tmp_repo, "unmerged")
    args = _ordered("unmerged", ["--descoped", "probe"], position)
    result = _run(DESTROY, tmp_repo, *args)
    assert result.returncode == 0, (
        f"--descoped {position} <branch> must override the Iron Law, "
        f"got {result.returncode}\nstderr: {result.stderr}"
    )
    assert "probe" in result.stdout, "the descope reason must be echoed"
    assert str(worktree) not in _worktree_paths(tmp_repo)


@pytest.mark.parametrize("position", ["before", "after"])
def test_base_override_in_either_position(tmp_repo: Path, position: str):
    """--base must take EFFECT from either position.

    Shares its control with --descoped: test_unmerged_branch_refuses_without_
    descoped proves the default base (main) refuses this branch, so a destroy
    that succeeds here can only have honoured --base. Value-consuming flags are
    the risky shape in first position, since `shift 2` runs before <branch> is
    set — this covers that shape a second time alongside --descoped.
    """
    worktree = _provision(tmp_repo, "unmerged")
    args = _ordered("unmerged", ["--base", "batch/x"], position)
    result = _run(DESTROY, tmp_repo, *args)
    assert result.returncode == 0, (
        f"--base {position} <branch> must verify against the given ref, "
        f"got {result.returncode}\nstderr: {result.stderr}"
    )
    assert str(worktree) not in _worktree_paths(tmp_repo)


@pytest.mark.parametrize("position", ["before", "after"])
def test_new_creates_branch_in_either_position(tmp_repo: Path, position: str):
    """--new must take EFFECT from either position."""
    branch = f"feat/{position}"
    result = _run(CREATE, tmp_repo, *_ordered(branch, ["--new"], position))
    assert result.returncode == 0, (
        f"--new {position} <branch> must create the branch, got {result.returncode}\n"
        f"stderr: {result.stderr}"
    )
    assert branch in _git(tmp_repo, "branch", "--list", branch).stdout


# --- The other two scripts' flags must take effect too ---------------------


def test_porcelain_selects_porcelain_output(tmp_repo: Path):
    """--porcelain must actually change the output format.

    Nothing covered this: with PORCELAIN neutered to 0, all 28 tests passed —
    the same gap this file was rewritten to close, reintroduced in the commit
    that closed it. orchestrating-issue-backlog counts worktree slots with
    `worktree-list.sh --porcelain | grep -c '^worktree '`, so a dropped flag
    yields 0, reads as "no slots consumed", and over-provisions against the
    project ceiling — silently, and in the unsafe direction.
    """
    _provision(tmp_repo, "merged")

    porcelain = _run(LIST, tmp_repo, "--porcelain")
    assert porcelain.returncode == 0, porcelain.stderr
    keyed = [ln for ln in porcelain.stdout.splitlines() if ln.startswith("worktree ")]
    assert len(keyed) == 2, (
        "--porcelain must emit one 'worktree <path>' key per worktree "
        f"(main + merged); got {porcelain.stdout!r}"
    )

    default = _run(LIST, tmp_repo)
    assert default.returncode == 0, default.stderr
    assert not [
        ln for ln in default.stdout.splitlines() if ln.startswith("worktree ")
    ], "the default output must NOT be porcelain, or the flag proves nothing"


def test_quiet_silences_the_audit(tmp_repo: Path):
    """--quiet must actually silence the audit's stdout."""
    loud = _run(AUDIT, tmp_repo)
    assert loud.returncode == 0, loud.stderr
    assert loud.stdout.strip(), "without --quiet the audit reports its verdict"

    quiet = _run(AUDIT, tmp_repo, "--quiet")
    assert quiet.returncode == 0, quiet.stderr
    assert quiet.stdout == "", f"--quiet must print nothing, got {quiet.stdout!r}"


def test_create_source_redirects_the_audit_call():
    """SOURCE-SHAPE check, not a behavioural one — see the caveat below.

    create's stdout contract must not depend on the audit honouring --quiet.

    create's stdout is exactly the worktree path. It runs the audit as a
    pre-flight, and neutering QUIET in the audit failed nine tests in
    test_worktree_venv_knob.py — a file about the venv knob, which is where the
    breakage would have been misdiagnosed. The redirect makes the isolation
    structural rather than a behaviour of the child.

    This asserts the shape of the CALL, not the behaviour: it cannot catch the
    audit growing a second stdout path that ignores --quiet. A behavioural
    version would have to fabricate a zombie — a background process whose argv
    references a deleted worktree path — which is racy and spawns processes in
    the suite. The redirect is what actually provides the guarantee; this test
    only keeps it from being removed.
    """
    calls = [
        line
        for line in CREATE.read_text().splitlines()
        if "audit-worktree-zombies.sh" in line
        and "--quiet" in line
        and not line.lstrip().startswith("#")
    ]
    assert calls, "expected worktree-create.sh to invoke the audit with --quiet"
    for line in calls:
        assert ">/dev/null" in line, (
            "the audit's stdout must be redirected, not merely quietened: "
            f"{line.strip()!r}"
        )


# --- Properties every script in the directory must share -------------------


@pytest.mark.parametrize(
    "script", [CREATE, DESTROY, LIST, AUDIT], ids=["create", "destroy", "list", "audit"]
)
def test_help_works_in_any_position(tmp_repo: Path, script: Path):
    """A trailing --help prints help in all four scripts.

    worktree-list.sh already scanned every argument for --help and said why in
    a comment; the other three did not follow it.
    """
    result = _run(script, tmp_repo, "merged", "--help")
    assert result.returncode == 0, (
        f"trailing --help must exit 0, got {result.returncode}\nstderr: {result.stderr}"
    )
    assert result.stdout.startswith("Usage:"), (
        f"trailing --help must print usage, got: {result.stdout[:120]!r}"
    )


def test_help_after_existing_branch_does_not_provision(tmp_repo: Path):
    """The escalation: a documentation request must not mutate the repo.

    `create <existing-branch> --help` fell through to provisioning — it created
    a worktree and printed its path where help was asked for.
    """
    before = _worktree_paths(tmp_repo)
    result = _run(CREATE, tmp_repo, "merged", "--help")
    assert result.stdout.startswith("Usage:")
    assert _worktree_paths(tmp_repo) == before, "--help must never provision a worktree"


@pytest.mark.parametrize("script", [CREATE, DESTROY], ids=["create", "destroy"])
def test_second_positional_is_rejected_by_name(tmp_repo: Path, script: Path):
    """create and destroy take ONE positional; a second is named in the error.

    create dropped it silently; destroy called it an "unknown flag", which a
    bare word is not. Asserting the token — 'stray', not just the phrase — is
    the point: reporting the wrong token is the whole subject of #262.
    """
    result = _run(script, tmp_repo, "merged", "stray")
    assert result.returncode == 2, (
        f"expected tooling exit 2, got {result.returncode}\nstderr: {result.stderr}"
    )
    assert "unexpected argument 'stray'" in result.stderr, (
        f"the SECOND positional must be the token named; got: {result.stderr!r}"
    )
    assert "unknown flag" not in result.stderr, "a bare word must not be called a flag"


@pytest.mark.parametrize("script", [LIST, AUDIT], ids=["list", "audit"])
def test_any_positional_is_rejected_by_name(tmp_repo: Path, script: Path):
    """list and audit take NO positionals; the first bare word is the error.

    Kept separate from the create/destroy case rather than parametrized with
    it: passing ("merged", "stray") to these two reports 'merged', so a shared
    test asserting on a generic phrase silently checked a different token than
    its name implied.
    """
    result = _run(script, tmp_repo, "stray")
    assert result.returncode == 2, (
        f"expected tooling exit 2, got {result.returncode}\nstderr: {result.stderr}"
    )
    assert "unexpected argument 'stray'" in result.stderr
    assert "unknown flag" not in result.stderr, "a bare word must not be called a flag"


@pytest.mark.parametrize(
    "script", [CREATE, DESTROY, LIST, AUDIT], ids=["create", "destroy", "list", "audit"]
)
def test_unknown_flag_is_rejected(tmp_repo: Path, script: Path):
    """An unrecognised flag is an error in all four, not a silent no-op.

    worktree-list.sh used to ignore it and exit 0, so `--porcelian` produced
    human-readable output and a caller parsing porcelain keys got none.
    """
    result = _run(script, tmp_repo, "--bogus")
    assert result.returncode == 2, (
        f"expected exit 2, got {result.returncode}\nstderr: {result.stderr}"
    )
    assert "unknown flag '--bogus'" in result.stderr


@pytest.mark.parametrize(
    "script", [CREATE, DESTROY, LIST, AUDIT], ids=["create", "destroy", "list", "audit"]
)
def test_argument_error_does_not_bury_the_diagnosis(tmp_repo: Path, script: Path):
    """An argument error prints a short hint, not the whole usage block.

    The full dump (23 lines for create, 69 for destroy) printed to stderr
    directly under the ERROR line, so the diagnosis scrolled off the top and a
    `| tail` on the output showed only boilerplate — which is how the #262
    misdiagnosis was lost. `--help` still prints everything.
    """
    result = _run(script, tmp_repo, "--bogus")
    assert result.returncode == 2
    lines = [ln for ln in result.stderr.splitlines() if ln.strip()]
    assert lines[0].startswith("ERROR:"), "the diagnosis must come first"
    assert len(lines) <= 4, (
        f"argument errors must stay short enough to survive a `| tail`; "
        f"got {len(lines)} lines: {lines!r}"
    )
    assert "--help" in result.stderr, "the short hint must point at the full usage"

    full = _run(script, tmp_repo, "--help")
    assert len(full.stdout.splitlines()) > len(lines), (
        "--help must still print the full description"
    )
