"""A link that resolves can still be wasted disk, or search nothing (#573).

#281 made a configured link that does not resolve a finding. Two states pass
that check and still deserve a line from the daily hook, from
CannObserv/index#32's setup checks:

- **A full clone where a stub would do.** On an external store a linked
  sibling is read for its `.socraticode.json` alone — the path only selects
  the collection — so a whole checkout there is disk spent for nothing. Not on
  a managed store, where the sibling must be a checkout this host indexed, and
  not where the sibling carries its own SocratiCode manifest: one host can be
  the home of both repos.
- **A link whose collection is missing or empty.** It contributes nothing to
  `codebase_search` with `includeLinked: true`, and upstream says nothing.

Both are DEFECTS: `socraticode-health.sh` prints only when the driver exits
non-zero, so a note would never reach the session. Each is one line, and
silent when there is nothing to fix.

The collection read is one read-only `points/count` per resolved link, on the
store and with the environment the server was launched with — the route #333's
artifact counts take. The id is upstream's `effectiveBaseProjectId()`
(socraticode 1.16.2 `dist/config.js:186`, read by `resolveLinkedCollections()`
at `:365`): the sibling's own `.socraticode.json` `projectId`, else the sha256
of its resolved path — never `SOCRATICODE_PROJECT_ID`, never a branch suffix.
"""

import hashlib
import json
import socket
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .test_context_artifact_parity import (
    CONTEXT_ALL_INDEXED,
    DEFAULT_REPLIES,
    DRIVER,
    STATUS_COMPLETE,
    _clean_env,
    _listed_chunks,
    _repo,
    _run_health_check,
    requires_node,
)

SKILL_DIR = DRIVER.parent.parent
HOOK = SKILL_DIR / "scripts" / "socraticode-health.sh"
LINKED_REF = SKILL_DIR / "references" / "linked-projects.md"

REPLIES = {
    **DEFAULT_REPLIES,
    "codebase_status": STATUS_COMPLETE,
    "codebase_context": CONTEXT_ALL_INDEXED,
}
ARTIFACT_POINTS = _listed_chunks(CONTEXT_ALL_INDEXED)

CLONE = "a full checkout where a one-file stub would do"
NOTHING = "nothing to codebase_search with includeLinked"
NOT_COUNTED = "linked collections not counted in the store"


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def _store(collections: dict) -> Iterator[tuple[int, list]]:
    """A Qdrant answering the counts health-check makes.

    A filtered count is an artifact count (#333), answered from the listing so
    the fixture tests links and not artifact parity. An unfiltered one is a
    collection count: `collections` maps a name to its points, and a name it
    lacks is Qdrant's own 404, whose wording names the collection.
    """
    received: list = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 — http.server's spelling
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append({"path": self.path, "body": body})
            if not self.path.endswith("/points/count"):
                self._send(200, {"result": []})
                return
            if "filter" in body:
                name = body["filter"]["must"][0]["match"]["value"]
                self._send(200, {"result": {"count": ARTIFACT_POINTS.get(name, 0)}})
                return
            collection = self.path.split("/")[2]
            if collection not in collections:
                error = f"Not found: Collection `{collection}` doesn't exist!"
                self._send(404, {"status": {"error": error}})
                return
            self._send(200, {"result": {"count": collections[collection]}})

        def _send(self, status: int, payload: dict) -> None:
            reply = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *_args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_address[1], received
    finally:
        server.shutdown()
        server.server_close()


def _project(tmp_path: Path, links: list[str], project_id: str = "index") -> Path:
    repo = _repo(tmp_path)
    (repo / ".socraticode.json").write_text(
        json.dumps({"projectId": project_id, "linkedProjects": links})
    )
    return repo


def _stub(tmp_path: Path, name: str, project_id: str | None = None) -> Path:
    sibling = tmp_path / name
    sibling.mkdir()
    (sibling / ".socraticode.json").write_text(
        json.dumps({"projectId": project_id or name})
    )
    return sibling


def _clone(
    tmp_path: Path, name: str, manifest: bool = False, declare: bool = True
) -> Path:
    """A whole checkout: a git dir and some source beside the config file."""
    sibling = tmp_path / name
    (sibling / ".git").mkdir(parents=True)
    (sibling / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (sibling / "src").mkdir()
    (sibling / "src" / "app.py").write_text("x = 1\n" * 4000)
    if declare:
        (sibling / ".socraticode.json").write_text(json.dumps({"projectId": name}))
    if manifest:
        (sibling / ".socraticodecontextartifacts.json").write_text('{"artifacts": []}')
    return sibling


def _check(tmp_path: Path, repo: Path, port: int, **env: str) -> tuple:
    return _run_health_check(tmp_path, repo, REPLIES, port, extra_env=env)


def _linked_findings(report: dict) -> list[str]:
    return [f for f in report["findings"] if CLONE in f or NOTHING in f]


EXTERNAL = {"QDRANT_MODE": "external"}


class TestAFullCloneWhereAStubWouldDo:
    @requires_node
    def test_a_stub_link_says_nothing(self, tmp_path: Path) -> None:
        _stub(tmp_path, "watcher")
        repo = _project(tmp_path, ["../watcher"])
        with _store({"codebase_watcher": 120}) as (port, _):
            result, report, _ = _check(tmp_path, repo, port, **EXTERNAL)
        assert report is not None, result.stderr
        assert _linked_findings(report) == [], report["findings"]
        assert result.returncode == 0, result.stderr

    @requires_node
    def test_a_full_clone_on_an_external_store_is_one_defect_with_its_size(
        self, tmp_path: Path
    ) -> None:
        _clone(tmp_path, "watcher")
        repo = _project(tmp_path, ["../watcher"])
        with _store({"codebase_watcher": 120}) as (port, _):
            result, report, _ = _check(tmp_path, repo, port, **EXTERNAL)
        found = [f for f in report["findings"] if CLONE in f]
        assert len(found) == 1, report["findings"]
        line = found[0]
        assert not line.startswith("note: "), line
        assert "\n" not in line, line
        assert "../watcher" in line, line
        assert "KiB" in line or "MiB" in line or "GiB" in line, line
        assert '{"projectId": "watcher"}' in line, line
        assert result.returncode == 1, result.stderr
        assert report["linkedProjects"]["clones"][0]["path"] == "../watcher", report

    @requires_node
    def test_a_clone_with_its_own_manifest_is_that_repos_home(
        self, tmp_path: Path
    ) -> None:
        _clone(tmp_path, "watcher", manifest=True)
        repo = _project(tmp_path, ["../watcher"])
        with _store({"codebase_watcher": 120}) as (port, _):
            result, report, _ = _check(tmp_path, repo, port, **EXTERNAL)
        assert _linked_findings(report) == [], report["findings"]
        assert result.returncode == 0, result.stderr

    @requires_node
    def test_a_clone_on_a_managed_store_is_required(self, tmp_path: Path) -> None:
        _clone(tmp_path, "watcher")
        repo = _project(tmp_path, ["../watcher"])
        with _store({"codebase_watcher": 120}) as (port, _):
            result, report, _ = _check(tmp_path, repo, port)
        assert not [f for f in report["findings"] if CLONE in f], report["findings"]
        assert result.returncode == 0, result.stderr

    @requires_node
    def test_a_clone_naming_no_id_asks_for_the_siblings_own(
        self, tmp_path: Path
    ) -> None:
        sibling = _clone(tmp_path, "watcher", declare=False)
        repo = _project(tmp_path, ["../watcher"])
        hashed = hashlib.sha256(str(sibling).encode()).hexdigest()[:12]
        with _store({f"codebase_{hashed}": 5}) as (port, _):
            _, report, _ = _check(tmp_path, repo, port, **EXTERNAL)
        line = next(f for f in report["findings"] if CLONE in f)
        assert '{"projectId": "<sibling\'s projectId>"}' in line, line


class TestALinkThatSearchesNothing:
    @requires_node
    def test_a_missing_collection_is_one_defect(self, tmp_path: Path) -> None:
        _stub(tmp_path, "watcher")
        repo = _project(tmp_path, ["../watcher"])
        with _store({}) as (port, received):
            result, report, _ = _check(tmp_path, repo, port, **EXTERNAL)
        found = [f for f in report["findings"] if NOTHING in f]
        assert len(found) == 1, report["findings"]
        assert "\n" not in found[0], found
        assert "../watcher (codebase_watcher: no such collection)" in found[0], found
        assert "from its own host" in found[0], found
        assert result.returncode == 1, result.stderr
        assert any(
            r["path"] == "/collections/codebase_watcher/points/count"
            and "filter" not in r["body"]
            for r in received
        ), received

    @requires_node
    def test_an_empty_collection_is_one_defect(self, tmp_path: Path) -> None:
        _stub(tmp_path, "watcher")
        repo = _project(tmp_path, ["../watcher"])
        with _store({"codebase_watcher": 0}) as (port, _):
            result, report, _ = _check(tmp_path, repo, port, **EXTERNAL)
        found = [f for f in report["findings"] if NOTHING in f]
        assert len(found) == 1, report["findings"]
        assert "../watcher (codebase_watcher: 0 points)" in found[0], found
        assert result.returncode == 1, result.stderr

    @requires_node
    def test_a_populated_collection_says_nothing(self, tmp_path: Path) -> None:
        _stub(tmp_path, "watcher")
        _stub(tmp_path, "notifier")
        repo = _project(tmp_path, ["../watcher", "../notifier"])
        with _store({"codebase_watcher": 3, "codebase_notifier": 9}) as (port, _):
            result, report, _ = _check(tmp_path, repo, port, **EXTERNAL)
        assert _linked_findings(report) == [], report["findings"]
        assert result.returncode == 0, result.stderr

    @requires_node
    def test_a_managed_store_names_this_host_as_the_fix(self, tmp_path: Path) -> None:
        sibling = _clone(tmp_path, "watcher", declare=False)
        repo = _project(tmp_path, ["../watcher"])
        hashed = hashlib.sha256(str(sibling).encode()).hexdigest()[:12]
        with _store({}) as (port, _):
            _, report, _ = _check(tmp_path, repo, port)
        line = next(f for f in report["findings"] if NOTHING in f)
        assert f"codebase_{hashed}" in line, line
        assert "on this host" in line, line

    @requires_node
    def test_the_prefix_is_read_as_upstream_reads_it(self, tmp_path: Path) -> None:
        _stub(tmp_path, "watcher")
        repo = _project(tmp_path, ["../watcher"])
        with _store({"pfx_codebase_watcher": 4}) as (port, received):
            result, report, _ = _check(
                tmp_path, repo, port, QDRANT_COLLECTION_PREFIX="pfx_", **EXTERNAL
            )
        assert _linked_findings(report) == [], report["findings"]
        assert any(
            r["path"] == "/collections/pfx_codebase_watcher/points/count"
            for r in received
        ), received

    @requires_node
    def test_an_unreachable_store_is_not_a_missing_collection(
        self, tmp_path: Path
    ) -> None:
        _stub(tmp_path, "watcher")
        repo = _project(tmp_path, ["../watcher"])
        result, report, _ = _check(tmp_path, repo, _closed_port(), **EXTERNAL)
        assert not [f for f in report["findings"] if NOTHING in f], report["findings"]
        notes = [f for f in report["findings"] if NOT_COUNTED in f]
        assert notes and notes[0].startswith("note: "), report["findings"]
        assert "cannot reach Qdrant" in notes[0], notes
        assert result.returncode == 0, result.stderr

    @requires_node
    def test_a_refused_launch_reads_no_linked_collection(self, tmp_path: Path) -> None:
        """An external store with no projectId: the launch is refused, the
        environment addresses the wrong collections, so nothing is counted."""
        _stub(tmp_path, "watcher")
        repo = _repo(tmp_path)
        (repo / ".socraticode.json").write_text(
            json.dumps({"linkedProjects": ["../watcher"]})
        )
        with _store({}) as (port, received):
            _, report, _ = _check(tmp_path, repo, port, **EXTERNAL)
        assert report.get("serverChecks") == "skipped", report
        assert not [f for f in report["findings"] if NOTHING in f], report["findings"]
        assert received == [], received

    @requires_node
    def test_a_repo_without_links_pays_nothing(self, tmp_path: Path) -> None:
        repo = _project(tmp_path, [])
        with _store({}) as (port, received):
            result, report, _ = _check(tmp_path, repo, port, **EXTERNAL)
        assert not [r for r in received if "filter" not in r["body"]], received
        assert report["linkedProjects"]["collections"] is None, report
        assert result.returncode == 0, result.stderr


def _finding(fn: str, *args: object) -> str | None:
    script = (
        f"import {{ {fn} }} from {json.dumps(str(DRIVER))};"
        f"process.stdout.write(JSON.stringify({fn}(...{json.dumps(list(args))})));"
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


class TestTheFindingsAreOneLinePureFunctions:
    @requires_node
    def test_nothing_to_fix_is_null(self) -> None:
        assert _finding("linkedCloneFinding", []) is None
        assert _finding("linkedCollectionFinding", [], True) is None

    @requires_node
    def test_an_unmeasured_size_is_said(self) -> None:
        line = _finding(
            "linkedCloneFinding",
            [{"path": "../a", "source": ".socraticode.json", "id": "a", "kib": None}],
        )
        assert "size not measured" in line, line

    @requires_node
    def test_several_links_share_one_line(self) -> None:
        line = _finding(
            "linkedCollectionFinding",
            [
                {"path": "../a", "collection": "codebase_a", "points": None},
                {"path": "../b", "collection": "codebase_b", "points": 0},
            ],
            True,
        )
        assert "\n" not in line, line
        assert "2 resolved links" in line, line
        assert "../a (codebase_a: no such collection)" in line, line
        assert "../b (codebase_b: 0 points)" in line, line


class TestTheDocsSayWhatTheCheckNowSees:
    def test_linked_projects_no_longer_says_it_cannot_see(self) -> None:
        text = LINKED_REF.read_text()
        assert "cannot see whether a link" not in text, (
            "health-check now counts a resolved link's collection (#573)"
        )
        assert "#573" in text or "/issues/573" in text, text

    def test_the_hook_help_lists_both_findings(self) -> None:
        text = HOOK.read_text()
        assert "full checkout" in text and "#573" in text, (
            "socraticode-health.sh --help must list #573's two findings"
        )

    def test_the_driver_help_lists_both_findings(self) -> None:
        text = DRIVER.read_text()
        usage = text[text.index("infra triage on a cadence") :]
        assert "#573" in usage[: usage.index("  resolve  ")], (
            "the health-check usage must name #573"
        )
