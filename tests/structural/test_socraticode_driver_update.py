"""`mcp-driver.mjs update` runs `codebase_update` through the driver's launch (#483).

A host following the policy block runs `codebase_update` in the same change as
a context-manifest `description` edit, and must cap every SocratiCode launch:
uncapped, one cost a host 58 minutes of its bus (CannObserv/replicator#94). From
a post-merge host step there is no session server to call, and the driver had
no `update`, so CannObserv/replicator#153 wrote a throwaway shim over
`withClient` to get the pinned launch and the cap. Every host would have had to
reinvent it.

What the subcommand owes, each a test here:

- **The driver's terms for its server** — auto-resume off and the watcher on
  manual, as `index` has them since #349: a server launched to update and exit
  must not stay to keep the index current.
- **The store gate** — a launch is a write, so it refuses the wrong store as
  `index` does.
- **The counts it re-indexed**, as JSON on stdout.
- **Non-zero when it did not run.** SocratiCode 1.16.1's `codebase_update`
  takes the project's index lock non-reentrantly and, when another process
  holds it, *returns* "Updated project index" with zero counts and "Another
  process is already indexing this project, skipping" among its progress lines
  (`indexer.js` `updateProjectIndex`). Read as success, that is an update that
  never ran (the case CannObserv/replicator#135 met).
"""

import json
from pathlib import Path

from .test_socraticode_external_store import (
    _config,
    _driver,
    _launch_marker,
    _project,
)
from .test_socraticode_graph_yield import DRIVER, SKILL_MD, requires_node

# A stub server that records its environment and every tool call, and answers
# from STUB_REPLIES. A local copy, as the other suites keep theirs.
RECORDING_SERVER = """
import { readFileSync, writeFileSync, appendFileSync } from 'node:fs';
writeFileSync(process.env.STUB_ENV_OUT, JSON.stringify({
  autoResume: process.env.SOCRATICODE_AUTO_RESUME ?? null,
  watcher: process.env.SOCRATICODE_WATCHER ?? null,
}));
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
    appendFileSync(process.env.STUB_CALLS, JSON.stringify(msg.params) + '\\n');
    const text = replies[msg.params.name];
    if (text == null) {
      send({ jsonrpc: '2.0', id: msg.id, error: { message: `stub: no reply for ${msg.params.name}` } });
      continue;
    }
    send({ jsonrpc: '2.0', id: msg.id, result: { content: [{ type: 'text', text }] } });
  }
});
"""

# index-tools.js `codebase_update`, 1.16.1, for a run that took the lock.
UPDATED = """Updated project index: /repo
Added: 1
Updated: 3
Removed: 2
New chunks: 17

Progress:
Scanning files...
Indexed 4 changed file(s)"""

# The same reply when another process holds the index lock: the counts are
# zero because nothing ran, and only a progress line says so.
LOCK_HELD = """Updated project index: /repo
Added: 0
Updated: 0
Removed: 0
New chunks: 0

Progress:
Another process is already indexing this project, skipping"""

# A run in this server already holds the project (formatIndexingInProgressMessage).
IN_PROGRESS = """⚠ Indexing is already in progress for: /repo
Cannot run codebase_update — please wait for the current operation to finish.

Operation: Full index
Phase: embedding

Use codebase_status to check current indexing state."""

# A git-targeted run reports its skip in the headline instead.
SKIPPED = """Index update skipped: Another process is already indexing this project, skipping
Added: 0
Updated: 0
Removed: 0
New chunks: 0"""

# A reclamation barrier on the project's identity: the other early return in
# updateProjectIndex, zero counts again, the refusal only among the progress.
RECLAIMED = """Updated project index: /repo
Added: 0
Updated: 0
Removed: 0
New chunks: 0

Progress:
Refusing to index: identity broker is being reclaimed"""

DOCKER_DOWN = """❌ Docker is not available.

SocratiCode requires Docker to manage the Qdrant container."""


def _update(tmp_path: Path, reply: str) -> tuple:
    project = _project(tmp_path)
    _config(project, {"projectId": "broker"})
    stub = tmp_path / "recording-server.mjs"
    stub.write_text(RECORDING_SERVER)
    replies = tmp_path / "replies.json"
    replies.write_text(json.dumps({"codebase_update": reply}))
    env_out = tmp_path / "server-env.json"
    calls = tmp_path / "calls.jsonl"
    result = _driver(
        project,
        "update",
        SOCRATICODE_ENTRY=str(stub),
        STUB_REPLIES=str(replies),
        STUB_ENV_OUT=str(env_out),
        STUB_CALLS=str(calls),
    )
    seen = json.loads(env_out.read_text()) if env_out.exists() else None
    made = (
        [json.loads(ln) for ln in calls.read_text().splitlines()]
        if calls.exists()
        else []
    )
    return result, project, seen, made


class TestTheUpdateRuns:
    @requires_node
    def test_it_calls_codebase_update_once_for_the_project(
        self, tmp_path: Path
    ) -> None:
        result, project, _, made = _update(tmp_path, UPDATED)
        assert result.returncode == 0, result.stderr
        assert made == [
            {"name": "codebase_update", "arguments": {"projectPath": str(project)}}
        ], made

    @requires_node
    def test_its_server_neither_resumes_nor_watches(self, tmp_path: Path) -> None:
        result, _, seen, _ = _update(tmp_path, UPDATED)
        assert seen == {"autoResume": "off", "watcher": "manual"}, (
            "the update's server must index and exit, not stay to keep the "
            f"index current (#349, #483): {seen}\n{result.stderr}"
        )

    @requires_node
    def test_it_reports_what_it_re_indexed(self, tmp_path: Path) -> None:
        result, project, _, _ = _update(tmp_path, UPDATED)
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report == {
            "projectPath": str(project),
            "ran": True,
            "added": 1,
            "updated": 3,
            "removed": 2,
            "chunksCreated": 17,
        }, report
        assert "1 added, 3 updated, 2 removed, 17 new chunk(s)" in result.stderr, (
            result.stderr
        )


class TestAnUpdateThatDidNotRunFails:
    @requires_node
    def test_a_lock_held_elsewhere_is_not_a_success(self, tmp_path: Path) -> None:
        result, _, _, _ = _update(tmp_path, LOCK_HELD)
        assert result.returncode == 1, (
            "codebase_update skipped under another process's lock and the "
            f"driver reported success (#483)\n{result.stderr}"
        )
        assert json.loads(result.stdout)["ran"] is False, result.stdout
        assert "another process holds this project's index lock" in result.stderr, (
            result.stderr
        )

    @requires_node
    def test_a_git_targeted_skip_is_not_a_success(self, tmp_path: Path) -> None:
        result, _, _, _ = _update(tmp_path, SKIPPED)
        assert result.returncode == 1, result.stderr
        assert "another process holds this project's index lock" in result.stderr, (
            result.stderr
        )

    @requires_node
    def test_a_run_already_in_progress_is_not_a_success(self, tmp_path: Path) -> None:
        result, _, _, _ = _update(tmp_path, IN_PROGRESS)
        assert result.returncode == 1, result.stderr
        assert "already in progress" in result.stderr, result.stderr

    @requires_node
    def test_a_reclamation_refusal_is_not_a_success(self, tmp_path: Path) -> None:
        """CR 1088: the same headline and zero counts as a run that found
        nothing to change."""
        result, _, _, _ = _update(tmp_path, RECLAIMED)
        assert result.returncode == 1, result.stderr
        assert json.loads(result.stdout)["ran"] is False, result.stdout
        assert "Refusing to index" in result.stderr, result.stderr

    @requires_node
    def test_any_other_reply_fails_with_the_reply(self, tmp_path: Path) -> None:
        result, _, _, _ = _update(tmp_path, DOCKER_DOWN)
        assert result.returncode == 1, result.stderr
        assert "Docker is not available" in result.stderr, result.stderr


class TestTheUpdateIsGatedAndNamed:
    @requires_node
    def test_it_refuses_the_wrong_store(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        entry, marker = _launch_marker(tmp_path)
        result = _driver(
            project, "update", QDRANT_MODE="external", SOCRATICODE_ENTRY=str(entry)
        )
        assert result.returncode == 1, result.stderr
        assert "refusing to launch a server" in result.stderr, result.stderr
        assert not marker.exists(), "update launched a server into the wrong store"

    def test_the_usage_names_it(self) -> None:
        usage = DRIVER.read_text()
        start = usage.index("const USAGE = `")
        block = usage[start : usage.index("`;", start)]
        assert "\n  update   " in block, "mcp-driver.mjs's usage does not list `update`"

    def test_skill_md_names_it_where_it_prescribes_codebase_update(self) -> None:
        text = " ".join(SKILL_MD.read_text().split())
        assert 'mcp-driver.mjs" update' in text, (
            "SKILL.md prescribes codebase_update for a stale artifact without "
            "naming the capped path outside a session (#483)"
        )
