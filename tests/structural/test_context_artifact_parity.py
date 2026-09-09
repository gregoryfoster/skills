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
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "init-socraticode"
DRIVER = SKILL_DIR / "scripts" / "mcp-driver.mjs"
DOC_REF = SKILL_DIR / "references" / "socraticode-doc.md"
ARTIFACTS_REF = SKILL_DIR / "references" / "context-artifacts.md"
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
import { appendFileSync, readFileSync } from 'node:fs';
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
    // Every tools/call is logged, answered or not. A fixture the driver never
    // reads is a fixture that proves nothing, and there is no other way from
    // Python to tell "the reply satisfied the check" from "the reply was never
    // asked for" — see TestHealthCheckReportsTheParityGap.test_full_parity.
    appendFileSync(process.env.STUB_CALLS, msg.params.name + '\\n');
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
    for k in (
        "SOCRATICODE_DRIVER",
        "SOCRATICODE_PROBE_FILE",
        "HEALTH_TIMEOUT_MS",
        "SOCRATICODE_HEALTH_FORCE",
    ):
        env.pop(k, None)
    env.update(extra)
    return env


# Every source file in the fixture repo is stamped here, well BEFORE the
# `2026-08-09` index times in the fixtures above. Freshness is a comparison
# between two clocks, so a fixture that leaves one of them at "now" tests
# whatever day the suite happens to run (#225).
SOURCE_MTIME = "2026-08-01T00:00:00+00:00"
# After the fixtures' index time: an edit the index has not seen.
EDITED_AFTER_INDEXING = "2026-08-10T09:30:00+00:00"


def _stamp(path: Path, when: str = SOURCE_MTIME) -> None:
    ts = datetime.fromisoformat(when).timestamp()
    os.utime(path, (ts, ts))


def _repo(tmp_path: Path, artifacts: object = "default") -> Path:
    """A project directory whose manifest paths actually resolve.

    `validateManifest` stats every path, and a non-resolving one is an error —
    which would put this test on the invalid-manifest branch by accident.

    Every path is stamped older than the fixtures' index times, so the default
    repo is *fresh* and a test opts into staleness by re-stamping one path.
    Directories are stamped last: creating an entry bumps the containing
    directory's own mtime, and the whole point of the directory case is that
    the directory's own mtime is not the thing being measured.
    """
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "schema.sql").write_text("-- schema\n")
    (repo / "AGENTS.md").write_text("# conventions\n")
    if artifacts == "default":
        artifacts = {
            "artifacts": [
                {
                    "name": "database-schema",
                    "path": "./docs/schema.sql",
                    "description": "d",
                },
                {"name": "reference-docs", "path": "./docs/", "description": "d"},
                {"name": "agent-guidelines", "path": "./AGENTS.md", "description": "d"},
            ]
        }
    if artifacts is not None:
        (repo / MANIFEST_NAME).write_text(json.dumps(artifacts))
    for path in (repo / "docs" / "schema.sql", repo / "AGENTS.md", repo / "docs", repo):
        _stamp(path)
    return repo


def _health_check(tmp_path: Path, repo: Path, replies: dict) -> tuple:
    """Run `mcp-driver.mjs health-check` against a scripted stub server.

    Returns (CompletedProcess, parsed stdout JSON or None, list of tools called).
    """
    stub = tmp_path / "stub-server.mjs"
    stub.write_text(STUB_SERVER)
    reply_file = tmp_path / "replies.json"
    reply_file.write_text(json.dumps(replies))
    calls = tmp_path / "calls.txt"
    calls.write_text("")
    result = subprocess.run(
        ["node", str(DRIVER), "health-check", str(repo)],
        capture_output=True,
        text=True,
        timeout=60,
        env=_clean_env(
            SOCRATICODE_ENTRY=str(stub),
            STUB_REPLIES=str(reply_file),
            STUB_CALLS=str(calls),
            HEALTH_TIMEOUT_MS="30000",
        ),
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        report = None
    return result, report, calls.read_text().split()


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
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    @requires_node
    def test_the_live_reply_parses(self) -> None:
        parsed = self._parse(CONTEXT_LISTING)
        assert [a["name"] for a in parsed] == [
            "database-schema",
            "reference-docs",
            "agent-guidelines",
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
        result, report, _calls = _health_check(
            tmp_path, _repo(tmp_path), DEFAULT_REPLIES
        )
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
        _, report, _calls = _health_check(tmp_path, _repo(tmp_path), DEFAULT_REPLIES)
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
        result, _, _calls = _health_check(tmp_path, _repo(tmp_path), DEFAULT_REPLIES)
        assert result.returncode == 1, result.stdout + result.stderr

    @requires_node
    def test_full_parity_says_nothing(self, tmp_path: Path) -> None:
        """Re-anchored: this test used to pass without reading its own fixture.

        #214 short-circuited `codebase_context` whenever the status line's
        numerator already matched the declared count — so on this reply, with
        `Context artifacts: 3 artifacts indexed`, the driver never asked, and
        `CONTEXT_ALL_INDEXED` was never parsed. The assertions below held
        because nothing had contradicted them, not because anything had
        confirmed them; the same green would have come back with a fixture of
        gibberish. The tell was invisible to any keyword sweep — the test named
        the right fixture, it just never reached the code that reads it.

        #225 retired the short-circuit (freshness lives only in that reply), so
        the fixture is live again. It is anchored on the call log and on
        `report["artifacts"]` so it cannot quietly go hollow a second time: a
        count re-derived from `declared` would satisfy `indexed == 3` on its
        own, which is why the tool call itself is asserted.
        """
        replies = {
            **DEFAULT_REPLIES,
            "codebase_status": STATUS_COMPLETE,
            "codebase_context": CONTEXT_ALL_INDEXED,
        }
        result, report, calls = _health_check(tmp_path, _repo(tmp_path), replies)
        assert "codebase_context" in calls, (
            "health-check declared full parity without ever asking "
            f"codebase_context; every artifact assertion here is hollow: {calls}"
        )
        artifacts = report.get("artifacts")
        assert artifacts is not None, report
        assert artifacts["indexed"] == 3 and artifacts["declared"] == 3, artifacts
        assert artifacts["unindexed"] == [], artifacts
        assert report["healthy"] is True, report
        assert result.returncode == 0, result.stdout + result.stderr

    @requires_node
    def test_a_repo_with_no_manifest_is_not_a_finding(self, tmp_path: Path) -> None:
        """No artifacts configured is a choice, not a degradation."""
        replies = {
            **DEFAULT_REPLIES,
            "codebase_status": STATUS_COMPLETE,
            "codebase_context": CONTEXT_NONE,
        }
        repo = _repo(tmp_path, artifacts=None)
        result, report, _calls = _health_check(tmp_path, repo, replies)
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
        repo = _repo(
            tmp_path, artifacts={"artifacts": [{"name": "x", "path": "./nope.md"}]}
        )
        replies = {
            **DEFAULT_REPLIES,
            "codebase_status": STATUS_COMPLETE,
            "codebase_context": CONTEXT_NONE,
        }
        result, report, _calls = _health_check(tmp_path, repo, replies)
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
        result, report, _calls = _health_check(tmp_path, _repo(tmp_path), replies)
        parity = [f for f in report["findings"] if "context artifact" in f]
        assert parity, report
        assert "2/3" in " ".join(parity), parity
        assert result.returncode == 1, result.stdout


class TestHealthCheckReportsStaleArtifacts:
    """#225: `14/14 indexed` is a PRESENCE check, and presence is not freshness.

    #214 works exactly as advertised on CannObserv/observo — the driver reported
    `{"declared": 14, "indexed": 14, "unindexed": []}`. Three of those fourteen
    were stale at that moment: `architecture` (`docs/ARCHITECTURE.md`, edited
    04:49, indexed 04:19), `wire-protocol-schemas`, and `implementation-plans`.
    `codebase_context_search` was answering from superseded chunks with three
    green lights over it.

    That is the same silence #214 exists to kill, reached by a worse route. An
    unindexed artifact is *absent* from search: the caller gets nothing and
    knows to look elsewhere. A stale one answers confidently from old content,
    and there is no signal at all — so it is a defect and it sets the exit code,
    not a note.

    The directory case is the harder half, and it is why the comparison is
    against the newest DESCENDANT rather than against the artifact path's own
    mtime. `design-specs`, `implementation-plans` and `alembic-migrations` point
    at directories; a plan written today under `docs/plans/` leaves the artifact
    "indexed" and the count unchanged, and a directory's own mtime moves when an
    entry is added or removed and never when a file two levels down is edited.
    """

    @staticmethod
    def _stale(report: dict) -> str:
        return " ".join(f for f in report["findings"] if "stale" in f)

    @requires_node
    def test_an_edited_artifact_is_a_finding(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        _stamp(repo / "AGENTS.md", EDITED_AFTER_INDEXING)
        replies = {
            **DEFAULT_REPLIES,
            "codebase_status": STATUS_COMPLETE,
            "codebase_context": CONTEXT_ALL_INDEXED,
        }
        result, report, _calls = _health_check(tmp_path, repo, replies)
        assert self._stale(report), (
            "every artifact reported indexed, one of them edited after its "
            f"index timestamp, and health-check said nothing (#225):\n{report}"
        )
        assert "agent-guidelines" in self._stale(report), self._stale(report)
        assert result.returncode == 1, result.stdout + result.stderr

    @requires_node
    def test_the_finding_is_a_defect_not_a_note(self, tmp_path: Path) -> None:
        """The severity call #220's contract made possible.

        A note is a measurement no action changes. This one is repaired by a
        named single call — `codebase_context_index` — and until it is run the
        index answers wrongly rather than emptily.
        """
        repo = _repo(tmp_path)
        _stamp(repo / "AGENTS.md", EDITED_AFTER_INDEXING)
        replies = {
            **DEFAULT_REPLIES,
            "codebase_status": STATUS_COMPLETE,
            "codebase_context": CONTEXT_ALL_INDEXED,
        }
        _, report, _calls = _health_check(tmp_path, repo, replies)
        line = next(f for f in report["findings"] if "stale" in f)
        assert not line.startswith("note: "), (
            f"a stale artifact was filed as a free statistic: {line!r}"
        )
        assert report["healthy"] is False, report

    @requires_node
    def test_the_finding_names_every_stale_artifact_and_the_count(
        self, tmp_path: Path
    ) -> None:
        """`3 stale` alone is the `2/3` problem again: it says look, not where."""
        repo = _repo(tmp_path)
        _stamp(repo / "AGENTS.md", EDITED_AFTER_INDEXING)
        _stamp(repo / "docs" / "schema.sql", EDITED_AFTER_INDEXING)
        replies = {
            **DEFAULT_REPLIES,
            "codebase_status": STATUS_COMPLETE,
            "codebase_context": CONTEXT_ALL_INDEXED,
        }
        _, report, _calls = _health_check(tmp_path, repo, replies)
        line = self._stale(report)
        assert "agent-guidelines" in line, line
        assert "database-schema" in line, line
        # schema.sql lives under ./docs/, so the directory artifact is stale too.
        assert "reference-docs" in line, line
        assert "3 stale" in line, line

    @requires_node
    def test_a_directory_is_judged_by_its_newest_descendant(
        self, tmp_path: Path
    ) -> None:
        """The observo/power-map shape: a new plan under an indexed docs tree.

        Every directory on the path is stamped OLD after the file is created,
        so an implementation that stats the artifact path itself — or that only
        looks one level down — reports this tree fresh. It is not: a plan
        written today is invisible to `codebase_context_search`, the artifact
        is still "indexed", and the count has not moved.
        """
        repo = _repo(tmp_path)
        plans = repo / "docs" / "plans" / "2026"
        plans.mkdir(parents=True)
        new_plan = plans / "2026-08-10-a-plan.md"
        new_plan.write_text("# a plan written after the last index run\n")
        _stamp(new_plan, EDITED_AFTER_INDEXING)
        for directory in (plans, repo / "docs" / "plans", repo / "docs", repo):
            _stamp(directory)
        replies = {
            **DEFAULT_REPLIES,
            "codebase_status": STATUS_COMPLETE,
            "codebase_context": CONTEXT_ALL_INDEXED,
        }
        result, report, _calls = _health_check(tmp_path, repo, replies)
        assert "reference-docs" in self._stale(report), (
            "a file added two levels under the `./docs/` artifact left it "
            f"reported fresh — the directory's own mtime is not the answer "
            f"(#225):\n{report}"
        )
        assert result.returncode == 1, result.stdout

    @requires_node
    def test_a_fresh_tree_is_silent(self, tmp_path: Path) -> None:
        """The check must not fire on every repo that has ever been indexed."""
        replies = {
            **DEFAULT_REPLIES,
            "codebase_status": STATUS_COMPLETE,
            "codebase_context": CONTEXT_ALL_INDEXED,
        }
        result, report, _calls = _health_check(tmp_path, _repo(tmp_path), replies)
        assert not self._stale(report), report
        assert result.returncode == 0, result.stdout + result.stderr

    @requires_node
    def test_an_unindexed_artifact_is_not_also_called_stale(
        self, tmp_path: Path
    ) -> None:
        """Two defects, two findings, and no double-counting.

        `reference-docs` is unindexed in this reply, so it has no index time to
        compare against and #214 already names it. Reporting it twice would
        make the stale count useless as a number.
        """
        repo = _repo(tmp_path)
        _stamp(repo / "AGENTS.md", EDITED_AFTER_INDEXING)
        _, report, _calls = _health_check(tmp_path, repo, DEFAULT_REPLIES)
        parity = " ".join(
            f
            for f in report["findings"]
            if "context artifact" in f and "stale" not in f
        )
        assert "2/3" in parity and "reference-docs" in parity, parity
        stale = self._stale(report)
        assert "agent-guidelines" in stale, stale
        assert "reference-docs" not in stale, stale
        assert "1 stale" in stale, stale

    @requires_node
    def test_an_artifact_with_no_index_time_is_not_guessed_at(
        self, tmp_path: Path
    ) -> None:
        """A loose parser must degrade to `unknown`, never to a verdict.

        If a server build stops printing the timestamp, calling every artifact
        stale would train the cohort to ignore the line — and calling every one
        fresh would rebuild the silence. Neither: say which ones could not be
        judged, in the JSON where an operator can see it.
        """
        repo = _repo(tmp_path)
        _stamp(repo / "AGENTS.md", EDITED_AFTER_INDEXING)
        untimed = CONTEXT_ALL_INDEXED.replace(
            "Status: ✓ indexed (3 chunks, 2026-08-09T04:46:35.009Z)",
            "Status: ✓ indexed",
        )
        replies = {
            **DEFAULT_REPLIES,
            "codebase_status": STATUS_COMPLETE,
            "codebase_context": untimed,
        }
        result, report, _calls = _health_check(tmp_path, repo, replies)
        assert not self._stale(report), (
            "an artifact whose index time the server did not report was called "
            f"stale on a guess:\n{report}"
        )
        assert "agent-guidelines" in report["artifacts"]["unjudged"], report
        assert result.returncode == 0, result.stdout + result.stderr

    @requires_node
    def test_the_report_carries_both_clocks(self, tmp_path: Path) -> None:
        """A name alone does not settle "is this worth a re-index".

        Thirty minutes behind and three days behind get the same sentence; the
        JSON has to carry the pair the finding was derived from.
        """
        repo = _repo(tmp_path)
        _stamp(repo / "AGENTS.md", EDITED_AFTER_INDEXING)
        replies = {
            **DEFAULT_REPLIES,
            "codebase_status": STATUS_COMPLETE,
            "codebase_context": CONTEXT_ALL_INDEXED,
        }
        _, report, _calls = _health_check(tmp_path, repo, replies)
        entry = next(
            a for a in report["artifacts"]["stale"] if a["name"] == "agent-guidelines"
        )
        assert entry["lastIndexed"].startswith("2026-08-09"), entry
        assert entry["sourceMtime"].startswith("2026-08-10"), entry

    @requires_node
    def test_a_failed_codebase_context_still_degrades_rather_than_lies(
        self, tmp_path: Path
    ) -> None:
        """No reply, no timestamps, no staleness claim in either direction."""
        repo = _repo(tmp_path)
        _stamp(repo / "AGENTS.md", EDITED_AFTER_INDEXING)
        replies = {k: v for k, v in DEFAULT_REPLIES.items() if k != "codebase_context"}
        _, report, _calls = _health_check(tmp_path, repo, replies)
        assert not self._stale(report), report
        assert report["artifacts"]["error"], report


class TestFreshnessWalkMatchesTheArtifactWalk:
    """#235/#270: the freshness clock must only be moved by content the artifact can contain.

    `newestMtimeMs` judges a directory artifact by its newest descendant, and
    until #235 it pruned exactly `node_modules` and `.git`. A `.pytest_cache/`
    rewritten by every test run moved the driver's clock, the artifact's
    `lastIndexed` did not, and health-check reported a byte-identical artifact
    stale — a finding the named remedy cannot clear, which is #220's shape one
    feature over.

    The server's walk is `dist/services/context-artifacts.js`, and what it
    excludes moved underneath us. Through **1.12.x** it globbed `**/*` with
    `dot: false` and `ignore: ["**/node_modules/**", "**/.git/**"]`, and that
    was the whole filter. Since **1.13.0** (`SocratiCode#117`) every surviving
    file also goes through `createIgnoreFilter`/`shouldIgnore`, so the walk
    additionally drops all 48 of `dist/services/ignore.js`'s
    `DEFAULT_IGNORE_PATTERNS` — `build`, `dist`, `vendor`, `coverage`,
    `*.lock`, `__pycache__` and the rest. The two surviving glob ignores are
    now a subtree-pruning optimisation over two of those defaults, which the
    server's own source says.

    That inverted the one entry #235 deliberately EXEMPTED from the prune list.
    `__pycache__` was counted on purpose, because on 1.12.x it really was
    embedded (#229 measured 32 of an artifact's 86 chunks as bytecode). On
    1.13.x it is not, so the exemption re-opened #235 through the single hole
    cut for it: a `.pyc` rewrite — a Python version bump, an edited migration —
    reports `stale`, and re-indexing cannot clear it, because the re-indexed
    content does not contain the file whose mtime moved (#270).

    The prune list is therefore a CLAIM about the server's walker, not a local
    convenience, and this class is where the two sides are pinned together.
    Every semantic here was verified against the installed server, not read off
    its source: `readArtifactContent` and `newestMtimeMs` were run over one
    46-file tree covering every pattern form and its decoys (`buildish/`,
    `distant.md`, `sitemap.xml`, a nested `sub/venv/` against the anchored
    `/venv`), and the embedded set and the counted set were identical in both
    directions. Dot exclusion applies to files as well as directories
    (`.coverage`), at every depth, but NOT to the artifact root itself — glob
    matches paths under `cwd`, so a dot-rooted artifact still embeds its plain
    contents, and the ignore chain is rooted the same way.
    """

    @staticmethod
    def _newest(target: Path) -> float | None:
        script = (
            f"import {{ newestMtimeMs }} from {json.dumps(str(DRIVER))};"
            f"process.stdout.write(JSON.stringify(newestMtimeMs("
            f"{json.dumps(str(target))})));"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    @staticmethod
    def _ms(when: str) -> float:
        return datetime.fromisoformat(when).timestamp() * 1000

    @requires_node
    def test_toolchain_cache_churn_under_a_dot_directory_is_not_stale(
        self, tmp_path: Path
    ) -> None:
        """The field case, end to end: a test run rewrote `.pytest_cache/`.

        The cache contents are stamped after the index time; every non-dot
        ancestor is restamped old afterwards, per this file's fixture
        convention, because creating an entry bumps the containing directory's
        own mtime and the property under test is the walk, not that bump.
        Nothing the artifact embeds has changed, so health-check must be
        silent: a stale finding here is repaired by no call — re-indexing
        changes nothing, because the files that moved the clock are never
        indexed (#235).
        """
        repo = _repo(tmp_path)
        cache = repo / "docs" / ".pytest_cache" / "v" / "cache"
        cache.mkdir(parents=True)
        churned = cache / "lastfailed"
        churned.write_text("{}\n")
        _stamp(churned, EDITED_AFTER_INDEXING)
        for directory in (repo / "docs", repo):
            _stamp(directory)
        replies = {
            **DEFAULT_REPLIES,
            "codebase_status": STATUS_COMPLETE,
            "codebase_context": CONTEXT_ALL_INDEXED,
        }
        result, report, _calls = _health_check(tmp_path, repo, replies)
        stale = " ".join(f for f in report["findings"] if "stale" in f)
        assert not stale, (
            "a .pytest_cache rewrite under ./docs/ produced a stale finding, "
            "but `dot: false` means the artifact never embeds it — the clock "
            f"was moved by content the artifact cannot contain (#235):\n{report}"
        )
        assert result.returncode == 0, result.stdout + result.stderr

    @requires_node
    def test_a_dot_file_is_not_counted(self, tmp_path: Path) -> None:
        """`dot: false` excludes dot FILES too, not only dot directories.

        `.coverage` is the field shape: a dot file at the artifact root,
        rewritten by every test run, never embedded.
        """
        tree = tmp_path / "tree"
        tree.mkdir()
        (tree / "a.md").write_text("a\n")
        (tree / ".coverage").write_text("sqlite\n")
        _stamp(tree / "a.md")
        _stamp(tree / ".coverage", EDITED_AFTER_INDEXING)
        _stamp(tree)
        newest = self._newest(tree)
        assert newest == pytest.approx(self._ms(SOURCE_MTIME), abs=10), (
            f"a dot file moved the freshness clock to {newest}; the server's "
            "walk never embeds it (#235)"
        )

    @requires_node
    def test_pycache_is_no_longer_counted(self, tmp_path: Path) -> None:
        """The inversion #270 is about, and the reason it needed a code change.

        `__pycache__` is not a dotfile, so `dot: false` never excluded it, and
        through 1.12.x the glob's two ignores did not name it either — it was
        embedded, and #235 exempted it from the prune list on purpose. Since
        1.13.0 the walk runs the full ignore chain and `__pycache__`/`*.pyc`
        are both in its built-in defaults, so the server embeds neither.

        Counting it now is the #235 failure re-entering through the one hole
        cut for it, and it is the strictly worse half of that failure: CPython
        rewrites a `.pyc` only when the source or magic number changes, so this
        stays quiet until a Python version bump or an edited migration, then
        reports `stale` on an artifact whose embedded content did not change —
        with a remedy that cannot clear it.
        """
        tree = tmp_path / "tree"
        (tree / "__pycache__").mkdir(parents=True)
        (tree / "a.py").write_text("pass\n")
        bytecode = tree / "__pycache__" / "a.cpython-312.pyc"
        bytecode.write_bytes(b"\x00")
        _stamp(tree / "a.py")
        _stamp(bytecode, EDITED_AFTER_INDEXING)
        _stamp(tree / "__pycache__")
        _stamp(tree)
        newest = self._newest(tree)
        assert newest == pytest.approx(self._ms(SOURCE_MTIME), abs=10), (
            f"a __pycache__ rewrite moved the freshness clock (got {newest}); "
            "since socraticode 1.13.0 the artifact walk runs the ignore chain "
            "and `__pycache__`/`*.pyc` are built-in defaults, so the server "
            "embeds neither and this is a stale finding no re-index can clear "
            "(#270)"
        )

    @requires_node
    def test_a_loose_pyc_outside_pycache_is_not_counted_either(
        self, tmp_path: Path
    ) -> None:
        """`*.pyc` is its own default pattern, not a consequence of the dirname.

        Pinned separately because the one-line fix this finding invited — add
        `__pycache__` to the prune list — passes the test above and fails this
        one. The suffix patterns are half the list.
        """
        tree = tmp_path / "tree"
        tree.mkdir()
        (tree / "a.py").write_text("pass\n")
        loose = tree / "a.cpython-312.pyc"
        loose.write_bytes(b"\x00")
        _stamp(tree / "a.py")
        _stamp(loose, EDITED_AFTER_INDEXING)
        _stamp(tree)
        newest = self._newest(tree)
        assert newest == pytest.approx(self._ms(SOURCE_MTIME), abs=10), (
            f"a loose .pyc moved the freshness clock (got {newest}); `*.pyc` "
            "is a default ignore pattern in its own right (#270)"
        )

    @requires_node
    def test_a_build_directory_is_not_counted(self, tmp_path: Path) -> None:
        """The class #270 opens beyond the bytecode case.

        `build` is a default ignore pattern at any depth, so a `./docs/`
        artifact over a Sphinx `docs/build/` is the same false `stale` with a
        different name — and there are a dozen more (`dist`, `out`, `target`,
        `coverage`, `vendor`, `_build`, `deps`, `obj`, `.tox`). Fixing only the
        measured case would have left every one of them open.
        """
        tree = tmp_path / "tree"
        (tree / "build" / "html").mkdir(parents=True)
        (tree / "index.rst").write_text("doc\n")
        generated = tree / "build" / "html" / "index.html"
        generated.write_text("<html>\n")
        _stamp(tree / "index.rst")
        _stamp(generated, EDITED_AFTER_INDEXING)
        for directory in (tree / "build" / "html", tree / "build", tree):
            _stamp(directory)
        newest = self._newest(tree)
        assert newest == pytest.approx(self._ms(SOURCE_MTIME), abs=10), (
            f"a build/ rewrite moved the freshness clock (got {newest}); "
            "`build` is one of the server's built-in ignore defaults and is "
            "never embedded (#270)"
        )

    @requires_node
    def test_a_log_file_is_not_counted(self, tmp_path: Path) -> None:
        """A suffix pattern with no directory to prune — the other match form."""
        tree = tmp_path / "tree"
        tree.mkdir()
        (tree / "a.md").write_text("a\n")
        churned = tree / "run.log"
        churned.write_text("line\n")
        _stamp(tree / "a.md")
        _stamp(churned, EDITED_AFTER_INDEXING)
        _stamp(tree)
        newest = self._newest(tree)
        assert newest == pytest.approx(self._ms(SOURCE_MTIME), abs=10), (
            f"a *.log rewrite moved the freshness clock (got {newest}); "
            "`*.log` is a built-in ignore default (#270)"
        )

    @requires_node
    def test_venv_is_anchored_to_the_artifact_root(self, tmp_path: Path) -> None:
        """`/venv` is anchored, and the anchoring is load-bearing both ways.

        The server anchors `venv` and `env` deliberately: unanchored they match
        ordinary module names and delete real source (`clap_complete/src/env/`,
        per `ignore.js`'s own comment). So a nested `sub/venv/` IS embedded and
        MUST still be counted — an over-eager prune that treated the name as
        any-depth would under-report real staleness. Verified against the
        server: it embeds `sub/venv/lib/a.py` and not `venv/lib/a.py`.
        """
        tree = tmp_path / "tree"
        (tree / "venv" / "lib").mkdir(parents=True)
        (tree / "sub" / "venv" / "lib").mkdir(parents=True)
        (tree / "a.py").write_text("pass\n")
        rooted = tree / "venv" / "lib" / "dep.py"
        rooted.write_text("dep\n")
        _stamp(tree / "a.py")
        _stamp(rooted, EDITED_AFTER_INDEXING)
        # Every directory, deepest first — `sub/` and `sub/venv/` are counted
        # (that is the second half of this test), so leaving them at their
        # creation time would measure the fixture instead of the walk.
        directories = (
            tree / "venv" / "lib",
            tree / "venv",
            tree / "sub" / "venv" / "lib",
            tree / "sub" / "venv",
            tree / "sub",
            tree,
        )
        for directory in directories:
            _stamp(directory)
        assert self._newest(tree) == pytest.approx(self._ms(SOURCE_MTIME), abs=10), (
            "a root-level venv/ moved the freshness clock; `/venv` is an "
            "anchored ignore default (#270)"
        )

        nested = tree / "sub" / "venv" / "lib" / "mod.py"
        nested.write_text("mod\n")
        _stamp(nested, EDITED_AFTER_INDEXING)
        for directory in directories:
            _stamp(directory)
        assert self._newest(tree) == pytest.approx(
            self._ms(EDITED_AFTER_INDEXING), abs=10
        ), (
            "a NESTED venv/ stopped moving the freshness clock; `/venv` is "
            "anchored to the artifact root, so the server still embeds "
            "sub/venv/ and a prune that matched the bare name at any depth "
            "would hide real staleness (#270)"
        )

    @requires_node
    def test_an_ordinary_name_that_merely_starts_with_one_is_kept(
        self, tmp_path: Path
    ) -> None:
        """The decoys: `buildish/`, `distant.md`, `sitemap.xml`.

        A prune written with `startsWith`/`includes` rather than whole-segment
        and whole-suffix matching passes every test above and silently stops
        reporting staleness for ordinary files. Verified against the server:
        all three are embedded.
        """
        tree = tmp_path / "tree"
        (tree / "buildish").mkdir(parents=True)
        for name in ("distant.md", "sitemap.xml"):
            (tree / name).write_text("x\n")
        (tree / "buildish" / "real.md").write_text("x\n")
        _stamp(tree / "distant.md")
        _stamp(tree / "sitemap.xml")
        _stamp(tree / "buildish" / "real.md", EDITED_AFTER_INDEXING)
        for directory in (tree / "buildish", tree):
            _stamp(directory)
        newest = self._newest(tree)
        assert newest == pytest.approx(self._ms(EDITED_AFTER_INDEXING), abs=10), (
            f"`buildish/` was pruned as if it were `build` (got {newest}); the "
            "ignore defaults match whole path segments and whole suffixes, and "
            "a substring prune hides real staleness (#270)"
        )

    @requires_node
    def test_a_dot_rooted_artifact_is_still_judged(self, tmp_path: Path) -> None:
        """The root is exempt from the dot rule, on both sides.

        glob's `dot: false` filters the matched path segments UNDER `cwd`,
        never `cwd` itself — verified: an artifact pointing at `./.claude/`
        embeds `file.md` and `sub/deep.md`. So the walk must visit a dot-named
        target unconditionally and only skip dot ENTRIES, or a dot-rooted
        artifact would be reported eternally fresh.
        """
        root = tmp_path / ".claude"
        (root / "sub").mkdir(parents=True)
        deep = root / "sub" / "deep.md"
        deep.write_text("d\n")
        _stamp(deep, EDITED_AFTER_INDEXING)
        _stamp(root / "sub")
        _stamp(root)
        newest = self._newest(root)
        assert newest == pytest.approx(self._ms(EDITED_AFTER_INDEXING), abs=10), (
            f"a dot-named artifact root was skipped or its descendants ignored "
            f"(got {newest}); glob exempts the cwd from `dot: false`, and the "
            "walk must match (#235)"
        )

    @requires_node
    def test_node_modules_and_git_are_still_pruned(self, tmp_path: Path) -> None:
        """The other half of the parity claim: the server's explicit ignores.

        `.git` is doubly excluded now (ignore list and dot rule); pinning it
        keeps the pair honest if the dot rule is ever reworked.
        """
        tree = tmp_path / "tree"
        (tree / "node_modules" / "pkg").mkdir(parents=True)
        (tree / ".git").mkdir()
        (tree / "a.md").write_text("a\n")
        vendored = tree / "node_modules" / "pkg" / "index.js"
        vendored.write_text("x\n")
        gitfile = tree / ".git" / "index"
        gitfile.write_text("x\n")
        _stamp(tree / "a.md")
        for churned in (vendored, gitfile):
            _stamp(churned, EDITED_AFTER_INDEXING)
        for directory in (
            tree / "node_modules" / "pkg",
            tree / "node_modules",
            tree / ".git",
            tree,
        ):
            _stamp(directory)
        newest = self._newest(tree)
        assert newest == pytest.approx(self._ms(SOURCE_MTIME), abs=10), (
            f"node_modules or .git moved the freshness clock (got {newest}); "
            "the server ignores both (#235)"
        )

    def test_the_prune_site_names_the_server_walker(self) -> None:
        """The list is a claim about two server files, and must say so.

        The next editor of either side needs to know the walk is not a local
        style choice: it mirrors `dot: false` from the artifact walk plus the
        default patterns from the ignore chain, and drifting from it re-opens
        #235. A source pin, not a behavior — the behaviors are the tests above.

        `ignore.js` is named as well as `context-artifacts.js` because #270 is
        what happens when only one of the two is watched: the driver's comment
        pinned the glob call exactly, stayed accurate about it, and went stale
        anyway when the filter moved into the file it did not mention.
        """
        source = DRIVER.read_text()
        region = source[source.index("// PARITY, not preference") :]
        region = region[: region.index("\n// Asymmetric on purpose")]
        for pointer in ("context-artifacts.js", "ignore.js", "dot: false"):
            assert pointer in region, (
                f"newestMtimeMs's prune list no longer names {pointer!r}; "
                "without the pointer, the parity looks like a style choice and "
                "drifts (#235, #270)"
            )

    def test_the_prune_site_pins_the_server_version(self) -> None:
        """The habit that made #270 findable, kept.

        The old comment said "socraticode 1.12.0" against a behaviour that
        changed in 1.13.0, which is the only reason the drift could be spotted
        by reading rather than by a user hitting it. An unversioned claim about
        another project's internals cannot be audited.
        """
        source = DRIVER.read_text()
        region = source[source.index("// PARITY, not preference") :]
        region = region[: region.index("\n// Asymmetric on purpose")]
        assert "1.13" in region, (
            "newestMtimeMs's prune list no longer pins the socraticode version "
            "it was transcribed from. That pin is what let #270 be found by "
            "reading the server's source instead of by a false stale finding "
            "in the field (#270)"
        )

    def test_the_residual_layers_are_named_not_left_to_be_rediscovered(
        self,
    ) -> None:
        """What the driver deliberately does NOT mirror, said out loud.

        Mirroring the defaults was a judgement call: the chain's other two
        layers — artifact-local `.gitignore`/`.socraticodeignore`, and
        virtualenvs found by marker — need a gitignore engine and a marker
        scan, and this driver has no dependencies. That is a defensible trade
        and an indefensible silence. A reader who hits the residual false
        `stale` and finds no acknowledgement of it will either re-derive the
        whole chain or distrust the check.
        """
        source = DRIVER.read_text()
        region = source[source.index("// THE RESIDUAL") :]
        region = region[: region.index("function newestMtimeMs")]
        lowered = region.lower()
        for token in (".gitignore", ".socraticodeignore", "pyvenv.cfg"):
            assert token in lowered, (
                f"the prune site no longer names {token!r} as a layer of the "
                "server's ignore chain that this walk does not mirror; the "
                "residual false `stale` it can still produce then looks like a "
                "bug rather than a stated limit (#270)"
            )

    @requires_node
    def test_the_transcribed_defaults_match_the_servers_list(self) -> None:
        """The transcription is the whole fix, so pin its shape.

        Not a copy of the server's array — that would only restate this file's
        own guess. What is pinned is that the list is present, complete enough
        to cover every form the server uses, and parsed into the three buckets
        the walk consults. The list's agreement with a running 1.13.2 server
        was established by differential test (see the class docstring); this
        keeps an editor from quietly dropping entries from it afterwards.
        """
        script = (
            f"import {{ SERVER_DEFAULT_IGNORE_PATTERNS as p }} from "
            f"{json.dumps(str(DRIVER))};"
            f"process.stdout.write(JSON.stringify(p));"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert result.returncode == 0, result.stderr
        patterns = json.loads(result.stdout)
        assert len(patterns) == 48, (
            f"the transcribed default-ignore list has {len(patterns)} entries, "
            "not the 48 in socraticode 1.13.2's DEFAULT_IGNORE_PATTERNS. If the "
            "server's list changed, re-transcribe it and re-run the "
            "differential check; if an entry was dropped by hand, #235 is open "
            "again for that name (#270)"
        )
        # One representative of each pattern form the walk has to handle.
        for pattern in ("__pycache__", "*.pyc", "build", "/venv", "bin/Debug"):
            assert pattern in patterns, (
                f"{pattern!r} is missing from the transcribed defaults; the "
                "walk's three buckets are derived from this list, so a dropped "
                "entry silently stops pruning (#270)"
            )


class TestParsesTheIndexTimestamp:
    """The freshness half of the same reply #214 already reads."""

    @staticmethod
    def _parse(text: str) -> list:
        script = (
            f"import {{ parseContextArtifacts }} from {json.dumps(str(DRIVER))};"
            f"process.stdout.write(JSON.stringify(parseContextArtifacts("
            f"{json.dumps(text)})));"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    @requires_node
    def test_the_status_line_yields_the_index_time(self) -> None:
        parsed = self._parse(CONTEXT_LISTING)
        assert parsed[0]["lastIndexed"] == "2026-08-09T04:46:34.264Z", parsed[0]
        assert parsed[1]["lastIndexed"] is None, (
            f"an unindexed artifact has no index time to report: {parsed[1]}"
        )

    @requires_node
    def test_the_source_path_comes_with_it(self) -> None:
        """Freshness needs the path, and the manifest is not keyed by name here."""
        parsed = self._parse(CONTEXT_LISTING)
        assert [a["path"] for a in parsed] == [
            "./docs/schema.sql",
            "./docs/",
            "./AGENTS.md",
        ], parsed


class TestArtifactsRefExplainsTheIgnoreChain:
    """#229 then #270: the same bullets, once the server grew the filter.

    `references/context-artifacts.md` used to say a directory artifact honours
    no ignore file, that its binary guard was present but could not fire, and
    that adding `__pycache__` to `.socraticodeignore` changed nothing. All
    three were measured and true on `socraticode@1.12.0`, and all three are
    false on 1.13.x: `SocratiCode#117` — the upstream fix for the bug #229
    filed — put `createIgnoreFilter`/`shouldIgnore` and a real `isBinaryContent`
    sniff behind the artifact walk.

    So this class is the same shape it was, aimed at the corrected claims. Two
    things it now insists on that the old version could not:

    The **rooting** is the non-obvious half and the half a reader gets wrong.
    The chain is built with the ARTIFACT path, not the project path, so the
    repo-root `.socraticodeignore` that Phase 4 writes does not reach a subtree
    artifact at all. "Directory artifacts honour `.socraticodeignore` now" is
    the natural summary of #117 and is wrong in exactly the case the docs are
    about; measured on 1.13.2, `*.sql` in a repo-root `.socraticodeignore` left
    a `versions/` artifact still embedding its `.sql`.

    The **cost direction reverses**. Every earlier finding here was about an
    artifact absorbing content it should not. The defaults now apply inside an
    artifact, so the new failure is content going MISSING — a `./docs/`
    artifact silently losing a Sphinx `docs/build/` — and it fails just as
    quietly, with a chunk count that is merely lower than expected.

    Scoped to **Field notes** rather than to the whole document, for the reason
    `test_the_note_covers_the_third_diagnosis` learned one file over: a
    doc-wide keyword sweep can be green before the prose it requires is
    written.
    """

    @staticmethod
    def _field_notes() -> str:
        text = ARTIFACTS_REF.read_text()
        start = text.index("## Field notes")
        end = text.find("\n## ", start + len("## Field notes"))
        return text[start : end if end != -1 else len(text)]

    @staticmethod
    def _bullet(opening: str) -> str:
        """One `- ` bullet of **Field notes**, from `opening` to the next bullet.

        Section scope is too coarse for a claim whose own bullet header already
        contains the keyword. `test_the_freshness_interaction_is_covered` pinned
        `"stale"` against the whole section and was VACUOUS on arrival: the
        bullet opens *"…makes the health-check say `stale`"*, so the header
        alone satisfied it and the ordering advice underneath — the one thing in
        this doc neither source issue knew — could be deleted with the suite
        green. Proved by mutation in #230's CR round 2, not by reading.

        This is the granularity `TestGeneratedDocExplainsTheSymptom` arrived at
        one class down, for the same reason and in its own words: "a section-wide
        pin would have been green before the prose it is meant to require was
        written."

        The missing-opening case is asserted rather than left to `str.index`,
        because a reworded bullet header is the likeliest way this ever fails
        and `ValueError: substring not found` would raise from here — throwing
        away the caller's message, which is the part that explains what the
        bullet has to say (#230 CR round 3).
        """
        notes = TestArtifactsRefExplainsTheIgnoreChain._field_notes()
        assert opening in notes, (
            f"references/{ARTIFACTS_REF.name}'s **Field notes** has no bullet "
            f"opening {opening!r}. If the bullet was reworded, re-aim this "
            "call; if it was deleted, the caller's assertion is what tells you "
            "what it was for."
        )
        start = notes.index(opening)
        end = notes.find("\n- ", start + len(opening))
        return notes[start : end if end != -1 else len(notes)]

    def test_the_chain_is_stated_with_its_version_boundary(self) -> None:
        """Both halves, because consumers run both server versions.

        A flat "artifacts honour the ignore chain" is as wrong for a 1.12.x
        reader as the old text is for a 1.13.x one, and this doc is vendored
        into repos that pin different servers. The boundary is the fact.

        Scoped to the bullet, not the section, and the section-wide version was
        VACUOUS on arrival exactly as `_bullet` warns: other bullets cite
        `1.13.2` and `1.12.x` for their own measurements, so deleting the
        boundary from the bullet that states the rule left the suite green.
        Proved by mutation, not by reading.
        """
        bullet = self._bullet("- **A directory artifact runs the ignore chain")
        assert "1.13" in bullet and "1.12" in bullet, (
            f"references/{ARTIFACTS_REF.name}'s **Field notes** states the "
            "artifact walk's ignore behaviour without the version boundary. "
            "It changed in socraticode 1.13.0 (SocratiCode#117); a reader on "
            "either side of that needs to know which half applies (#270)"
        )
        lowered = bullet.lower()
        assert "createignorefilter" in lowered or "ignore chain" in lowered, (
            f"references/{ARTIFACTS_REF.name}'s **Field notes** no longer says "
            "a directory artifact runs the ignore chain at all — the correction "
            "#270 is about (#270)"
        )

    def test_the_chain_is_rooted_at_the_artifact_not_the_repo(self) -> None:
        """The correction inside the correction.

        Phase 4 writes `.socraticodeignore` at the repo root, and this document
        is where an author looks to find out whether it governs their artifact.
        For a subtree artifact it does not — `createIgnoreFilter` is called with
        the artifact path. Saying only "artifacts honour `.socraticodeignore`
        now" would send a reader to edit the one file that cannot help them.
        """
        notes = self._field_notes().lower()
        assert "rooted at the artifact" in notes, (
            f"references/{ARTIFACTS_REF.name}'s **Field notes** does not say "
            "the ignore chain is rooted at the ARTIFACT directory rather than "
            "the repo. Without it, the natural reading of SocratiCode#117 is "
            "that the repo-root `.socraticodeignore` now filters artifacts — "
            "which is false for every artifact that is not the repo root, and "
            "is the case this doc's own example uses (#270)"
        )
        assert "repo-root" in notes or "repo root" in notes, (
            f"references/{ARTIFACTS_REF.name}'s **Field notes** states the "
            "rooting rule abstractly but never says what it means for the "
            "repo-root `.socraticodeignore` Phase 4 writes (#270)"
        )

    def test_the_defaults_can_now_drop_content_you_wanted(self) -> None:
        """The new hazard, which points the opposite way from the old one.

        Everything this class pinned before #270 was about an artifact
        absorbing junk. The defaults applying inside an artifact is the mirror
        image — `docs/build/`, a directory of `*.lock` fixtures — and it is
        just as silent. A doc that only announces the good news leaves the
        reader with no account of a chunk count lower than they expected.
        """
        notes = self._field_notes()
        assert "DEFAULT_IGNORE_PATTERNS" in notes or "built-in defaults" in notes, (
            f"references/{ARTIFACTS_REF.name}'s **Field notes** does not name "
            "the built-in default patterns that now apply INSIDE an artifact "
            "(#270)"
        )
        bullet = self._bullet("- **The built-in defaults now apply INSIDE").lower()
        assert "check the artifact subtree" in bullet, (
            f"references/{ARTIFACTS_REF.name}'s **Field notes** names the "
            "defaults without telling the reader to check their artifact "
            "subtree for names the defaults drop. The failure is silent — no "
            "error, nothing above debug, only a chunk count lower than "
            "expected — so the instruction to go look IS the mitigation (#270)"
        )

    def test_the_binary_guard_history_is_kept_with_its_resolution(self) -> None:
        """Retire the claim, keep the mechanism.

        The `readFile(…, "utf-8")` trap is why the bug existed and is a real
        hazard in anyone's own code, so the paragraph is worth keeping — but a
        reader must not leave believing it still describes the running server.
        Deleting it outright would also strand #229's measured numbers, which
        are the evidence for the 1.12.x half of the version boundary above.
        """
        bullet = self._bullet("- **The binary guard works now").lower()
        assert "u+fffd" in bullet and "readfile" in bullet, (
            f"references/{ARTIFACTS_REF.name}'s **Field notes** dropped the "
            "mechanism behind the old bytecode hazard. It is why a guard that "
            "looks present could not fire, and it is a trap a reader can "
            "reproduce in their own code (#229)"
        )
        assert "isbinarycontent" in bullet, (
            f"references/{ARTIFACTS_REF.name}'s **Field notes** describes the "
            "guard that could not fire without naming the one that replaced "
            "it. `isBinaryContent` over a Buffer is what makes the 1.13.x half "
            "of the claim checkable (#270)"
        )

    def test_the_freshness_parity_and_its_residual_are_covered(self) -> None:
        """#225's walk had to move with the server, and did not move all the way.

        The old bullet's advice was an ORDERING — clear the build output, then
        re-index — because re-indexing re-embedded the bytecode. That is gone:
        the server excludes it, and the driver no longer counts it (#270). What
        replaces it is narrower and must be stated, because it is the one case
        where a `stale` finding should be dismissed rather than acted on.
        """
        bullet = self._bullet("- **Staleness parity").lower()
        assert "#270" in bullet or "transcribed" in bullet, (
            f"references/{ARTIFACTS_REF.name}'s **Field notes** no longer says "
            "the driver's freshness walk mirrors the server's exclusions. That "
            "parity is the reason a stale finding can be trusted at all (#235)"
        )
        assert "residual" in bullet or "does **not** mirror" in bullet, (
            f"references/{ARTIFACTS_REF.name}'s **Field notes** claims the "
            "freshness walk matches the server without naming what it does "
            "not mirror — artifact-local ignore files and marker-found "
            "virtualenvs. A reader who hits that false `stale` has no way to "
            "know it is a stated limit rather than a bug (#270)"
        )


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
        return text[start : end if end != -1 else len(text)]

    @classmethod
    def _context_search_note(cls) -> str:
        """Just the `codebase_context_search` bullet, to the next one."""
        notes = cls._per_tool_notes()
        start = notes.index("- **`codebase_context_search`**")
        end = notes.find("\n- ", start)
        return notes[start : end if end != -1 else len(notes)]

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

    def test_the_note_covers_the_third_diagnosis(self) -> None:
        """A WRONG answer, not a missing one (#225).

        The two documented diagnoses both end in `codebase_context_search`
        returning nothing, so a reader who *got* an answer stops reading. The
        third case gives them a confident answer off superseded chunks, and it
        is the one they will not think to check.

        Scoped to the `codebase_context_search` bullet on purpose. Searching the
        whole section for "stale" already matches the `codebase_impact` bullet's
        "if the graph is stale or low-yield" — a different tool and a different
        failure — so a section-wide pin would have been green before the prose
        it is meant to require was written.
        """
        notes = self._context_search_note().lower()
        assert "stale" in notes, (
            f"references/{DOC_REF.name}'s **Per-tool notes** explains an empty "
            "`codebase_context_search` two ways and never mentions the third "
            "shape: the artifact is indexed, the answer arrives, and it is out "
            "of date. Three of observo's fourteen artifacts were in that state "
            "while the check reported 14/14 (#225)."
        )
