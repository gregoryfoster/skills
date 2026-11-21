"""`.skills/attest-local-gate`: a green local gate, said on the commit (#688).

In a private, duration-shaped repo whose PRs come from people, the gate a
developer just ran locally runs again on a billed runner. The lever (#602):
the ship posts a commit status, `gate/local` = `success`, on the SHA it
pushed, and CI skips its heavy tier when that status is there.

The step is opt-in and lives inside `push.sh`, which every shipping path
already runs: a direct ship pushes the default branch, and `pr` mode pushes
the PR's head. With the knob on, `push.sh` sources `_attest-gate.sh` and:

1. **verifies before it pushes:** the tree is clean, and the gate (the
   project's `scripts/pre-ship.sh`, else the skill's) exits 0 on it;
2. **pushes;**
3. **writes the status, then reads it back** through the combined status.

What this file pins, in the order the issue asks:

- **No knob, no change.** The same stdout and stderr as the script before
  the knob existed, no `gh` call (so no token scope is used), no gate run,
  and no need for the library to exist beside `push.sh`. `off` is absent.
- **Never `success` for a tree the gate didn't pass.** A failing gate, a gate
  that couldn't run, a dirty tree and a tree the gate changed all end before
  the push, with no `gh` call.
- **A reused pass may attest.** The step asks the gate and takes its exit
  code; it never forces a fresh run.
- **A refused write is loud and doesn't fail the ship.** The push landed, so
  the exit is 0, with gh's own message and a NOT POSTED block on stderr.
- **The knob is read from the commit.** One word, `on` or `off`; anything
  else is exit 2 before the push, never `on` and never silently `off`.

No network. `gh` is a fake that records its arguments; the remote is a local
bare repository reached through `insteadOf`, so `origin`'s configured URL
still names GitHub. The live write is the run's own verification, on #688.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.utils.skill_loader import SKILLS_DIR

SKILL = SKILLS_DIR / "shipping-work"
PUSH = SKILL / "scripts" / "push.sh"
LIB = SKILL / "scripts" / "_attest-gate.sh"
KNOB = ".skills/attest-local-gate"
CONTEXT = "gate/local"
GITHUB_URL = "https://github.com/acme/widgets.git"

# push.sh as it was before the knob (5642148b), whole. The no-knob tests run
# it beside the current script and want the same bytes out of both.
PRE_KNOB_PUSH = """\
#!/usr/bin/env bash
# push.sh
# Pushes the current branch to origin.
# Detects the git project root automatically; safe to invoke from any directory.
#
# Usage: bash "<push.sh>" [--help]
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: bash \\"$0\\""
  echo ""
  echo "Pushes the current git branch to origin."
  echo "Automatically resolves the git project root regardless of invocation directory."
  exit 0
fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

BRANCH=$(git branch --show-current)
echo "Pushing $BRANCH to origin..."
# -u sets upstream tracking on first push; no-op when tracking is already configured.
git push -u origin "$BRANCH"
echo "Push succeeded."
"""

# The project's own gate. It records that it ran, whether the remote already
# had HEAD (it must not: the gate is asked before the push), and GATE_STAMP as
# it arrived. $GATE_DO changes the tree under the run; $GATE_EXIT is its code.
GATE_STUB = """\
#!/usr/bin/env bash
log="${ATTEST_LOG:?}"
head=$(git rev-parse HEAD)
if git ls-remote origin 2>/dev/null | grep -q "^$head"; then pushed=yes; else pushed=no; fi
printf 'gate\\tpushed=%s\\tstamp=%s\\tcwd=%s\\n' "$pushed" "${GATE_STAMP-unset}" "$(pwd -P)" >>"$log"
echo "stub gate: stdout line"
echo "stub gate: stderr line" >&2
case "${GATE_DO:-}" in
  untracked) echo x >gate-left-this ;;
  modify) echo x >>tracked.txt ;;
  commit) git commit -q --allow-empty -m "made by the gate" ;;
esac
[ -z "${GATE_SIGNAL:-}" ] || kill -"$GATE_SIGNAL" $$
exit "${GATE_EXIT:-0}"
"""

# A whole gate of the project's own that records its pass with the skill's
# gate-stamp.sh, as attestation.md tells such a repo to: a tree it already
# passed is answered without running.
STAMPING_GATE = """\
#!/usr/bin/env bash
set -euo pipefail
log="${ATTEST_LOG:?}"
stamp="${STAMP_SH:?}"
key=$(bash "$stamp" key) || key=""
if [ -n "$key" ] && bash "$stamp" check "$key" >/dev/null; then
  printf 'gate\\treused\\n' >>"$log"
  echo "this exact tree already passed"
  exit 0
fi
printf 'gate\\tran\\n' >>"$log"
[ -z "$key" ] || bash "$stamp" write "$key" --label "stub suite"
"""

# gh, recording every call as one tab-separated line. A POST answers with
# $GH_POST_EXIT and $GH_POST_STDERR and remembers the state it was given; the
# combined-status read answers with what was posted, or $GH_READBACK. Real gh
# applies --jq itself, so the fake prints what that expression would.
FAKE_GH = """\
#!/usr/bin/env bash
log="${ATTEST_LOG:?}"
{ printf 'gh'; for a in "$@"; do printf '\\t%s' "$a"; done; printf '\\n'; } >>"$log"
post=0 path="" prev=""
for a in "$@"; do
  if [ "$prev" = "--method" ] && [ "$a" = "POST" ]; then post=1; fi
  case "$a" in repos/*) path=$a ;; esac
  prev=$a
done
if [ "$post" = 1 ]; then
  [ -z "${GH_POST_STDERR:-}" ] || echo "$GH_POST_STDERR" >&2
  [ "${GH_POST_EXIT:-0}" = 0 ] || exit "$GH_POST_EXIT"
  for a in "$@"; do case "$a" in state=*) echo "${a#state=}" >"${GH_STATE:?}" ;; esac; done
  echo '{"id": 1, "state": "success"}'
  exit 0
fi
case "$path" in
  */commits/*/status*)
    [ -z "${GH_GET_STDERR:-}" ] || echo "$GH_GET_STDERR" >&2
    [ "${GH_GET_EXIT:-0}" = 0 ] || exit "$GH_GET_EXIT"
    if [ -n "${GH_READBACK+set}" ]; then echo "$GH_READBACK"
    elif [ -f "${GH_STATE:?}" ]; then cat "$GH_STATE"
    else echo none; fi
    ;;
  *) echo "fake gh: unexpected call" >&2; exit 97 ;;
esac
"""

# ssh -G, for an scp-like remote: an ssh_config alias names github.com.
FAKE_SSH = """\
#!/usr/bin/env bash
host=""
for a in "$@"; do host=$a; done
case "$host" in
  github-acme) echo "hostname github.com" ;;
  *) echo "hostname $host" ;;
esac
"""


def _env(**extra: str) -> dict:
    """No inherited GIT_*: under a hook GIT_DIR would point the fixture at this repo (#189)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_HOST", "GATE_STAMP"):
        env.pop(name, None)
    env.update(extra)
    return env


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(),
    ).stdout.strip()


@dataclass
class World:
    root: Path
    repo: Path
    remote: Path
    bindir: Path
    log: Path
    state: Path

    def head(self) -> str:
        return _git(self.repo, "rev-parse", "HEAD")

    def tree(self) -> str:
        return _git(self.repo, "rev-parse", "HEAD^{tree}")

    def remote_has(self, sha: str) -> bool:
        return (
            subprocess.run(
                ["git", "-C", str(self.remote), "cat-file", "-e", sha],
                capture_output=True,
                env=_env(),
            ).returncode
            == 0
        )

    def lines(self, kind: str) -> list[list[str]]:
        if not self.log.exists():
            return []
        rows = [line.split("\t") for line in self.log.read_text().splitlines()]
        return [row for row in rows if row[0] == kind]

    def commit_knob(self, text: str) -> None:
        knob = self.repo / KNOB
        knob.parent.mkdir(exist_ok=True)
        knob.write_text(text)
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "the knob")

    def push(
        self, script: Path = PUSH, path: str | None = None, **env: str
    ) -> subprocess.CompletedProcess:
        base = _env(
            ATTEST_LOG=str(self.log),
            GH_STATE=str(self.state),
            ATTEST_READBACK_PAUSE="0",
            **env,
        )
        base["PATH"] = path or f"{self.bindir}:{base.get('PATH', '/usr/bin:/bin')}"
        return subprocess.run(
            ["bash", str(script)],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=base,
            timeout=120,
        )


def _world(root: Path, url: str = GITHUB_URL, gate: bool = True) -> World:
    """A checkout on main whose origin's configured URL names GitHub and whose
    pushes land in a local bare repository."""
    root.mkdir(parents=True, exist_ok=True)
    remote = root / "remote.git"
    repo = root / "repo"
    bindir = root / "bin"
    repo.mkdir()
    bindir.mkdir()
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        env=_env(),
    )
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "remote", "add", "origin", url)
    _git(repo, "config", f"url.{remote}.insteadOf", url)
    (repo / "tracked.txt").write_text("x\n")
    if gate:
        stub = repo / "scripts" / "pre-ship.sh"
        stub.parent.mkdir()
        stub.write_text(GATE_STUB)
        stub.chmod(0o755)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    for name, text in (("gh", FAKE_GH), ("ssh", FAKE_SSH)):
        tool = bindir / name
        tool.write_text(text)
        tool.chmod(0o755)
    return World(root, repo, remote, bindir, root / "calls.log", root / "gh-state")


@pytest.fixture
def world(tmp_path: Path) -> World:
    return _world(tmp_path / "w")


@pytest.fixture
def on(world: World) -> World:
    world.commit_knob("on\n")
    return world


def _path_without_gh(tmp_path: Path, farm: bool) -> str:
    """A PATH with git and the shell's tools on it and no gh. The system
    directories do, unless gh is installed into one of them (a host that got
    it from apt has /usr/bin/gh): then a directory of links to everything
    there but gh stands in. `farm` asks for the links either way, so that
    arm is exercised on every host instead of skipped on most."""
    dirs = ["/usr/bin", "/bin"]
    if not farm and not shutil.which("gh", path=":".join(dirs)):
        return ":".join(dirs)
    links = tmp_path / "no-gh"
    links.mkdir()
    for d in dirs:
        for tool in Path(d).iterdir():
            if tool.name != "gh" and not (links / tool.name).exists():
                (links / tool.name).symlink_to(tool)
    return str(links)


def _is_the_plain_push(stdout: str, branch: str = "main") -> None:
    """The pre-knob script's two lines around git's own, whose wording for
    the upstream it set varies by version. Nothing about an attestation."""
    assert stdout.startswith(f"Pushing {branch} to origin...\n"), stdout
    assert stdout.endswith("Push succeeded.\n"), stdout
    assert "ttest" not in stdout, stdout
    assert len(stdout.splitlines()) <= 3, stdout


def _posts(world: World) -> list[list[str]]:
    return [row for row in world.lines("gh") if "POST" in row]


def _nothing_was_pushed(world: World, result: subprocess.CompletedProcess) -> None:
    assert not world.remote_has(world.head()), result.stdout + result.stderr
    assert "Push succeeded." not in result.stdout
    assert world.lines("gh") == [], "no status may be written before a push"


class TestWithoutTheKnobNothingChanges:
    """Every cohort repo ships with this skill. One without the knob gets the
    script it had: the same bytes on both streams, no gh call, no gate run."""

    def _twins(self, tmp_path: Path, prepare=None):
        old_script = tmp_path / "pre-knob-push.sh"
        old_script.write_text(PRE_KNOB_PUSH)
        results = []
        for name, script in (("old", old_script), ("new", PUSH)):
            w = _world(tmp_path / name)
            if prepare:
                prepare(w)
            result = w.push(script=script)
            results.append((w, result))
        return results

    @staticmethod
    def _same(results) -> None:
        (old_w, old), (new_w, new) = results
        assert old.returncode == 0, old.stdout + old.stderr
        assert new.returncode == old.returncode, new.stdout + new.stderr
        assert new.stdout == old.stdout
        assert new.stderr.replace(str(new_w.root), "<W>") == old.stderr.replace(
            str(old_w.root), "<W>"
        )
        _is_the_plain_push(new.stdout)
        assert "ttest" not in new.stderr
        for w in (old_w, new_w):
            assert w.remote_has(w.head())
            assert w.lines("gh") == [], "no gh call: no token scope is used"
            assert w.lines("gate") == [], "the push runs no gate without the knob"

    def test_the_output_is_the_pre_knob_scripts_byte_for_byte(self, tmp_path):
        self._same(self._twins(tmp_path))

    def test_off_reads_as_absent(self, tmp_path):
        """A repo may keep the file to say why it is off."""
        self._same(
            self._twins(
                tmp_path, lambda w: w.commit_knob("# went public 2026-11\noff\n")
            )
        )

    def test_a_feature_branch_pushes_as_before(self, tmp_path):
        def branch(w: World) -> None:
            _git(w.repo, "checkout", "-q", "-b", "work")
            (w.repo / "tracked.txt").write_text("y\n")
            _git(w.repo, "commit", "-q", "-am", "work")

        (old_w, old), (new_w, new) = self._twins(tmp_path, branch)
        assert new.returncode == old.returncode == 0, new.stdout + new.stderr
        assert new.stdout == old.stdout
        _is_the_plain_push(new.stdout, "work")
        assert new_w.lines("gh") == [] and new_w.lines("gate") == []

    def test_a_dirty_tree_still_pushes(self, tmp_path):
        """The tree-clean rule belongs to the attestation, not to the push."""

        def dirty(w: World) -> None:
            (w.repo / "tracked.txt").write_text("uncommitted\n")
            (w.repo / "scratch").write_text("untracked\n")

        self._same(self._twins(tmp_path, dirty))

    def test_the_library_need_not_exist_beside_push(self, tmp_path):
        """A consumer that vendors per-file symlinks and never linked the
        library ships as before: without the knob it is never looked for."""
        w = _world(tmp_path / "w")
        alone = tmp_path / "alone" / "scripts"
        alone.mkdir(parents=True)
        shutil.copy(PUSH, alone / "push.sh")
        result = w.push(script=alone / "push.sh")
        assert result.returncode == 0, result.stdout + result.stderr
        _is_the_plain_push(result.stdout)
        assert w.remote_has(w.head())

    @pytest.mark.parametrize(
        "text", ["off\n", "# public repo\r\n\r\n  off  \r\n"], ids=["bare", "commented"]
    )
    def test_off_needs_no_library_either(self, tmp_path, text):
        """CR 2667: `off` is the same as no file, so a copied push.sh with
        no library beside it pushes as it did before the knob."""
        w = _world(tmp_path / "w")
        w.commit_knob(text)
        alone = tmp_path / "alone" / "scripts"
        alone.mkdir(parents=True)
        shutil.copy(PUSH, alone / "push.sh")
        result = w.push(script=alone / "push.sh")
        assert result.returncode == 0, result.stdout + result.stderr
        _is_the_plain_push(result.stdout)
        assert "ttest" not in result.stderr
        assert w.remote_has(w.head())
        assert w.lines("gh") == [] and w.lines("gate") == []

    def test_a_failing_push_still_fails_as_git_does(self, tmp_path):
        w = _world(tmp_path / "w")
        _git(w.repo, "config", f"url.{w.root / 'nowhere.git'}.insteadOf", GITHUB_URL)
        _git(w.repo, "config", "--unset", f"url.{w.remote}.insteadOf")
        result = w.push()
        assert result.returncode != 0
        assert "Push succeeded." not in result.stdout
        assert w.lines("gh") == []


class TestAGreenGateIsSaidOnTheCommit:
    def test_it_verifies_then_pushes_then_writes_then_reads_back(self, on):
        sha, tree = on.head(), on.tree()
        result = on.push()
        assert result.returncode == 0, result.stdout + result.stderr
        assert on.remote_has(sha)

        (gate,) = on.lines("gate")
        assert "pushed=no" in gate, "the gate is asked before the push"
        assert f"cwd={on.repo.resolve()}" in gate

        post, read = on.lines("gh")
        assert post[1:4] == ["api", "--hostname", "github.com"]
        assert f"repos/acme/widgets/statuses/{sha}" in post
        assert "state=success" in post
        assert f"context={CONTEXT}" in post
        (description,) = [a for a in post if a.startswith("description=")]
        assert tree in description, "the description names the tree, for a reader"
        assert len(description) - len("description=") <= 140

        assert "POST" not in read
        assert f"repos/acme/widgets/commits/{sha}/status?per_page=100" in read, (
            "read back through the combined status, as CI reads it, a whole page"
        )
        assert not any(a.endswith("/statuses") for a in read)

        assert "Push succeeded." in result.stdout
        assert f"Attestation: {CONTEXT} = success posted on {sha}" in result.stdout
        assert result.stdout.index("stub gate: stdout line") < result.stdout.index(
            "Pushing main to origin..."
        )
        assert "stub gate: stderr line" in result.stderr, "the gate's stderr is shown"

    def test_the_read_back_asks_for_this_context_only(self, on):
        on.push()
        read = on.lines("gh")[-1]
        jq = read[read.index("--jq") + 1]
        assert f'select(.context == "{CONTEXT}")' in jq
        assert ".statuses[]" in jq

    def test_pr_mode_attests_the_branch_head(self, on):
        """`pr` mode pushes the branch, so its head, which the PR's CI reads
        as pull_request.head.sha, is what carries the status."""
        _git(on.repo, "checkout", "-q", "-b", "work")
        (on.repo / "tracked.txt").write_text("y\n")
        _git(on.repo, "commit", "-q", "-am", "work")
        sha = on.head()
        result = on.push()
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Pushing work to origin..." in result.stdout
        assert f"repos/acme/widgets/statuses/{sha}" in _posts(on)[0]
        assert _git(on.remote, "rev-parse", "refs/heads/work") == sha

    def test_a_reused_pass_attests_and_a_fresh_run_is_never_forced(self, on):
        """The step asks the gate and takes its answer. It sets no
        GATE_STAMP, so a gate that reuses a recorded pass for this exact tree
        answers 0 without running, and that answer attests."""
        result = on.push()
        assert result.returncode == 0, result.stdout + result.stderr
        assert "stamp=unset" in on.lines("gate")[0]
        assert len(_posts(on)) == 1

    def test_a_rejected_push_is_gits_own_failure_and_nothing_is_written(self, on):
        """CR 2666: the gate passed, then git refused the push. That is
        git's exit code, after the Pushing line, and no status."""
        on.push()
        on.log.unlink()
        other = on.root / "other"
        subprocess.run(
            ["git", "clone", "-q", str(on.remote), str(other)],
            check=True,
            capture_output=True,
            env=_env(),
        )
        _git(other, "config", "user.email", "test@example.com")
        _git(other, "config", "user.name", "test")
        _git(other, "commit", "-q", "--allow-empty", "-m", "someone else's")
        _git(other, "push", "-q", "origin", "main")
        _git(on.repo, "commit", "-q", "--allow-empty", "-m", "mine")
        result = on.push()
        assert result.returncode == 1, result.stdout + result.stderr
        assert "Pushing main to origin..." in result.stdout
        assert "Push succeeded." not in result.stdout
        assert "Nothing was pushed" not in result.stderr, "that line is the gate's"
        assert len(on.lines("gate")) == 1 and on.lines("gh") == []

    def test_a_detached_head_fails_as_git_does(self, on):
        _git(on.repo, "checkout", "-q", "--detach")
        result = on.push()
        assert result.returncode != 0
        assert "Push succeeded." not in result.stdout
        assert on.lines("gh") == []

    def test_a_pass_reused_from_a_real_stamp_attests(self, tmp_path):
        """CR 2671: the decision, run for real. The project's gate records
        its pass with gate-stamp.sh; the next push of that tree is answered
        from the stamp without running, and it attests all the same. A new
        commit is a new tree, and runs."""
        w = _world(tmp_path / "w", gate=False)
        gate = w.repo / "scripts" / "pre-ship.sh"
        gate.parent.mkdir()
        gate.write_text(STAMPING_GATE)
        w.commit_knob("on\n")
        stamp = str(SKILL / "scripts" / "gate-stamp.sh")
        for expected in ("ran", "reused"):
            result = w.push(STAMP_SH=stamp)
            assert result.returncode == 0, result.stdout + result.stderr
            assert w.lines("gate")[-1] == ["gate", expected]
            assert f"{CONTEXT} = success posted on {w.head()}" in result.stdout
        assert len(_posts(w)) == 2
        _git(w.repo, "commit", "-q", "--allow-empty", "-m", "same tree, new commit")
        (w.repo / "tracked.txt").write_text("a new tree\n")
        _git(w.repo, "commit", "-q", "-am", "a new tree")
        result = w.push(STAMP_SH=stamp)
        assert result.returncode == 0, result.stdout + result.stderr
        assert w.lines("gate")[-1] == ["gate", "ran"]

    def test_only_the_outcome_line_begins_attestation(self, on):
        """CR 2673: SKILL.md says to report "its `Attestation:` line", so
        there is one, and the line before the gate reads otherwise."""
        result = on.push()
        lines = [x for x in result.stdout.splitlines() if x.startswith("Attestation:")]
        assert len(lines) == 1 and "posted on" in lines[0], result.stdout
        assert "Gate before the push (.skills/attest-local-gate is on)" in result.stdout

    def test_the_callers_gate_stamp_reaches_the_gate_unchanged(self, on):
        on.push(GATE_STAMP="off")
        assert "stamp=off" in on.lines("gate")[0]

    def test_running_it_again_writes_again(self, on):
        """The retry after a refused write: the push is a no-op, the gate
        answers again, and the status is written."""
        first = on.push(GH_POST_EXIT="1", GH_POST_STDERR="gh: HTTP 502")
        assert first.returncode == 0 and "ATTESTATION NOT POSTED" in first.stderr
        second = on.push()
        assert second.returncode == 0, second.stdout + second.stderr
        assert (
            f"Attestation: {CONTEXT} = success posted on {on.head()}" in second.stdout
        )

    def test_the_comments_and_blank_lines_of_the_knob_are_ignored(self, world):
        world.commit_knob("# attest the local gate (#688)\r\n\r\n  on  \r\n")
        result = world.push()
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(_posts(world)) == 1

    @pytest.mark.parametrize(
        ("url", "slug", "host"),
        [
            ("https://github.com/acme/widgets", "acme/widgets", "github.com"),
            ("git@github.com:acme/widgets.git", "acme/widgets", "github.com"),
            ("git@github-acme:acme/widgets.git", "acme/widgets", "github.com"),
            ("ssh://git@github.com/acme/widgets.git", "acme/widgets", "github.com"),
            (
                "https://ghe.example.com/acme/widgets.git",
                "acme/widgets",
                "ghe.example.com",
            ),
            (
                "https://ghe.example.com:8443/acme/widgets/",
                "acme/widgets",
                "ghe.example.com:8443",
            ),
            ("ssh://git@github.com:22/acme/widgets.git", "acme/widgets", "github.com"),
        ],
        ids=[
            "https",
            "scp",
            "ssh-alias",
            "ssh-url",
            "enterprise",
            "https-port",
            "ssh-port",
        ],
    )
    def test_the_repo_is_origins_own(self, tmp_path, url, slug, host):
        """origin is where push.sh pushed, so its configured URL names the
        repository, never gh's pick among the remotes (an `upstream` fork
        parent would win there). An ssh alias is resolved as #576 does."""
        w = _world(tmp_path / "w", url=url)
        _git(
            w.repo, "remote", "add", "upstream", "https://github.com/parent/widgets.git"
        )
        w.commit_knob("on\n")
        result = w.push()
        assert result.returncode == 0, result.stdout + result.stderr
        post = _posts(w)[0]
        assert post[1:4] == ["api", "--hostname", host]
        assert f"repos/{slug}/statuses/{w.head()}" in post


class TestTheGateIsWhatStep1Resolves:
    def test_the_skills_own_gate_answers_when_the_project_has_none(self, tmp_path):
        """A repo with no scripts/pre-ship.sh is gated by the skill's, found
        beside push.sh."""
        w = _world(tmp_path / "w", gate=False)
        w.commit_knob("on\n")
        skill = tmp_path / "skill" / "scripts"
        skill.mkdir(parents=True)
        shutil.copy(PUSH, skill / "push.sh")
        shutil.copy(LIB, skill / "_attest-gate.sh")
        (skill / "pre-ship.sh").write_text(GATE_STUB)
        result = w.push(script=skill / "push.sh")
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(w.lines("gate")) == 1 and len(_posts(w)) == 1

    def test_a_wrapper_beside_the_link_wins_over_the_links_target(self, tmp_path):
        """The per-file symlink shape keeps a real pre-ship.sh wrapper beside
        links to the vendored scripts. Step 1 runs that wrapper, so the
        attestation asks it too, not the vendored gate beside push.sh's
        target, which would run without the env the wrapper loads."""
        w = _world(tmp_path / "w", gate=False)
        w.commit_knob("on\n")
        vendor = tmp_path / "vendor" / "scripts"
        vendor.mkdir(parents=True)
        shutil.copy(PUSH, vendor / "push.sh")
        shutil.copy(LIB, vendor / "_attest-gate.sh")
        (vendor / "pre-ship.sh").write_text("#!/usr/bin/env bash\nexit 1\n")
        local = tmp_path / "consumer" / "scripts"
        local.mkdir(parents=True)
        (local / "push.sh").symlink_to(vendor / "push.sh")
        (local / "pre-ship.sh").write_text(GATE_STUB)
        result = w.push(script=local / "push.sh")
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(w.lines("gate")) == 1, "the wrapper beside the link ran"
        assert len(_posts(w)) == 1

    def test_the_library_is_found_through_a_per_file_symlink(self, tmp_path):
        w = _world(tmp_path / "w")
        w.commit_knob("on\n")
        local = tmp_path / "consumer" / "scripts"
        local.mkdir(parents=True)
        (local / "push.sh").symlink_to(PUSH)
        result = w.push(script=local / "push.sh")
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(_posts(w)) == 1

    def test_a_missing_library_is_exit_2_before_the_push(self, tmp_path):
        """The knob is on and the step can't run: said, never skipped."""
        w = _world(tmp_path / "w")
        w.commit_knob("on\n")
        alone = tmp_path / "alone" / "scripts"
        alone.mkdir(parents=True)
        shutil.copy(PUSH, alone / "push.sh")
        result = w.push(script=alone / "push.sh")
        assert result.returncode == 2, result.stdout + result.stderr
        assert "_attest-gate.sh" in result.stderr
        _nothing_was_pushed(w, result)

    def test_no_gate_anywhere_is_exit_2_before_the_push(self, tmp_path):
        w = _world(tmp_path / "w", gate=False)
        w.commit_knob("on\n")
        skill = tmp_path / "skill" / "scripts"
        skill.mkdir(parents=True)
        shutil.copy(PUSH, skill / "push.sh")
        shutil.copy(LIB, skill / "_attest-gate.sh")
        result = w.push(script=skill / "push.sh")
        assert result.returncode == 2, result.stdout + result.stderr
        assert "pre-ship.sh" in result.stderr
        _nothing_was_pushed(w, result)


class TestNeverSuccessForATreeTheGateDidNotPass:
    def test_a_failing_gate_is_exit_1_and_nothing_is_pushed(self, on):
        result = on.push(GATE_EXIT="1")
        assert result.returncode == 1, result.stdout + result.stderr
        assert "the gate failed" in result.stderr
        assert "Nothing was pushed" in result.stderr
        _nothing_was_pushed(on, result)

    @pytest.mark.parametrize(
        ("env", "code"),
        [
            ({"GATE_EXIT": "2"}, "2"),
            ({"GATE_EXIT": "127"}, "127"),
            ({"GATE_SIGNAL": "TERM"}, "143"),
        ],
        ids=["exit-2", "exit-127", "sigterm"],
    )
    def test_a_gate_that_could_not_run_is_exit_2(self, on, env, code):
        """Exit 2 is never a pass, and neither is a gate that was killed."""
        result = on.push(**env)
        assert result.returncode == 2, result.stdout + result.stderr
        assert f"exit {code}" in result.stderr
        assert "Nothing was pushed" in result.stderr
        _nothing_was_pushed(on, result)

    @pytest.mark.parametrize("kind", ["tracked", "untracked", "staged"])
    def test_a_dirty_tree_is_exit_1_and_the_gate_is_not_asked(self, on, kind):
        """A gate run on files that aren't the commit says nothing about the
        commit, so it isn't run at all."""
        if kind == "untracked":
            (on.repo / "scratch").write_text("x\n")
        else:
            (on.repo / "tracked.txt").write_text("uncommitted\n")
            if kind == "staged":
                _git(on.repo, "add", "-A")
        result = on.push()
        assert result.returncode == 1, result.stdout + result.stderr
        assert "uncommitted" in result.stderr
        assert on.lines("gate") == []
        _nothing_was_pushed(on, result)

    def test_a_knob_switched_off_in_the_work_tree_only_is_a_dirty_tree(self, on):
        (on.repo / KNOB).write_text("off\n")
        result = on.push()
        assert result.returncode == 1, result.stdout + result.stderr
        _nothing_was_pushed(on, result)

    @pytest.mark.parametrize("did", ["untracked", "modify", "commit"])
    def test_a_tree_the_gate_changed_is_exit_1(self, on, did):
        """The gate passed on something, but no longer on what is here."""
        result = on.push(GATE_DO=did)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "changed under the gate" in result.stderr
        assert "Push succeeded." not in result.stdout
        assert on.lines("gh") == []

    def test_untracked_files_git_was_told_to_hide_are_still_a_dirty_tree(self, on):
        """CR 2664: with status.showUntrackedFiles=no a bare `git status`
        lists no untracked file, so a gate that passes only because of one
        attested a commit that lacks it."""
        _git(on.repo, "config", "status.showUntrackedFiles", "no")
        (on.repo / "helper.js").write_text("the gate needs this\n")
        result = on.push()
        assert result.returncode == 1, result.stdout + result.stderr
        assert "helper.js" in result.stderr
        assert on.lines("gate") == []
        _nothing_was_pushed(on, result)

    def test_a_submodule_git_was_told_to_ignore_is_still_a_dirty_tree(
        self, on, tmp_path
    ):
        """CR 2664: `ignore = dirty` in .gitmodules hides an edit inside a
        submodule, and a consumer vendors this very gate in one."""
        lib = tmp_path / "lib"
        lib.mkdir()
        _git(lib, "init", "-q", "-b", "main")
        _git(lib, "config", "user.email", "test@example.com")
        _git(lib, "config", "user.name", "test")
        (lib / "gate.sh").write_text("exit 1\n")
        _git(lib, "add", "-A")
        _git(lib, "commit", "-q", "-m", "lib")
        _git(
            on.repo,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(lib),
            "vendor",
        )
        _git(on.repo, "config", "-f", ".gitmodules", "submodule.vendor.ignore", "dirty")
        _git(on.repo, "add", "-A")
        _git(on.repo, "commit", "-q", "-m", "vendor the lib")
        (on.repo / "vendor" / "gate.sh").write_text("exit 0\n")
        assert _git(on.repo, "status", "--porcelain") == "", "git hides the edit"
        result = on.push()
        assert result.returncode == 1, result.stdout + result.stderr
        assert "vendor" in result.stderr
        assert on.lines("gate") == []
        _nothing_was_pushed(on, result)

    @pytest.mark.parametrize("flag", ["--skip-worktree", "--assume-unchanged"])
    def test_a_path_git_was_told_not_to_watch_cannot_be_vouched_for(self, on, flag):
        """CR 2664: git reports no change to such a path, whatever is in it,
        so the files the gate ran on can't be shown to be the commit's."""
        _git(on.repo, "update-index", flag, "tracked.txt")
        (on.repo / "tracked.txt").write_text("not what was committed\n")
        assert _git(on.repo, "status", "--porcelain") == "", "git hides the edit"
        result = on.push()
        assert result.returncode == 1, result.stdout + result.stderr
        assert "tracked.txt" in result.stderr
        assert "not to watch" in result.stderr
        assert on.lines("gate") == []
        _nothing_was_pushed(on, result)

    def test_a_gate_that_leaves_a_hidden_untracked_file_changed_the_tree(self, on):
        _git(on.repo, "config", "status.showUntrackedFiles", "no")
        result = on.push(GATE_DO="untracked")
        assert result.returncode == 1, result.stdout + result.stderr
        assert "changed under the gate" in result.stderr
        assert on.lines("gh") == []

    def test_an_unreadable_tree_state_is_exit_2(self, on):
        """git status failing is not a clean tree (#257)."""
        (on.repo / ".git" / "index").write_bytes(b"not an index")
        result = on.push()
        assert result.returncode == 2, result.stdout + result.stderr
        assert on.lines("gate") == []
        assert on.lines("gh") == []
        assert "Push succeeded." not in result.stdout


class TestARefusedWriteIsLoudAndTheShipGoesOn:
    def _refused(self, world: World, result: subprocess.CompletedProcess) -> None:
        assert result.returncode == 0, result.stdout + result.stderr
        assert world.remote_has(world.head()), "the push landed first"
        assert "Push succeeded." in result.stdout
        assert "ATTESTATION NOT POSTED" in result.stderr
        assert "ship goes on" in result.stderr
        assert "full tier" in result.stderr
        assert "by hand" in result.stderr
        assert f"Attestation: {CONTEXT} NOT posted" in result.stdout
        assert f"{CONTEXT} = success posted" not in result.stdout

    @pytest.mark.parametrize(
        ("code", "message"),
        [
            ("1", "gh: Resource not accessible by personal access token (HTTP 403)"),
            ("1", "error connecting to api.github.com"),
            ("4", "To get started with GitHub CLI, please run:  gh auth login"),
            ("1", "gh: No commit found for SHA (HTTP 422)"),
        ],
        ids=["no-scope", "network", "no-token", "unknown-sha"],
    )
    def test_ghs_refusal_is_shown_verbatim(self, on, code, message):
        result = on.push(GH_POST_EXIT=code, GH_POST_STDERR=message)
        self._refused(on, result)
        assert message in result.stderr
        assert f"exit {code}" in result.stderr
        assert len(on.lines("gh")) == 1, "nothing is read back after a refusal"

    @pytest.mark.parametrize("farm", [False, True], ids=["system-dirs", "link-farm"])
    def test_no_gh_on_path(self, on, tmp_path, farm):
        result = on.push(path=_path_without_gh(tmp_path, farm))
        self._refused(on, result)
        assert "gh is not on PATH" in result.stderr
        assert on.lines("gh") == []

    def test_an_origin_that_names_no_host_repo(self, tmp_path):
        w = _world(tmp_path / "w", url=str(tmp_path / "w" / "remote.git"))
        w.commit_knob("on\n")
        result = w.push()
        self._refused(w, result)
        assert "origin" in result.stderr
        assert w.lines("gh") == []

    def test_the_status_goes_where_the_push_went(self, tmp_path):
        """CR 2668: with a push URL of its own, origin's commits land in
        that repository, so that is the one to write to."""
        w = _world(tmp_path / "w")
        elsewhere = "https://github.com/acme/elsewhere.git"
        _git(w.repo, "config", "remote.origin.pushurl", elsewhere)
        _git(w.repo, "config", f"url.{w.remote}.insteadOf", elsewhere)
        w.commit_knob("on\n")
        result = w.push()
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"repos/acme/elsewhere/statuses/{w.head()}" in _posts(w)[0]

    def test_two_push_urls_name_no_one_repository(self, on):
        _git(on.repo, "config", "--add", "remote.origin.pushurl", GITHUB_URL)
        _git(on.repo, "config", "--add", "remote.origin.pushurl", GITHUB_URL)
        result = on.push()
        self._refused(on, result)
        assert "more than one URL" in result.stderr
        assert on.lines("gh") == []

    def test_a_token_in_origins_url_is_never_printed(self, tmp_path):
        """CR 2669: the refusal quotes the URL, and the transcript keeps it."""
        url = "https://bot:ghp_SECRETTOKEN@git.example.com/group/sub/widgets.git"
        w = _world(tmp_path / "w", url=url)
        w.commit_knob("on\n")
        result = w.push()
        self._refused(w, result)
        assert "ghp_SECRETTOKEN" not in result.stdout + result.stderr
        assert "https://git.example.com/group/sub/widgets.git" in result.stderr
        assert "names no host/owner/repo" in result.stderr

    def test_an_ssh_host_that_ssh_cannot_name_says_so(self, tmp_path):
        """CR 2669: not "names no repository", which sends the reader to
        the URL when the fault is ssh's."""
        w = _world(tmp_path / "w", url="git@github-acme:acme/widgets.git")
        (w.bindir / "ssh").write_text("#!/usr/bin/env bash\nexit 255\n")
        w.commit_knob("on\n")
        result = w.push()
        self._refused(w, result)
        assert "ssh -G could not name the host behind 'github-acme'" in result.stderr
        assert w.lines("gh") == []

    def test_a_head_that_moved_during_the_push(self, on):
        """A pre-push hook that commits: what was verified is no longer
        HEAD, so nothing is written for either commit."""
        hook = on.repo / ".git" / "hooks" / "pre-push"
        hook.parent.mkdir(exist_ok=True)
        hook.write_text(
            "#!/usr/bin/env bash\ngit commit -q --allow-empty -m 'made by the hook'\n"
        )
        hook.chmod(0o755)
        result = on.push()
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ATTESTATION NOT POSTED" in result.stderr
        assert "HEAD moved" in result.stderr
        assert on.lines("gh") == []


class TestAWriteThatDoesNotReadBackIsNotConfirmed:
    def test_another_state_in_the_combined_status(self, on):
        result = on.push(GH_READBACK="failure")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ATTESTATION NOT CONFIRMED" in result.stderr
        assert "failure" in result.stderr
        assert f"{CONTEXT} = success posted" not in result.stdout
        assert f"Attestation: {CONTEXT} NOT confirmed" in result.stdout

    def test_no_such_context_in_the_combined_status(self, on):
        result = on.push(GH_READBACK="none")
        assert "ATTESTATION NOT CONFIRMED" in result.stderr
        assert result.returncode == 0

    def test_a_read_back_that_fails(self, on):
        result = on.push(GH_GET_EXIT="1", GH_GET_STDERR="gh: HTTP 500")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ATTESTATION NOT CONFIRMED" in result.stderr
        assert "gh: HTTP 500" in result.stderr

    def test_the_read_back_is_tried_again_before_giving_up(self, on):
        """A write can take a moment to show in the combined status."""
        on.push(GH_READBACK="none")
        reads = [row for row in on.lines("gh") if "POST" not in row]
        assert len(reads) == 3


class TestTheKnobIsReadFromTheCommit:
    REMEDY = "'on' or 'off'"

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "\n\n",
            "# on\n",
            "yes\n",
            "ON\n",
            "on off\n",
            "on\non\n",
            "true\n",
            "pr\n",
            "on # attest\n",
            "\ufeffon\n",
            "on\x0c\n",
            "o\x00n\n",
            "on\x00\n",
        ],
        ids=[
            "empty",
            "blank",
            "comment-only",
            "yes",
            "upper",
            "two-words",
            "twice",
            "true",
            "pr",
            "trailing-comment",
            "bom",
            "form-feed",
            "nul-inside",
            "nul-after",
        ],
    )
    def test_an_unusable_knob_is_exit_2_before_the_push(self, world, text):
        """Never `on`, and never silently `off`: a typo that fell back either
        way would write where nobody asked, or stop writing without a word."""
        world.commit_knob(text)
        result = world.push()
        assert result.returncode == 2, result.stdout + result.stderr
        assert KNOB in result.stderr
        assert self.REMEDY in result.stderr
        assert world.lines("gate") == []
        _nothing_was_pushed(world, result)

    def test_a_word_with_invisible_characters_is_shown_escaped(self, world):
        """CR 2673: a BOM echoed raw reads "says 'on': write 'on' or 'off'"."""
        world.commit_knob("\ufeffon\n")
        result = world.push()
        assert result.returncode == 2
        assert "says 'on'" not in result.stderr
        assert "says a word with bytes outside printable ASCII" in result.stderr

    def test_a_plain_wrong_word_is_quoted(self, world):
        world.commit_knob("yes\n")
        assert "says 'yes'" in world.push().stderr

    def test_a_knob_that_is_not_committed_is_exit_2(self, world):
        """Only a committed knob turns writes on: one developer's untracked
        file can't decide it for the repo. Ignored here, so the tree is
        clean and the refusal is the knob's own."""
        (world.repo / ".git" / "info").mkdir(exist_ok=True)
        (world.repo / ".git" / "info" / "exclude").write_text(".skills/\n")
        (world.repo / ".skills").mkdir()
        (world.repo / KNOB).write_text("on\n")
        result = world.push()
        assert result.returncode == 2, result.stdout + result.stderr
        assert "not in the commit" in result.stderr
        _nothing_was_pushed(world, result)

    def test_a_symlink_is_not_a_knob(self, world):
        (world.repo / ".skills").mkdir()
        (world.repo / ".skills" / "really").write_text("on\n")
        (world.repo / KNOB).symlink_to("really")
        _git(world.repo, "add", "-A")
        _git(world.repo, "commit", "-q", "-m", "a linked knob")
        result = world.push()
        assert result.returncode == 2, result.stdout + result.stderr
        assert "regular file" in result.stderr
        _nothing_was_pushed(world, result)

    def test_the_commit_decides_not_the_branch_it_came_from(self, on):
        """A branch that removes the knob stops attesting with that commit."""
        _git(on.repo, "checkout", "-q", "-b", "work")
        _git(on.repo, "rm", "-q", KNOB)
        _git(on.repo, "commit", "-q", "-m", "drop the knob")
        result = on.push()
        assert result.returncode == 0, result.stdout + result.stderr
        _is_the_plain_push(result.stdout, "work")
        assert on.lines("gh") == [] and on.lines("gate") == []


class TestTheLibraryAlone:
    def test_running_it_does_nothing(self, world):
        """There is no command-line path to the write: only push.sh, after
        the gate answered, in the same process."""
        result = subprocess.run(
            ["bash", str(LIB)],
            cwd=world.repo,
            capture_output=True,
            text=True,
            env=_env(ATTEST_LOG=str(world.log), PATH=f"{world.bindir}:/usr/bin:/bin"),
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert world.lines("gh") == []

    def test_help(self):
        result = subprocess.run(
            ["bash", str(LIB), "--help"], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0
        assert "sourced by push.sh" in result.stdout
        assert KNOB in result.stdout

    def test_push_help_names_the_knob(self):
        result = subprocess.run(
            ["bash", str(PUSH), "--help"], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0
        assert KNOB in result.stdout
        assert CONTEXT in result.stdout
