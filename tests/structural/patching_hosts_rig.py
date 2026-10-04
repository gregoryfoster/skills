"""The stub rig patching-hosts' script tests share (#313).

A fixture root, stubs on PATH for every command that asks the running system,
and the knob. Every stub is a symlink to one dispatcher, which logs its argv
and then answers from the cases a test set for the name it was called by.
Unmatched, a stub exits 1 with nothing on stdout: a reading that couldn't be
taken.

Each test module runs the whole script under the system's bash (3.2 on
macOS), and subclasses Host with a `run` that builds that script's command
line.
"""

import contextlib
import json
import os
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL = REPO_ROOT / "skills" / "patching-hosts"
DAY = 86400
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

# Every command the probe may run that asks the system, so none reaches the
# machine running the tests.
STUBBED = (
    "systemctl",
    "journalctl",
    "systemd-analyze",
    "apt-config",
    "apt-get",
    "apt-cache",
    "apt-mark",
    "dpkg-query",
    "dpkg",
    "needrestart",
    "pro",
    "psql",
    "pg_lsclusters",
    "tailscale",
    "docker",
    "redis-cli",
    "ss",
    "unattended-upgrade",
    "runuser",
    "git",
    "hostname",
    "curl",
    "timeout",
    "time",
)


def clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["LC_ALL"] = "C"
    env.pop("APT_CONFIG", None)
    return env


# Its fields split on the record separator: psql's own -F is the unit
# separator.
DISPATCH = """#!/bin/sh
name=${0##*/}
printf '%s\\036%s\\036%s\\n' "$name" "$*" "${APT_CONFIG:-}" >> "$STUB_LOG"
. "$STUB_CASES/$name"
exit 1
"""
_DISPATCHER: list[Path] = []


@contextlib.contextmanager
def dispatcher(tmp_path_factory):
    """The session's dispatcher, for a module-scoped autouse fixture."""
    p = tmp_path_factory.mktemp("stub") / "dispatch"
    p.write_text(DISPATCH)
    p.chmod(0o755)
    # Run it once, so its first-exec scan is paid here and not in a run.
    subprocess.run(
        [str(p)],
        env={"STUB_LOG": "/dev/null", "STUB_CASES": "/nonexistent"},
        capture_output=True,
    )
    _DISPATCHER[:] = [p]
    yield
    _DISPATCHER.clear()


def pattern(glob: str) -> str:
    """A `case` pattern: `*` stays a wildcard, everything else is literal."""
    return "*".join("'" + part.replace("'", "'\\''") + "'" for part in glob.split("*"))


class Host:
    """A fixture root, the stubs that answer for it, and the knob."""

    STUBBED: tuple[str, ...] = STUBBED
    # What a stub does when no case matches. timeout runs its command, after
    # its options and the cases a test set.
    FALLBACKS: dict[str, str] = {
        "timeout": 'while case $1 in -k | -s) shift 2 ;; -*) shift ;; *) false ;; esac; do :; done; shift; exec "$@"',
        # GNU time, as noble's 1.9 writes its -o file: a failed command's
        # status line, then the format, here with a max RSS of 2048 KiB.
        "time": (
            "f=; o=; while [ $# -gt 0 ]; do case $1 in -f) f=$2; shift 2 ;; -o) o=$2; shift 2 ;; *) break ;; esac; done\n"
            'rc=0; "$@" || rc=$?\n'
            '{ if [ "$rc" -ne 0 ]; then echo "Command exited with non-zero status $rc"; fi; '
            'printf "%s\\n" "$f" | sed "s/%M/2048/"; } > "$o"\n'
            "exit $rc"
        ),
    }

    def __init__(
        self,
        tmp_path: Path,
        *,
        live: bool = True,
        uptime_days: int = 40,
        sudo: bool | str = True,
    ):
        self.tmp = tmp_path
        self.root = tmp_path / "root"
        self.bin = tmp_path / "bin"
        self.repo = tmp_path / "repo"
        self.log = tmp_path / "argv.log"
        self.knob_path = tmp_path / "knob"
        self.tmpdir = tmp_path / "tmp"
        for d in (self.root, self.bin, self.repo, self.tmpdir):
            d.mkdir()
        self.now = int(time.time())
        self.sudo = sudo
        self.missing: set[str] = set()
        self.cases: dict[str, list[tuple[str, str, int, str]]] = {
            n: [] for n in self.STUBBED
        }
        if live:
            (self.root / "run" / "systemd" / "system").mkdir(parents=True)
        self.write(
            "proc/stat", f"cpu  1 2 3\nbtime {self.now - uptime_days * DAY - 60}\n"
        )
        self.chain([(4242, "bash", 0), (1, "systemd", 0)])

    # --- the tree -----------------------------------------------------------

    def write(
        self,
        rel: str,
        text: str | bytes = "",
        mode: int | None = None,
        age_days: float | None = None,
    ) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            p.write_bytes(text)
        else:
            p.write_text(text)
        if mode is not None:
            p.chmod(mode)
        if age_days is not None:
            then = self.now - age_days * DAY
            os.utime(p, (then, then))
        return p

    def link(self, rel: str, target: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.symlink_to(target)

    def mask(self, unit: str) -> None:
        self.link(f"etc/systemd/system/{unit}", "/dev/null")

    def enable(self, unit: str, target: str = "timers.target") -> None:
        self.write(
            f"usr/lib/systemd/system/{unit}", f"[Unit]\n[Install]\nWantedBy={target}\n"
        )
        self.link(
            f"etc/systemd/system/{target}.wants/{unit}",
            f"/usr/lib/systemd/system/{unit}",
        )

    def chain(self, procs: list[tuple[int, str, int]]) -> None:
        for i, (pid, comm, adj) in enumerate(procs):
            ppid = procs[i + 1][0] if i + 1 < len(procs) else 0
            self.write(f"proc/{pid}/status", f"Name:\t{comm}\nPPid:\t{ppid}\n")
            self.write(f"proc/{pid}/comm", comm + "\n")
            self.write(f"proc/{pid}/oom_score_adj", f"{adj}\n")

    # --- the stubs ----------------------------------------------------------

    def on(
        self,
        cmd: str,
        glob: str,
        stdout: str = "",
        rc: int = 0,
        stderr: str = "",
        script: str | None = None,
    ) -> "Host":
        """Answer CMD's argv matching GLOB, or run SCRIPT, a shell snippet, instead."""
        self.cases[cmd].append((glob, stdout, rc, stderr, script))
        return self

    def installed(self, *pkgs: str) -> "Host":
        for p in pkgs:
            self.on("dpkg-query", "*-W -f ${db:Status-Abbrev} " + p, "ii ")
        return self

    def show(self, unit: str, **props: str) -> "Host":
        return self.on(
            "systemctl",
            f"show*-- {unit}",
            "".join(f"{k}={v}\n" for k, v in props.items()),
        )

    def apt_config(self, **values: str) -> "Host":
        names = {"Enable": "PE", "Lists": "PU", "UU": "PUU", "Reboot": "UR"}
        self.on(
            "apt-config",
            "shell*",
            "".join(f"{names[k]}='{v}'\n" for k, v in values.items()),
        )
        return self

    def absent(self, *names: str) -> "Host":
        """Take NAMES off PATH: no stub for them, and none of the system's."""
        self.missing.update(names)
        return self

    def _system_path(self) -> str:
        # With nothing missing, the system's own directories. Otherwise a
        # directory of links to everything in them but the missing names, so
        # a real /usr/bin/docker can't stand in for an absent one.
        if not self.missing:
            return SYSTEM_PATH
        sysbin = self.tmp / "sysbin"
        if not sysbin.exists():
            sysbin.mkdir()
            for d in SYSTEM_PATH.split(":"):
                for entry in sorted(Path(d).iterdir()):
                    link = sysbin / entry.name
                    if entry.name not in self.missing and not link.is_symlink():
                        link.symlink_to(entry)
        return str(sysbin)

    def knob(self, text: str) -> "Host":
        self.knob_path.write_text(text)
        return self

    def _write_stubs(self) -> None:
        # A symlink to the session's dispatcher, and a sourced file of cases:
        # macOS scans a newly written executable on its first run, about 0.1 s
        # each, which made every probe run here cost 2 s.
        cases = self.tmp / "cases"
        cases.mkdir(exist_ok=True)
        for name, rows in self.cases.items():
            lines = ['case "$*" in']
            for i, row in enumerate(rows):
                glob, out, rc, err = row[:4]
                if len(row) > 4 and row[4]:
                    lines.append(f"  {pattern(glob)}) {row[4]} ;;")
                    continue
                o = cases / f".{name}.{i}.out"
                o.write_text(out)
                redirect = ""
                if err:
                    (cases / f".{name}.{i}.err").write_text(err)
                    redirect = f" cat '{cases}/.{name}.{i}.err' >&2;"
                lines.append(f"  {pattern(glob)}) cat '{o}';{redirect} exit {rc} ;;")
            lines += ["esac", self.FALLBACKS.get(name, "exit 1"), ""]
            (cases / name).write_text("\n".join(lines))
        # sudo runs its command as root, or as -u's user, and id answers for
        # whoever that is. sudo="reset" drops the environment, as sudoers'
        # env_reset can: only PATH and the stubs' own variables survive.
        sudo_exec = 'exec "$@"\n'
        if self.sudo == "reset":
            sudo_exec = (
                'exec env -i PATH="$PATH" STUB_LOG="$STUB_LOG" '
                'STUB_CASES="$STUB_CASES" STUB_USER="$STUB_USER" "$@"\n'
            )
        (cases / "sudo").write_text(
            "STUB_USER=root\n"
            "while [ $# -gt 0 ]; do case $1 in -n) shift ;; -u) STUB_USER=$2; shift 2 ;; --) shift; break ;; *) break ;; esac; done\n"
            "export STUB_USER\n" + sudo_exec
            if self.sudo
            else "echo 'sudo: a password is required' >&2\nexit 1\n"
        )
        (cases / "id").write_text(
            "case ${STUB_USER:-exedev} in root) u=0 ;; *) u=1000 ;; esac\n"
            'case "$1" in -u) echo $u ;; -un) echo ${STUB_USER:-exedev} ;; *) echo "uid=$u(${STUB_USER:-exedev})" ;; esac\nexit 0\n'
        )
        (cases / "choom").write_text(
            "while [ $# -gt 0 ]; do case $1 in -n) shift 2 ;; --) shift; break ;; *) break ;; esac; done\n"
            'exec "$@"\n'
        )
        for name in (*self.STUBBED, "sudo", "id", "choom"):
            link = self.bin / name
            if name in self.missing:
                link.unlink(missing_ok=True)
            elif not link.is_symlink():
                link.symlink_to(_DISPATCHER[0])

    def execute(self, cmd: list[str], rc: int = 0, env_extra: dict | None = None):
        """Run CMD against the stubs; its JSON when it exits 0, else the result."""
        self._write_stubs()
        env = clean_env()
        env.update(env_extra or {})
        env["PATH"] = f"{self.bin}:{self._system_path()}"
        env["TMPDIR"] = str(self.tmpdir)
        env["STUB_LOG"] = str(self.log)
        env["STUB_CASES"] = str(self.tmp / "cases")
        # From tmp_path, so a stray glob in the script could only expand there.
        r = subprocess.run(
            cmd, capture_output=True, text=True, env=env, timeout=180, cwd=self.tmp
        )
        self.result = r
        assert r.returncode == rc, f"exit {r.returncode}\n{r.stderr}"
        return json.loads(r.stdout) if rc == 0 else r

    def calls(self, name: str | None = None) -> list[tuple[str, str, str]]:
        if not self.log.exists():
            return []
        # split("\n"), not splitlines(): that breaks on the record separator too.
        lines = [line for line in self.log.read_text().split("\n") if line]
        rows = [tuple((line.split("\x1e") + ["", ""])[:3]) for line in lines]
        return [r for r in rows if name is None or r[0] == name]
