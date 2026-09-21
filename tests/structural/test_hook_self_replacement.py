"""#306 — the auto-refresh hook survives its own bytes being replaced mid-run.

`.claude/hooks/skills-submodule-update.sh` is a symlink into the submodule its
own `git submodule update` rewrites, and bash does not read a script once: it
reads it in pieces, resuming by byte offset. If the file's bytes change under a
running hook, everything after the update resumes at an old offset into new
content — on the path that commits and, since #293, pushes. The file's size is
not a marginal concern: it went from 19,086 to 35,062 bytes across
`b013b65..d3f91c8`.

The fix wraps the whole script in one `{ … }` block ending in `exit`, so bash
parses it to the closing brace before running any of it and never reads past
that brace. What this file pins, and why each is shaped the way it is:

- **The tail runs as written when the file is replaced in place mid-run.**
  A `git` shim rewrites the running copy at the moment the hook calls
  `git submodule update`, and the run must still commit and push. The
  replacement is contrived on purpose: every byte offset the old parse
  position could resume at is a `:` no-op line, followed by one line that
  records it ran. A realistic edit would do — the range above grew the file
  by 16 KB — but where its offsets land depends on the layout of the day, so
  whether the pre-fix hook garbles, re-runs a stretch of itself or happens to
  land on a statement boundary would change as the script is edited. This way
  the unprotected outcome is always the same one.
- **The fixture reaches the hazard.** The same run against a copy with the
  braces stripped out must execute the replacement's bytes and never commit.
  Without this control the first test could pass because the shim stopped
  rewriting anything, or stopped rewriting in place.
- **Git's own update is not an in-place writer — measured, not assumed.** Run
  through a real submodule update, an unprotected copy of the hook still runs
  its original tail, because git's checkout unlinks the old file and creates
  a new one, so the running bash keeps reading the inode it opened. That is
  why the braces are defence in depth against other writers (cp onto an
  existing file, a redirect) rather than the fix for an observed git corruption, and why the
  hook's own comment says so. Pinned here so that claim cannot go stale in
  prose: a git that starts rewriting in place turns this red.

Keep this list current — it is the file's index.
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

MS_SCRIPTS = "skills/managing-skills/scripts"
VENDOR = "skills-vendor/acme-skills"
FILE_TRANSPORT = {"GIT_ALLOW_PROTOCOL": "file"}

HOOK_SUBJECTS = {
    "chore: update skills submodules",
    "chore: refresh .skills/doctor.sh",
    "chore: update skills submodules and refresh .skills/doctor.sh",
}


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — `GIT_DIR` outranks `git -C` and the
    cwd, and git exports it to every hook, so an unscrubbed fixture would
    address the real repository (docs/STYLE.md). An identity is supplied
    because the hook commits."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
    )
    return env


def _git(repo: Path, *args: str, env_extra: dict | None = None) -> str:
    env = _clean_env()
    env.update(env_extra or {})
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    ).stdout


def _unbraced(text: str) -> str:
    """The hook without its wrapper: the line that opens the block and the
    last line that closes it, removed and nothing else — so the control runs
    exactly the statements the protected hook runs, read incrementally."""
    lines = text.split("\n")
    assert "{" in lines, "the hook has no line opening its `{ … }` block"
    body = [ln for ln in lines if ln.strip()]
    assert body[-1] == "}" and body[-2] == "exit 0", (
        "the hook must end in `exit 0` then a closing brace, with nothing after"
    )
    lines.remove("{")
    last = len(lines) - 1 - lines[::-1].index("}")
    del lines[last]
    return "\n".join(lines)


def _replacement(original: str) -> str:
    """New bytes, longer than the original, in which every offset the old
    parse position can resume at is a `:` no-op — then one line recording
    that replaced bytes ran. Deterministic whatever the hook's layout."""
    pad = ":\n" * (len(original.encode()) + 4096)
    return "#!/usr/bin/env bash\n" + pad + 'echo replaced >>"$MARK"\nexit 0\n'


def _vendor_tree(root: Path) -> None:
    scripts = root / MS_SCRIPTS
    scripts.mkdir(parents=True)
    shutil.copy2(DOCTOR, scripts / "doctor.sh")
    shutil.copy2(INSTALLER, scripts / "install-doctor.sh")
    (scripts / "install-doctor.sh").chmod(0o755)


# ------------------------------------------------ an in-place writer (shim)


@pytest.fixture
def consumer(tmp_path: Path):
    """A consumer on main tracking a bare remote, with a registered vendor
    whose update a `git` shim performs by rewriting the running hook copy IN
    PLACE — same inode, new bytes — and then reporting success.

    The tail's work is real: the first install writes an untracked doctor, so
    a hook that reaches its commit step commits it and pushes it.
    """
    from types import SimpleNamespace

    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-q", "-b", "main", str(origin))
    repo = tmp_path / "repo"
    _vendor_tree(repo / VENDOR)
    (repo / ".gitmodules").write_text(
        f'[submodule "acme-skills"]\n\tpath = {VENDOR}\n'
        "\turl = https://example.invalid/acme-skills.git\n"
    )
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "push", "-q", "-u", "origin", "main")

    hook = tmp_path / "hook" / "skills-submodule-update.sh"
    hook.parent.mkdir()
    new_bytes = tmp_path / "replacement.sh"

    shims = tmp_path / "bin"
    shims.mkdir()
    real_git = shutil.which("git") or "/usr/bin/git"
    (shims / "git").write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = submodule ]; then\n'
        '  if [ "$2" = update ]; then\n'
        "    # `>` truncates and rewrites the SAME inode: the in-place writer.\n"
        f'    cat "{new_bytes}" > "{hook}"\n'
        '  elif [ "$2" = status ]; then\n'
        f"    echo ' 1111111111111111111111111111111111111111 {VENDOR}'\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        f'exec {real_git} "$@"\n'
    )
    (shims / "git").chmod(0o755)
    return SimpleNamespace(
        path=repo,
        origin=origin,
        hook=hook,
        new_bytes=new_bytes,
        shims=shims,
        mark=tmp_path / "replaced-bytes-ran",
    )


def _run_copy(fx, text: str) -> subprocess.CompletedProcess:
    fx.hook.write_text(text)
    fx.new_bytes.write_text(_replacement(text))
    inode = fx.hook.stat().st_ino
    env = _clean_env()
    env["PATH"] = f"{fx.shims}:{env.get('PATH', '/usr/bin:/bin')}"
    env["MARK"] = str(fx.mark)
    result = subprocess.run(
        ["bash", str(fx.hook)],
        cwd=fx.path,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert fx.hook.read_text() == fx.new_bytes.read_text(), (
        "the shim never rewrote the running copy, so nothing here was tested"
    )
    assert fx.hook.stat().st_ino == inode, (
        "the rewrite replaced the file rather than writing it in place — the "
        "running bash kept its old inode and this fixture tests nothing"
    )
    return result


def _origin_head_subject(fx) -> str:
    return _git(fx.origin, "log", "-1", "--format=%s", "main").strip()


class TestTheTailRunsAsWritten:
    def test_a_file_rewritten_in_place_mid_run_does_not_change_what_runs(
        self, consumer
    ):
        """The fix. The hook's bytes are replaced at the update, and the rest
        of the run — install, commit, push — still happens as parsed."""
        result = _run_copy(consumer, HOOK.read_text())

        assert result.returncode == 0, result.stderr
        assert not consumer.mark.exists(), (
            "the running hook executed bytes that were written after it started "
            "— bash read past the update into the replacement (#306)"
        )
        subject = _origin_head_subject(consumer)
        assert subject in HOOK_SUBJECTS, (
            f"the tail never committed and pushed: the remote's head is {subject!r}"
        )
        log = (consumer.path / ".git" / "skills-update.log").read_text()
        assert "unpushed: pushed" in log, log

    def test_the_fixture_reaches_the_hazard(self, consumer):
        """The control. Without the braces, the same run resumes inside the
        replacement: it records that replaced bytes ran and never reaches the
        commit — which is what makes the first test's pass mean something."""
        result = _run_copy(consumer, _unbraced(HOOK.read_text()))

        assert result.returncode == 0, result.stderr
        assert consumer.mark.exists(), (
            "an unprotected hook survived an in-place rewrite of itself, so "
            "the fixture no longer exercises the hazard the braces close"
        )
        assert _origin_head_subject(consumer) == "init", (
            "the unprotected tail committed and pushed anyway"
        )


# -------------------------------------------- git's own writer (real update)


class TestGitReplacesByUnlink:
    def test_a_real_submodule_update_leaves_the_running_inode_alone(
        self, tmp_path: Path
    ):
        """The measurement behind the hook's comment. An UNPROTECTED hook,
        run through the symlink into a real submodule whose upstream ships the
        replacement bytes, still runs its original tail: git's checkout
        unlinked the old file and created a new one, and bash kept reading the
        inode it had opened. Measured on git 2.39.3; if a git release ever
        rewrites in place, this goes red and the comment is wrong."""
        unbraced = _unbraced(HOOK.read_text())
        up = tmp_path / "up"
        _vendor_tree(up)
        hook_in_vendor = up / MS_SCRIPTS / "skills-submodule-update.sh"
        hook_in_vendor.write_text(unbraced)
        hook_in_vendor.chmod(0o755)
        _git(tmp_path, "init", "-q", "-b", "main", str(up))
        _git(up, "add", "-A")
        _git(up, "commit", "-qm", "the hook as the consumer runs it")

        repo = tmp_path / "repo"
        _git(tmp_path, "init", "-q", "-b", "main", str(repo))
        (repo / "README.md").write_text("consumer\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        _git(repo, "submodule", "add", "-q", str(up), VENDOR, env_extra=FILE_TRANSPORT)
        link = repo / ".claude" / "hooks" / "skills-submodule-update.sh"
        link.parent.mkdir(parents=True)
        link.symlink_to(f"../../{VENDOR}/{MS_SCRIPTS}/skills-submodule-update.sh")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "vendor, and the hook linked into it")

        replacement = _replacement(unbraced)
        hook_in_vendor.write_text(replacement)
        _git(up, "commit", "-qam", "upstream ships different, longer bytes")

        running = repo / VENDOR / MS_SCRIPTS / "skills-submodule-update.sh"
        inode = running.stat().st_ino
        mark = tmp_path / "replaced-bytes-ran"
        env = _clean_env()
        env.update(FILE_TRANSPORT)
        env["MARK"] = str(mark)
        result = subprocess.run(
            ["bash", ".claude/hooks/skills-submodule-update.sh"],
            cwd=repo,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )

        assert result.returncode == 0, result.stderr
        assert running.read_text() == replacement, (
            "the update did not bring the new bytes in, so nothing was measured"
        )
        assert running.stat().st_ino != inode, (
            "git rewrote the running script IN PLACE — the hook's comment "
            "claims it unlinks and recreates; re-measure and update it"
        )
        assert not mark.exists(), "the running hook read the new bytes"
        subject = _git(repo, "log", "-1", "--format=%s").strip()
        assert subject in HOOK_SUBJECTS, (
            f"the original tail did not run to its commit: {subject!r}"
        )
