"""#335 — audit-worktree-zombies.sh finds a zombie on macOS too.

The audit enumerated candidates with `pgrep -af`. On Linux (procps) `-a`
prints the full command line; on macOS and the BSDs it means "include the
ancestors in the match", so each line was a bare PID. With no command line
there was no worktree path to extract, every candidate was skipped, and the
audit printed "No worktree zombies." and exited 0 — fail-open, and quietly.
The repo's ship gate runs on a Mac, so no test saw it.

Two tiers here, so the regression shows on either runner:

- **Stubs.** `pgrep` is stubbed on PATH in both platforms' `-af` shapes. The
  fix no longer calls it, so what the stub now catches is a return to
  `pgrep -af`: the BSD shape fails on any runner, not only on a Mac. A `ps`
  stub prints a canned table, which holds the width (`-ww`), failure (exit 2)
  and name-ending cases the real `ps` can't be made to show.
- **Real processes.** A process whose argv names a vanished worktree, found by
  whatever `ps` the runner has. These also hold the issue's second part: the
  shell that ran the audit, and its parents, are never listed, so the printed
  `Kill all:` recipe never kills the caller.

No API calls. Each test gets a fresh tmp repo.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "using-git-worktrees"
    / "scripts"
)
AUDIT = SCRIPTS / "audit-worktree-zombies.sh"
CREATE = SCRIPTS / "worktree-create.sh"

STUB_PID = "4242"
LIVE_PID = "4243"


def _scrubbed() -> dict:
    """Env without inherited GIT_* vars (docs/STYLE.md, #189)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=_scrubbed(),
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "commit", "--allow-empty", "-m", "initial")
    (repo / ".worktrees" / "live").mkdir(parents=True)
    return repo


def _root(repo: Path) -> Path:
    return repo / ".worktrees"


def _env(repo: Path, stubs: Path | None = None, **extra: str) -> dict:
    env = _scrubbed()
    env["WORKTREE_ROOT"] = str(_root(repo))
    if stubs is not None:
        env["PATH"] = f"{stubs}{os.pathsep}{env['PATH']}"
    env.update(extra)
    return env


def _audit(repo: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(AUDIT), *args],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=env,
        timeout=60,
    )


def _listed(stdout: str) -> set:
    """PIDs the audit listed as zombies (its `  <pid> <cmdline>` lines)."""
    return set(re.findall(r"^  (\d+) ", stdout, re.MULTILINE))


def _write_stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def _stubs(tmp_path: Path, repo: Path, pgrep_shape: str, ps_body: str = "") -> Path:
    """`pgrep` in one platform's `-af` shape, and `ps` printing a canned table.

    The table holds a zombie (its worktree is gone) and a live process (its
    worktree exists), as `<pid> <ppid> <args>`. Like procps, the `ps` stub cuts
    each line at `$COLUMNS` unless it was asked for unlimited width (`ww`).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    root = _root(repo)
    zombie_cmd = f"python3 -c pass {root}/ghost-branch/x"
    live_cmd = f"python3 -c pass {root}/live/server.py"
    table = tmp_path / "ps-table"
    table.write_text(
        f"    1     0 /sbin/init\n"
        f" {STUB_PID}     1 {zombie_cmd}\n"
        f" {LIVE_PID}     1 {live_cmd}\n"
    )
    if pgrep_shape == "bsd":
        pgrep_out = f"{STUB_PID}\n{LIVE_PID}\n"
    else:
        pgrep_out = f"{STUB_PID} {zombie_cmd}\n{LIVE_PID} {live_cmd}\n"
    (tmp_path / "pgrep-out").write_text(pgrep_out)
    _write_stub(bin_dir / "pgrep", f'cat "{tmp_path / "pgrep-out"}"\n')
    _write_stub(
        bin_dir / "ps",
        ps_body
        or (
            "wide=0\n"
            'for a in "$@"; do case "$a" in *ww*) wide=1 ;; esac; done\n'
            'if [ "$wide" = 1 ] || [ -z "${COLUMNS:-}" ]; then\n'
            f'  cat "{table}"\n'
            "else\n"
            f'  cut -c "1-$COLUMNS" "{table}"\n'
            "fi\n"
        ),
    )
    return bin_dir


# --- Stubs: both platforms' output shapes, on any runner ---------------------


@pytest.mark.parametrize("shape", ["bsd", "procps"])
def test_a_zombie_is_found_whatever_pgrep_prints(tmp_path, repo, shape):
    """The filed bug: under BSD `pgrep -af` (bare PIDs) nothing was found."""
    stubs = _stubs(tmp_path, repo, shape)
    result = _audit(repo, _env(repo, stubs))
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert _listed(result.stdout) == {STUB_PID}, result.stdout
    assert f"{_root(repo)}/ghost-branch/x" in result.stdout, (
        "the zombie's command line is printed, so the operator can judge it"
    )


def test_a_command_line_longer_than_the_terminal_is_not_cut(tmp_path, repo):
    """procps cuts `args` at `$COLUMNS` without `ww`; a wrapper exporting
    COLUMNS would cut the worktree path off and fail open again."""
    stubs = _stubs(tmp_path, repo, "bsd")
    columns = str(len(f" {STUB_PID}     1 python3 -c pass "))
    result = _audit(repo, _env(repo, stubs, COLUMNS=columns))
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert _listed(result.stdout) == {STUB_PID}, result.stdout


def test_a_failing_ps_is_a_tooling_failure_not_a_clean_bill(tmp_path, repo):
    """Exit 2 is the documented tooling-failure code; "No worktree zombies."
    from an audit that read no process table is the fail-open this issue is."""
    stubs = _stubs(
        tmp_path,
        repo,
        "bsd",
        ps_body='echo "ps: operation not permitted" >&2\nexit 1\n',
    )
    result = _audit(repo, _env(repo, stubs))
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    assert "No worktree zombies." not in result.stdout
    assert "operation not permitted" in result.stderr, (
        "the failing tool's own stderr reaches the operator"
    )


def test_create_says_the_audit_failed_not_that_zombies_exist(tmp_path, repo):
    """create's preamble told every non-zero exit apart from 0 only, so an
    audit that could not run would have been reported as zombies found."""
    stubs = _stubs(
        tmp_path,
        repo,
        "bsd",
        ps_body='echo "ps: operation not permitted" >&2\nexit 1\n',
    )
    result = subprocess.run(
        ["bash", str(CREATE), "--new", "feat/x"],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_env(repo, stubs),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "zombies detected" not in result.stderr, result.stderr
    assert "could not run" in result.stderr, result.stderr


def _table_stubs(tmp_path: Path, repo: Path, *args_lines: str) -> Path:
    """`ps` printing one process per `args` line, PIDs from 5000 up."""
    table = tmp_path / "ps-table-given"
    table.write_text(
        "".join(f" {5000 + i}     1 {args}\n" for i, args in enumerate(args_lines))
    )
    return _stubs(tmp_path, repo, "bsd", f'cat "{table}"\n')


# Shell text names a worktree followed by punctuation that ends the word. A
# live session's `cd <root>/live; …` was listed as a zombie of `live;`, and its
# `Kill all:` recipe would have killed that session's running commands. Found
# by the issue's real repro on the operator's Mac once the audit could see.
PUNCTUATED = [
    "bash -c cd {wt}; exec sleep 60",
    "bash -c cd '{wt}' && sleep 60",
    'bash -c cd "{wt}" && sleep 60',
    "bash -c (cd {wt}) && sleep 60",
    "bash -c cd {wt}&&sleep 60",
    "bash -c ls {wt}|wc -l",
    "env PATH={wt}:/usr/bin sleep 60",
    "bash -c echo `ls {wt}`",
]


@pytest.mark.parametrize(
    "template", PUNCTUATED, ids=[";", "'", '"', ")", "&", "|", ":", "`"]
)
def test_punctuation_after_a_live_worktree_is_not_part_of_its_name(
    tmp_path, repo, template
):
    stubs = _table_stubs(tmp_path, repo, template.format(wt=_root(repo) / "live"))
    result = _audit(repo, _env(repo, stubs))
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert _listed(result.stdout) == set(), result.stdout


@pytest.mark.parametrize(
    "template", PUNCTUATED, ids=[";", "'", '"', ")", "&", "|", ":", "`"]
)
def test_punctuation_after_a_vanished_worktree_still_finds_it(tmp_path, repo, template):
    """Control: the same text naming a vanished worktree is a zombie."""
    stubs = _table_stubs(
        tmp_path, repo, template.format(wt=_root(repo) / "ghost-branch")
    )
    result = _audit(repo, _env(repo, stubs))
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert _listed(result.stdout) == {"5000"}, result.stdout


# --- Real processes: whatever ps this runner has -----------------------------


@pytest.fixture
def zombie(repo):
    """A real process whose argv names a worktree that does not exist."""
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(120)",
            f"{_root(repo)}/ghost-branch/x",
        ]
    )
    yield str(proc.pid)
    proc.kill()
    proc.wait()


def test_a_real_zombie_is_found(repo, zombie):
    """The issue's repro, on the runner's own ps."""
    result = _audit(repo, _env(repo))
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert zombie in _listed(result.stdout), result.stdout


def _run_from(repo: Path, script: str) -> tuple:
    """Run `script` under `bash -c`; it prints `CALLER=<pid>` lines first."""
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_env(repo, AUDIT=str(AUDIT)),
        timeout=60,
    )
    callers = set(re.findall(r"^CALLER=(\d+)$", result.stdout, re.MULTILINE))
    return result, callers


def test_the_shell_that_ran_the_audit_is_never_listed(repo, zombie):
    """The issue's Linux finding: a caller whose own command text names a
    vanished worktree was listed, so `Kill all:` would kill the caller."""
    # `; exit $rc` keeps bash from exec'ing the audit in the caller's place.
    script = (
        f": {_root(repo)}/ghost-caller/y\n"
        'echo "CALLER=$$"\n'
        'bash "$AUDIT"; rc=$?; exit $rc\n'
    )
    result, callers = _run_from(repo, script)
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert zombie in _listed(result.stdout), result.stdout
    assert len(callers) == 1
    assert not callers & _listed(result.stdout), result.stdout


def test_no_ancestor_of_the_audit_is_listed(repo, zombie):
    """Under create's preamble the wrapper is the audit's grandparent, so
    excluding `$PPID` alone is not enough: the whole chain is the caller."""
    inner = 'echo "CALLER=$$"; bash "$AUDIT"; rc=$?; exit $rc'
    script = (
        f": {_root(repo)}/ghost-caller/y\n"
        'echo "CALLER=$$"\n'
        f"bash -c '{inner}' : {_root(repo)}/ghost-inner/z; rc=$?; exit $rc\n"
    )
    result, callers = _run_from(repo, script)
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert zombie in _listed(result.stdout), result.stdout
    assert len(callers) == 2
    assert not callers & _listed(result.stdout), result.stdout


def test_a_live_worktree_process_is_not_listed(repo):
    """Control: a process in a worktree that still exists is no zombie."""
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(120)",
            f"{_root(repo)}/live/server.py",
        ]
    )
    try:
        result = _audit(repo, _env(repo))
    finally:
        proc.kill()
        proc.wait()
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert result.stdout.strip() == "No worktree zombies."


# --- Both spellings of the root (#533, CR 1242) ------------------------------
#
# A root reached through a symlink has two spellings: as configured, and
# resolved. The audit matched the configured one only, so a process started
# under the resolved spelling was missed and the audit said "No worktree
# zombies." On macOS, /tmp is a symlink to /private/tmp. The match is a
# substring, so a /tmp root already found /private/tmp/... names; here `link`
# and `real` share no such overlap, which is the general case.


@pytest.fixture
def linked_root(repo, tmp_path):
    """`(configured, resolved)`: a root configured through a symlink."""
    real = tmp_path / "real-wt"
    (real / "live").mkdir(parents=True)
    link = tmp_path / "link-wt"
    link.symlink_to(real, target_is_directory=True)
    return link, real.resolve()


def _sleeper(*argv_tail: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)", *argv_tail]
    )


def _audit_with_root(repo: Path, root: Path) -> subprocess.CompletedProcess:
    return _audit(repo, _env(repo, WORKTREE_ROOT=str(root)))


def _stop(proc: subprocess.Popen) -> None:
    proc.kill()
    proc.wait()


def test_a_zombie_under_the_resolved_spelling_is_found(repo, linked_root):
    """The filed miss: configured through the link, started under the target."""
    configured, resolved = linked_root
    proc = _sleeper(f"{resolved}/ghost-branch/x")
    try:
        result = _audit_with_root(repo, configured)
    finally:
        _stop(proc)
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert str(proc.pid) in _listed(result.stdout), result.stdout


def test_a_zombie_under_the_configured_spelling_is_still_found(repo, linked_root):
    """Control: adding the resolved spelling does not drop the configured one."""
    configured, _ = linked_root
    proc = _sleeper(f"{configured}/ghost-branch/x")
    try:
        result = _audit_with_root(repo, configured)
    finally:
        _stop(proc)
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert str(proc.pid) in _listed(result.stdout), result.stdout


def test_a_live_worktree_under_the_resolved_spelling_is_not_listed(repo, linked_root):
    """Control: the second spelling widens the match, not what is a zombie."""
    configured, resolved = linked_root
    proc = _sleeper(f"{resolved}/live/server.py")
    try:
        result = _audit_with_root(repo, configured)
    finally:
        _stop(proc)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert str(proc.pid) not in _listed(result.stdout), result.stdout


@pytest.mark.parametrize("live_first", ["resolved", "configured"])
def test_the_first_name_is_first_across_both_spellings(repo, linked_root, live_first):
    """CR 1241 stays an accepted limit: a process is checked by the first
    worktree name in its command line. A second spelling searched after the
    first would reach a later name, and widen the `Kill all:` recipe."""
    configured, resolved = linked_root
    live_root, ghost_root = (
        (resolved, configured) if live_first == "resolved" else (configured, resolved)
    )
    proc = _sleeper(f"{live_root}/live/server.py", f"{ghost_root}/ghost-branch/x")
    try:
        result = _audit_with_root(repo, configured)
    finally:
        _stop(proc)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert str(proc.pid) not in _listed(result.stdout), result.stdout


def test_a_caller_under_no_link_cannot_learn_one(repo, linked_root):
    """Pinned limit, not a goal: the root is given resolved and the caller
    stands under no symlink, so nothing names the link, and a process
    started under it is still missed. Changing this is a decision."""
    configured, resolved = linked_root
    proc = _sleeper(f"{configured}/ghost-branch/x")
    try:
        result = _audit(
            repo, _env(repo, WORKTREE_ROOT=str(resolved), PWD=str(repo.resolve()))
        )
    finally:
        _stop(proc)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert str(proc.pid) not in _listed(result.stdout), result.stdout


# --- The caller's spelling of the root (#533, CR 1738) -----------------------
#
# The default root is built with `pwd -P`, so it is always the resolved
# spelling, and the audit had no other: a repo reached through a symlink (the
# issue's /tmp -> /private/tmp) left a process under the caller's spelling of
# `<repo>/.worktrees/<gone>` unlisted. The caller's `pwd -L` against its
# `pwd -P` names that link. Each test sets PWD, since the audit runs in a
# child whose PWD is otherwise the parent's, and bash drops a PWD that does
# not name its directory.


@pytest.fixture
def linked_repo(tmp_path):
    """`(logical, physical)` checkout of a repo reached through a symlinked
    parent, with a linked worktree `live` under the default root."""
    real_parent = tmp_path / "real-parent"
    physical = real_parent / "repo"
    physical.mkdir(parents=True)
    _git(physical, "init", "-b", "main")
    _git(physical, "config", "user.email", "test@example.com")
    _git(physical, "config", "user.name", "test")
    _git(physical, "commit", "--allow-empty", "-m", "initial")
    _git(physical, "worktree", "add", "-q", "-b", "live", ".worktrees/live")
    link_parent = tmp_path / "link-parent"
    link_parent.symlink_to(real_parent, target_is_directory=True)
    return link_parent / "repo", physical.resolve()


def _audit_from(cwd: Path, **extra: str) -> subprocess.CompletedProcess:
    """The audit run from `cwd` as spelled, under the default root unless
    `extra` sets one."""
    env = _scrubbed()
    env.pop("WORKTREE_ROOT", None)
    env["PWD"] = str(cwd)
    env.update(extra)
    return subprocess.run(
        ["bash", str(AUDIT)],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=60,
    )


@pytest.mark.parametrize("stand_in", ["primary", "linked worktree"])
def test_a_zombie_under_the_callers_spelling_of_the_default_root_is_found(
    linked_repo, stand_in
):
    """The issue's headline case. From the linked worktree too: the default
    root lives under the primary checkout, not the caller's toplevel."""
    logical, _ = linked_repo
    cwd = logical if stand_in == "primary" else logical / ".worktrees" / "live"
    proc = _sleeper(f"{logical}/.worktrees/ghost-branch/x")
    try:
        result = _audit_from(cwd)
    finally:
        _stop(proc)
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert str(proc.pid) in _listed(result.stdout), result.stdout


def test_a_live_worktree_under_the_callers_spelling_is_not_listed(linked_repo):
    """Control: the caller's spelling widens the match, not what is a zombie."""
    logical, _ = linked_repo
    proc = _sleeper(f"{logical}/.worktrees/live/server.py")
    try:
        result = _audit_from(logical)
    finally:
        _stop(proc)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert str(proc.pid) not in _listed(result.stdout), result.stdout


def test_the_callers_spelling_is_checked_against_the_root(tmp_path):
    """The common-suffix strip can overreach: `L/proj` links to `R/proj`, so it
    maps `R` to `L`, though `L` is no spelling of `R`. A root `R/wt` would gain
    `L/wt`, a different place, and a process under it would be listed. The
    derived spelling must resolve to the root, or it is dropped."""
    physical = tmp_path / "R" / "proj"
    physical.mkdir(parents=True)
    _git(physical, "init", "-b", "main")
    (tmp_path / "R" / "wt").mkdir()
    (tmp_path / "L").mkdir()
    logical = tmp_path / "L" / "proj"
    logical.symlink_to(physical, target_is_directory=True)
    proc = _sleeper(f"{tmp_path / 'L' / 'wt'}/ghost-branch/x")
    try:
        result = _audit_from(
            logical, WORKTREE_ROOT=str((tmp_path / "R" / "wt").resolve())
        )
    finally:
        _stop(proc)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert str(proc.pid) not in _listed(result.stdout), result.stdout


def test_at_a_tie_the_longer_spelling_wins(repo):
    """`<root>/b` links back to `<root>`, and the caller stands in it, so the
    root (`<root>`) and the caller's spelling (`<root>/b`) start at the same
    place in `<root>/b/ghost-branch/x`. The shorter reads the name `b`, which
    exists, and would hide the zombie. The longer is the later spelling here,
    so taking the first one found would get this wrong."""
    root = _root(repo).resolve()
    (root / "b").symlink_to(root, target_is_directory=True)
    proc = _sleeper(f"{root}/b/ghost-branch/x")
    try:
        result = _audit_from(root / "b")
    finally:
        _stop(proc)
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert str(proc.pid) in _listed(result.stdout), result.stdout
