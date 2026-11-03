"""A consumer repo for the refresh hook's interrupted and rolled-back runs.

`skills-submodule-update.sh` is tested elsewhere against shimmed or plain-file
vendor trees. The runs here (#555, #550) are about what a refresh leaves behind
when it stops part way, or when its push is refused, so they need everything a
real refresh touches:

- a real `skills-vendor/` submodule over the `file` transport, recorded one
  commit behind its upstream, so a refresh visibly moves the pointer;
- a vendored `install-doctor.sh` and `doctor.sh` that differ between the two
  commits, so the doctor a run installs says which pointer it came from;
- a bare `origin` the superproject tracks, so the push and its rollback are
  real.

A run is started in its own process group (`start_new_session`). A fixture
kills the hook the way the VS Code extension's config-cache process does
(#555): `kill -<SIG> 0` from inside the run, which reaches the hook, its git
children and the killer itself, and nothing outside the group. Without its own
group, `kill 0` would reach the test runner.
"""

import os
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "skills" / "managing-skills" / "scripts"
HOOK = SCRIPTS / "skills-submodule-update.sh"
DOCTOR = SCRIPTS / "doctor.sh"
INSTALLER = SCRIPTS / "install-doctor.sh"

VENDOR = "skills-vendor/acme-skills"
MS_SCRIPTS = "skills/managing-skills/scripts"
DOCTOR_PATH = ".skills/doctor.sh"

# `git submodule` refuses the `file` transport by default since git 2.38.
FILE_TRANSPORT = {"GIT_ALLOW_PROTOCOL": "file"}

MSG_SUB = "chore: update skills submodules"
MSG_BOTH = "chore: update skills submodules and refresh .skills/doctor.sh"


def clean_env() -> dict:
    """Env without inherited GIT_* vars (docs/STYLE.md, #189), with an
    identity, since the hook commits."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
    )
    env.update(FILE_TRANSPORT)
    return env


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        env=clean_env(),
    )


def _vendor_commit(up: Path, doctor_text: str, message: str) -> str:
    scripts = up / MS_SCRIPTS
    (scripts / "doctor.sh").write_text(doctor_text)
    (scripts / "doctor.sh").chmod(0o755)
    git(up, "add", "-A")
    git(up, "commit", "-qm", message)
    return git(up, "rev-parse", "HEAD").stdout.strip()


def build(tmp_path: Path, *, doctor_tracked: bool = True) -> SimpleNamespace:
    """The consumer, its origin and its vendored upstream.

    `doctor_tracked` chooses the doctor's state before any run: committed at
    the recorded pointer's version, or absent (the hook's first session-start
    install then writes it untracked, the #86 case).
    """
    v1 = DOCTOR.read_text()
    # Appended, so the header install-doctor.sh checks for stays first.
    v2 = v1 + "# fixture: the upstream commit the refresh brings in\n"

    up = tmp_path / "up"
    git(tmp_path, "init", "-q", "-b", "main", str(up))
    (up / MS_SCRIPTS).mkdir(parents=True)
    shutil.copy2(INSTALLER, up / MS_SCRIPTS / "install-doctor.sh")
    (up / MS_SCRIPTS / "install-doctor.sh").chmod(0o755)
    before = _vendor_commit(up, v1, "vendor c1")

    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-q", "-b", "main", str(origin))

    repo = tmp_path / "work"
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    # A developer's global core.hooksPath would bypass the consumer hook a
    # test installs below.
    git(repo, "config", "core.hooksPath", str(repo / ".git" / "hooks"))
    git(repo, "remote", "add", "origin", str(origin))
    (repo / "README.md").write_text("consumer\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    git(repo, "submodule", "add", "-q", str(up), VENDOR)
    if doctor_tracked:
        (repo / ".skills").mkdir()
        (repo / DOCTOR_PATH).write_text(v1)
        (repo / DOCTOR_PATH).chmod(0o755)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "vendor acme-skills")
    git(repo, "push", "-q", "-u", "origin", "main")

    after = _vendor_commit(up, v2, "vendor c2")

    bindir = tmp_path / "bin"
    bindir.mkdir()
    ns = SimpleNamespace(
        path=repo,
        origin=origin,
        up=up,
        bindir=bindir,
        before=before,
        after=after,
        v1=v1,
        v2=v2,
        kill_flag=tmp_path / "kill-armed",
    )
    write_shim(ns)
    return ns


def write_shim(c: SimpleNamespace, kill_when: str = "", signal_name: str = "KILL"):
    """A `git` on the hook's PATH that delegates to real git, and once — while
    `c.kill_flag` exists — kills the run's whole process group when the
    `kill_when` test (a bash condition over "$@") holds."""
    real_git = shutil.which("git") or "/usr/bin/git"
    arm = ""
    if kill_when:
        arm = (
            f'if [ -f "{c.kill_flag}" ] && {kill_when}; then\n'
            f'  rm -f "{c.kill_flag}"\n'
            f"  kill -{signal_name} 0\n"
            "  sleep 5\n"
            "fi\n"
        )
    shim = c.bindir / "git"
    shim.write_text(f'#!/usr/bin/env bash\n{arm}exec {real_git} "$@"\n')
    shim.chmod(0o755)


def arm_pre_commit_kill(c: SimpleNamespace, signal_name: str) -> None:
    """A consumer pre-commit hook that kills the run from inside `git
    commit`, once. The consumer's own pre-commit framework is where the
    11-01 run spent its last second."""
    hook = c.path / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        "#!/bin/sh\n"
        f'if [ -f "{c.kill_flag}" ]; then\n'
        f'  rm -f "{c.kill_flag}"\n'
        f"  kill -{signal_name} 0\n"
        "  sleep 5\n"
        "fi\n"
        "exit 0\n"
    )
    hook.chmod(0o755)
    c.kill_flag.write_text("")


def run_hook(c: SimpleNamespace, timeout: float = 120) -> subprocess.CompletedProcess:
    """One session start. Waits for the whole process group to be gone, so a
    killed run's git children cannot still be writing when the test looks."""
    env = clean_env()
    env["PATH"] = f"{c.bindir}:{env.get('PATH', '/usr/bin:/bin')}"
    proc = subprocess.Popen(
        ["bash", str(HOOK)],
        cwd=c.path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    out, err = proc.communicate(timeout=timeout)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            break
        except PermissionError:
            break  # the group id was reused by someone else's process
        time.sleep(0.05)
    else:
        os.killpg(proc.pid, signal.SIGKILL)
        raise AssertionError("the run's process group outlived the run")
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


def gitlink(c: SimpleNamespace, rev: str = "HEAD") -> str:
    """The pointer the superproject records at `rev`."""
    return git(c.path, "rev-parse", f"{rev}:{VENDOR}").stdout.strip()


def content(c: SimpleNamespace) -> str:
    """The commit the vendored checkout actually holds."""
    return git(c.path / VENDOR, "rev-parse", "HEAD").stdout.strip()


def staged(c: SimpleNamespace) -> list[str]:
    out = git(c.path, "diff", "--cached", "--name-only").stdout
    return [line for line in out.split("\n") if line]


def ahead(c: SimpleNamespace) -> int:
    out = git(c.path, "rev-list", "--count", "@{u}..HEAD", check=False).stdout
    return int(out.strip()) if out.strip().isdigit() else -1


def origin_gitlink(c: SimpleNamespace) -> str:
    return git(c.origin, "rev-parse", f"main:{VENDOR}").stdout.strip()


def log_text(c: SimpleNamespace) -> str:
    log = c.path / ".git" / "skills-update.log"
    return log.read_text() if log.exists() else ""


def lock(c: SimpleNamespace) -> Path:
    return c.path / ".git" / "skills-update.lock"


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def spend_todays_lock(c: SimpleNamespace) -> None:
    lock(c).write_text(today() + "\n")


def break_remote(c: SimpleNamespace) -> None:
    """Point origin somewhere that does not exist: the push fails after the
    commit, as an unreachable remote or a missing credential makes it."""
    git(c.path, "remote", "set-url", "origin", str(c.path.parent / "gone.git"))
