"""An external store needs no Docker, and is never addressed without a projectId (#287).

The CannObserv cohort runs one shared SocratiCode store: Qdrant and Ollama on
one VM, every repo a client with `QDRANT_MODE=external`. Reviewing broker's
adoption (CannObserv/broker#17) against this skill found three places that
assumed the local Docker stack, and one that did harm:

- **Preflight demanded Docker in every mode.** Gate 1 failed unless Docker was
  installed and answering. An external client needs neither, so #281's advice
  to run `preflight.sh --check` answered such a host with a ✗ that was not a
  defect. Docker is now gated only when something will run in it — a managed
  Qdrant, or an Ollama embedder that is (or will fall back to) a container.
- **`docker info` started Docker.** On broker's VM `docker.service` is disabled
  and `docker.socket` enabled, and a read-only `docker ps` brought up dockerd
  and containerd beside the cohort's production Redis on a 2 GB, no-swap node.
  Preflight now asks systemd, and runs no docker command against a socket whose
  daemon is down.
- **Nothing wrote a `projectId`, and linked projects went in as absolute
  paths.** Without one the id is sha256(<path>)[:12], which on hosts that check
  repos out at the same path is not per-host: broker's VM and notifier's clone
  of broker both resolved to `d4eab3ecb321`, two hosts writing one collection
  set under a host-local lock. The driver now refuses to launch a server into
  that state, since the server's startup auto-resume makes a launch a write.

And one the issue named as the adoption's third step: an untrusted folder
drops the settings `env` block, so the server falls back to managed mode and
starts a local stack instead of failing. Trust is checked by its effect.

Preflight is driven through stubs on a PATH that holds nothing else, so no case
here can reach a real Docker daemon, a real store, or a real `claude`.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from .test_socraticode_graph_yield import (
    DRIVER,
    GRAPH_OK_HIGH_UNRESOLVED,
    HEALTH_OK,
    HOOK,
    STATUS_CLEAN,
    STUB_SERVER,
    _clean_env,
    _repo,
    requires_node,
)
from .test_socraticode_node_gate import PREFLIGHT, STORE_VARIABLES, requires_bash

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL = REPO_ROOT / "skills" / "init-socraticode"
SKILL_MD = SKILL / "SKILL.md"
EXTERNAL_REF = SKILL / "references" / "external-store.md"
LINKED_REF = SKILL / "references" / "linked-projects.md"

STORE_URL = "https://index.tail0.ts.net:6333"
OLLAMA_URL = "http://index:11434"
NATIVE_OLLAMA = "http://localhost:11434/api/tags"
KEY = "k3y-that-must-never-be-printed"

# Everything preflight runs besides the stubbed tools. Linked into their own
# directory rather than inheriting PATH, so a host with a real docker, curl or
# systemctl cannot answer in the stubs' place.
PREFLIGHT_TOOLS = ("git", "sed", "grep", "head", "tail", "tr")

CURL_STUB = """#!{python}
import json, os, sys
args = sys.argv[1:]
stdin = sys.stdin.read() if "-K" in args else ""
url = args[-1]
with open(os.path.join(os.environ["STUB_DIR"], "curl.log"), "a") as log:
    log.write(json.dumps({{"argv": args, "stdin": stdin}}) + "\\n")
with open(os.environ["CURL_REPLIES"]) as f:
    replies = json.load(f)
reply = replies.get(url + (" +key" if "api-key:" in stdin else "")) or replies.get(url)
code, rc = reply if reply else ("000", 7)
sys.stdout.write(str(code))
sys.exit(int(rc))
"""

SYSTEMCTL_STUB = """#!/bin/sh
echo "$*" >> "$STUB_DIR/systemctl.log"
case "$*" in
  "is-active --quiet docker.socket") [ "$SOCKET" = active ] ;;
  "is-active --quiet docker.service") [ "$SERVICE" = active ] ;;
  "is-enabled docker") echo disabled; exit 1 ;;
  "is-enabled docker.socket") echo enabled ;;
  "is-enabled docker.service") echo "${SERVICE_ENABLED:-disabled}" ;;
  "is-failed --quiet docker.service") [ "${SERVICE_FAILED:-no}" = yes ] ;;
  *) exit 1 ;;
esac
"""


def _host(tmp_path: Path, *, docker: bool = True, systemd: bool = False) -> Path:
    """A bin dir: stubbed node/npm/npx/claude/curl, and docker/systemctl on request."""
    stub_dir = tmp_path / "stubs"
    binv = stub_dir / "bin"
    binv.mkdir(parents=True)
    for tool in PREFLIGHT_TOOLS:
        found = shutil.which(tool)
        assert found, f"{tool} must be on PATH for preflight to run at all"
        (binv / tool).symlink_to(found)
    stubs = {
        # v22 answers the Node gate without the Node 26 registry read.
        "node": '#!/bin/sh\n[ "$1" = --version ] && echo v22.11.0\nexit 0\n',
        "npm": "#!/bin/sh\nexit 1\n",
        "npx": "#!/bin/sh\nexit 0\n",
        "claude": (
            "#!/bin/sh\n"
            'echo "$* AUTO_RESUME=${SOCRATICODE_AUTO_RESUME:-}" >> "$STUB_DIR/claude.log"\n'
            "exit 0\n"
        ),
        "curl": CURL_STUB.format(python=sys.executable),
    }
    if docker:
        stubs["docker"] = '#!/bin/sh\necho "$*" >> "$STUB_DIR/docker.log"\nexit 0\n'
    if systemd:
        stubs["systemctl"] = SYSTEMCTL_STUB
    for name, body in stubs.items():
        (binv / name).write_text(body)
        (binv / name).chmod(0o755)
    return binv


def _project(tmp_path: Path, **settings: dict) -> Path:
    """A git repo; `local=` and `shared=` become the two settings files' env."""
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(
        ["git", "init", "-q", str(project)],
        check=True,
        capture_output=True,
        env=_clean_env(),
    )
    names = {"local": "settings.local.json", "shared": "settings.json"}
    for which, env in settings.items():
        (project / ".claude").mkdir(exist_ok=True)
        (project / ".claude" / names[which]).write_text(json.dumps({"env": env}))
    return project


def _preflight(
    tmp_path: Path,
    project: Path,
    binv: Path,
    curl: dict | None = None,
    **env: str,
) -> subprocess.CompletedProcess:
    stub_dir = binv.parent
    replies = stub_dir / "curl-replies.json"
    replies.write_text(json.dumps(curl or {}))
    base = {
        k: v
        for k, v in os.environ.items()
        if k not in STORE_VARIABLES and k != "CLAUDECODE" and not k.startswith("GIT_")
    }
    base.update(
        PATH=str(binv),
        STUB_DIR=str(stub_dir),
        CURL_REPLIES=str(replies),
        SOCKET="inactive",
        SERVICE="inactive",
        # Preflight reads user settings for values (#287 CR 7); the developer's
        # own ~/.claude/settings.json must not be one of them.
        CLAUDE_CONFIG_DIR=str(stub_dir / "claude-config"),
        # A socket path that does not exist unless a test makes one, so the
        # idle-socket checks (#287 CR 10) never read the host's real socket.
        DOCKER_HOST=f"unix://{stub_dir / 'docker.sock'}",
    )
    base.update(env)
    return subprocess.run(
        [shutil.which("bash") or "/bin/bash", str(PREFLIGHT)],
        cwd=str(project),
        capture_output=True,
        text=True,
        timeout=60,
        env=base,
    )


def _log(binv: Path, tool: str) -> str:
    path = binv.parent / f"{tool}.log"
    return path.read_text() if path.exists() else ""


def _curl_calls(binv: Path) -> list[dict]:
    return [json.loads(line) for line in _log(binv, "curl").splitlines()]


def _line(out: str, needle: str) -> str:
    return next((ln for ln in out.splitlines() if needle in ln), "")


EXTERNAL = {
    "QDRANT_MODE": "external",
    "QDRANT_URL": STORE_URL,
    "OLLAMA_MODE": "external",
    "OLLAMA_URL": OLLAMA_URL,
}
STORE_OPEN = {
    f"{STORE_URL}/collections": ["200", 0],
    f"{OLLAMA_URL}/api/tags": ["200", 0],
}


class TestDockerIsGatedOnlyWhenSomethingRunsInIt:
    @requires_bash
    def test_an_external_store_and_embedder_need_no_docker(
        self, tmp_path: Path
    ) -> None:
        """The #281 host: configured, external, no Docker at all — and green."""
        binv = _host(tmp_path, docker=False)
        result = _preflight(tmp_path, _project(tmp_path), binv, STORE_OPEN, **EXTERNAL)
        assert "✗" not in result.stdout, result.stdout
        assert result.returncode == 0, result.stdout
        assert "✓" in _line(result.stdout, "Docker not needed"), result.stdout

    @requires_bash
    def test_a_managed_store_still_needs_docker(self, tmp_path: Path) -> None:
        binv = _host(tmp_path, docker=False)
        result = _preflight(tmp_path, _project(tmp_path), binv)
        assert "✗" in _line(result.stdout, "Docker not installed"), result.stdout
        assert "managed Qdrant" in _line(result.stdout, "Docker not installed")
        assert result.returncode == 1

    @requires_bash
    def test_auto_ollama_with_no_native_one_needs_docker(self, tmp_path: Path) -> None:
        """Upstream's `auto` falls back to a container when localhost:11434 is
        silent — so an external store alone does not make a host Docker-free,
        and the ✗ must say which setting would."""
        binv = _host(tmp_path, docker=False)
        env = {"QDRANT_MODE": "external", "QDRANT_URL": STORE_URL}
        curl = {f"{STORE_URL}/collections": ["200", 0], NATIVE_OLLAMA: ["000", 7]}
        result = _preflight(tmp_path, _project(tmp_path), binv, curl, **env)
        line = _line(result.stdout, "Docker not installed")
        assert "✗" in line and "Ollama" in line, result.stdout
        assert "OLLAMA_MODE=external" in result.stdout, result.stdout
        assert result.returncode == 1

    @requires_bash
    def test_docker_mode_ollama_needs_docker_beside_an_external_store(
        self, tmp_path: Path
    ) -> None:
        binv = _host(tmp_path, docker=False)
        env = {
            "QDRANT_MODE": "external",
            "QDRANT_URL": STORE_URL,
            "OLLAMA_MODE": "docker",
        }
        result = _preflight(tmp_path, _project(tmp_path), binv, STORE_OPEN, **env)
        line = _line(result.stdout, "Docker not installed")
        assert "✗" in line and "OLLAMA_MODE=docker" in line, result.stdout
        assert "managed Qdrant" not in line, (
            "the store is external; only Ollama needs it"
        )

    @requires_bash
    def test_a_host_with_docker_still_hears_how_to_drop_it(
        self, tmp_path: Path
    ) -> None:
        """#287 CR 22: the Docker-free nudge used to print only when Docker was
        missing, so the host running the fallback container never heard it —
        and its boot line blamed Qdrant, which it does not run."""
        binv = _host(tmp_path, systemd=True)
        env = {"QDRANT_MODE": "external", "QDRANT_URL": STORE_URL}
        curl = {f"{STORE_URL}/collections": ["200", 0], NATIVE_OLLAMA: ["000", 7]}
        result = _preflight(
            tmp_path, _project(tmp_path), binv, curl, SERVICE="active", **env
        )
        assert "daemon reachable" in result.stdout, result.stdout
        nudge = _line(result.stdout, "keeps it Docker-free")
        assert "•" in nudge and "OLLAMA_MODE=external" in nudge, result.stdout
        boot = _line(result.stdout, "at boot")
        assert "Ollama container" in boot and "Qdrant" not in boot, boot

    @requires_bash
    def test_auto_ollama_with_a_native_one_needs_none(self, tmp_path: Path) -> None:
        binv = _host(tmp_path, docker=False)
        env = {"QDRANT_MODE": "external", "QDRANT_URL": STORE_URL}
        curl = {f"{STORE_URL}/collections": ["200", 0], NATIVE_OLLAMA: ["200", 0]}
        result = _preflight(tmp_path, _project(tmp_path), binv, curl, **env)
        assert "Docker not needed" in result.stdout, result.stdout
        assert result.returncode == 0, result.stdout

    @requires_bash
    def test_a_cloud_embedder_is_not_probed_for(self, tmp_path: Path) -> None:
        binv = _host(tmp_path, docker=False)
        env = {
            "QDRANT_MODE": "external",
            "QDRANT_URL": STORE_URL,
            "EMBEDDING_PROVIDER": "openai",
        }
        result = _preflight(tmp_path, _project(tmp_path), binv, STORE_OPEN, **env)
        assert "Docker not needed" in result.stdout, result.stdout
        assert not any(NATIVE_OLLAMA in c["argv"] for c in _curl_calls(binv))


class TestValuesUpstreamRefuses:
    """#287 CR 9: upstream throws on these, so each is a server that will not
    start — and the gates must not read a typo as a choice."""

    @requires_bash
    @pytest.mark.parametrize(
        "variable,value",
        [("EMBEDDING_PROVIDER", "Ollama"), ("OLLAMA_MODE", "extern")],
    )
    def test_an_invalid_value_fails(
        self, tmp_path: Path, variable: str, value: str
    ) -> None:
        binv = _host(tmp_path)
        env = {**EXTERNAL, variable: value}
        result = _preflight(tmp_path, _project(tmp_path), binv, STORE_OPEN, **env)
        line = _line(result.stdout, f"{variable}={value}")
        assert "✗" in line and "throws at startup" in line, result.stdout
        assert result.returncode == 1

    @requires_bash
    def test_ollama_mode_is_checked_whatever_the_provider(self, tmp_path: Path) -> None:
        binv = _host(tmp_path)
        env = {**EXTERNAL, "EMBEDDING_PROVIDER": "openai", "OLLAMA_MODE": "Docker"}
        result = _preflight(tmp_path, _project(tmp_path), binv, STORE_OPEN, **env)
        assert "✗" in _line(result.stdout, "OLLAMA_MODE=Docker"), result.stdout

    @requires_bash
    def test_a_qdrant_mode_typo_is_named(self, tmp_path: Path) -> None:
        """Never refused upstream, only read as managed — so said aloud."""
        binv = _host(tmp_path)
        result = _preflight(tmp_path, _project(tmp_path), binv, QDRANT_MODE="extrenal")
        line = _line(result.stdout, "QDRANT_MODE=extrenal")
        assert "•" in line and "managed" in line, result.stdout
        assert "Store: managed" in result.stdout, result.stdout


class TestASocketActivatedDaemonIsNotStarted:
    """`docker info` connects to the socket, and connecting starts the daemon."""

    @requires_bash
    def test_an_idle_socket_is_not_probed(self, tmp_path: Path) -> None:
        binv = _host(tmp_path, systemd=True)
        result = _preflight(tmp_path, _project(tmp_path), binv, SOCKET="active")
        assert _log(binv, "docker") == "", (
            f"a docker command ran against an idle socket: {_log(binv, 'docker')!r}"
        )
        assert "✓" in _line(result.stdout, "socket-activated"), result.stdout
        assert result.returncode == 0, result.stdout

    @requires_bash
    @pytest.mark.parametrize(
        "state,expected",
        [
            ({"SERVICE_ENABLED": "masked"}, "is masked"),
            ({"SERVICE_FAILED": "yes"}, "is failed"),
        ],
    )
    def test_an_idle_socket_that_cannot_start_the_daemon_fails(
        self, tmp_path: Path, state: dict, expected: str
    ) -> None:
        """#287 CR 10: socket activation cannot start a masked service, and a
        failed one is retried by the first call — neither earns the ✓."""
        binv = _host(tmp_path, systemd=True)
        result = _preflight(
            tmp_path, _project(tmp_path), binv, SOCKET="active", **state
        )
        assert "✗" in _line(result.stdout, expected), result.stdout
        assert _log(binv, "docker") == "", "still no docker command"
        assert result.returncode == 1

    @requires_bash
    @pytest.mark.skipif(os.geteuid() == 0, reason="root can write any file")
    def test_an_unwritable_socket_fails(self, tmp_path: Path) -> None:
        binv = _host(tmp_path, systemd=True)
        sock = binv.parent / "docker.sock"
        sock.write_text("")
        sock.chmod(0o444)
        result = _preflight(tmp_path, _project(tmp_path), binv, SOCKET="active")
        assert "✗" in _line(result.stdout, "not writable"), result.stdout
        assert "usermod -aG docker" in result.stdout, result.stdout

    @requires_bash
    def test_a_running_daemon_is_still_probed(self, tmp_path: Path) -> None:
        binv = _host(tmp_path, systemd=True)
        result = _preflight(
            tmp_path, _project(tmp_path), binv, SOCKET="active", SERVICE="active"
        )
        assert "info" in _log(binv, "docker"), result.stdout
        assert "daemon reachable" in result.stdout, result.stdout

    @requires_bash
    def test_an_ollama_fallback_on_an_idle_socket_is_not_probed(
        self, tmp_path: Path
    ) -> None:
        """External store, auto Ollama with no native one: Docker is needed for
        the fallback container — and the idle socket still is not touched."""
        binv = _host(tmp_path, systemd=True)
        env = {"QDRANT_MODE": "external", "QDRANT_URL": STORE_URL}
        curl = {f"{STORE_URL}/collections": ["200", 0], NATIVE_OLLAMA: ["000", 7]}
        result = _preflight(
            tmp_path, _project(tmp_path), binv, curl, SOCKET="active", **env
        )
        line = _line(result.stdout, "socket-activated")
        assert "✓" in line and "Ollama" in line, result.stdout
        assert _log(binv, "docker") == "", _log(binv, "docker")

    @requires_bash
    def test_an_external_store_runs_no_docker_command(self, tmp_path: Path) -> None:
        """Broker's host exactly: socket enabled, daemon down, client external."""
        binv = _host(tmp_path, systemd=True)
        _preflight(
            tmp_path, _project(tmp_path), binv, STORE_OPEN, SOCKET="active", **EXTERNAL
        )
        assert _log(binv, "docker") == "", _log(binv, "docker")

    @requires_bash
    def test_the_plugin_check_cannot_auto_resume(self, tmp_path: Path) -> None:
        """`claude mcp list` starts the server, whose startup auto-resume writes
        to the index and, in managed mode, probes Docker."""
        binv = _host(tmp_path)
        _preflight(tmp_path, _project(tmp_path), binv)
        listed = _line(_log(binv, "claude"), "mcp list")
        assert listed, _log(binv, "claude")
        assert "AUTO_RESUME=off" in listed, listed


class TestTheExternalStoreGate:
    @requires_bash
    def test_qdrant_url_is_required(self, tmp_path: Path) -> None:
        """broker#17 trap 3: the URL built from a host uses port 16333."""
        binv = _host(tmp_path)
        env = {k: v for k, v in EXTERNAL.items() if k != "QDRANT_URL"}
        result = _preflight(
            tmp_path, _project(tmp_path), binv, STORE_OPEN, QDRANT_HOST="index", **env
        )
        line = _line(result.stdout, "QDRANT_URL is not set")
        assert "✗" in line, result.stdout
        assert "16333" in result.stdout, result.stdout
        assert result.returncode == 1

    @requires_bash
    def test_the_host_hint_reads_the_port_it_names(self, tmp_path: Path) -> None:
        """#287 CR 11: the hint read QDRANT_PORT from the environment only, and
        with it set said "uses port 6333, not Qdrant's 6333"."""
        binv = _host(tmp_path)
        env = {k: v for k, v in EXTERNAL.items() if k != "QDRANT_URL"}
        project = _project(tmp_path, local={"QDRANT_PORT": "6333"})
        result = _preflight(
            tmp_path, project, binv, STORE_OPEN, QDRANT_HOST="index", **env
        )
        assert "plain http on port 6333" in result.stdout, result.stdout
        assert "not Qdrant's 6333" not in result.stdout, result.stdout
        assert "not enough for this skill" in result.stdout, (
            "stricter than upstream by choice, and worded as such"
        )

    @requires_bash
    def test_a_key_is_never_sent_over_plain_http(self, tmp_path: Path) -> None:
        binv = _host(tmp_path)
        env = {
            **EXTERNAL,
            "QDRANT_URL": "http://index.tail0.ts.net:6333",
            "QDRANT_API_KEY": KEY,
        }
        result = _preflight(tmp_path, _project(tmp_path), binv, STORE_OPEN, **env)
        assert "✗" in _line(result.stdout, "is not https"), result.stdout
        assert not any(
            "index.tail0.ts.net:6333" in " ".join(c["argv"]) for c in _curl_calls(binv)
        ), "upstream refuses before connecting, so the gate must not connect either"

    @requires_bash
    def test_loopback_may_carry_a_key_over_http(self, tmp_path: Path) -> None:
        binv = _host(tmp_path)
        url = "http://localhost:6333"
        env = {**EXTERNAL, "QDRANT_URL": url, "QDRANT_API_KEY": KEY}
        curl = {
            f"{url}/collections": ["401", 0],
            f"{url}/collections +key": ["200", 0],
            f"{OLLAMA_URL}/api/tags": ["200", 0],
        }
        result = _preflight(tmp_path, _project(tmp_path), binv, curl, **env)
        assert "is not https" not in result.stdout, result.stdout
        assert "accepts QDRANT_API_KEY" in result.stdout, result.stdout

    @requires_bash
    def test_a_short_name_tls_failure_names_the_full_one(self, tmp_path: Path) -> None:
        """broker#17 trap 4: the short name is not in the certificate's SAN."""
        binv = _host(tmp_path)
        url = "https://index:6333"
        curl = {f"{url}/collections": ["000", 60], f"{OLLAMA_URL}/api/tags": ["200", 0]}
        result = _preflight(
            tmp_path, _project(tmp_path), binv, curl, **{**EXTERNAL, "QDRANT_URL": url}
        )
        assert "✗" in _line(result.stdout, "did not verify"), result.stdout
        assert "MagicDNS" in result.stdout, result.stdout

    @requires_bash
    def test_a_full_name_tls_failure_does_not_blame_the_name(
        self, tmp_path: Path
    ) -> None:
        binv = _host(tmp_path)
        curl = {
            f"{STORE_URL}/collections": ["000", 60],
            f"{OLLAMA_URL}/api/tags": ["200", 0],
        }
        result = _preflight(tmp_path, _project(tmp_path), binv, curl, **EXTERNAL)
        assert "did not verify" in result.stdout, result.stdout
        assert "MagicDNS" not in result.stdout, result.stdout

    @requires_bash
    def test_a_failed_handshake_is_not_blamed_on_the_name(self, tmp_path: Path) -> None:
        """#287 CR 8: exit 35 is a handshake that never happened — most often a
        port serving plain http — and no certificate was ever read."""
        binv = _host(tmp_path)
        url = "https://localhost:18765"
        curl = {f"{url}/collections": ["000", 35], f"{OLLAMA_URL}/api/tags": ["200", 0]}
        result = _preflight(
            tmp_path, _project(tmp_path), binv, curl, **{**EXTERNAL, "QDRANT_URL": url}
        )
        assert "✗" in _line(result.stdout, "handshake failed"), result.stdout
        assert "serve TLS" in result.stdout, result.stdout
        assert "MagicDNS" not in result.stdout, result.stdout

    @requires_bash
    def test_every_probe_ignores_curlrc(self, tmp_path: Path) -> None:
        """`-q` has to be curl's first argument to stop ~/.curlrc being read; a
        `--fail` there turned a 401 into exit 22."""
        binv = _host(tmp_path)
        env = {"QDRANT_MODE": "external", "QDRANT_URL": STORE_URL}
        curl = {f"{STORE_URL}/collections": ["401", 0], NATIVE_OLLAMA: ["000", 7]}
        _preflight(tmp_path, _project(tmp_path), binv, curl, QDRANT_API_KEY=KEY, **env)
        calls = _curl_calls(binv)
        assert len(calls) == 3, calls  # native probe, store, store with the key
        assert all(c["argv"][0] == "-q" for c in calls), calls

    @requires_bash
    @pytest.mark.parametrize(
        "url", ["HTTPS://INDEX.TAIL0.TS.NET:6333", "http://LOCALHOST:6333"]
    )
    def test_scheme_and_host_compare_as_upstream_parses_them(
        self, tmp_path: Path, url: str
    ) -> None:
        """Upstream's URL parser lowercases both; neither of these is plain
        http to a remote host."""
        binv = _host(tmp_path)
        curl = {
            f"{url}/collections": ["401", 0],
            f"{url}/collections +key": ["200", 0],
            f"{OLLAMA_URL}/api/tags": ["200", 0],
        }
        result = _preflight(
            tmp_path,
            _project(tmp_path),
            binv,
            curl,
            QDRANT_API_KEY=KEY,
            **{**EXTERNAL, "QDRANT_URL": url},
        )
        assert "is not https" not in result.stdout, result.stdout
        assert "accepts QDRANT_API_KEY" in result.stdout, result.stdout

    @requires_bash
    def test_a_dns_failure_names_the_acl(self, tmp_path: Path) -> None:
        """A peer the tailnet ACL does not admit presents as DNS, not a denial."""
        binv = _host(tmp_path)
        curl = {
            f"{STORE_URL}/collections": ["000", 6],
            f"{OLLAMA_URL}/api/tags": ["200", 0],
        }
        result = _preflight(tmp_path, _project(tmp_path), binv, curl, **EXTERNAL)
        assert "✗" in _line(result.stdout, "cannot resolve"), result.stdout
        assert "ACL" in result.stdout, result.stdout

    @requires_bash
    def test_a_guarded_store_with_no_key_asks_for_one(self, tmp_path: Path) -> None:
        binv = _host(tmp_path)
        curl = {
            f"{STORE_URL}/collections": ["401", 0],
            f"{OLLAMA_URL}/api/tags": ["200", 0],
        }
        result = _preflight(tmp_path, _project(tmp_path), binv, curl, **EXTERNAL)
        line = _line(result.stdout, "requires an API key")
        assert "✗" in line, result.stdout
        assert "settings.local.json" in result.stdout, result.stdout

    @requires_bash
    def test_a_rejected_key_is_named_by_its_length(self, tmp_path: Path) -> None:
        """A truncated key 401s exactly like a wrong one; the length is the
        only cheap way to tell them apart."""
        binv = _host(tmp_path)
        curl = {
            f"{STORE_URL}/collections": ["401", 0],
            f"{OLLAMA_URL}/api/tags": ["200", 0],
        }
        result = _preflight(
            tmp_path, _project(tmp_path), binv, curl, QDRANT_API_KEY=KEY, **EXTERNAL
        )
        line = _line(result.stdout, "rejects QDRANT_API_KEY")
        assert "✗" in line and f"{len(KEY)} characters" in line, result.stdout

    @requires_bash
    def test_an_accepted_key_passes(self, tmp_path: Path) -> None:
        binv = _host(tmp_path)
        curl = {
            f"{STORE_URL}/collections": ["401", 0],
            f"{STORE_URL}/collections +key": ["200", 0],
            f"{OLLAMA_URL}/api/tags": ["200", 0],
        }
        result = _preflight(
            tmp_path, _project(tmp_path), binv, curl, QDRANT_API_KEY=KEY, **EXTERNAL
        )
        assert "✓" in _line(result.stdout, "accepts QDRANT_API_KEY"), result.stdout
        assert result.returncode == 0, result.stdout

    @requires_bash
    def test_the_key_reaches_curl_on_stdin_only(self, tmp_path: Path) -> None:
        """argv is readable by every process on the host for the life of the
        call; and nothing a gate prints may carry the secret."""
        binv = _host(tmp_path)
        curl = {
            f"{STORE_URL}/collections": ["401", 0],
            f"{STORE_URL}/collections +key": ["200", 0],
        }
        result = _preflight(
            tmp_path, _project(tmp_path), binv, curl, QDRANT_API_KEY=KEY, **EXTERNAL
        )
        calls = _curl_calls(binv)
        assert any(KEY in c["stdin"] for c in calls), calls
        assert not any(KEY in " ".join(c["argv"]) for c in calls), calls
        assert KEY not in result.stdout + result.stderr

    @requires_bash
    def test_values_come_from_the_project_settings(self, tmp_path: Path) -> None:
        """A plain-shell run on a configured repo: nothing in the environment,
        the mode in settings.json and the key in settings.local.json."""
        binv = _host(tmp_path, docker=False)
        project = _project(tmp_path, shared=EXTERNAL, local={"QDRANT_API_KEY": KEY})
        curl = {
            f"{STORE_URL}/collections": ["401", 0],
            f"{STORE_URL}/collections +key": ["200", 0],
            f"{OLLAMA_URL}/api/tags": ["200", 0],
        }
        result = _preflight(tmp_path, project, binv, curl)
        assert "QDRANT_MODE from .claude/settings.json" in result.stdout, result.stdout
        assert "accepts QDRANT_API_KEY" in result.stdout, result.stdout
        assert "Docker not needed" in result.stdout, result.stdout

    @requires_bash
    def test_an_escaped_value_is_refused_not_misread(self, tmp_path: Path) -> None:
        """#287 CR 7: `"se\\"c\\\\ret"` used to read as `se\\` and be probed,
        then reported as a rejected 3-character key."""
        binv = _host(tmp_path)
        project = _project(
            tmp_path, shared=EXTERNAL, local={"QDRANT_API_KEY": 'se"c\\ret'}
        )
        curl = {
            f"{STORE_URL}/collections": ["401", 0],
            f"{STORE_URL}/collections +key": ["200", 0],
            f"{OLLAMA_URL}/api/tags": ["200", 0],
        }
        result = _preflight(tmp_path, project, binv, curl)
        warned = _line(result.stdout, "does not decode")
        assert "•" in warned and "QDRANT_API_KEY" in warned, result.stdout
        assert "rejects QDRANT_API_KEY" not in result.stdout, result.stdout
        assert not any(c["stdin"] for c in _curl_calls(binv)), (
            "an unreadable key must not be sent at all"
        )

    @requires_bash
    def test_user_settings_supply_a_value(self, tmp_path: Path) -> None:
        """The reference offers user settings as a host-wide key's home; a
        plain-shell run was told the key was not set."""
        binv = _host(tmp_path)
        config = binv.parent / "claude-config"
        config.mkdir()
        (config / "settings.json").write_text(
            json.dumps({"env": {"QDRANT_API_KEY": KEY}})
        )
        curl = {
            f"{STORE_URL}/collections": ["401", 0],
            f"{STORE_URL}/collections +key": ["200", 0],
            f"{OLLAMA_URL}/api/tags": ["200", 0],
        }
        result = _preflight(tmp_path, _project(tmp_path, shared=EXTERNAL), binv, curl)
        assert "accepts QDRANT_API_KEY" in result.stdout, result.stdout

    @requires_bash
    def test_user_settings_are_not_the_project_block(self, tmp_path: Path) -> None:
        """User settings apply trusted or not, so a store declared there is
        named as the source and never judged as a dropped project block."""
        binv = _host(tmp_path, docker=False)
        config = binv.parent / "claude-config"
        config.mkdir()
        (config / "settings.json").write_text(json.dumps({"env": EXTERNAL}))
        result = _preflight(
            tmp_path, _project(tmp_path), binv, STORE_OPEN, CLAUDECODE="1"
        )
        assert f"QDRANT_MODE from {config / 'settings.json'}" in result.stdout, (
            result.stdout
        )
        assert "env block" not in result.stdout, result.stdout
        assert result.returncode == 0, result.stdout

    @requires_bash
    def test_local_settings_win_and_the_environment_wins_over_both(
        self, tmp_path: Path
    ) -> None:
        binv = _host(tmp_path)
        local_url = "https://local.tail0.ts.net:6333"
        env_url = "https://env.tail0.ts.net:6333"
        project = _project(tmp_path, shared=EXTERNAL, local={"QDRANT_URL": local_url})
        curl = {
            f"{local_url}/collections": ["200", 0],
            f"{env_url}/collections": ["200", 0],
            f"{OLLAMA_URL}/api/tags": ["200", 0],
        }
        from_files = _preflight(tmp_path, project, binv, curl)
        assert f"answers at {local_url}" in from_files.stdout, from_files.stdout
        from_env = _preflight(tmp_path, project, binv, curl, QDRANT_URL=env_url)
        assert f"answers at {env_url}" in from_env.stdout, from_env.stdout


class TestTrustIsCheckedByItsEffect:
    """An untrusted folder drops the env block, and the server then starts a
    local stack rather than reporting missing configuration."""

    @requires_bash
    def test_a_session_without_the_block_fails(self, tmp_path: Path) -> None:
        binv = _host(tmp_path)
        project = _project(tmp_path, shared=EXTERNAL)
        result = _preflight(tmp_path, project, binv, STORE_OPEN, CLAUDECODE="1")
        line = _line(result.stdout, "does not carry")
        assert "✗" in line, result.stdout
        assert "Docker" in line, "the ✗ must say what the fallback does"
        assert "trust" in result.stdout, result.stdout
        assert result.returncode == 1

    @requires_bash
    def test_the_mode_alone_is_not_the_block(self, tmp_path: Path) -> None:
        """#287 CR 2, reproduced: QDRANT_MODE reached the session from somewhere
        else, OLLAMA_MODE did not. Reading the file for the missing one said
        trusted and Docker-free while the server ran Ollama in auto mode."""
        binv = _host(tmp_path)
        project = _project(tmp_path, shared=EXTERNAL)
        result = _preflight(
            tmp_path,
            project,
            binv,
            STORE_OPEN,
            CLAUDECODE="1",
            QDRANT_MODE="external",
            QDRANT_URL=STORE_URL,
        )
        line = _line(result.stdout, "does not carry")
        assert "✗" in line, result.stdout
        assert "OLLAMA_MODE, OLLAMA_URL" in line, line
        assert "QDRANT_MODE" not in line.split("(")[1], "name only what is missing"
        assert "Docker" in line, line

    @requires_bash
    def test_a_missing_key_is_named_without_its_value(self, tmp_path: Path) -> None:
        """A key installed after the session started: the server 401s rather
        than falling back, so the ✗ must not claim a Docker fallback — and the
        value must appear nowhere."""
        binv = _host(tmp_path)
        project = _project(tmp_path, shared=EXTERNAL, local={"QDRANT_API_KEY": KEY})
        curl = {
            f"{STORE_URL}/collections": ["401", 0],
            f"{STORE_URL}/collections +key": ["200", 0],
            f"{OLLAMA_URL}/api/tags": ["200", 0],
        }
        result = _preflight(tmp_path, project, binv, curl, CLAUDECODE="1", **EXTERNAL)
        line = _line(result.stdout, "does not carry")
        assert "✗" in line and "(QDRANT_API_KEY)" in line, result.stdout
        assert "Docker" not in line, line
        assert KEY not in result.stdout + result.stderr

    @requires_bash
    def test_a_session_with_the_block_passes(self, tmp_path: Path) -> None:
        binv = _host(tmp_path)
        project = _project(tmp_path, shared=EXTERNAL)
        result = _preflight(
            tmp_path, project, binv, STORE_OPEN, CLAUDECODE="1", **EXTERNAL
        )
        assert "✓" in _line(
            result.stdout, "carries .claude/settings.json's env block"
        ), result.stdout
        assert result.returncode == 0, result.stdout

    @requires_bash
    def test_outside_a_session_it_is_advisory(self, tmp_path: Path) -> None:
        """A plain shell cannot see what a session would carry; unconfirmed is
        not broken."""
        binv = _host(tmp_path)
        project = _project(tmp_path, shared=EXTERNAL)
        result = _preflight(tmp_path, project, binv, STORE_OPEN)
        line = _line(result.stdout, "unconfirmed")
        assert "•" in line and "✗" not in line, result.stdout
        assert result.returncode == 0, result.stdout

    @requires_bash
    def test_a_managed_repo_hears_nothing_about_it(self, tmp_path: Path) -> None:
        binv = _host(tmp_path)
        result = _preflight(tmp_path, _project(tmp_path), binv, CLAUDECODE="1")
        assert "env block" not in result.stdout, result.stdout


# ── the driver ───────────────────────────────────────────────────────────────


def _store(project: Path, **env: str) -> dict:
    """`storeConfig()` from a one-shot node eval, with its findings rendered."""
    script = (
        "import { storeConfig } from "
        f"{json.dumps(str(DRIVER))};"
        f"const r = storeConfig({json.dumps(str(project))});"
        "process.stdout.write(JSON.stringify(r));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
        env=_clean_env(**env),
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _defects(r: dict) -> list[str]:
    return [f["message"] for f in r["findings"] if f["severity"] == "defect"]


def _notes(r: dict) -> list[str]:
    return [f["message"] for f in r["findings"] if f["severity"] == "note"]


def _config(project: Path, body: dict) -> None:
    (project / ".socraticode.json").write_text(json.dumps(body))


def _hash(path: Path) -> str:
    return hashlib.sha256(str(path).encode()).hexdigest()[:12]


class TestStoreConfig:
    """The driver's transcription of upstream's projectId resolution, and the
    mode the project settings declare against the one this process carries."""

    @requires_node
    def test_a_managed_default_install_is_untouched(self, tmp_path: Path) -> None:
        """Most installs: no settings, no config, per-host store. The hash is
        harmless there and must not become a finding."""
        r = _store(_project(tmp_path))
        assert r["store"] == "managed" and r["findings"] == [], r
        assert r["projectId"]["source"] == "path hash", r

    @requires_node
    def test_the_path_hash_is_sha256_of_the_resolved_path(self, tmp_path: Path) -> None:
        """config.js coreProjectId: sha256(path.resolve(folder))[:12]. Checked
        against that formula restated here, not against upstream itself — the
        server package is no dependency of this suite (#287 CR 19)."""
        project = _project(tmp_path)
        r = _store(project)
        assert r["pathHash"] == _hash(project), r
        assert r["projectId"]["value"] == r["pathHash"], r

    @requires_node
    def test_the_branch_suffix_follows_upstream(self, tmp_path: Path) -> None:
        """SOCRATICODE_BRANCH_AWARE appends the sanitized branch to the hash,
        and only to the hash: a declared projectId ignores it."""
        project = _project(tmp_path)
        for args in (
            ["commit", "-q", "--allow-empty", "-m", "init"],
            ["checkout", "-q", "-b", "feat/x-y"],
        ):
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(project),
                    "-c",
                    "user.email=t@example.com",
                    "-c",
                    "user.name=t",
                    *args,
                ],
                check=True,
                capture_output=True,
                env=_clean_env(),
            )
        r = _store(project, SOCRATICODE_BRANCH_AWARE="true")
        assert r["projectId"]["value"] == f"{_hash(project)}__feat_x-y", r
        _config(project, {"projectId": "broker"})
        r = _store(project, SOCRATICODE_BRANCH_AWARE="true")
        assert r["projectId"]["value"] == "broker", r

    @requires_node
    def test_an_external_store_without_a_projectId_is_a_defect(
        self, tmp_path: Path
    ) -> None:
        project = _project(tmp_path)
        r = _store(project, QDRANT_MODE="external")
        [defect] = _defects(r)
        assert "declares no projectId" in defect, defect
        assert f"codebase_{_hash(project)}" in defect, (
            "name the collection it would write"
        )

    @requires_node
    def test_a_declared_projectId_clears_it(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        _config(project, {"projectId": "broker"})
        r = _store(project, QDRANT_MODE="external")
        assert r["findings"] == [], r
        assert r["projectId"] == {"value": "broker", "source": ".socraticode.json"}, r

    @requires_node
    def test_the_environment_override_ranks_first(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        _config(project, {"projectId": "broker"})
        r = _store(project, QDRANT_MODE="external", SOCRATICODE_PROJECT_ID="other")
        assert r["projectId"] == {
            "value": "other",
            "source": "SOCRATICODE_PROJECT_ID",
        }, r

    @requires_node
    def test_the_own_path_hash_as_projectId_names_nothing(self, tmp_path: Path) -> None:
        """broker#18: a copied hash id is the same collision as none at all."""
        project = _project(tmp_path)
        _config(project, {"projectId": _hash(project)})
        [defect] = _defects(_store(project, QDRANT_MODE="external"))
        assert "own path hash" in defect, defect

    @requires_node
    def test_an_invalid_projectId_is_a_defect_in_either_mode(
        self, tmp_path: Path
    ) -> None:
        """Upstream throws on every call rather than sanitize it."""
        project = _project(tmp_path)
        _config(project, {"projectId": "not.valid"})
        [defect] = _defects(_store(project))
        assert "[a-zA-Z0-9_-]" in defect, defect

    @requires_node
    def test_a_sibling_on_the_same_id_is_a_defect(self, tmp_path: Path) -> None:
        """broker#18: a copied `"projectId": "notifier"` writes into notifier's
        set, and search drops the link as a duplicate of this project."""
        project = _project(tmp_path)
        (tmp_path / "notifier").mkdir()
        _config(tmp_path / "notifier", {"projectId": "notifier"})
        _config(project, {"projectId": "notifier", "linkedProjects": ["../notifier"]})
        [defect] = _defects(_store(project, QDRANT_MODE="external"))
        assert "also linked project ../notifier" in defect, defect

    @requires_node
    def test_a_sibling_with_an_invalid_id_breaks_every_linked_search(
        self, tmp_path: Path
    ) -> None:
        """#287 CR 12: upstream's resolveLinkedCollections throws on it, so
        every includeLinked search fails — not only the bad sibling's."""
        project = _project(tmp_path)
        (tmp_path / "archiver").mkdir()
        _config(tmp_path / "archiver", {"projectId": "bad id!"})
        _config(project, {"projectId": "broker", "linkedProjects": ["../archiver"]})
        [defect] = _defects(_store(project, QDRANT_MODE="external"))
        assert "../archiver" in defect and "throws" in defect, defect

    @requires_node
    def test_two_siblings_on_one_id_are_named(self, tmp_path: Path) -> None:
        """Upstream keeps the first and drops the second without a word."""
        project = _project(tmp_path)
        for name in ("archiver", "watcher"):
            (tmp_path / name).mkdir()
            _config(tmp_path / name, {"projectId": "archiver"})
        _config(
            project,
            {"projectId": "broker", "linkedProjects": ["../archiver", "../watcher"]},
        )
        [defect] = _defects(_store(project, QDRANT_MODE="external"))
        assert "../archiver and ../watcher" in defect, defect

    @requires_node
    def test_an_absolute_linked_entry_is_a_note(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        (tmp_path / "archiver").mkdir()
        _config(
            project,
            {"projectId": "broker", "linkedProjects": [str(tmp_path / "archiver")]},
        )
        r = _store(project, QDRANT_MODE="external")
        assert _defects(r) == [], r
        [note] = _notes(r)
        assert "is absolute" in note and "relative" in note, note

    @requires_node
    def test_a_declared_store_this_process_lacks_is_a_defect(
        self, tmp_path: Path
    ) -> None:
        """The untrusted-folder fallback, seen from a process: settings say
        external, and a server launched from here would run managed."""
        project = _project(tmp_path, shared={"QDRANT_MODE": "external"})
        _config(project, {"projectId": "broker"})
        r = _store(project)
        assert r["declared"] == {"mode": "external", "in": ".claude/settings.json"}, r
        [defect] = _defects(r)
        assert "does not carry: QDRANT_MODE (.claude/settings.json)" in defect, defect
        assert "Docker" in defect, defect

    @requires_node
    def test_both_defects_surface_together(self, tmp_path: Path) -> None:
        """Keyed on the CONFIGURED store: fixing trust alone must not walk the
        operator into the projectId defect on the next run."""
        project = _project(tmp_path, shared={"QDRANT_MODE": "external"})
        defects = _defects(_store(project))
        assert len(defects) == 2, defects
        assert any("declares no projectId" in d for d in defects), defects

    @requires_node
    def test_local_settings_override_shared_ones(self, tmp_path: Path) -> None:
        project = _project(
            tmp_path,
            shared={"QDRANT_MODE": "external"},
            local={"QDRANT_MODE": "managed"},
        )
        r = _store(project)
        assert r["declared"] == {
            "mode": "managed",
            "in": ".claude/settings.local.json",
        }, r
        assert r["findings"] == [], r


def _driver(project: Path, *args: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", str(DRIVER), *args, str(project)],
        capture_output=True,
        text=True,
        timeout=60,
        env=_clean_env(**env),
    )


def _launch_marker(tmp_path: Path) -> tuple[Path, Path]:
    """A server entry that records being started, and the file it writes."""
    marker = tmp_path / "server-launched"
    entry = tmp_path / "marker-server.mjs"
    entry.write_text(
        "import { writeFileSync } from 'node:fs';\n"
        f"writeFileSync({json.dumps(str(marker))}, 'launched');\n"
        "process.exit(1);\n"
    )
    return entry, marker


class TestValidateStore:
    @requires_node
    def test_a_defect_fails_with_a_verdict(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        result = _driver(project, "validate-store", QDRANT_MODE="external")
        assert result.returncode == 1, result.stderr
        verdict = json.loads(result.stdout)
        assert verdict["valid"] is False and verdict["store"] == "external", verdict
        assert verdict["pathHash"] == _hash(project), verdict
        assert "  - this project uses an external store" in result.stderr, result.stderr

    @requires_node
    def test_a_clean_config_passes(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        _config(project, {"projectId": "broker"})
        result = _driver(project, "validate-store", QDRANT_MODE="external")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["valid"] is True
        assert 'projectId "broker"' in result.stderr, result.stderr


class TestTheDriverDoesNotLaunchIntoTheWrongStore:
    """A launch is a write: startup auto-resume updates any collection that
    already exists, and status or query calls start the watcher."""

    @requires_node
    @pytest.mark.parametrize("command", ["index", "status", "verify"])
    def test_launching_commands_refuse(self, tmp_path: Path, command: str) -> None:
        project = _project(tmp_path)
        entry, marker = _launch_marker(tmp_path)
        result = _driver(
            project, command, QDRANT_MODE="external", SOCRATICODE_ENTRY=str(entry)
        )
        assert result.returncode == 1, result.stderr
        assert "refusing to launch a server" in result.stderr, result.stderr
        assert not marker.exists(), f"{command} launched a server into the wrong store"

    @requires_node
    def test_a_bad_sibling_does_not_stop_this_project(self, tmp_path: Path) -> None:
        """#287 CR 12: a sibling's invalid id breaks includeLinked search, but
        no write of this project's lands anywhere wrong — reported, and the
        launch goes ahead."""
        project = _project(tmp_path)
        (tmp_path / "archiver").mkdir()
        _config(tmp_path / "archiver", {"projectId": "bad id!"})
        _config(project, {"projectId": "broker", "linkedProjects": ["../archiver"]})
        gate = _driver(project, "validate-store", QDRANT_MODE="external")
        assert gate.returncode == 0, gate.stderr
        assert json.loads(gate.stdout)["valid"] is True
        assert "not ones that block a launch" in gate.stderr, gate.stderr
        entry, marker = _launch_marker(tmp_path)
        _driver(project, "status", QDRANT_MODE="external", SOCRATICODE_ENTRY=str(entry))
        assert marker.exists(), "status refused to launch over a sibling's stub"

    @requires_node
    def test_health_check_reports_and_skips_its_server_checks(
        self, tmp_path: Path
    ) -> None:
        project = _project(tmp_path, shared={"QDRANT_MODE": "external"})
        entry, marker = _launch_marker(tmp_path)
        result = _driver(
            project,
            "health-check",
            SOCRATICODE_ENTRY=str(entry),
            HEALTH_TIMEOUT_MS="30000",
        )
        assert not marker.exists(), (
            "health-check launched a server into the wrong store"
        )
        assert result.returncode == 1, result.stderr
        report = json.loads(result.stdout)
        assert report["serverChecks"] == "skipped", report
        assert report["store"]["declared"]["mode"] == "external", report
        assert "  - the project settings declare store variables" in result.stderr
        assert "  - note: the server checks did not run" in result.stderr, (
            "a report with no infrastructure findings reads as clean infrastructure"
        )

    @requires_node
    def test_a_clean_external_store_is_measured_as_before(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        _config(project, {"projectId": "broker"})
        stub = tmp_path / "stub-server.mjs"
        stub.write_text(STUB_SERVER)
        replies = tmp_path / "replies.json"
        replies.write_text(
            json.dumps(
                {
                    "codebase_health": HEALTH_OK,
                    "codebase_status": STATUS_CLEAN,
                    "codebase_graph_status": GRAPH_OK_HIGH_UNRESOLVED,
                }
            )
        )
        result = _driver(
            project,
            "health-check",
            QDRANT_MODE="external",
            SOCRATICODE_ENTRY=str(stub),
            STUB_REPLIES=str(replies),
            HEALTH_TIMEOUT_MS="30000",
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert "serverChecks" not in report, report
        assert report["store"]["projectId"]["value"] == "broker", report


# STUB_SERVER, prefixed with a line recording the environment it was started
# with. The second `node:fs` import is legal ESM; the stub itself is unchanged.
ENV_RECORDING_SERVER = (
    "import { writeFileSync } from 'node:fs';\n"
    "writeFileSync(process.env.STUB_ENV_OUT, JSON.stringify({\n"
    "  autoResume: process.env.SOCRATICODE_AUTO_RESUME ?? null,\n"
    "  watcher: process.env.SOCRATICODE_WATCHER ?? null,\n"
    "}));\n"
) + STUB_SERVER

INDEX_REPLIES = {
    "codebase_index": "Indexing started in the background for: /repo",
    "codebase_status": STATUS_CLEAN,
    "codebase_graph_status": GRAPH_OK_HIGH_UNRESOLVED,
    "codebase_health": HEALTH_OK,
}


class TestTheDriversOwnServerDoesNotWrite:
    """#287 CR 1. Upstream's startup auto-resume runs an incremental update of
    the server's cwd project whenever its collection exists; through the health
    hook that cwd is the session's, and with a shared projectId a worktree's
    files went into the store once a day, from a hook that "never re-indexes"."""

    def _launch(self, tmp_path: Path, command: str, **env: str) -> dict:
        project = _project(tmp_path)
        _config(project, {"projectId": "broker"})
        stub = tmp_path / "env-server.mjs"
        stub.write_text(ENV_RECORDING_SERVER)
        replies = tmp_path / "replies.json"
        replies.write_text(json.dumps(INDEX_REPLIES))
        seen = tmp_path / "server-env.json"
        result = _driver(
            project,
            command,
            SOCRATICODE_ENTRY=str(stub),
            STUB_REPLIES=str(replies),
            STUB_ENV_OUT=str(seen),
            HEALTH_TIMEOUT_MS="30000",
            POLL_INTERVAL_MS="10",
            **env,
        )
        assert seen.exists(), f"{command} never launched the stub: {result.stderr}"
        return json.loads(seen.read_text())

    @requires_node
    @pytest.mark.parametrize("command", ["status", "verify", "health-check"])
    def test_read_only_commands_start_neither_writer(
        self, tmp_path: Path, command: str
    ) -> None:
        seen = self._launch(tmp_path, command, SOCRATICODE_AUTO_RESUME="all")
        assert seen == {"autoResume": "off", "watcher": "manual"}, (
            "the caller's own SOCRATICODE_AUTO_RESUME must not loosen the "
            f"driver's terms for its server: {seen}"
        )

    @requires_node
    def test_index_keeps_the_watcher_but_not_auto_resume(self, tmp_path: Path) -> None:
        """A completed index starting its watcher is upstream's sequence; an
        incremental run racing the full index the driver asked for is not."""
        seen = self._launch(tmp_path, "index")
        assert seen == {"autoResume": "off", "watcher": None}, seen


class TestTheHookCarriesItIntoTheSession:
    @requires_node
    def test_a_store_defect_reaches_the_session(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        (repo / ".claude").mkdir()
        (repo / ".claude" / "settings.json").write_text(
            json.dumps({"env": {"QDRANT_MODE": "external"}})
        )
        entry, marker = _launch_marker(tmp_path)
        result = subprocess.run(
            ["bash", str(HOOK)],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(
                HOME=str(tmp_path / "home"),
                SOCRATICODE_DRIVER=str(DRIVER),
                SOCRATICODE_ENTRY=str(entry),
                SOCRATICODE_HEALTH_FORCE="1",
            ),
        )
        assert result.returncode == 0, result.stderr
        assert "does not carry: QDRANT_MODE" in result.stdout, result.stdout
        assert "declares no projectId" in result.stdout, result.stdout
        assert "FAILED TO RUN" not in result.stdout, result.stdout
        assert not marker.exists()


# ── the documents ────────────────────────────────────────────────────────────


class TestTheSkillStatesTheOrder:
    def test_projectId_precedes_the_env_block(self) -> None:
        body = SKILL_MD.read_text()
        assert "`STORE`" in body, "the parameter must be collectable"
        step4 = body.index("**`.socraticode.json`**")
        step5 = body.index("**Client `env` block**")
        assert step4 < step5, "the projectId step must come first"
        assert "Never the block alone" in " ".join(body.split())

    def test_trust_is_confirmed_before_the_index(self) -> None:
        """Inside step 5 — after the block is written, before any phase that
        could launch a server — not merely somewhere in the file."""
        body = " ".join(SKILL_MD.read_text().split())
        step5 = body[body.index("**Client `env` block**") : body.index("### Phase 4")]
        for phrase in ("trusting the folder", "re-run this skill", "bare"):
            assert phrase in step5, f"{phrase!r} missing from step 5: {step5}"
        assert "This session cannot index" in step5, (
            "the session that wrote the block runs a server started without it"
        )

    def test_phase_five_gates_on_the_store(self) -> None:
        body = SKILL_MD.read_text()
        phase5 = body[body.index("### Phase 5") : body.index("### Phase 6")]
        assert "validate-store" in phase5, phase5

    def test_linked_projects_are_written_relative(self) -> None:
        flat = " ".join(LINKED_REF.read_text().split())
        assert "relative to the repo root" in flat, flat
        assert "Migrating an older install" in flat, flat

    def test_the_reference_carries_the_env_block(self) -> None:
        body = EXTERNAL_REF.read_text()
        for key in ("QDRANT_MODE", "QDRANT_URL", "OLLAMA_MODE", "OLLAMA_URL"):
            assert f'"{key}"' in body, key
        assert '"QDRANT_API_KEY"' not in body, (
            "the key belongs in a git-ignored file, never in the block shown for "
            "the tracked settings.json"
        )

    def test_the_health_hook_no_longer_assumes_docker(self) -> None:
        body = HOOK.read_text()
        flat = " ".join(body.split())
        assert "needs a running MCP server and Docker" not in body
        assert "a reachable URL for an external one" in flat, (
            "the header must name what an external store needs instead"
        )
        help_text = subprocess.run(
            ["bash", str(HOOK), "--help"], capture_output=True, text=True, timeout=30
        ).stdout
        assert "runs no docker command of its own" in " ".join(help_text.split())
