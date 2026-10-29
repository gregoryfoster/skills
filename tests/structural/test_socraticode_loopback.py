"""SocratiCode's managed containers are created on loopback, and a wide one is reported (#494).

SocratiCode creates its stack with `docker run -p ${QDRANT_PORT}:6333 …` and no
host IP, so an unauthenticated Qdrant holding every indexed chunk's source
text, and its Ollama, listen on every interface. Docker's publishes bypass the
host firewall. Qdrant's telemetry is on. SocratiCode finds its containers by
name and starts an existing one, so a container created first on 127.0.0.1
holds — until it is removed, when the next call recreates it wide. Measured
with socraticode 1.16.1 against a throwaway Docker daemon on 2026-10-28.

The fix has three parts, and each is a class here:

- **`loopback-containers.sh` creates what is missing and touches nothing
  else.** Upstream's argv, with `127.0.0.1:` on each publish and telemetry
  off. It never removes, stops, renames or recreates a container: the swap is
  a manual procedure that needs the operator's approval.
- **Preflight fails a missing or a wide container,** reading them through that
  script's `--check`, and only where Docker already answered.
- **The daily hook reads the listeners,** with `ss` or `lsof`, never docker.

A stub stands in for docker throughout, holding its containers in a JSON file,
so no case here reaches a real daemon.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from .test_socraticode_external_store import _host, _preflight, _project
from .test_socraticode_graph_yield import HOOK, _clean_env, _repo, requires_node

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL = REPO_ROOT / "skills" / "init-socraticode"
SCRIPT = SKILL / "scripts" / "loopback-containers.sh"
PREFLIGHT = SKILL / "scripts" / "preflight.sh"
REFERENCE = SKILL / "references" / "loopback-containers.md"
SKILL_MD = SKILL / "SKILL.md"

QDRANT_IMAGE = "qdrant/qdrant:v1.17.0"
OLLAMA_IMAGE = "ollama/ollama:latest"

# Upstream's own `docker run`, as 1.13.1 and 1.16.1 issue it
# (dist/services/docker.js startQdrant / startOllama, constants.js), with the
# default ports. The script's must equal it but for the host IP and the one
# environment variable.
UPSTREAM_RUN = {
    "qdrant": [
        "run", "-d", "--name", "socraticode-qdrant",
        "-p", "16333:6333", "-p", "16334:6334",
        "-v", "socraticode_qdrant_data:/qdrant/storage",
        "--restart", "unless-stopped",
        QDRANT_IMAGE,
    ],
    "ollama": [
        "run", "-d", "--name", "socraticode-ollama",
        "-p", "11435:11434",
        "-v", "socraticode_ollama_data:/root/.ollama",
        "--restart", "unless-stopped",
        OLLAMA_IMAGE,
    ],
}  # fmt: skip

# Containers live in $STUB_CONTAINERS: {name: {state, binds: [[ip, port]], env}}.
# `inspect --format` prints the layout the script's template produces — state,
# a tab, `ip|port ` per publish, then one environment variable per line — since
# a stub cannot evaluate a Go template. The real template was run against
# Docker 27.5.1 on 2026-10-28.
DOCKER_STUB = r"""#!{python}
import json, os, sys
args = sys.argv[1:]
with open(os.path.join(os.environ["STUB_DIR"], "docker.log"), "a") as log:
    log.write(json.dumps(args) + "\n")
path = os.environ["STUB_CONTAINERS"]
state = json.load(open(path)) if os.path.exists(path) else {{}}
cmd = args[0] if args else ""
if cmd == "inspect":
    name = args[-1]
    if name not in state:
        sys.stderr.write(f"Error: No such object: {{name}}\n")
        sys.exit(1)
    c = state[name]
    if "--format" in args:
        binds = "".join(f"{{ip}}|{{port}} " for ip, port in c.get("binds", []))
        sys.stdout.write(c.get("state", "running") + "\t" + binds + "\n")
        for e in c.get("env", []):
            sys.stdout.write(e + "\n")
    else:
        sys.stdout.write(json.dumps([c]) + "\n")
elif cmd == "ps":
    f = args[args.index("--filter") + 1].split("=", 1)[1]
    for name in state:
        if f in name:
            print(name)
elif cmd == "run":
    if os.environ.get("STUB_RUN_FAIL"):
        sys.stderr.write(os.environ["STUB_RUN_FAIL"] + "\n")
        sys.exit(125)
    name = args[args.index("--name") + 1]
    binds, env = [], []
    for i, a in enumerate(args):
        if a == "-p":
            parts = args[i + 1].split(":")
            binds.append(["" if len(parts) == 2 else parts[0], parts[-2]])
        if a == "-e":
            env.append(args[i + 1])
    state[name] = {{"state": "running", "binds": binds, "env": env}}
    json.dump(state, open(path, "w"))
    print("0123456789ab")
sys.exit(0)
"""

LOOPBACK_Q = {"state": "running", "binds": [["127.0.0.1", "16333"], ["127.0.0.1", "16334"]],
              "env": ["PATH=/usr/bin", "QDRANT__TELEMETRY_DISABLED=true"]}  # fmt: skip
LOOPBACK_O = {"state": "running", "binds": [["127.0.0.1", "11435"]], "env": []}
# What upstream's own run leaves: HostIp "" on each publish, telemetry on.
WIDE_Q = {"state": "running", "binds": [["", "16333"], ["", "16334"]], "env": []}
WIDE_O = {"state": "running", "binds": [["", "11435"]], "env": []}

MUTATING = {"run", "rm", "stop", "rename", "start", "kill", "create", "restart", "pull"}


class Docker:
    """A bin dir whose docker is the stub, beside the tools the script needs."""

    def __init__(self, tmp_path: Path, containers: dict | None = None) -> None:
        self.dir = tmp_path / "docker-stub"
        self.bin = self.dir / "bin"
        self.bin.mkdir(parents=True)
        stub = self.bin / "docker"
        stub.write_text(DOCKER_STUB.format(python=sys.executable))
        stub.chmod(0o755)
        self.state = self.dir / "containers.json"
        self.state.write_text(json.dumps(containers or {}))
        self.log = self.dir / "docker.log"
        self.log.touch()

    def env(self) -> dict:
        return {"STUB_DIR": str(self.dir), "STUB_CONTAINERS": str(self.state)}

    def calls(self) -> list[list[str]]:
        return [json.loads(ln) for ln in self.log.read_text().splitlines()]

    def mutations(self) -> list[list[str]]:
        return [c for c in self.calls() if c and c[0] in MUTATING]

    def runs(self) -> list[list[str]]:
        return [c for c in self.calls() if c and c[0] == "run"]


def _script(docker: Docker, *args: str, **env: str) -> subprocess.CompletedProcess:
    base = {k: v for k, v in os.environ.items()
            if k not in ("QDRANT_PORT", "QDRANT_GRPC_PORT", "OLLAMA_PORT", "DOCKER_HOST")}  # fmt: skip
    base.update(docker.env())
    base["PATH"] = f"{docker.bin}{os.pathsep}{base.get('PATH', '')}"
    base.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=base,
    )


def _rows(result: subprocess.CompletedProcess) -> dict[str, tuple[str, str]]:
    rows = {}
    for line in result.stdout.splitlines():
        target, name, verdict, detail = line.split("\t")
        rows[target] = (verdict, detail)
    return rows


def _upstream_but_loopback(
    target: str, qp="16333", qg="16334", op="11435"
) -> list[str]:
    """Upstream's argv, with 127.0.0.1 on each publish and telemetry off."""
    argv = list(UPSTREAM_RUN[target])
    ports = {"16333": qp, "16334": qg, "11435": op}
    for i, a in enumerate(argv):
        if argv[i - 1] == "-p":
            host, cont = a.split(":")
            argv[i] = f"127.0.0.1:{ports[host]}:{cont}"
    if target == "qdrant":
        argv[-1:-1] = ["-e", "QDRANT__TELEMETRY_DISABLED=true"]
    return argv


class TestTheScriptCreatesWhatIsMissing:
    def test_it_creates_both_with_upstreams_argv_on_loopback(self, tmp_path):
        docker = Docker(tmp_path)
        result = _script(docker, "qdrant", "ollama")
        assert result.returncode == 0, result.stderr
        assert docker.runs() == [
            _upstream_but_loopback("qdrant"),
            _upstream_but_loopback("ollama"),
        ]
        rows = _rows(result)
        assert rows["qdrant"][0] == "created" and "telemetry off" in rows["qdrant"][1]
        assert rows["ollama"][0] == "created"

    def test_it_creates_only_the_targets_it_is_given(self, tmp_path):
        docker = Docker(tmp_path)
        assert _script(docker, "qdrant").returncode == 0
        assert [r[3] for r in docker.runs()] == ["socraticode-qdrant"]

    def test_upstreams_port_variables_reach_the_publishes(self, tmp_path):
        docker = Docker(tmp_path)
        result = _script(docker, "qdrant", "ollama",
                         QDRANT_PORT="26333", QDRANT_GRPC_PORT="26334", OLLAMA_PORT="21435")  # fmt: skip
        assert result.returncode == 0, result.stderr
        assert docker.runs() == [
            _upstream_but_loopback("qdrant", "26333", "26334", "21435"),
            _upstream_but_loopback("ollama", "26333", "26334", "21435"),
        ]

    def test_an_image_can_be_overridden(self, tmp_path):
        docker = Docker(tmp_path)
        _script(
            docker, "--qdrant-image", "q:1", "--ollama-image", "o:2", "qdrant", "ollama"
        )
        assert [r[-1] for r in docker.runs()] == ["q:1", "o:2"]

    def test_a_failed_run_is_unknown_and_keeps_dockers_message(self, tmp_path):
        docker = Docker(tmp_path)
        result = _script(
            docker, "qdrant", STUB_RUN_FAIL="Bind for 0.0.0.0:16333 failed"
        )
        assert result.returncode == 1
        assert _rows(result)["qdrant"][0] == "unknown"
        assert "Bind for 0.0.0.0:16333 failed" in result.stderr, (
            "docker's own message must reach the operator, not be swallowed"
        )

    def test_a_rerun_is_a_no_op(self, tmp_path):
        docker = Docker(tmp_path)
        _script(docker, "qdrant", "ollama")
        before = len(docker.runs())
        result = _script(docker, "qdrant", "ollama")
        assert result.returncode == 0
        assert len(docker.runs()) == before
        assert {v for v, _ in _rows(result).values()} == {"ok"}


class TestTheScriptNeverTouchesAnExistingContainer:
    """The swap is a manual procedure with the operator's approval, never this script."""

    @pytest.mark.parametrize("check", [False, True], ids=["create", "check"])
    def test_a_wide_container_is_reported_and_left_alone(self, tmp_path, check):
        docker = Docker(
            tmp_path, {"socraticode-qdrant": WIDE_Q, "socraticode-ollama": WIDE_O}
        )
        result = _script(docker, *(["--check"] if check else []), "qdrant", "ollama")
        assert result.returncode == 1
        assert docker.mutations() == [], docker.mutations()
        rows = _rows(result)
        assert rows["qdrant"][0] == "wide"
        assert (
            "0.0.0.0:16333" in rows["qdrant"][1]
            and "telemetry not disabled" in rows["qdrant"][1]
        )
        assert rows["ollama"][0] == "wide"

    def test_check_creates_nothing(self, tmp_path):
        docker = Docker(tmp_path)
        result = _script(docker, "--check", "qdrant", "ollama")
        assert result.returncode == 1
        assert docker.mutations() == []
        assert {v for v, _ in _rows(result).values()} == {"missing"}

    def test_no_mutating_docker_verb_but_run_appears_in_the_script(self):
        text = SCRIPT.read_text()
        for verb in MUTATING - {"run"}:
            assert not re.search(rf"\bdocker\s+{verb}\b", text), verb


class TestTheScriptsVerdicts:
    @pytest.mark.parametrize(
        ("ip", "verdict"),
        [("127.0.0.1", "ok"), ("::1", "ok"), ("", "wide"), ("0.0.0.0", "wide"),
         ("::", "wide"), ("100.64.0.7", "wide")],
    )  # fmt: skip
    def test_only_loopback_is_ok(self, tmp_path, ip, verdict):
        c = {"state": "running", "binds": [[ip, "11435"]], "env": []}
        docker = Docker(tmp_path, {"socraticode-ollama": c})
        assert _rows(_script(docker, "--check", "ollama"))["ollama"][0] == verdict

    def test_qdrant_on_loopback_with_telemetry_on(self, tmp_path):
        c = dict(LOOPBACK_Q, env=["PATH=/usr/bin"])
        docker = Docker(tmp_path, {"socraticode-qdrant": c})
        result = _script(docker, "--check", "qdrant")
        assert result.returncode == 1
        assert _rows(result)["qdrant"][0] == "telemetry"

    def test_a_name_containing_the_containers_is_a_decoy(self, tmp_path):
        """SocratiCode's existence check is `.includes(name)`."""
        old = dict(LOOPBACK_Q, state="exited")
        docker = Docker(
            tmp_path, {"socraticode-qdrant": LOOPBACK_Q, "socraticode-qdrant-old": old}
        )
        verdict, detail = _rows(_script(docker, "--check", "qdrant"))["qdrant"]
        assert verdict == "decoy" and "socraticode-qdrant-old" in detail

    def test_the_mitigations_backup_name_is_not_a_decoy(self, tmp_path):
        docker = Docker(
            tmp_path, {"socraticode-qdrant": LOOPBACK_Q, "bak494-qdrant": WIDE_Q}
        )
        assert _rows(_script(docker, "--check", "qdrant"))["qdrant"][0] == "ok"

    def test_a_container_publishing_nothing_is_unknown(self, tmp_path):
        docker = Docker(
            tmp_path,
            {"socraticode-ollama": {"state": "exited", "binds": [], "env": []}},
        )
        assert _rows(_script(docker, "--check", "ollama"))["ollama"][0] == "unknown"

    @pytest.mark.parametrize(
        "args",
        [[], ["redis"], ["--qdrant-image"], ["--bogus", "qdrant"]],
        ids=["no-target", "bad-target", "flag-without-value", "unknown-flag"],
    )
    def test_usage_errors_exit_2(self, tmp_path, args):
        assert _script(Docker(tmp_path), *args).returncode == 2

    def test_a_non_numeric_port_exits_2(self, tmp_path):
        assert _script(Docker(tmp_path), "qdrant", QDRANT_PORT="16333x").returncode == 2


def _newest_cached_socraticode() -> Path | None:
    best = None
    for pkg in Path.home().glob(".npm/_npx/*/node_modules/socraticode/package.json"):
        try:
            version = tuple(
                int(x) for x in json.loads(pkg.read_text())["version"].split(".")
            )
        except (ValueError, KeyError, json.JSONDecodeError):
            continue
        if best is None or version > best[0]:
            best = (version, pkg.parent)
    return best[1] if best else None


class TestTheArgvMatchesTheCachedUpstream:
    """Where a SocratiCode build is cached here, its docker.js still issues UPSTREAM_RUN.

    The tripwire for an upstream that changes its image, volume or ports: the
    script would then create a container upstream does not, and this fails
    where that build is installed, naming what moved.
    """

    def test_the_newest_cached_build_agrees(self):
        root = _newest_cached_socraticode()
        if root is None:
            pytest.skip("no socraticode build in the npx cache to compare against")
        docker_js = (root / "dist" / "services" / "docker.js").read_text()
        constants = (root / "dist" / "constants.js").read_text()
        for needle in (
            '"-p", `${QDRANT_PORT}:6333`',
            '"-p", `${QDRANT_GRPC_PORT}:6334`',
            '"-v", "socraticode_qdrant_data:/qdrant/storage"',
            '"-p", `${OLLAMA_PORT}:11434`',
            '"-v", "socraticode_ollama_data:/root/.ollama"',
            '"--restart", "unless-stopped"',
        ):
            assert needle in docker_js, f"{root}: docker.js no longer issues {needle}"
        for needle in (
            'QDRANT_CONTAINER_NAME = "socraticode-qdrant"',
            'OLLAMA_CONTAINER_NAME = "socraticode-ollama"',
            f'QDRANT_IMAGE = "{QDRANT_IMAGE}"',
            f'OLLAMA_IMAGE = "{OLLAMA_IMAGE}"',
            'process.env.QDRANT_PORT || "16333"',
            'process.env.QDRANT_GRPC_PORT || "16334"',
            'process.env.OLLAMA_PORT || "11435"',
        ):
            assert needle in constants, f"{root}: constants.js no longer has {needle}"

    def test_the_scripts_defaults_are_the_tests(self):
        text = SCRIPT.read_text()
        assert f'QDRANT_IMAGE="{QDRANT_IMAGE}"' in text
        assert f'OLLAMA_IMAGE="{OLLAMA_IMAGE}"' in text


# ── Preflight ────────────────────────────────────────────────────────────────


def _preflight_with(tmp_path: Path, containers: dict | None, **env: str):
    binv = _host(tmp_path)
    stub = binv / "docker"
    stub.write_text(DOCKER_STUB.format(python=sys.executable))
    stub.chmod(0o755)
    state = binv.parent / "containers.json"
    if containers is not None:
        state.write_text(json.dumps(containers))
    result = _preflight(tmp_path, _project(tmp_path), binv,
                        STUB_CONTAINERS=str(state), **env)  # fmt: skip
    log = binv.parent / "docker.log"
    calls = (
        [json.loads(ln) for ln in log.read_text().splitlines()] if log.exists() else []
    )
    return result, calls


def _line(result: subprocess.CompletedProcess, needle: str) -> str:
    lines = [ln for ln in result.stdout.splitlines() if needle in ln]
    assert lines, f"no line with {needle!r}:\n{result.stdout}"
    return lines[0]


class TestPreflightReadsTheContainers:
    def test_loopback_containers_pass(self, tmp_path):
        result, _ = _preflight_with(tmp_path, {"socraticode-qdrant": LOOPBACK_Q,
                                               "socraticode-ollama": LOOPBACK_O})  # fmt: skip
        assert "✓" in _line(
            result, "socraticode-qdrant (running) is on loopback, telemetry off"
        )
        assert "✓" in _line(result, "socraticode-ollama (running) is on loopback")

    def test_a_missing_container_fails_and_names_the_create_command(self, tmp_path):
        result, calls = _preflight_with(tmp_path, {})
        assert result.returncode == 1
        assert "✗" in _line(result, "socraticode-qdrant does not exist yet")
        hint = _line(result, "create it on loopback first:")
        assert f'bash "{SCRIPT}" qdrant ollama' in hint, hint
        assert not [c for c in calls if c and c[0] in MUTATING], (
            "preflight created something"
        )

    def test_a_wide_container_fails_and_points_at_the_reference(self, tmp_path):
        result, calls = _preflight_with(tmp_path, {"socraticode-qdrant": WIDE_Q,
                                                   "socraticode-ollama": LOOPBACK_O})  # fmt: skip
        assert result.returncode == 1
        line = _line(result, "socraticode-qdrant (running) publishes beyond loopback")
        assert "✗" in line and "read the index" in line
        assert "references/loopback-containers.md" in _line(
            result, "with the operator's approval"
        )
        assert not [c for c in calls if c and c[0] in MUTATING]

    def test_a_wide_ollama_is_its_embedder_not_the_index(self, tmp_path):
        result, _ = _preflight_with(tmp_path, {"socraticode-qdrant": LOOPBACK_Q,
                                               "socraticode-ollama": WIDE_O})  # fmt: skip
        line = _line(result, "socraticode-ollama (running) publishes beyond loopback")
        assert "use its embedder" in line and "read the index" not in line

    def test_telemetry_on_is_a_warning(self, tmp_path):
        q = dict(LOOPBACK_Q, env=[])
        result, _ = _preflight_with(tmp_path, {"socraticode-qdrant": q,
                                               "socraticode-ollama": LOOPBACK_O})  # fmt: skip
        assert result.returncode == 0, result.stdout
        assert "•" in _line(result, "QDRANT__TELEMETRY_DISABLED=true is not set")

    def test_non_default_ports_go_in_front_of_the_command(self, tmp_path):
        result, _ = _preflight_with(
            tmp_path, {}, QDRANT_PORT="26333", OLLAMA_PORT="21435"
        )
        hint = _line(result, "create it on loopback first:")
        assert "QDRANT_PORT=26333 OLLAMA_PORT=21435 bash" in hint, hint
        assert "QDRANT_GRPC_PORT" not in hint, "a default port stays out of the command"

    def test_an_external_store_with_a_native_ollama_reads_no_container(self, tmp_path):
        result, calls = _preflight_with(
            tmp_path, {},
            QDRANT_MODE="external", QDRANT_URL="https://index.tail0.ts.net:6333",
            OLLAMA_MODE="external", OLLAMA_URL="http://index:11434",
        )  # fmt: skip
        assert not [c for c in calls if c and c[0] in ("inspect", "ps")], calls
        assert "does not exist yet" not in result.stdout

    def test_auto_ollama_beside_a_managed_store_is_probed_for_a_native_one(
        self, tmp_path
    ):
        """Gate 1 probes only beside an external store; Gate 1b needs the answer here too."""
        binv = _host(tmp_path)
        stub = binv / "docker"
        stub.write_text(DOCKER_STUB.format(python=sys.executable))
        stub.chmod(0o755)
        state = binv.parent / "containers.json"
        state.write_text(json.dumps({}))
        native = {"http://localhost:11434/api/tags": ["200", 0]}
        result = _preflight(tmp_path, _project(tmp_path), binv, curl=native,
                            STUB_CONTAINERS=str(state))  # fmt: skip
        assert "socraticode-qdrant does not exist yet" in result.stdout
        assert "socraticode-ollama" not in result.stdout, (
            "a native Ollama answers, so no Ollama container will be created"
        )

    def test_an_idle_socket_is_not_inspected(self, tmp_path):
        binv = _host(tmp_path, systemd=True)
        stub = binv / "docker"
        stub.write_text(DOCKER_STUB.format(python=sys.executable))
        stub.chmod(0o755)
        result = _preflight(tmp_path, _project(tmp_path), binv, SOCKET="active",
                            STUB_CONTAINERS=str(binv.parent / "containers.json"))  # fmt: skip
        assert not (binv.parent / "docker.log").exists(), (
            "a docker command ran against an idle socket"
        )
        assert "•" in _line(result, "SocratiCode's containers were not inspected")


# ── The daily hook ───────────────────────────────────────────────────────────

SS_WIDE = """State  Recv-Q Send-Q Local Address:Port  Peer Address:Port Process
LISTEN 0      4096         0.0.0.0:16333      0.0.0.0:*
LISTEN 0      4096         0.0.0.0:16334      0.0.0.0:*
LISTEN 0      4096            [::]:16333         [::]:*
LISTEN 0      4096       127.0.0.1:11435      0.0.0.0:*
LISTEN 0      128          0.0.0.0:22         0.0.0.0:*
"""
SS_LOOPBACK = """State  Recv-Q Send-Q Local Address:Port  Peer Address:Port Process
LISTEN 0      4096       127.0.0.1:16333      0.0.0.0:*
LISTEN 0      4096       127.0.0.1:16334      0.0.0.0:*
LISTEN 0      4096           [::1]:11435         [::]:*
LISTEN 0      4096   127.0.0.53%lo:53         0.0.0.0:*
LISTEN 0      128          0.0.0.0:22         0.0.0.0:*
"""
# Older iproute2 prints no State column when only one state is selected.
SS_NO_STATE = """Recv-Q Send-Q Local Address:Port  Peer Address:Port
0      4096                *:11435            *:*
"""
LSOF_WIDE = "p4366\nf150\nn127.0.0.1:16333\nf151\nn*:11435\np5000\nf3\nn[::1]:16334\n"
LSOF_LOOPBACK = (
    "p4366\nf150\nn127.0.0.1:16333\nf151\nn127.0.0.1:16334\nf154\nn[::1]:11435\n"
)

FINDING = "listens beyond loopback"


class Hook:
    """The hook in a configured repo, with uname, ss, lsof and docker stubbed."""

    def __init__(self, tmp_path: Path, *, os_name: str = "Linux") -> None:
        self.tmp = tmp_path
        self.repo = _repo(tmp_path)
        self.bin = tmp_path / "hook-bin"
        self.bin.mkdir()
        self.calls = tmp_path / "calls.log"
        self.calls.touch()
        stubs = {
            "uname": f'#!/bin/sh\necho "uname $*" >> "{self.calls}"\necho {os_name}\n',
            "ss": f'#!/bin/sh\necho "ss $*" >> "{self.calls}"\n'
            '[ -n "${STUB_SS_FAIL:-}" ] && exit 1\nprintf %s "$STUB_SS"\n',
            "lsof": f'#!/bin/sh\necho "lsof $*" >> "{self.calls}"\nprintf %s "$STUB_LSOF"\n[ -n "$STUB_LSOF" ]\n',
            "docker": f'#!/bin/sh\necho "docker $*" >> "{self.calls}"\nexit 0\n',
        }
        for name, body in stubs.items():
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        self.driver = tmp_path / "driver.mjs"
        self.driver.write_text("process.exit(0);\n")

    def run(
        self, *, path: str | None = None, **env: str
    ) -> subprocess.CompletedProcess:
        base = _clean_env(
            SOCRATICODE_HEALTH_FORCE="1",
            SOCRATICODE_HEALTH_CAP="off",
            SOCRATICODE_DRIVER=str(self.driver),
            PATH=path or f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            STUB_SS="",
            STUB_LSOF="",
        )
        # _clean_env points QDRANT_PORT at a closed port for the driver's sake;
        # these cases are about the listener, so they use upstream's default.
        base["QDRANT_PORT"] = "16333"
        base.update(env)
        return subprocess.run(
            ["bash", str(HOOK)], cwd=str(self.repo), capture_output=True,
            text=True, timeout=60, env=base,
        )  # fmt: skip

    def log(self) -> str:
        p = self.repo / ".git" / "socraticode-health.log"
        return p.read_text() if p.exists() else ""

    def called(self, tool: str) -> list[str]:
        return [
            ln for ln in self.calls.read_text().splitlines() if ln.split()[0] == tool
        ]


@requires_node
class TestTheHookReadsListeners:
    def test_a_wide_listener_is_reported(self, tmp_path):
        hook = Hook(tmp_path)
        result = hook.run(STUB_SS=SS_WIDE)
        assert result.returncode == 0
        line = next(ln for ln in result.stdout.splitlines() if FINDING in ln)
        assert "16333 (Qdrant HTTP) on 0.0.0.0, ::" in line, line
        assert "16334 (Qdrant gRPC) on 0.0.0.0" in line, line
        assert "11435" not in line, "a loopback Ollama is not a finding"
        assert "references/loopback-containers.md" in result.stdout
        assert "listeners beyond loopback" in hook.log()

    def test_loopback_only_is_silent(self, tmp_path):
        hook = Hook(tmp_path)
        result = hook.run(STUB_SS=SS_LOOPBACK)
        assert result.stdout == "", result.stdout

    def test_an_ss_without_a_state_column_is_read_too(self, tmp_path):
        result = Hook(tmp_path).run(STUB_SS=SS_NO_STATE)
        assert "11435 (Ollama) on *" in result.stdout, result.stdout

    def test_the_session_ports_are_the_ones_checked(self, tmp_path):
        ss = "LISTEN 0 4096 0.0.0.0:26333 0.0.0.0:*\nLISTEN 0 4096 0.0.0.0:16333 0.0.0.0:*\n"
        result = Hook(tmp_path).run(STUB_SS=ss, QDRANT_PORT="26333")
        assert "26333 (Qdrant HTTP)" in result.stdout
        assert "16333" not in result.stdout

    def test_macos_reads_lsof(self, tmp_path):
        hook = Hook(tmp_path, os_name="Darwin")
        result = hook.run(STUB_LSOF=LSOF_WIDE)
        assert "11435 (Ollama) on *" in result.stdout, result.stdout
        assert "16333" not in result.stdout and "16334" not in result.stdout
        assert hook.called("lsof") and not hook.called("ss")

    def test_macos_loopback_is_silent(self, tmp_path):
        result = Hook(tmp_path, os_name="Darwin").run(STUB_LSOF=LSOF_LOOPBACK)
        assert result.stdout == "", result.stdout

    def test_a_failed_ss_is_logged_not_said(self, tmp_path):
        hook = Hook(tmp_path)
        result = hook.run(STUB_SS_FAIL="1")
        assert result.stdout == ""
        assert "listeners not read: ss -ltn failed" in hook.log()

    def test_the_hook_runs_no_docker_command(self, tmp_path):
        hook = Hook(tmp_path)
        hook.run(STUB_SS=SS_WIDE)
        assert hook.called("docker") == []

    def test_a_listener_is_reported_after_the_drivers_findings(self, tmp_path):
        """After the driver, so a container its codebase_status created is seen today."""
        hook = Hook(tmp_path)
        hook.driver.write_text(
            "process.stderr.write('  - graph is not READY\\n'); process.exit(1);\n"
        )
        out = hook.run(STUB_SS=SS_WIDE).stdout
        assert out.index("graph is not READY") < out.index(FINDING), out

    def test_it_is_reported_where_node_is_missing(self, tmp_path):
        hook = Hook(tmp_path)
        bin_dir = tmp_path / "no-node"
        bin_dir.mkdir()
        for tool in (
            "bash",
            "git",
            "date",
            "cat",
            "wc",
            "tail",
            "mv",
            "rm",
            "dirname",
            "grep",
        ):
            found = shutil.which(tool)
            assert found, tool
            (bin_dir / tool).symlink_to(found)
        for stub in ("uname", "ss"):
            (bin_dir / stub).symlink_to(hook.bin / stub)
        assert shutil.which("node", path=str(bin_dir)) is None
        result = hook.run(path=str(bin_dir), STUB_SS=SS_WIDE)
        assert "node is not on PATH" in result.stdout
        assert FINDING in result.stdout, result.stdout

    def test_it_is_reported_where_the_driver_is_missing(self, tmp_path):
        hook = Hook(tmp_path)
        result = hook.run(STUB_SS=SS_WIDE, SOCRATICODE_DRIVER=str(tmp_path / "absent.mjs"),
                          HOME=str(tmp_path))  # fmt: skip
        assert "mcp-driver.mjs was not found" in result.stdout
        assert FINDING in result.stdout


class TestTheContractIsWritten:
    def test_the_skill_runs_the_create_before_any_codebase_call(self):
        text = SKILL_MD.read_text()
        assert "loopback-containers.sh" in text
        assert "before any `codebase_*` call" in text
        assert "references/loopback-containers.md" in text

    def test_the_reference_holds_the_mitigations_traps(self):
        text = REFERENCE.read_text()
        for needle in (
            "must not contain",  # the backup name, against the substring match
            "Rename, then stop, then run",
            '"exact": true',
            "fetch failed",
            "MaskedPaths",
            "operator's approval",
            "--pull never",
        ):
            assert needle in text, needle

    def test_the_hook_still_runs_no_docker_command(self):
        code = "\n".join(
            ln
            for ln in HOOK.read_text().splitlines()
            if not ln.lstrip().startswith("#")
        )
        assert not re.search(r"(^|[;&|(]\s*|\s)docker\s", code.split("EOF", 2)[-1]), (
            "the hook's contract is no docker command of its own"
        )
