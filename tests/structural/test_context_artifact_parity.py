"""health-check reports declared ≠ indexed context artifacts (#214).

`init-socraticode`'s health-check flags infrastructure problems, a FAILED last
operation, an INCOMPLETE index and a low-yield graph. None of them fire on the
shape `CannObserv/power-map#454` found: a **completed** operation that left an
artifact unindexed.

    ✓ Indexed 2 artifacts: …
    ✗ 1 error:
      • reference-docs: fetch failed

`codebase_status` then settled at `Context artifacts: 2/3 indexed (45 chunks)`
and stayed there — last operation completed, index not INCOMPLETE, every
container green — while a 2.5M `./docs` tree was unreachable via
`codebase_context_search` and nothing reported it. That is #107's shape one
level up: three green lights over a silently degraded index. So the gap is a
finding, and a finding sets `process.exitCode = 1` like every other one in
`cmdHealthCheck`.

Not hypothetical, and not only power-map: while this was being written, a live
`codebase_context` on `cannabis_observer/code/cli` returned 12 of 13 artifacts
indexed, with `env-example` sitting at `○ not yet indexed` behind a green
`Status: green`. The fixtures below are that reply, trimmed.

Why the manifest is the denominator and not the status line: `parseArtifacts`
reports `0/0` for `Context artifacts: 7 configured, not yet indexed` (its own
selftest pins that), and `0/0` again when the line is absent entirely, so the
server's own count cannot tell "nothing declared" from "nothing indexed yet".
`.socraticodecontextartifacts.json` can.

The driver is exercised end to end against a stub MCP server — plain
newline-delimited JSON-RPC on stdio, scripted per tool — because the property
under test is a *finding and an exit code*, not a parse. No Docker, no network,
no real server.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "init-socraticode"
DRIVER = SKILL_DIR / "scripts" / "mcp-driver.mjs"
DOC_REF = SKILL_DIR / "references" / "socraticode-doc.md"
MANIFEST_NAME = ".socraticodecontextartifacts.json"

requires_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is required to exercise mcp-driver.mjs",
)

# One live `codebase_context` reply, trimmed to three of its thirteen blocks.
# The middle one is the real unindexed artifact, verbatim.
CONTEXT_LISTING = """Context Artifacts for: /repo
Config: .socraticodecontextartifacts.json (3 artifacts)

━━━ database-schema ━━━
  Path: ./docs/schema.sql
  Description: PostgreSQL schema.
  Status: ✓ indexed (42 chunks, 2026-08-09T04:46:34.264Z)

━━━ reference-docs ━━━
  Path: ./docs/
  Description: The docs tree.
  Status: ○ not yet indexed

━━━ agent-guidelines ━━━
  Path: ./AGENTS.md
  Description: Conventions.
  Status: ✓ indexed (3 chunks, 2026-08-09T04:46:35.009Z)

Use codebase_context_search to search across artifacts.
"""

CONTEXT_ALL_INDEXED = CONTEXT_LISTING.replace(
    "Status: ○ not yet indexed",
    "Status: ✓ indexed (577 chunks, 2026-08-09T04:48:31.005Z)",
)

CONTEXT_NONE = "No context artifacts configured for: /repo\n"

HEALTH_OK = "Docker: ✓ running\nQdrant: ✓ healthy\nOllama: ✓ nomic-embed-text present"

STATUS_PARTIAL = """Project: /repo
Collection: codebase_2acf94e22bba
Status: green
Indexed chunks: 1252

Last operation: Incremental update — completed

Context artifacts: 2/3 indexed (45 chunks)
  Some artifacts are not yet indexed. Run codebase_context_index to index all.
"""

STATUS_COMPLETE = """Project: /repo
Status: green
Indexed chunks: 1252

Last operation: Incremental update — completed

Context artifacts: 3 artifacts indexed (622 chunks)
"""

GRAPH_OK = """Code Graph Status

Status: READY
Files (nodes): 374
Dependencies (edges): 1512
Symbols: 3767
"""

STUB_SERVER = """
import { readFileSync } from 'node:fs';
const replies = JSON.parse(readFileSync(process.env.STUB_REPLIES, 'utf8'));
let buf = '';
const send = (o) => process.stdout.write(JSON.stringify(o) + '\\n');
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
  buf += chunk;
  let nl;
  while ((nl = buf.indexOf('\\n')) >= 0) {
    const line = buf.slice(0, nl).trim();
    buf = buf.slice(nl + 1);
    if (!line) continue;
    let msg;
    try { msg = JSON.parse(line); } catch { continue; }
    if (msg.id == null) continue;
    if (msg.method !== 'tools/call') { send({ jsonrpc: '2.0', id: msg.id, result: {} }); continue; }
    const text = replies[msg.params.name];
    if (text == null) {
      send({ jsonrpc: '2.0', id: msg.id, error: { message: `stub: no reply for ${msg.params.name}` } });
      continue;
    }
    send({ jsonrpc: '2.0', id: msg.id, result: { content: [{ type: 'text', text }] } });
  }
});
"""

DEFAULT_REPLIES = {
    "codebase_health": HEALTH_OK,
    "codebase_status": STATUS_PARTIAL,
    "codebase_graph_status": GRAPH_OK,
    "codebase_context": CONTEXT_LISTING,
}


def _clean_env(**extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("SOCRATICODE_DRIVER", "SOCRATICODE_PROBE_FILE",
              "HEALTH_TIMEOUT_MS", "SOCRATICODE_HEALTH_FORCE"):
        env.pop(k, None)
    env.update(extra)
    return env


def _repo(tmp_path: Path, artifacts: object = "default") -> Path:
    """A project directory whose manifest paths actually resolve.

    `validateManifest` stats every path, and a non-resolving one is an error —
    which would put this test on the invalid-manifest branch by accident.
    """
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "schema.sql").write_text("-- schema\n")
    (repo / "AGENTS.md").write_text("# conventions\n")
    if artifacts == "default":
        artifacts = {
            "artifacts": [
                {"name": "database-schema", "path": "./docs/schema.sql", "description": "d"},
                {"name": "reference-docs", "path": "./docs/", "description": "d"},
                {"name": "agent-guidelines", "path": "./AGENTS.md", "description": "d"},
            ]
        }
    if artifacts is not None:
        (repo / MANIFEST_NAME).write_text(json.dumps(artifacts))
    return repo


def _health_check(tmp_path: Path, repo: Path, replies: dict) -> tuple:
    """Run `mcp-driver.mjs health-check` against a scripted stub server.

    Returns (CompletedProcess, parsed stdout JSON or None).
    """
    stub = tmp_path / "stub-server.mjs"
    stub.write_text(STUB_SERVER)
    reply_file = tmp_path / "replies.json"
    reply_file.write_text(json.dumps(replies))
    result = subprocess.run(
        ["node", str(DRIVER), "health-check", str(repo)],
        capture_output=True, text=True, timeout=60,
        env=_clean_env(
            SOCRATICODE_ENTRY=str(stub),
            STUB_REPLIES=str(reply_file),
            HEALTH_TIMEOUT_MS="30000",
        ),
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        report = None
    return result, report


class TestParsesPerArtifactStatus:
    """The reply names the artifact; nothing in the driver read it before."""

    @staticmethod
    def _parse(text: str) -> list:
        script = (
            f"import {{ parseContextArtifacts }} from {json.dumps(str(DRIVER))};"
            f"process.stdout.write(JSON.stringify(parseContextArtifacts("
            f"{json.dumps(text)})));"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True, text=True, timeout=60, env=_clean_env(),
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    @requires_node
    def test_the_live_reply_parses(self) -> None:
        parsed = self._parse(CONTEXT_LISTING)
        assert [a["name"] for a in parsed] == [
            "database-schema", "reference-docs", "agent-guidelines"
        ], parsed
        assert [a["indexed"] for a in parsed] == [True, False, True], parsed

    @requires_node
    @pytest.mark.parametrize(
        "status",
        [
            pytest.param("○ not yet indexed", id="pending"),
            pytest.param("✗ error: fetch failed", id="errored"),
            pytest.param("✗ fetch failed", id="bare-error"),
            pytest.param("failed to index", id="prose-failure"),
        ],
    )
    def test_only_a_positive_status_counts_as_indexed(self, status: str) -> None:
        """Unknown wording must fall to *not* indexed.

        The pending state is the one shape confirmed against a live server; the
        error state is the field case, whose exact rendering we have only from
        `codebase_context_index`'s report. Treating an unrecognised status as
        indexed would rebuild the silent-green hole this finding exists to
        close, so the predicate is deliberately asymmetric.
        """
        parsed = self._parse(CONTEXT_LISTING.replace("○ not yet indexed", status))
        assert [a["indexed"] for a in parsed] == [True, False, True], parsed
        assert parsed[1]["status"] == status

    @requires_node
    def test_a_project_with_no_artifacts_parses_to_nothing(self) -> None:
        assert self._parse(CONTEXT_NONE) == []


class TestHealthCheckReportsTheParityGap:
    """The field case, end to end, against a stub server."""

    @requires_node
    def test_a_completed_index_that_left_an_artifact_unindexed_is_a_finding(
        self, tmp_path: Path
    ) -> None:
        result, report = _health_check(tmp_path, _repo(tmp_path), DEFAULT_REPLIES)
        assert report is not None, result.stdout + result.stderr
        assert report["healthy"] is False, report
        parity = [f for f in report["findings"] if "context artifact" in f]
        assert parity, (
            "health-check saw 3 declared artifacts and 2 indexed and reported "
            f"nothing about it — the #214 gap:\n{report}"
        )

    @requires_node
    def test_the_finding_names_the_artifact_and_the_counts(
        self, tmp_path: Path
    ) -> None:
        """`2/3` alone sends a reader back to `codebase_status`.

        The whole cost of the field case was not knowing *which* artifact was
        missing: the answer decides whether to re-index one path or debug the
        manifest.
        """
        _, report = _health_check(tmp_path, _repo(tmp_path), DEFAULT_REPLIES)
        parity = " ".join(f for f in report["findings"] if "context artifact" in f)
        assert "2/3" in parity, parity
        assert "reference-docs" in parity, parity

    @requires_node
    def test_the_gap_exits_one(self, tmp_path: Path) -> None:
        """Informational would reproduce the shape the issue is filed about.

        Every other `findings.push` in `cmdHealthCheck` sets
        `process.exitCode = 1`, and the once-per-day hook keys on that exit code
        to decide whether it has anything to say.
        """
        result, _ = _health_check(tmp_path, _repo(tmp_path), DEFAULT_REPLIES)
        assert result.returncode == 1, result.stdout + result.stderr

    @requires_node
    def test_full_parity_says_nothing(self, tmp_path: Path) -> None:
        replies = {**DEFAULT_REPLIES,
                   "codebase_status": STATUS_COMPLETE,
                   "codebase_context": CONTEXT_ALL_INDEXED}
        result, report = _health_check(tmp_path, _repo(tmp_path), replies)
        assert report["healthy"] is True, report
        assert result.returncode == 0, result.stdout + result.stderr

    @requires_node
    def test_a_repo_with_no_manifest_is_not_a_finding(self, tmp_path: Path) -> None:
        """No artifacts configured is a choice, not a degradation."""
        replies = {**DEFAULT_REPLIES,
                   "codebase_status": STATUS_COMPLETE,
                   "codebase_context": CONTEXT_NONE}
        repo = _repo(tmp_path, artifacts=None)
        result, report = _health_check(tmp_path, repo, replies)
        assert report["healthy"] is True, report
        assert result.returncode == 0, result.stdout + result.stderr

    @requires_node
    def test_an_invalid_manifest_is_reported_not_died_on(self, tmp_path: Path) -> None:
        """`expectedArtifactCount()` calls `die()`, and `die()` is `process.exit`.

        Two reasons that is the wrong helper *here*. The command's contract is
        JSON on stdout — the same reason `cmdHealthCheck` sets `exitCode`
        instead of calling `exit()`, since node's stdout is async on a pipe and
        `exit()` abandons what has not drained. And an invalid manifest is
        itself the silent-green case #85 documented: the server rejects it,
        `codebase_status` then omits the artifact line entirely, and every
        reading reports a contented `0/0`.
        """
        repo = _repo(tmp_path, artifacts={"artifacts": [{"name": "x", "path": "./nope.md"}]})
        replies = {**DEFAULT_REPLIES, "codebase_status": STATUS_COMPLETE,
                   "codebase_context": CONTEXT_NONE}
        result, report = _health_check(tmp_path, repo, replies)
        assert report is not None, (
            "health-check died on an invalid manifest instead of reporting it, "
            f"so its JSON contract went with it:\n{result.stdout}\n{result.stderr}"
        )
        assert any(MANIFEST_NAME in f for f in report["findings"]), report
        assert result.returncode == 1, result.stdout

    @requires_node
    def test_the_gap_is_still_reported_when_the_artifact_cannot_be_named(
        self, tmp_path: Path
    ) -> None:
        """`codebase_context` failing must degrade, not disable.

        The count alone is worth strictly more than silence, and this is the
        one place the status line's own numerator is trustworthy.
        """
        replies = {k: v for k, v in DEFAULT_REPLIES.items() if k != "codebase_context"}
        result, report = _health_check(tmp_path, _repo(tmp_path), replies)
        parity = [f for f in report["findings"] if "context artifact" in f]
        assert parity, report
        assert "2/3" in " ".join(parity), parity
        assert result.returncode == 1, result.stdout


class TestGeneratedDocExplainsTheSymptom:
    """The addendum: the per-tool note covers only half the failure.

    `codebase_context_search` returning nothing has two diagnoses that look
    identical from the caller's seat. The manifest one — a path that does not
    resolve, skipped silently — is documented. The field case is the sibling:
    the path resolves, the operation completes, and the artifact is *still* not
    indexed, which the manifest cannot tell you and `codebase_context` can.
    Without it a reader checks their manifest, finds it correct, and concludes
    the answer is not in the docs — which is what the artifact was for.
    """

    @staticmethod
    def _per_tool_notes() -> str:
        text = DOC_REF.read_text()
        start = text.index("## Per-tool notes")
        end = text.find("\n## ", start + len("## Per-tool notes"))
        return text[start:end if end != -1 else len(text)]

    def test_the_note_covers_the_resolving_but_unindexed_case(self) -> None:
        notes = self._per_tool_notes().lower()
        assert "codebase_context`" in notes or "codebase_context " in notes, (
            f"references/{DOC_REF.name}'s **Per-tool notes** must send a reader "
            "with no context-search results to `codebase_context`, which is the "
            "only per-artifact index status there is (#214)"
        )
        assert "indexed" in notes, (
            f"references/{DOC_REF.name}'s **Per-tool notes** still explains an "
            "empty `codebase_context_search` only as a manifest problem. The "
            "field case had a correct manifest and an unindexed artifact "
            "(CannObserv/power-map#454)."
        )

    def test_the_manifest_case_is_not_replaced_by_it(self) -> None:
        """Two diagnoses, one symptom — the note has to keep both."""
        notes = self._per_tool_notes().lower()
        assert "silently" in notes and "manifest" in notes, (
            f"references/{DOC_REF.name} dropped the non-resolving-path case "
            "while adding its sibling; both are live"
        )
