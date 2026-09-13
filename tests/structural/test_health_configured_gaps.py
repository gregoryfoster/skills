"""A project configured for SocratiCode is told when it cannot have it (#281).

`CannObserv/notifier` lost its whole SocratiCode install — no `node`, no plugin,
no Qdrant image, no volume — and the daily health hook noticed every time:

    [2026-08-31T15:52:56Z] node not on PATH — skipped
    ...
    [2026-09-10T00:42:54Z] node not on PATH — skipped

Nine days, five sessions, no session line. Every agent in them was told by
`AGENTS.md` to prefer `codebase_search` over `grep`, against a tool that could
not start. The skip was defensible for a repo that never adopted SocratiCode,
and the hook had already ruled that repo out: the manifest gate runs first. So
two conditions this file pins move from the log to the session:

- **No node, past the manifest gate.** The plugin starts its server with `npx`
  on the PATH the hook inherits, so the tools will fail. Reported, once a day,
  with the fallback an agent can use this session.
- **No driver, past the manifest gate.** A repo carrying the manifest vendors
  this skill, so the check's own instrument missing means nothing was measured
  — the FAILED TO RUN sentence, for the same fact. The tools may be fine, so
  this one does not tell a session to stop using them.

And one the server itself drops without a word: a linked project whose path
does not resolve. `loadLinkedProjects()` in socraticode 1.13.3 skips it by
design; the driver now reads both sources the same way and names the gap, so a
cohort that believes it has cross-repo search can find out it does not.

Every case that makes the hook louder is paired with the one it must not touch:
a repo with no manifest hears nothing, however broken its host.
"""

import json
import shutil
import subprocess
from pathlib import Path

from .test_socraticode_graph_yield import (
    DRIVER,
    GRAPH_OK_HIGH_UNRESOLVED,
    HEALTH_OK,
    HOOK,
    STATUS_CLEAN,
    STUB_SERVER,
    _clean_env,
    _health_check,
    _repo,
    requires_node,
)

# The commands socraticode-health.sh runs before it reaches the node check.
# A PATH holding exactly these, and no node, is the notifier host in miniature.
# Linked rather than filtering node's directory out of PATH: on most hosts that
# directory also holds git, and a hook that cannot run git exits silently at
# its first line, which would pass the silent case and fail the loud one for
# the wrong reason.
HOOK_TOOLS = ("git", "dirname", "cat", "date", "wc", "tail", "mv", "rm", "grep")

NODE_LINE = "node is not on PATH"
DRIVER_LINE = "mcp-driver.mjs was not found"


def _path_without_node(tmp_path: Path) -> str:
    bin_dir = tmp_path / "bin-without-node"
    bin_dir.mkdir()
    for tool in HOOK_TOOLS:
        found = shutil.which(tool)
        assert found, f"{tool} must be on PATH for the hook to run at all"
        (bin_dir / tool).symlink_to(found)
    assert shutil.which("node", path=str(bin_dir)) is None
    return str(bin_dir)


def _run_hook(repo: Path, tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    """HOME is pointed at the fixture, so the fifth driver candidate —
    `$HOME/.claude/skills/…` — cannot find a real install on the machine
    running the suite and turn a missing-driver case into a measured one."""
    base = {"HOME": str(tmp_path / "home")}
    base.update(env)
    return subprocess.run(
        # By absolute path: with PATH narrowed, a bare "bash" is looked up in
        # the narrowed PATH, where it deliberately is not.
        [shutil.which("bash") or "/bin/bash", str(HOOK)],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=60,
        env=_clean_env(**base),
    )


class TestAMissingNodeIsReported:
    """No node on the hook's PATH, in a repo that carries the manifest."""

    def test_it_reaches_the_session(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = _run_hook(
            repo,
            tmp_path,
            PATH=_path_without_node(tmp_path),
            SOCRATICODE_HEALTH_FORCE="1",
        )
        assert result.returncode == 0, result.stderr
        assert NODE_LINE in result.stdout, (
            "a configured project whose toolchain is gone must hear about it — "
            f"this is the notifier case, logged and never shown: {result.stdout!r}"
        )
        assert ".socraticodecontextartifacts.json" in result.stdout, (
            "the line must say why this repo, of all repos, is being told: "
            f"{result.stdout!r}"
        )
        assert "codebase_* tools will fail" in result.stdout, result.stdout

    def test_it_gives_the_session_a_fallback(self, tmp_path: Path) -> None:
        """The reader at session start is an agent the policy block has just
        sent to codebase_search. The line has to tell it what to do instead,
        not only what is broken."""
        repo = _repo(tmp_path)
        result = _run_hook(
            repo,
            tmp_path,
            PATH=_path_without_node(tmp_path),
            SOCRATICODE_HEALTH_FORCE="1",
        )
        assert "grep/rg" in result.stdout, result.stdout
        assert "preflight.sh --check" in result.stdout, (
            f"and the operator the command that names the gap: {result.stdout!r}"
        )

    def test_an_unconfigured_repo_still_hears_nothing(self, tmp_path: Path) -> None:
        """The case the skip was right about, and still is. A machine that
        never installed SocratiCode must not be nagged about it — the
        tuned-out reporter #180 exists to prevent."""
        repo = _repo(tmp_path, manifest=False)
        result = _run_hook(
            repo,
            tmp_path,
            PATH=_path_without_node(tmp_path),
            SOCRATICODE_HEALTH_FORCE="1",
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "", (
            f"no manifest, no report — whatever the host lacks: {result.stdout!r}"
        )

    def test_it_is_said_once_a_day_and_logged(self, tmp_path: Path) -> None:
        """The lock is stamped before this check, so the report rides the
        same one-a-day cadence as every other finding rather than repeating in
        every session of a broken day."""
        repo = _repo(tmp_path)
        path = _path_without_node(tmp_path)
        first = _run_hook(repo, tmp_path, PATH=path)
        second = _run_hook(repo, tmp_path, PATH=path)
        assert NODE_LINE in first.stdout, first.stdout
        assert second.stdout == "", (
            f"the UTC-day lock must hold for this finding too: {second.stdout!r}"
        )
        log = (repo / ".git" / "socraticode-health.log").read_text()
        assert "node not on PATH — reported" in log, log
        assert "skipped" not in log, (
            "the log must not still call it a skip, which is what made nine "
            f"days of it read as nothing:\n{log}"
        )

    def test_the_detail_doc_is_named_only_where_it_exists(self, tmp_path: Path) -> None:
        """An install older than docs/SOCRATICODE.md would be sent to a file it
        does not have."""
        path = _path_without_node(tmp_path)
        (tmp_path / "bare").mkdir()
        bare = _repo(tmp_path / "bare")
        without = _run_hook(bare, tmp_path, PATH=path, SOCRATICODE_HEALTH_FORCE="1")
        assert NODE_LINE in without.stdout, without.stdout
        assert "docs/SOCRATICODE.md" not in without.stdout, without.stdout

        (tmp_path / "documented").mkdir()
        documented = _repo(tmp_path / "documented")
        (documented / "docs").mkdir()
        (documented / "docs" / "SOCRATICODE.md").write_text("# SocratiCode\n")
        with_doc = _run_hook(
            documented, tmp_path, PATH=path, SOCRATICODE_HEALTH_FORCE="1"
        )
        assert "see docs/SOCRATICODE.md" in with_doc.stdout, with_doc.stdout


class TestAMissingDriverIsReported:
    """Node present, driver nowhere. The case `test_socraticode_graph_yield.py`
    used to pin as silent, "a condition the hook cannot judge"; past the
    manifest gate the hook can judge it, and what it can say is that nothing
    was measured."""

    @requires_node
    def test_it_says_nothing_was_measured(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = _run_hook(
            repo,
            tmp_path,
            SOCRATICODE_DRIVER="/nonexistent/mcp-driver.mjs",
            SOCRATICODE_HEALTH_FORCE="1",
        )
        assert result.returncode == 0, result.stderr
        assert DRIVER_LINE in result.stdout, (
            "a missing driver in a configured repo is a check that did not run, "
            f"and silence reads as a clean day: {result.stdout!r}"
        )
        assert "Nothing was measured" in result.stdout, result.stdout
        assert "SOCRATICODE_DRIVER" in result.stdout, result.stdout

    @requires_node
    def test_it_does_not_tell_the_session_to_abandon_the_tools(
        self, tmp_path: Path
    ) -> None:
        """The driver is the hook's instrument, not the server. The tools may
        be working, so the node case's fallback would be wrong advice here."""
        repo = _repo(tmp_path)
        result = _run_hook(
            repo,
            tmp_path,
            SOCRATICODE_DRIVER="/nonexistent/mcp-driver.mjs",
            SOCRATICODE_HEALTH_FORCE="1",
        )
        assert "grep/rg" not in result.stdout, result.stdout
        assert "will fail" not in result.stdout, result.stdout

    @requires_node
    def test_an_unconfigured_repo_still_hears_nothing(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, manifest=False)
        result = _run_hook(
            repo,
            tmp_path,
            SOCRATICODE_DRIVER="/nonexistent/mcp-driver.mjs",
            SOCRATICODE_HEALTH_FORCE="1",
        )
        assert result.stdout == "", result.stdout


def _linked(project: Path, env_value: str | None = None) -> dict:
    """`linkedProjects()` and its finding, from a one-shot node eval."""
    script = (
        "import { linkedProjects, linkedProjectsFinding } from "
        f"{json.dumps(str(DRIVER))};"
        f"const r = linkedProjects({json.dumps(str(project))});"
        "process.stdout.write(JSON.stringify({ ...r, finding: linkedProjectsFinding(r) }));"
    )
    extra = {} if env_value is None else {"SOCRATICODE_LINKED_PROJECTS": env_value}
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
        env=_clean_env(**extra),
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _checkouts(tmp_path: Path, *names: str) -> Path:
    """A project directory beside sibling checkouts named `names`."""
    project = tmp_path / "project"
    project.mkdir()
    for name in names:
        (tmp_path / name).mkdir()
    return project


def _config(project: Path, body: object) -> None:
    text = body if isinstance(body, str) else json.dumps(body)
    (project / ".socraticode.json").write_text(text)


class TestLinkedProjectsConfiguredAgainstResolved:
    """The driver's transcription of `loadLinkedProjects()`, reported instead
    of dropped."""

    @requires_node
    def test_the_issues_line(self, tmp_path: Path) -> None:
        """Two of four resolve; the two that do not are named, with where each
        was declared, because the fix differs by source."""
        project = _checkouts(tmp_path, "notifier", "broker")
        _config(project, {"linkedProjects": ["../notifier", "../archiver"]})
        r = _linked(project, "../broker, ../watcher")
        assert r["configured"] == 4, r
        assert [m["path"] for m in r["resolved"]] == ["../notifier", "../broker"], r
        assert r["missing"] == [
            {"path": "../archiver", "source": ".socraticode.json"},
            {"path": "../watcher", "source": "SOCRATICODE_LINKED_PROJECTS"},
        ], r
        assert "linkedProjects — 2 of 4 resolved" in r["finding"], r["finding"]
        assert "../archiver (.socraticode.json)" in r["finding"], r["finding"]
        assert "../watcher (SOCRATICODE_LINKED_PROJECTS)" in r["finding"], r["finding"]

    @requires_node
    def test_it_names_the_one_tool_affected(self, tmp_path: Path) -> None:
        """Linked collections reach codebase_search only, and only with
        includeLinked: true. A line that said "search is degraded" would send a
        reader hunting through tools the links never touched."""
        project = _checkouts(tmp_path)
        _config(project, {"linkedProjects": ["../gone"]})
        finding = _linked(project)["finding"]
        assert "codebase_search" in finding and "includeLinked: true" in finding, (
            finding
        )

    @requires_node
    def test_it_counts_the_way_the_server_does(self, tmp_path: Path) -> None:
        """A path named in both sources is one link, the project itself is no
        link, and a blank entry is nothing — each as upstream's Set and its
        `resolved !== resolvedRoot` guard have it. A count that disagreed with
        the server's would be a new wrong number, not a report of the old one."""
        project = _checkouts(tmp_path, "notifier")
        _config(project, {"linkedProjects": ["../notifier", ".", "  ", 7]})
        r = _linked(project, f"{tmp_path / 'notifier'},,")
        assert r["configured"] == 1, r
        assert r["finding"] is None, r

    @requires_node
    def test_everything_resolving_is_silent(self, tmp_path: Path) -> None:
        project = _checkouts(tmp_path, "a", "b")
        _config(project, {"linkedProjects": ["../a"]})
        r = _linked(project, "../b")
        assert r["missing"] == [] and r["finding"] is None, r

    @requires_node
    def test_nothing_configured_is_silent(self, tmp_path: Path) -> None:
        """Most installs link nothing; they must not gain a line for it."""
        r = _linked(_checkouts(tmp_path))
        assert r["configured"] == 0 and r["finding"] is None, r

    @requires_node
    def test_an_unparseable_config_is_named(self, tmp_path: Path) -> None:
        """Upstream's loader returns null on any parse error, so every link the
        file declares goes at once — the same silent drop, wholesale."""
        project = _checkouts(tmp_path)
        _config(project, '{"linkedProjects": ["../a"],}')
        finding = _linked(project)["finding"]
        assert finding and "not valid JSON" in finding, finding
        assert "ignores the whole file" in finding, finding

    @requires_node
    def test_a_bare_string_is_named(self, tmp_path: Path) -> None:
        """`"linkedProjects": "../a"` is the likeliest slip, and upstream reads
        the key only when it is an array."""
        project = _checkouts(tmp_path, "a")
        _config(project, {"linkedProjects": "../a"})
        finding = _linked(project)["finding"]
        assert finding and "is not an array" in finding, finding


class TestTheLinkedGapReachesTheReport:
    """End to end through `health-check` against the scripted stub server, and
    on through the hook: a finding the driver computes and nothing prints is
    the silence this issue is about, one layer down."""

    REPLIES = {
        "codebase_health": HEALTH_OK,
        "codebase_status": STATUS_CLEAN,
        "codebase_graph_status": GRAPH_OK_HIGH_UNRESOLVED,
    }

    @requires_node
    def test_a_missing_link_is_a_defect(self, tmp_path: Path) -> None:
        """A defect, not a note: a named action repairs it, which is the line
        #220 drew. A note would exit 0 and the hook would print nothing."""
        project = _checkouts(tmp_path)
        _config(project, {"linkedProjects": ["../archiver"]})
        result, report = _health_check(tmp_path, project, self.REPLIES)
        assert report is not None, result.stdout + result.stderr
        assert result.returncode == 1, result.stderr
        assert report["healthy"] is False, report
        assert report["linkedProjects"]["missing"] == [
            {"path": "../archiver", "source": ".socraticode.json"}
        ], report
        assert "  - linkedProjects — 0 of 1 resolved" in result.stderr, result.stderr

    @requires_node
    def test_resolved_links_leave_a_clean_check_clean(self, tmp_path: Path) -> None:
        project = _checkouts(tmp_path, "archiver")
        _config(project, {"linkedProjects": ["../archiver"]})
        result, report = _health_check(tmp_path, project, self.REPLIES)
        assert result.returncode == 0, result.stderr
        assert report["linkedProjects"]["configured"] == 1, report
        assert not any("linkedProjects" in f for f in report["findings"]), report

    @requires_node
    def test_the_hook_carries_it_into_the_session(self, tmp_path: Path) -> None:
        """The hook resolves the real driver and the driver the stub server, so
        this is the path a session actually sees, minus Docker."""
        repo = _repo(tmp_path)
        _config(repo, {"linkedProjects": ["../archiver"]})
        stub = tmp_path / "stub-server.mjs"
        stub.write_text(STUB_SERVER)
        replies = tmp_path / "replies.json"
        replies.write_text(json.dumps(self.REPLIES))
        result = _run_hook(
            repo,
            tmp_path,
            SOCRATICODE_DRIVER=str(DRIVER),
            SOCRATICODE_ENTRY=str(stub),
            STUB_REPLIES=str(replies),
            SOCRATICODE_HEALTH_FORCE="1",
        )
        assert result.returncode == 0, result.stderr
        assert "linkedProjects — 0 of 1 resolved" in result.stdout, result.stdout
        assert "FAILED TO RUN" not in result.stdout, result.stdout
