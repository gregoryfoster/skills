"""A throwaway world for deploying-releases' core (#372): origin, checkout, root, host.

Ported from CannObserv/broker's ``tests/deploy/test_deploy.py`` at ``bbf1c72f``
(itself from CannObserv/status's and CannObserv/processor's harnesses), widened
to the core's hooks, targets and restarts. Real git, a temporary origin and
clone; stubs on ``PATH`` for ``uv``, ``sudo``, ``systemctl``, ``journalctl``,
``stat``, ``curl``, ``gh``, ``getent`` and ``logger`` that record every call,
and the checkout's ``scripts/co-pypi.sh`` stubbed the same way. ``FAKE_*``
variables make them play a failing sync, a venv that no longer runs, a unit
that dies on a build, a health endpoint on the wrong build, and so on.

The project is ``acme``. Its units, by default:

- ``acme-api.service``: long-running, enabled, verified by ``/health``;
- ``acme-probe.service`` + ``.timer``: a oneshot verified by its next tick;
- ``acme-backup.service`` + ``.timer``: a oneshot verified by one forced run.

The stubs play root (status#14): ``FAKE_ROOT_OWNED`` is a ledger of what root
owns, kept unwritable except through ``sudo``. They need GNU coreutils and
util-linux's ``flock``: on macOS the tests skip, and run in a Linux container,
as a user that is not root (the core refuses root)::

    docker run --rm -v "$PWD:/w:ro" ubuntu:24.04 bash -c '
      apt-get update -qq && apt-get install -yqq python3-pytest git jq >/dev/null &&
      cp -r /w /t && useradd -m u && chown -R u /t &&
      su u -c "cd /t && GNUBIN_REQUIRED=1 python3 -m pytest -q -p no:cacheprovider \\
        tests/structural/test_deploying_releases_core.py"'
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / "skills" / "deploying-releases"
CORE = SKILL / "assets" / "deploy.sh"
TEMPLATE = SKILL / "assets" / "deploy_hooks.sh.tmpl"
INSTALL = SKILL / "scripts" / "install.sh"

JOB = "lint + test"
API = "acme-api.service"
PROBE = "acme-probe.service"
BACKUP = "acme-backup.service"
HEALTH = "http://127.0.0.1:9000/health"

INDEX = "https://us-west1-python.pkg.dev/co-gcs/co-pypi/simple/"
UV_LOCK = f"""version = 1

[[package]]
name = "acme"
version = "0.1.0"
source = {{ editable = "." }}

[[package]]
name = "co-core"
version = "0.40.0"
source = {{ registry = "{INDEX}" }}
"""
WHEELHOUSE_LOCK = UV_LOCK.replace(f'registry = "{INDEX}"', 'registry = ".wheelhouse"')

# The hooks a repo shaped like broker plus an API would write.
HOOKS = """\
PROJECT=acme
GITHUB_REPO=CannObserv/acme
CI_JOBS=("lint + test")
UV_WRAPPER=scripts/co-pypi.sh
IMPORT_MODULES=(acme)
HOST_CONFIGS=("sysctl.d/60-acme.conf=/etc/sysctl.d/60-acme.conf")
verify() {
  case "$1" in
    acme-api.service) verify_http_health "http://127.0.0.1:9000/health" "$2" ;;
    acme-probe.service) verify_next_tick "$1" "$2" "Probe summary" ;;
    acme-backup.service) verify_forced_run "$1" "$2" "$ACME_BACKUP_STATE" '.revision == $want' ;;
    *) return 2 ;;
  esac
}
"""

STUB_CO_PYPI = r"""#!/usr/bin/env bash
echo "co-pypi $PWD $*" >> "$FAKE_LOG"
[[ -z "${FAKE_MINT_FAIL:-}" ]] || { echo "error: could not mint a token" >&2; exit 1; }
UV_INDEX_CO_PYPI_USERNAME=oauth2accesstoken UV_INDEX_CO_PYPI_PASSWORD=stand-in exec "$@"
"""

STUB_UV = r"""#!/usr/bin/env bash
echo "uv $PWD pair=${UV_INDEX_CO_PYPI_USERNAME:+set} PYDL=${UV_PYTHON_DOWNLOADS:-}" \
  "UPE=${UV_PROJECT_ENVIRONMENT:-} VENV=${VIRTUAL_ENV:-} $*" >> "$FAKE_LOG"
case "$1" in
  sync)
    [[ -n "${FAKE_SYNC_FAIL:-}" ]] && exit 1
    mkdir -p .venv/bin
    printf 'home = %s\n' "${FAKE_PYTHON_HOME:-/usr/bin}" > .venv/pyvenv.cfg
    cp "$FAKE_PYTHON" .venv/bin/python ;;
esac
exit 0
"""

# The release venv's interpreter: `-c` is the probe, which prints REVISION or dev.
STUB_PYTHON = r"""#!/usr/bin/env bash
echo "python $PWD $*" >> "$FAKE_LOG"
while [[ "$1" == -I || "$1" == -B ]]; do shift; done
case "$1" in
  -m) [[ "$2" == compileall && -n "${FAKE_COMPILE_FAIL:-}" ]] && exit 1 ;;
  -c)
    [[ -n "${FAKE_BROKEN_VENV:-}" ]] && { echo "probe: no interpreter" >&2; exit 2; }
    if [[ -f REVISION && -n "${FAKE_REVISION_SAYS:-}" ]]; then echo "$FAKE_REVISION_SAYS"; exit 0; fi
    cat REVISION 2>/dev/null || echo dev ;;
esac
exit 0
"""

STUB_SUDO = r"""#!/usr/bin/env bash
if [[ "$1" == -n ]]; then shift; else echo "sudo-without-n $*" >> "$FAKE_LOG"; fi
echo "sudo $*" >> "$FAKE_LOG"
[[ "$1" == chown && -n "${FAKE_CHOWN_FAIL:-}" ]] && exit 1
as_root() {
  local kind path opened=() rc=0
  while read -r kind path; do
    [[ -d "$path" && ! -L "$path" ]] && /bin/chmod u+w "$path" && opened+=("$path")
  done <"$FAKE_ROOT_OWNED"
  if [[ "$1" == rm && "$2" == -rf ]]; then
    for path in "${@:3}"; do [[ -e "$path" ]] && /bin/chmod -R u+w "$path"; done
  fi
  "$@" || rc=$?
  for path in "${opened[@]}"; do [[ -d "$path" ]] && /bin/chmod a-w "$path"; done
  return $rc
}
ledger() { echo "$1 $2" >>"$FAKE_ROOT_OWNED"; }
case "$1" in
  install)
    [[ -n "${FAKE_INSTALL_FAIL:-}" && "${@: -1}" == */"$FAKE_INSTALL_FAIL" ]] && exit 1
    args=()
    while (($#)); do
      if [[ ("$1" == -o || "$1" == -g) && "$2" == root ]]; then shift 2; continue; fi
      args+=("$1"); shift
    done
    set -- "${args[@]}"
    as_root "$@" || exit
    if [[ "$2" == -d* && " $* " != *" -o "* ]]; then
      ledger D "${@: -1}"
      /bin/chmod a-w "${@: -1}"
    fi
    exit 0 ;;
  chown)
    [[ "$2" == -R && "$3" == root:root ]] || { echo "stub sudo: chown $*?" >&2; exit 1; }
    [[ -z "$(find "$4" ! -type l -perm -u=w -print -quit)" ]] || echo "chown-of-writable $4" >> "$FAKE_LOG"
    ledger R "$4"
    exit 0 ;;
  rm)
    as_root "$@" || exit
    for path in "${@:2}"; do
      [[ -e "$path" || -L "$path" ]] || sed -i "\#^[DR] $path\(/.*\)\{0,1\}\$#d" "$FAKE_ROOT_OWNED"
    done
    exit 0 ;;
  mv)
    count="$(dirname "$FAKE_LOG")/mv-count"
    n=$(($(cat "$count") + 1)); echo "$n" > "$count"
    [[ "$n" == "${FAKE_MV_FAIL:-0}" ]] && exit 1
    as_root "$@"; exit ;;
  ln | chmod | touch | tee) as_root "$@"; exit ;;
  readlink) exec readlink "${@:2}" ;;
  systemctl) shift; FAKE_VIA_SUDO=1 exec systemctl "$@" ;;
esac
echo "stub sudo: $*?" >&2
exit 1
"""

STUB_STAT = r"""#!/usr/bin/env bash
if [[ "$1" == -c && ( "$2" == %u || "$2" == %u:%g ) ]]; then
  path="${@: -1}"
  while read -r kind owned; do
    if [[ "$path" == "$owned" || ("$kind" == R && "$path" == "$owned"/*) ]]; then
      [[ "$2" == %u ]] && echo 0 || echo 0:0
      exit 0
    fi
  done <"$FAKE_ROOT_OWNED"
fi
exec @STAT@ "$@"
"""

# systemd, as far as the core asks it. Each unit reports the build its
# installed WorkingDirectory= serves. A restart starts a new main PID whose
# /proc/<pid>/cwd is that directory, resolved; the probe ticks on its own, one
# invocation every FAKE_TICK_EVERY polls; the backup's forced run writes its
# state file. State lives in <tmp>/state.
STUB_SYSTEMCTL = r"""#!/usr/bin/env bash
[[ -n "${FAKE_VIA_SUDO:-}" ]] || echo "systemctl $*" >> "$FAKE_LOG"
dir="$(dirname "$FAKE_LOG")"
state="$dir/state"
wd_of() { sed -n 's/^WorkingDirectory=//p' "$FAKE_UNIT_DIR/$1" 2>/dev/null | tail -n 1; }
served() {
  local rev
  rev="$(cd -P "$(wd_of "$1")" 2>/dev/null && cat REVISION 2>/dev/null)" || rev=""
  echo "${rev:-dev}"
}
listed() { [[ " $2 " == *" $1 "* ]]; }
case "$1" in
  show)
    shift; props=(); value=0; unit=""
    while (($#)); do
      case "$1" in -p) props+=("$2"); shift ;; --value) value=1 ;; *) unit="$1" ;; esac
      shift
    done
    if [[ "$unit" == acme-probe.service && " ${props[*]} " == *" InvocationID "* ]]; then
      n=$(( $(cat "$dir/probe-polls") + 1 )); echo "$n" > "$dir/probe-polls"
      tick=$(( n / ${FAKE_TICK_EVERY:-2} ))
      build="$(served acme-probe.service)"
      rc=0; [[ "$build" == "${FAKE_PROBE_FAIL_BUILD:-none}" ]] && rc=1
      echo "tick-$tick $build" > "$dir/probe-tick"
    fi
    for p in "${props[@]}"; do
      case "$p" in
        MainPID) v="$(cat "$state/$unit.pid" 2>/dev/null || echo 0)" ;;
        ActiveState)
          if [[ "$unit" == acme-probe.service ]]; then v="${FAKE_PROBE_STATE:-inactive}"
          elif [[ "$unit" == acme-backup.service ]]; then
            left="$(cat "$dir/backup-busy")"
            if ((left > 0)); then echo $((left - 1)) > "$dir/backup-busy"; v=activating; else v=inactive; fi
          else v="$(cat "$state/$unit.active" 2>/dev/null || echo inactive)"; fi ;;
        NeedDaemonReload) v=no; listed "$unit" "${FAKE_NEEDS_RELOAD:-}" && v=yes ;;
        WorkingDirectory) v="$(wd_of "$unit")"; listed "$unit" "${FAKE_STALE_LOAD:-}" && v=/elsewhere ;;
        InvocationID) v="tick-$tick" ;;
        Result) v=success; ((rc == 0)) || v=exit-code ;;
        ExecMainStatus) v="$rc" ;;
        *) v="" ;;
      esac
      if ((value)); then echo "$v"; else echo "$p=$v"; fi
    done ;;
  restart)
    unit="$2"
    listed "$unit" "${FAKE_RESTART_FAIL:-}" && exit 1
    # systemd's 200/CHDIR: a WorkingDirectory= that does not resolve never starts.
    cwd="$(cd -P "$(wd_of "$unit")" 2>/dev/null && pwd)" || { echo failed > "$state/$unit.active"; exit 1; }
    n=$(( $(cat "$state/next-pid") + 1 )); echo "$n" > "$state/next-pid"
    echo "$n" > "$state/$unit.pid"
    if [[ "$(served "$unit")" == "${FAKE_DIES_ON:-none}" ]]; then
      echo failed > "$state/$unit.active"
    else
      echo active > "$state/$unit.active"
    fi
    mkdir -p "$FAKE_PROC/$n"
    ln -sfn "$cwd" "$FAKE_PROC/$n/cwd" ;;
  start)
    [[ "$2" == acme-backup.service ]] || exit 0
    build="$(served acme-backup.service)"
    [[ "$build" == "${FAKE_BACKUP_FAIL_BUILD:-none}" ]] && exit 1
    printf '{"outcome": "uploaded", "revision": "%s"}\n' "${FAKE_BACKUP_SAYS:-$build}" > "$FAKE_BACKUP_STATE" ;;
  try-restart) listed "$2" "${FAKE_TRY_RESTART_FAIL:-}" && exit 1 ;;
  is-active)
    unit="${@: -1}"
    listed "$unit" "${FAKE_INACTIVE:-}" && exit 3
    if [[ "$unit" == *.timer ]]; then [[ -f "$FAKE_UNIT_DIR/$unit" ]] || exit 3
    else [[ "$(cat "$state/$unit.active" 2>/dev/null)" == active ]] || exit 3; fi ;;
  is-enabled)
    unit="${@: -1}"
    grep -qxF "$unit" "$state/enabled" 2>/dev/null || exit 1 ;;
  enable)
    unit="${@: -1}"
    [[ "$unit" == "${FAKE_ENABLE_FAIL:-none}" ]] && exit 1
    echo "$unit" >> "$state/enabled" ;;
  reset-failed | daemon-reload) ;;
esac
exit 0
"""

STUB_JOURNALCTL = r"""#!/usr/bin/env bash
echo "journalctl $*" >> "$FAKE_LOG"
read -r tick build < "$(dirname "$FAKE_LOG")/probe-tick"
[[ "$1" == "_SYSTEMD_INVOCATION_ID=$tick" ]] || exit 0
echo "Starting acme-probe.service..."
printf '{"level": "INFO", "message": "Probe summary", "revision": "%s"}\n' "$build"
"""

# GitHub's Actions API from <tmp>/ci (runs-<n>.json in turn, the last repeating;
# jobs-<id>.json), else one green push run on main; and the API's /health,
# which reports the build acme-api.service's installed unit serves.
STUB_CURL = r"""#!/usr/bin/env bash
url="${@: -1}"
echo "curl $url" >> "$FAKE_LOG"
ci="$(dirname "$FAKE_LOG")/ci"
if [[ "$url" == http://127.0.0.1:9000/health ]]; then
  [[ -z "${FAKE_HEALTH_DOWN:-}" ]] || exit 7
  # FAKE_HEALTH_DEGRADED: 503 with the right build in the body, as curl
  # --fail answers it (no body, exit 22); without --fail the body comes back.
  if [[ -n "${FAKE_HEALTH_DEGRADED:-}" ]]; then
    [[ " $* " == *" -fsS "* || " $* " == *" --fail "* ]] && exit 22
    wd="$(sed -n 's/^WorkingDirectory=//p' "$FAKE_UNIT_DIR/acme-api.service" | tail -n 1)"
    printf '{"status": "degraded", "revision": "%s"}\n' "$(cd -P "$wd" 2>/dev/null && cat REVISION)"
    exit 0
  fi
  wd="$(sed -n 's/^WorkingDirectory=//p' "$FAKE_UNIT_DIR/acme-api.service" | tail -n 1)"
  rev="$(cd -P "$wd" 2>/dev/null && cat REVISION 2>/dev/null)" || rev=""
  rev="${rev:-dev}"
  [[ "$rev" == "${FAKE_HEALTH_STALE_ON:-none}" ]] && rev=stale
  printf '{"status": "ok", "revision": "%s"}\n' "$rev"
  exit 0
fi
if [[ -n "${FAKE_CI_ERROR:-}" ]]; then
  [[ " $* " == *" --fail-with-body "* ]] && echo "{\"message\":\"$FAKE_CI_ERROR\"}"
  exit 22
fi
case "$url" in
  */jobs*)
    id="${url#*/actions/runs/}"; id="${id%%/*}"
    cat "$ci/jobs-$id.json" 2>/dev/null ||
      echo '{"jobs":[{"name":"lint + test","status":"completed","conclusion":"success"}]}' ;;
  *)
    sha="${url#*head_sha=}"; sha="${sha%%&*}"
    n="$(cat "$ci/polls")"; echo $((n + 1)) > "$ci/polls"
    answers=("$ci"/runs-*.json)
    if [[ -e "${answers[0]}" ]]; then
      last=$((${#answers[@]} - 1))
      cat "$ci/runs-$((n < last ? n : last)).json"
    else
      echo "{\"workflow_runs\":[{\"id\":1,\"head_sha\":\"$sha\",\"event\":\"push\",
        \"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"success\",
        \"created_at\":\"2026-10-01T00:00:00Z\",\"html_url\":\"https://github.test/runs/1\"}]}"
    fi ;;
esac
"""

# gh api, answering as the curl stub does, and saying whether a token leaked in.
STUB_GH = r"""#!/usr/bin/env bash
echo "gh token=${GH_TOKEN:+leaked}${GITHUB_TOKEN:+leaked} $*" >> "$FAKE_LOG"
exec curl -sS --fail-with-body "https://api.github.com/${@: -1}"
"""

STUB_LOGGER = r"""#!/usr/bin/env bash
echo "logger $*" >> "$FAKE_LOG"
"""

STUB_GETENT = r"""#!/usr/bin/env bash
echo "getent $*" >> "$FAKE_LOG"
[[ "$1" == passwd && " ${FAKE_USERS:-} " == *" $2 "* ]] || exit 2
"""


def clean_env(extra: dict | None = None) -> dict:
    """The caller's environment without GIT_* (docs/STYLE.md: a hook's GIT_DIR
    would point a fixture's git at the real repo)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(extra or {})
    return env


def git(cwd: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=clean_env(env),
    ).stdout.strip()


def _cannot_run(reason: str) -> None:
    """Skip, loudly; or fail under GNUBIN_REQUIRED=1, where the core's tests
    must run (a Linux CI job, the container), as SHELLCHECK_REQUIRED does."""
    message = f"{reason}: the core's behaviour tests DID NOT RUN (GNUBIN_REQUIRED=1 makes this a failure)"
    if os.environ.get("GNUBIN_REQUIRED", "") not in ("", "0"):
        pytest.fail(message)
    pytest.skip(message)


def require_linux_tools() -> None:
    """The core runs on a Linux host: GNU stat and mv, util-linux flock, jq, bash 4."""
    missing = [t for t in ("flock", "jq", "git", "bash") if shutil.which(t) is None]
    if missing:
        _cannot_run(f"needs {', '.join(missing)} on PATH (a Linux host's tools)")
    probe = subprocess.run(["stat", "-c", "%a", "/"], capture_output=True, text=True)
    if probe.returncode != 0:
        _cannot_run("stat is not GNU stat (no -c), so this is not a Linux host")
    bash = subprocess.run(
        ["bash", "-c", "echo ${BASH_VERSINFO[0]}"], capture_output=True, text=True
    )
    if int(bash.stdout.strip() or 0) < 4:
        _cannot_run("bash on PATH is older than 4")


def unit(
    name: str,
    workdir: Path | str | None,
    *,
    version: str = "v1",
    kind: str = "simple",
    user: str | None = "acme",
) -> str:
    if name.endswith(".timer"):
        return f"[Timer]\n# {name} {version}\nOnUnitActiveSec=10min\n"
    lines = ["[Service]", f"# {name} {version}", f"Type={kind}"]
    if user:
        lines.append(f"User={user}")
    if workdir is not None:
        lines.append(f"WorkingDirectory={workdir}")
    return "\n".join(lines) + "\n"


class World:
    """A temp origin, clone, deploy root, host tree and stubbed PATH.

    By default the units are installed and run the dev checkout, and every
    release's units equal the installed ones once ``go_live`` has run.
    """

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.origin = tmp / "origin.git"
        self.checkout = tmp / "checkout"
        self.root = tmp / "srv"
        self.host = tmp / "host"
        self.units = self.host / "etc" / "systemd" / "system"
        self.proc = self.host / "proc"
        self.state = tmp / "state"
        self.backup_state = tmp / "backup-state.json"
        self.log = tmp / "calls.log"
        self.stubs = tmp / "stubs"
        self.ci = tmp / "ci"
        self.owned = tmp / "root-owned"
        for d in (self.root, self.stubs, self.ci, self.state, self.proc):
            d.mkdir(parents=True)
        self.units.mkdir(parents=True)
        self.log.touch()
        self.owned.write_text(f"D {self.root}\n")
        self.root.chmod(0o555)

        git(tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(tmp, "clone", "-q", str(self.origin), str(self.checkout))
        git(self.checkout, "config", "user.email", "t@example.com")
        git(self.checkout, "config", "user.name", "t")
        self.dev_units = self.units_on(self.checkout)
        self.live_units = self.units_on(self.root / "live")
        self.write_tree(self.checkout, self.dev_units)
        (self.checkout / "uv.lock").write_text(UV_LOCK)
        (self.checkout / "pyproject.toml").write_text('[project]\nname = "acme"\n')
        git(self.checkout, "add", "-A")
        self.main = [self.commit(f"main-{i}") for i in range(3)]
        git(self.checkout, "push", "-q", "origin", "main")
        git(self.checkout, "switch", "-q", "-c", "feature")
        self.feature = self.commit("feature")
        git(self.checkout, "push", "-q", "origin", "feature")
        git(self.checkout, "switch", "-q", "main")
        self.unpushed = self.commit("unpushed")
        self.install(self.dev_units)
        # The API runs, enabled, on the checkout; the timers are enabled.
        (self.state / "enabled").write_text(
            f"{API}\nacme-probe.timer\nacme-backup.timer\n"
        )
        (self.state / "next-pid").write_text("100")
        self.start(API)

        scripts = self.checkout / "scripts"
        scripts.mkdir()
        shutil.copy(CORE, scripts / "deploy.sh")
        (scripts / "co-pypi.sh").write_text(STUB_CO_PYPI)
        (scripts / "co-pypi.sh").chmod(0o755)
        self.hooks(HOOKS)

        for name, body in (
            ("uv", STUB_UV),
            ("sudo", STUB_SUDO),
            ("curl", STUB_CURL),
            ("gh", STUB_GH),
            ("logger", STUB_LOGGER),
            ("getent", STUB_GETENT),
            ("systemctl", STUB_SYSTEMCTL),
            ("journalctl", STUB_JOURNALCTL),
            (
                "stat",
                STUB_STAT.replace("@STAT@", shutil.which("stat") or "/usr/bin/stat"),
            ),
            ("fake-python", STUB_PYTHON),
        ):
            stub = self.stubs / name
            stub.write_text(body)
            stub.chmod(0o755)

    @staticmethod
    def units_on(workdir: Path, version: str = "v1") -> dict[str, str]:
        return {
            API: unit(API, workdir, version=version),
            PROBE: unit(PROBE, workdir, version=version, kind="oneshot"),
            "acme-probe.timer": unit("acme-probe.timer", None, version=version),
            BACKUP: unit(BACKUP, workdir, version=version, kind="oneshot"),
            "acme-backup.timer": unit("acme-backup.timer", None, version=version),
        }

    @staticmethod
    def write_tree(
        checkout: Path, files: dict[str, str | None], under: str = "deploy"
    ) -> None:
        for name, body in files.items():
            path = checkout / under / name
            if body is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)

    def hooks(self, text: str) -> None:
        """The checkout's scripts/deploy_hooks.sh, which the core sources."""
        (self.checkout / "scripts" / "deploy_hooks.sh").write_text(text)

    def commit(self, label: str, env: dict | None = None) -> str:
        (self.checkout / "version.txt").write_text(label)
        git(self.checkout, "add", "-A")
        git(self.checkout, "commit", "-q", "-m", label, env=env)
        return git(self.checkout, "rev-parse", "HEAD")

    def install(self, units: dict[str, str]) -> None:
        """Units as an operator installed them before this deploy."""
        for name, body in units.items():
            (self.units / name).write_text(body)

    def start(self, name: str) -> None:
        """The unit runs now, as systemd started it before this deploy."""
        n = int((self.state / "next-pid").read_text()) + 1
        (self.state / "next-pid").write_text(str(n))
        (self.state / f"{name}.pid").write_text(f"{n}\n")
        (self.state / f"{name}.active").write_text("active\n")

    def disable(self, name: str) -> None:
        lines = (self.state / "enabled").read_text().splitlines()
        (self.state / "enabled").write_text(
            "".join(f"{x}\n" for x in lines if x != name)
        )
        (self.state / f"{name}.active").write_text("inactive\n")

    def enabled(self) -> list[str]:
        return (self.state / "enabled").read_text().split()

    def run(self, *args: str, **fake: str) -> subprocess.CompletedProcess:
        env = clean_env(
            {
                "PATH": f"{self.stubs}:{os.environ['PATH']}",
                "HOME": str(self.tmp),
                "ACME_DEPLOY_ROOT": str(self.root),
                "ACME_DEPLOY_HOST": str(self.host),
                "ACME_DEPLOY_VERIFY_SECONDS": "2",
                "ACME_DEPLOY_TICK_SECONDS": "5",
                "ACME_DEPLOY_RUN_WAIT_SECONDS": "5",
                "ACME_DEPLOY_POLL_SECONDS": "0",
                "ACME_DEPLOY_CI_POLL_SECONDS": "0",
                "ACME_BACKUP_STATE": str(self.backup_state),
                "FAKE_LOG": str(self.log),
                "FAKE_ROOT_OWNED": str(self.owned),
                "FAKE_UNIT_DIR": str(self.units),
                "FAKE_PROC": str(self.proc),
                "FAKE_BACKUP_STATE": str(self.backup_state),
                "FAKE_PYTHON": str(self.stubs / "fake-python"),
                "FAKE_USERS": "acme",
                **fake,
            }
        )
        (self.tmp / "backup-busy").write_text(fake.get("FAKE_BACKUP_BUSY", "0"))
        (self.tmp / "probe-polls").write_text("0")
        (self.tmp / "probe-tick").write_text("none none\n")
        (self.ci / "polls").write_text("0")
        (self.tmp / "mv-count").write_text("0")
        argv = [str(self.checkout / "scripts" / "deploy.sh"), *args]
        return subprocess.run(
            argv, cwd=self.tmp, env=env, capture_output=True, text=True, timeout=120
        )

    def build(self, sha: str) -> str:
        return git(self.checkout, "rev-parse", "--short=12", sha)

    def release(self, sha: str) -> Path:
        return self.root / "releases" / self.build(sha)

    def push(
        self,
        units: dict[str, str | None] | None = None,
        env: dict | None = None,
        top: dict[str, str] | None = None,
        branch: str = "main",
    ) -> str:
        """Commit on top of origin's branch and push it, from a clone of its own
        (the checkout's main holds an unpushed commit)."""
        pusher = self.tmp / "pusher"
        if not pusher.exists():
            git(self.tmp, "clone", "-q", str(self.origin), str(pusher))
            git(pusher, "config", "user.email", "t@example.com")
            git(pusher, "config", "user.name", "t")
        git(pusher, "fetch", "-q", "origin")
        git(pusher, "switch", "-q", "-C", branch, f"origin/{branch}")
        self.write_tree(pusher, units or {})
        for name, body in (top or {}).items():
            path = pusher / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        git(pusher, "add", "-A")
        git(pusher, "commit", "-q", "--allow-empty", "-m", "pushed", env=env)
        git(pusher, "push", "-q", "origin", branch)
        git(self.checkout, "fetch", "-q", "origin")
        sha = git(pusher, "rev-parse", "HEAD")
        if branch == "main":
            self.main.append(sha)
        return sha

    def go_live(self, units: dict[str, str] | None = None) -> str:
        """The units run the release live names; returns the commit that put them there."""
        units = units or self.live_units
        sha = self.push(units)
        self.install(units)
        return sha

    def installed(self, name: str) -> str | None:
        path = self.units / name
        return path.read_text() if path.exists() else None

    def target(self, name: str = "live") -> str | None:
        link = self.root / name
        return os.readlink(link) if link.is_symlink() else None

    def ci_answers(self, *answers: list[dict] | str) -> None:
        for n, runs in enumerate(answers):
            body = (
                runs if isinstance(runs, str) else json.dumps({"workflow_runs": runs})
            )
            (self.ci / f"runs-{n}.json").write_text(body)

    def ci_jobs(self, run_id: int, **conclusions: str) -> None:
        jobs = {JOB: "success", **conclusions}
        body = [
            {"name": n, "status": "completed", "conclusion": c}
            for n, c in jobs.items()
            if c != "absent"
        ]
        (self.ci / f"jobs-{run_id}.json").write_text(json.dumps({"jobs": body}))

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines()

    def root_owned(self, path: Path) -> bool:
        for line in self.owned.read_text().splitlines():
            kind, owned = line.split(" ", 1)
            if str(path) == owned or (
                kind == "R" and str(path).startswith(owned + "/")
            ):
                return True
        return False

    def reset_log(self) -> None:
        self.log.write_text("")

    def cleanup(self) -> None:
        if self.root.exists():
            for path in [self.root, *self.root.rglob("*")]:
                if not path.is_symlink():
                    path.chmod(path.stat().st_mode | stat.S_IWUSR)


def ci_run(run_id: int, sha: str, **kw) -> dict:
    status = kw.get("status", "completed")
    return {
        "id": run_id,
        "head_sha": sha,
        "event": kw.get("event", "push"),
        "head_branch": kw.get("branch", "main"),
        "status": status,
        "conclusion": kw.get("conclusion", "success")
        if status == "completed"
        else None,
        "created_at": kw.get("created", "2026-10-01T00:00:00Z"),
        "html_url": f"https://github.test/runs/{run_id}",
    }


def assert_ok(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def index_of(calls: list[str], needle: str) -> int:
    return next(i for i, call in enumerate(calls) if needle in call)


def installs(calls: list[str]) -> list[str]:
    """The unit names `sudo install -m 644` wrote, in order."""
    return [
        Path(c.split()[-1]).name for c in calls if c.startswith("sudo install -m 644 ")
    ]


def restarts(calls: list[str]) -> list[str]:
    return [c.split()[-1] for c in calls if c.startswith("sudo systemctl restart ")]


def wait_for(predicate, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition never held"
        time.sleep(0.05)
