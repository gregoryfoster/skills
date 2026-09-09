"""Preflight's Node gate keys on the server build, not on a Node version (#269).

The gate used to hard-refuse Node 26+ outright, on the grounds that
`@qdrant/js-client-rest` < 1.19 hands its undici-6 Agent to Node's built-in
fetch, which is undici 8 on Node 26, killing the server at startup.

SocratiCode 1.13.0 fixed that deliberately — `src/services/qdrant-client-compat.ts`
pairs the client's Agent with a matching undici — so the refusal became a gate
that blocked working hosts. The ceiling was never really a Node version: it is a
question about which *build* will launch, and the plugin's `mcp.json` answers it
by running `npx -y --prefer-online socraticode@latest`.

Three properties are worth pinning, because each was wrong at some point:

- the floor is upstream's own `engines` (>=18.17.0), not a bare major — 18.0
  through 18.16 satisfy ">=18" and fail the package's constraint;
- Node 26+ fails only when the resolved build genuinely predates the fix;
- an unresolvable registry WARNS rather than refusing, because that proves
  nothing and the residual failure is loud at startup.

The gate is driven through a stubbed `node`/`npm` on PATH rather than by parsing
the script, so these assert behaviour rather than wording.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PREFLIGHT = REPO_ROOT / "skills" / "init-socraticode" / "scripts" / "preflight.sh"
SKILL_MD = REPO_ROOT / "skills" / "init-socraticode" / "SKILL.md"

requires_bash = pytest.mark.skipif(
    shutil.which("bash") is None,
    reason="bash is required to exercise preflight.sh",
)


def _stub_toolchain(tmp_path: Path, node_version: str, npm_reply: str | None) -> Path:
    """A PATH whose `node` reports `node_version` and whose `npm` prints a version.

    `npm_reply=None` stands for a registry that did not answer — the case the
    gate must warn about rather than refuse.

    `docker` is stubbed too, and that is not incidental. The exit-code
    assertions below are the point of several of these tests — the warn branch
    must NOT set `FAIL` — and the exit code is the whole script's, so an
    unstubbed Gate 1 would make them assert "this host runs Docker" instead.
    They would pass on a developer laptop and fail in CI and pre-commit, which
    is where this suite actually runs.
    """
    binv = tmp_path / "bin"
    binv.mkdir(exist_ok=True)
    (binv / "node").write_text(
        f'#!/bin/sh\n[ "$1" = "--version" ] && echo "{node_version}" && exit 0\nexit 0\n'
    )
    if npm_reply is None:
        (binv / "npm").write_text("#!/bin/sh\nexit 1\n")
    else:
        (binv / "npm").write_text(f'#!/bin/sh\necho "{npm_reply}"\n')
    # npx only has to exist; its own gate is not under test here.
    (binv / "npx").write_text("#!/bin/sh\nexit 0\n")
    # `docker info` succeeding is all Gate 1 asks for.
    (binv / "docker").write_text("#!/bin/sh\nexit 0\n")
    for name in ("node", "npm", "npx", "docker"):
        (binv / name).chmod(0o755)
    return binv


def _run(tmp_path: Path, node_version: str, npm_reply: str | None):
    binv = _stub_toolchain(tmp_path, node_version, npm_reply)
    env = dict(os.environ)
    env["PATH"] = f"{binv}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        ["bash", str(PREFLIGHT)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


def _node_line(out: str) -> str:
    """The gate's own line, isolated from the other gates' output."""
    return next((ln for ln in out.splitlines() if "Node" in ln), "")


class TestTheFloorIsUpstreamEngines:
    @requires_bash
    @pytest.mark.parametrize("version", ["v18.0.0", "v18.16.1", "v16.20.0"])
    def test_below_engines_fails(self, tmp_path: Path, version: str) -> None:
        """18.0-18.16 pass a bare ">=18" and fail the package's own constraint."""
        result = _run(tmp_path, version, "1.13.1")
        assert "✗" in _node_line(result.stdout), result.stdout
        assert result.returncode == 1

    @requires_bash
    @pytest.mark.parametrize("version", ["v18.17.0", "v20.11.0", "v22.18.0"])
    def test_supported_versions_pass_the_node_gate(
        self, tmp_path: Path, version: str
    ) -> None:
        result = _run(tmp_path, version, "1.13.1")
        assert "✓" in _node_line(result.stdout), result.stdout


class TestNode26KeysOnTheServerBuild:
    @requires_bash
    @pytest.mark.parametrize("node_version", ["v26.0.0", "v28.1.0"])
    def test_a_fixed_build_is_accepted(self, tmp_path: Path, node_version: str) -> None:
        """The regression #269 filed: a working host refused on the Node major."""
        result = _run(tmp_path, node_version, "1.13.1")
        assert "✓" in _node_line(result.stdout), result.stdout
        assert result.returncode == 0, result.stdout

    @requires_bash
    def test_a_build_predating_the_fix_still_fails(self, tmp_path: Path) -> None:
        """The original reason survives where it still applies."""
        result = _run(tmp_path, "v26.0.0", "1.12.0")
        assert "✗" in _node_line(result.stdout), result.stdout
        assert result.returncode == 1

    @requires_bash
    def test_an_unresolvable_registry_warns_and_does_not_block(
        self, tmp_path: Path
    ) -> None:
        """Unprovable either way, and the residual failure is loud at startup.

        Refusing here would block a working host because a network read did not
        answer — which is the same over-refusal #269 was filed about.
        """
        result = _run(tmp_path, "v26.0.0", None)
        line = _node_line(result.stdout)
        assert "✗" not in line, line
        assert "•" in line, f"expected the advisory marker, got: {line}"
        assert result.returncode == 0, result.stdout


class TestTheExitCodeAssertionsAreHermetic:
    """Why `docker` is stubbed: Gate 1 really is in the exit code.

    Without this, the `returncode == 0` assertions above would be reading the
    developer's Docker daemon rather than the Node gate, and would fail wherever
    this suite is actually enforced.
    """

    @requires_bash
    def test_a_broken_docker_would_have_failed_the_run(self, tmp_path: Path) -> None:
        binv = _stub_toolchain(tmp_path, "v26.0.0", "1.13.1")
        (binv / "docker").write_text("#!/bin/sh\nexit 1\n")
        (binv / "docker").chmod(0o755)
        env = dict(os.environ)
        env["PATH"] = f"{binv}{os.pathsep}{env['PATH']}"
        result = subprocess.run(
            ["bash", str(PREFLIGHT)],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        assert result.returncode == 1, (
            "Gate 1 is not reaching the exit code, so stubbing docker in "
            "_stub_toolchain is load-bearing for the assertions above"
        )
        assert "✓" in _node_line(result.stdout), (
            "…while the Node gate itself still passes — the two are independent"
        )


class TestTheDocsAgreeWithTheGate:
    def test_skill_md_does_not_still_promise_a_hard_refusal(self) -> None:
        body = SKILL_MD.read_text()
        assert "26+ hard-refused" not in body
        assert "hard refusal" not in body.lower(), (
            "SKILL.md still describes Node 26+ as a hard refusal; preflight now "
            "checks the resolved server build instead (#269)"
        )

    def test_no_doc_still_advertises_the_old_upper_bound(self) -> None:
        """`Node >=18 <26` and `Node<26` appeared in four places, README included."""
        for path in (SKILL_MD, REPO_ROOT / "README.md"):
            body = path.read_text()
            assert ">=18 <26" not in body, f"{path.name} still advertises <26"
            assert "Node<26" not in body, f"{path.name} still advertises Node<26"
