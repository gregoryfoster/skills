"""A crashed health check must not render as a clean one (#254).

`socraticode-health.sh` is silent when clean, so an operator who has internalised
that reads any output as *it spoke, therefore it ran*. Found in
`CannObserv/cannobserv`: the driver died on launch — an interpreter change under
the plugin's `mcp.json` picked a node the server's Qdrant client could not run
under — and the hook printed

    socraticode-health: findings from today's once-per-day check (see …):
    socraticode-health: this hook reports only. Re-index with codebase_index, …

a findings heading, a remedy footer, and nothing in between. Two independent
causes, each sufficient: node exits 1 for an unhandled rejection just as the
driver exits 1 for *defects found* (#220), and the hook opened its findings
block on `RC != 0` plus a non-empty stderr — which a stack trace satisfies.

This is the fourth appearance of one shape in this hook's history: #177
(reaching the driver through a symlink printed nothing and read as healthy),
#214 (declared ≠ indexed), #225 (indexed ≠ fresh), and now crashed ≠ clean. The
invariant they share, and what this file gates: **for a reporter that is silent
when clean, every failure mode must be louder than silence, never quieter.**

No server, no Docker, no network — the hook is pointed at stub drivers that
exit the way a crashed one does.
"""

import json
import subprocess
from pathlib import Path

# The hook's fixtures live with the hook's other tests. Imported rather than
# re-derived: a private `_repo` here would drift the first time the manifest
# guard those tests pin changes, and this file would keep passing against a
# repo shape the hook no longer recognises (#254 CR round 1).
from .test_socraticode_graph_yield import (
    DRIVER,
    HOOK,
    _clean_env,
    _repo,
    requires_node,
)

# The two sentences that mean "measured, and here is the list". Neither may
# appear when nothing was measured.
FINDINGS_HEADER = "findings from today's once-per-day check"
REPORTS_ONLY_FOOTER = "reports only"

# A driver crash as it actually arrives: launch chatter, an error, a stack.
# Not one `  - ` line anywhere, which is the whole point.
CRASH_STDERR = (
    "[driver] server launch (plugin mcp.json): npx -y socraticode\n"
    "Error: server process exited (code 1) with requests in flight\n"
    "    at ChildProcess.<anonymous> (mcp-driver.mjs:193:16)\n"
)


def _stub(repo: Path, *, exit_code: int, stderr: str = "") -> Path:
    """Local rather than imported: the sibling's `_stub_driver` also writes a
    JSON verdict on stdout, and every case here turns on stderr alone."""
    stub = repo / "stub-driver.mjs"
    stub.write_text(
        f"process.stderr.write({json.dumps(stderr)});\nprocess.exit({exit_code});\n"
    )
    return stub


def _run_hook(repo: Path, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HOOK)],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=60,
        env=_clean_env(SOCRATICODE_HEALTH_FORCE="1", **env),
    )


class TestCrashedCheckIsNotReportedAsClean:
    """The hook-side branch, which is the one that matters.

    It covers every driver version already vendored in a consumer — a repo
    running a driver older than the exit-code reservation below still gets a
    truthful sentence.
    """

    @requires_node
    def test_a_crash_does_not_print_a_findings_header(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        stub = _stub(repo, exit_code=1, stderr=CRASH_STDERR)
        result = _run_hook(repo, SOCRATICODE_DRIVER=str(stub))
        assert result.returncode == 0, result.stderr
        assert FINDINGS_HEADER not in result.stdout, (
            "a driver that crashed before measuring anything was announced "
            "under a heading that says findings — the shape that means "
            f"'I measured, here is the list':\n{result.stdout}"
        )
        assert REPORTS_ONLY_FOOTER not in result.stdout, (
            "the remedy footer tells the operator what to do about findings "
            "there are none of; with the header gone it is the last thing "
            f"still implying a completed check:\n{result.stdout}"
        )

    @requires_node
    def test_a_crash_says_it_did_not_run(self, tmp_path: Path) -> None:
        """Louder than silence, not quieter. Naming the exit code matters:
        it is what an operator carries to the log."""
        repo = _repo(tmp_path)
        stub = _stub(repo, exit_code=1, stderr=CRASH_STDERR)
        result = _run_hook(repo, SOCRATICODE_DRIVER=str(stub))
        assert "FAILED TO RUN" in result.stdout, (
            f"a crashed check must name itself as not-measured; got {result.stdout!r}"
        )
        assert "not a clean result" in result.stdout, result.stdout
        assert "exited 1" in result.stdout, (
            "the sentence must carry the driver's exit code, so the operator "
            f"can match it against the log: {result.stdout!r}"
        )

    @requires_node
    def test_a_crash_with_empty_stderr_is_still_reported(self, tmp_path: Path) -> None:
        """The old guard also required a non-empty stderr. A driver killed
        outright (SIGKILL, an OOM) measured nothing and says nothing — which
        the silent-when-clean contract renders as healthy."""
        repo = _repo(tmp_path)
        stub = _stub(repo, exit_code=137)
        result = _run_hook(repo, SOCRATICODE_DRIVER=str(stub))
        assert result.returncode == 0, result.stderr
        assert "FAILED TO RUN" in result.stdout, (
            "a driver that died without printing anything must not be silent "
            f"here; got {result.stdout!r}"
        )

    @requires_node
    def test_real_findings_still_print_with_their_header(self, tmp_path: Path) -> None:
        """The fix must not cost the reporting path. A crash branch that also
        eats real findings trades one silent failure for another."""
        repo = _repo(tmp_path)
        stub = _stub(
            repo,
            exit_code=1,
            stderr=(
                "[driver] SocratiCode health findings:\n"
                "  - graph yield LOW — 3 edge(s) across 374 files\n"
            ),
        )
        result = _run_hook(repo, SOCRATICODE_DRIVER=str(stub))
        assert FINDINGS_HEADER in result.stdout, result.stdout
        assert "graph yield LOW" in result.stdout, result.stdout
        assert REPORTS_ONLY_FOOTER in result.stdout, result.stdout
        assert "FAILED TO RUN" not in result.stdout, (
            "a run that produced findings was reported as one that could not "
            f"run:\n{result.stdout}"
        )

    @requires_node
    def test_a_clean_run_stays_silent(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        stub = _stub(repo, exit_code=0, stderr="[driver] nothing to report\n")
        result = _run_hook(repo, SOCRATICODE_DRIVER=str(stub))
        assert result.stdout == "", (
            f"silent-when-clean is the contract; got {result.stdout!r}"
        )

    @requires_node
    def test_a_thrown_error_reaches_the_same_branch(self, tmp_path: Path) -> None:
        """End to end through node's own unhandled-rejection path, not a
        hand-written exit code — that path is what produced the field case."""
        repo = _repo(tmp_path)
        stub = repo / "boom.mjs"
        stub.write_text(
            "await new Promise((_, rej) => "
            "rej(new Error('server process exited (code 1)')));\n"
        )
        result = _run_hook(repo, SOCRATICODE_DRIVER=str(stub))
        assert result.returncode == 0, result.stderr
        assert "FAILED TO RUN" in result.stdout, (
            f"a crashing driver read as a completed check: {result.stdout!r}"
        )


class TestDriverReservesAnIncompleteExitCode:
    """The driver-side half: 0/1/2 were taken, so a crash had nowhere to land.

    Not relied on by the hook — a consumer's vendored driver may predate it —
    but it makes the state legible to any other consumer of `health-check`.
    """

    @requires_node
    def test_a_throwing_command_exits_three(self, tmp_path: Path) -> None:
        """The field case exactly: a server that exits with a request in
        flight. `SOCRATICODE_ENTRY` points at a script that dies on launch, so
        this needs no Docker, no Qdrant and no network — the throw comes out of
        `RpcClient`'s own exit handler, where the real one came from."""
        entry = tmp_path / "dead-server.js"
        entry.write_text("process.exit(1);\n")
        result = subprocess.run(
            ["node", str(DRIVER), "health-check", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(SOCRATICODE_ENTRY=str(entry), HEALTH_TIMEOUT_MS="20000"),
        )
        assert result.returncode == 3, (
            "a health-check that could not run must not exit 1 — that is the "
            "code for defects found (#220), and the two readings are "
            f"opposites. Got {result.returncode}.\n{result.stderr}"
        )
        assert "DID NOT COMPLETE" in result.stderr, result.stderr

    def test_usage_publishes_the_code(self) -> None:
        usage = DRIVER.read_text()
        assert "Exit codes:" in usage, (
            "mcp-driver.mjs's USAGE must carry an exit-code table — the codes "
            "now carry three distinct meanings and a consumer keying on them "
            "has nowhere else to read them"
        )
        assert "DID NOT COMPLETE" in usage, (
            "the usage table must name the did-not-complete code, or a "
            "consumer keeps reading non-zero as 'defects found'"
        )
