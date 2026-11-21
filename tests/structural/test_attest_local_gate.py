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


def _is_the_plain_push(stdout: str, branch: str = "main") -> None:
    """The pre-knob script's two lines around git's own, whose wording for
    the upstream it set varies by version. Nothing about an attestation."""
    assert stdout.startswith(f"Pushing {branch} to origin...\n"), stdout
    assert stdout.endswith("Push succeeded.\n"), stdout
    assert "ttest" not in stdout, stdout
    assert len(stdout.splitlines()) <= 3, stdout


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

    def test_a_failing_push_still_fails_as_git_does(self, tmp_path):
        w = _world(tmp_path / "w")
        _git(w.repo, "config", f"url.{w.root / 'nowhere.git'}.insteadOf", GITHUB_URL)
        _git(w.repo, "config", "--unset", f"url.{w.remote}.insteadOf")
        result = w.push()
        assert result.returncode != 0
        assert "Push succeeded." not in result.stdout
        assert w.lines("gh") == []
