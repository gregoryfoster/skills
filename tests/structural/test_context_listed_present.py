"""A context artifact listed as indexed is counted in the store (#333).

#214 made "declared ≠ indexed" a finding and #225 "indexed ≠ fresh". Both
trust `codebase_context`'s `✓ indexed (N chunks, <time>)`, and that line is the
server's per-artifact metadata, not its points. After a full rebuild on
CannObserv/cannobserv#464 (1.14.0) both status tools listed eight artifacts
indexed while the context collection held points for two:

    | agent-guidelines | ✓ indexed (2 chunks, 2026-09-24T11:31:51Z) | 0 points |
    | design-docs      | ✓ indexed (319 chunks, …)                  | 319      |

Three of the six empty ones carried index times newer than their sources, so
they passed every check the driver had — and `codebase_context_search`
answered without them. `health-check` now counts each listed artifact's points
with a read-only `points/count` filtered on `artifactName`, against the stub
store in test_context_artifact_parity.py, which answers only for the
collection the server itself would address.
"""

import json
import re
import subprocess
from pathlib import Path

from .test_context_artifact_parity import (
    CONTEXT_ALL_INDEXED,
    CONTEXT_LISTING,
    DEFAULT_REPLIES,
    DRIVER,
    EDITED_AFTER_INDEXING,
    MISSING,
    STATUS_COMPLETE,
    _clean_env,
    _context_collection,
    _health_check,
    _listed_chunks,
    _qdrant_stub,
    _repo,
    _run_health_check,
    _stamp,
    requires_node,
)
from .test_stale_artifact_remedy import RUN_INCREMENTAL

REPLIES = {
    **DEFAULT_REPLIES,
    "codebase_status": STATUS_COMPLETE,
    "codebase_context": CONTEXT_ALL_INDEXED,
}
# The cannobserv shape at fixture size: the large directory artifact made it
# into the store, the two small files did not.
REBUILT = {"reference-docs": 577}


def _empty_finding(report: dict) -> list[str]:
    return [f for f in report["findings"] if "no chunks in the store" in f]


class TestTheListingIsCheckedAgainstTheStore:
    @requires_node
    def test_listed_but_absent_is_a_defect_naming_each_artifact(
        self, tmp_path: Path
    ) -> None:
        result, report, _ = _health_check(
            tmp_path, _repo(tmp_path), REPLIES, store_points=REBUILT
        )
        assert report is not None, result.stderr
        found = _empty_finding(report)
        assert found and not found[0].startswith("note: "), report["findings"]
        assert "3/3 listed indexed, 2 with no chunks in the store" in found[0], found
        assert "database-schema, agent-guidelines" in found[0], found
        assert [e["name"] for e in report["artifacts"]["empty"]] == [
            "database-schema",
            "agent-guidelines",
        ], report["artifacts"]
        assert result.returncode == 1, result.stdout

    @requires_node
    def test_fresh_timestamps_do_not_hide_an_empty_artifact(
        self, tmp_path: Path
    ) -> None:
        """The three that passed every check: listed, and newer than their sources."""
        _, report, _ = _health_check(
            tmp_path, _repo(tmp_path), REPLIES, store_points=REBUILT
        )
        assert report["artifacts"]["stale"] == [], report["artifacts"]
        assert report["artifacts"]["indexed"] == 3, report["artifacts"]
        assert _empty_finding(report), (
            "an artifact listed indexed, fresh by its timestamp and holding no "
            f"points reported nothing — the silence #214 set out to end\n{report}"
        )

    @requires_node
    def test_the_remedy_is_remove_then_index_not_update(self, tmp_path: Path) -> None:
        """codebase_update skips them: their content hash has not moved."""
        _, report, _ = _health_check(
            tmp_path, _repo(tmp_path), REPLIES, store_points=REBUILT
        )
        line = _empty_finding(report)[0]
        assert re.search(
            r"codebase_context_remove, then codebase_context_index", line
        ), line
        assert not RUN_INCREMENTAL.search(line), (
            "codebase_update re-embeds only artifacts whose content hash moved, "
            f"and the metadata says none did — it cannot repair this: {line!r}"
        )
        assert "1800 s" in line and "lastIndexedAt" in line, (
            "the remedy is the full re-embed #317 measured past the idle "
            f"timeout, so it must carry the not-a-failure rule: {line!r}"
        )

    @requires_node
    def test_an_empty_artifact_is_not_also_called_stale(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        _stamp(repo / "AGENTS.md", EDITED_AFTER_INDEXING)
        _, report, _ = _health_check(tmp_path, repo, REPLIES, store_points=REBUILT)
        assert not [f for f in report["findings"] if "stale" in f], (
            "an artifact with no points is not indexed, and was named twice — "
            f"once by the store count, once as stale\n{report['findings']}"
        )
        assert "agent-guidelines" in _empty_finding(report)[0]

    @requires_node
    def test_a_missing_collection_empties_every_listed_artifact(
        self, tmp_path: Path
    ) -> None:
        repo = _repo(tmp_path)
        _, report, _ = _health_check(tmp_path, repo, REPLIES, store_points=MISSING)
        line = _empty_finding(report)[0]
        assert "3 with no chunks" in line, line
        assert f"holds no {_context_collection(repo)} collection" in line, line
        assert report["artifacts"]["store"]["missing"] is True, report["artifacts"]

    @requires_node
    def test_an_unreadable_store_is_a_note(self, tmp_path: Path) -> None:
        result, report, _ = _health_check(
            tmp_path, _repo(tmp_path), REPLIES, indexed_hashes=None
        )
        notes = [f for f in report["findings"] if "not counted in the store" in f]
        assert notes and notes[0].startswith("note: "), report["findings"]
        assert "cannot reach Qdrant" in notes[0], notes
        assert not _empty_finding(report), report["findings"]
        assert result.returncode == 0, result.stdout

    @requires_node
    def test_a_count_that_differs_is_a_note(self, tmp_path: Path) -> None:
        points = {**_listed_chunks(CONTEXT_ALL_INDEXED), "database-schema": 40}
        result, report, _ = _health_check(
            tmp_path, _repo(tmp_path), REPLIES, store_points=points
        )
        notes = [f for f in report["findings"] if "differs from their listing" in f]
        assert notes and notes[0].startswith("note: "), report["findings"]
        assert "database-schema (listed 42, store 40)" in notes[0], notes
        assert result.returncode == 0, result.stdout

    @requires_node
    def test_full_presence_says_nothing(self, tmp_path: Path) -> None:
        _, report, _ = _health_check(tmp_path, _repo(tmp_path), REPLIES)
        assert report["artifacts"]["empty"] == [], report["artifacts"]
        assert report["artifacts"]["miscounted"] == [], report["artifacts"]
        assert report["findings"] == [], report["findings"]

    @requires_node
    def test_only_listed_indexed_artifacts_are_counted(self, tmp_path: Path) -> None:
        """An unindexed artifact is #214's finding; counting it adds nothing."""
        repo = _repo(tmp_path)
        replies = {**DEFAULT_REPLIES, "codebase_context": CONTEXT_LISTING}
        with _qdrant_stub(repo, {}, {}) as (port, received):
            _, report, _ = _run_health_check(tmp_path, repo, replies, port)
        counted = [
            r["body"]["filter"]["must"][0]["match"]["value"]
            for r in received
            if r["path"].endswith("/points/count")
        ]
        assert counted == ["database-schema", "agent-guidelines"], counted
        assert [e["name"] for e in report["artifacts"]["empty"]] == counted


class TestTheReadIsACountAndNothingElse:
    """The hook reports and never repairs: the store is read, never written."""

    @requires_node
    def test_each_request_is_a_scoped_exact_count(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        points = _listed_chunks(CONTEXT_ALL_INDEXED)
        with _qdrant_stub(repo, {}, points) as (port, received):
            _run_health_check(tmp_path, repo, REPLIES, port)
        counts = [r for r in received if r["path"].endswith("/points/count")]
        assert len(counts) == 3, received
        for r in counts:
            assert r["path"] == f"/collections/{_context_collection(repo)}/points/count"
            assert r["body"]["exact"] is True, r
            assert r["body"]["filter"]["must"][0]["key"] == "artifactName", r
        assert all(
            r["path"].endswith("/points/count")
            or r["path"] == "/collections/socraticode_metadata/points"
            for r in received
        ), (
            f"health-check made a store request that is not one of its two reads: {received}"
        )


class TestTheListedCountIsParsed:
    @requires_node
    def test_the_chunk_count_comes_off_the_status_line(self) -> None:
        script = (
            f"import {{ parseContextArtifacts }} from {json.dumps(str(DRIVER))};"
            "process.stdout.write(JSON.stringify(parseContextArtifacts("
            f"{json.dumps(CONTEXT_LISTING)}).map((a) => a.chunks)));"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == [42, None, 3]
