"""The graph gate measures yield, and the cadence hook reports it (#107).

`init-socraticode` used to accept `codebase_graph_status` reporting **READY**.
On `CannObserv/usa-wa` — a `uv` workspace with the standard src layout,
`packages/<dashed-name>/src/<underscored_module>/` — READY was reported for a
graph holding **3 dependency edges across 374 files, 81.8% unresolved**, because
the resolver cannot follow that three-way dashed-dir / `src/` / underscored-module
mismatch. Every green light was lit. The Code Exploration Policy the skill writes
then sent every agent to `codebase_graph_query` first, where the reply is an
ordinary sentence — "No dependency information found for this file." — which
reads as *nothing depends on this file* rather than *the tool failed*.

Two mechanisms answer that, and this file gates both:

- **The parsers.** `mcp-driver.mjs` grew `graphYield()`, a threshold on edges per
  node, and a probe for the empty-reply shape. They are pinned to fixtures in
  `scripts/parser-selftest.mjs`, which until now **nothing ran** — its own header
  said so. A tripwire nobody pulls is not a tripwire, so this file runs it.
- **The hook.** `scripts/socraticode-health.sh` re-uses the once-per-day
  SessionStart cadence `skills-submodule-update.sh` established. Its contract is
  narrow and worth pinning: silent when there is nothing to say or the repo
  never adopted SocratiCode, loud about a configured repo whose toolchain is
  gone (#281, pinned in test_health_configured_gaps.py), exit 0 on every path
  including the ones that fail.

The node tests skip loudly when node is absent, the way `TestShellcheck` skips
on a missing binary. No network, no Docker, no MCP server: the driver is
imported for its parsers, and the hook is pointed at a stub.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from .test_socraticode_node_gate import STORE_VARIABLES

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "skills" / "init-socraticode" / "scripts"
DRIVER = SCRIPTS / "mcp-driver.mjs"
SELFTEST = SCRIPTS / "parser-selftest.mjs"
HOOK = SCRIPTS / "socraticode-health.sh"
SKILL_MD = REPO_ROOT / "skills" / "init-socraticode" / "SKILL.md"
POLICY_REF = (
    REPO_ROOT
    / "skills"
    / "init-socraticode"
    / "references"
    / "code-exploration-policy.md"
)
DOC_REF = (
    REPO_ROOT / "skills" / "init-socraticode" / "references" / "socraticode-doc.md"
)

requires_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is required to exercise mcp-driver.mjs's parsers",
)


def _clean_env(**extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in (
        "SOCRATICODE_DRIVER",
        "SOCRATICODE_PROBE_FILE",
        "HEALTH_TIMEOUT_MS",
        "SOCRATICODE_HEALTH_FORCE",
        # health-check reads it since #281, and a session that runs this suite
        # may well have it set — the skill writes it into settings.local.json.
        "SOCRATICODE_LINKED_PROJECTS",
        # Read by the store guard since #287, which every server-launching
        # command runs first. A session on an external-store VM carries them
        # from its settings env block, and every fixture here declares no
        # projectId, so leaving them in would refuse each launch these make.
        *STORE_VARIABLES,
    ):
        env.pop(k, None)
    env.update(extra)
    return env


class TestParserSelftestRuns:
    """The fixture tripwire is now pulled automatically."""

    @requires_node
    def test_selftest_passes(self) -> None:
        result = subprocess.run(
            ["node", str(SELFTEST)],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert result.returncode == 0, (
            "scripts/parser-selftest.mjs failed. It pins mcp-driver.mjs's status "
            "parsers to fixtures synthesized from the server's own formatter; a "
            "failure means either a parser regressed or the server's strings "
            f"changed and the fixtures are stale.\n{result.stdout}\n{result.stderr}"
        )

    @requires_node
    def test_selftest_covers_yield(self) -> None:
        """A green selftest that never exercised yield would prove nothing."""
        result = subprocess.run(
            ["node", str(SELFTEST)],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert "graph YIELD" in result.stdout, (
            "parser-selftest.mjs must exercise the yield parsers — the #107 "
            "fixture (3 edges / 374 nodes / 81.8% unresolved, Status: READY) is "
            "the whole point of the gate"
        )


class TestDriverRunsThroughASymlink:
    """The driver must dispatch when reached through the vendoring symlink (#177).

    `RUN_AS_SCRIPT` compared `path.resolve(process.argv[1])` — which does not
    follow symlinks — against `fileURLToPath(import.meta.url)`, which is the
    realpath, because Node resolves the ESM main through symlinks. Through a
    symlink the two disagreed, the guard was false, and the process exited 0
    having printed nothing.

    That is the *normal* path: `skills/<name>` IS a symlink into
    `skills-vendor/` under the `managing-skills` pattern, so both documented
    invocation routes named the silent one. The failure signature is absence,
    which is why it needs its own test — a no-op driver and a healthy install
    look identical to every other assertion in this file.
    """

    @requires_node
    def test_help_prints_through_a_symlink(self, tmp_path: Path) -> None:
        link = tmp_path / "mcp-driver.mjs"
        link.symlink_to(DRIVER)
        result = subprocess.run(
            ["node", str(link), "--help"],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip(), (
            "the driver printed NOTHING when invoked through a symlink and "
            "still exited 0 (#177). Every documented invocation goes through "
            f"skills/init-socraticode/scripts/, which is a symlink.\n{result.stderr}"
        )

    @requires_node
    def test_an_unknown_command_still_fails_through_a_symlink(
        self, tmp_path: Path
    ) -> None:
        """Exit 0 with no output was the bug; a real dispatch must reject."""
        link = tmp_path / "mcp-driver.mjs"
        link.symlink_to(DRIVER)
        result = subprocess.run(
            ["node", str(link), "no-such-command"],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert result.returncode == 2, (
            "an unrecognised command must exit 2 through a symlink just as it "
            f"does through the real path; got {result.returncode}"
        )

    @requires_node
    def test_import_still_does_not_dispatch(self) -> None:
        """The property the guard exists for, preserved.

        `parser-selftest.mjs` imports this module for its parsers. A guard
        loosened until an import dispatches would spawn a server from the test
        suite.
        """
        script = f"await import({json.dumps(str(DRIVER))});"
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "", (
            "importing mcp-driver.mjs dispatched — the module must stay inert "
            f"when it is not the main script; got {result.stdout!r}"
        )

    @requires_node
    def test_a_symlinked_importer_does_not_dispatch(self, tmp_path: Path) -> None:
        """The realpath comparison must not collapse to 'any argv[1]'.

        A sibling script that imports the driver has a different realpath, so
        it must stay inert even though both resolve successfully.
        """
        importer = tmp_path / "importer.mjs"
        importer.write_text(f"await import({json.dumps(str(DRIVER))});\n")
        link = tmp_path / "importer-link.mjs"
        link.symlink_to(importer)
        result = subprocess.run(
            ["node", str(link)],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "", (
            f"a symlinked importer dispatched the driver; got {result.stdout!r}"
        )


class TestYieldVerdicts:
    """The threshold's behaviour, asserted from Python via a one-shot node eval."""

    @staticmethod
    def _yield(graph_status: str) -> dict:
        script = (
            f"import {{ graphYield }} from {json.dumps(str(DRIVER))};"
            f"process.stdout.write(JSON.stringify(graphYield({json.dumps(graph_status)})));"
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
    def test_the_usa_wa_graph_is_low(self) -> None:
        verdict = self._yield(
            "Status: READY\nFiles (nodes): 374\nDependencies (edges): 3\n"
            "Symbols: 3767\nCall edges: 23237\nUnresolved: 81.8%"
        )
        assert verdict["verdict"] == "low", verdict
        assert verdict["edgesPerNode"] < 0.1

    @requires_node
    def test_a_resolving_graph_is_ok(self) -> None:
        verdict = self._yield(
            "Status: READY\nFiles (nodes): 374\nDependencies (edges): 1512"
        )
        assert verdict["verdict"] == "ok", verdict

    @requires_node
    @pytest.mark.parametrize(
        "graph_status",
        [
            pytest.param(
                "Status: READY\nFiles (nodes): 6\nDependencies (edges): 0",
                id="too-few-files-to-judge",
            ),
            pytest.param("Status: BUILDING", id="unparseable"),
        ],
    )
    def test_unknown_is_not_folded_into_low(self, graph_status: str) -> None:
        """Writing the degraded policy asserts a repo's graph is broken.

        Asserting that from a status we could not read, or from a repo too small
        to judge, is the same class of error the gate exists to catch.
        """
        assert self._yield(graph_status)["verdict"] == "unknown"


def _graph_health(doc_text: str) -> str:
    """The generated doc's `## Graph health` section, heading to the next `##`.

    Deliberately a local six-liner rather than an import from
    `test_socraticode_policy_split.py`: AGENTS.md keeps structural rules in
    separate files so parallel worktrees merge clean, and a cross-module import
    would put that back.
    """
    start = doc_text.index("## Graph health")
    end = doc_text.find("\n## ", start + len("## Graph health"))
    return doc_text[start : end if end != -1 else len(doc_text)]


def _flowed(text: str) -> str:
    """Collapse whitespace, so a quotation may be re-wrapped freely.

    The doc wraps at ~76 columns and the finding is longer than that, so it
    necessarily spans lines there. Comparing flowed text asserts the words,
    not the wrap column — a reflow must not be able to fail this.
    """
    return " ".join(text.split())


def _verdict(graph_status: str, server_version: str | None = None) -> dict:
    """`graphVerdict` over one status string, as JSON.

    Module level, beside `_flowed` and `_graph_health`, because two classes need
    it: the #207 class that pins which measure rules, and the #297 class that
    pins staleness not deciding that. A private staticmethod reached across a
    class boundary makes renaming it break a test that never mentions it.
    """
    script = (
        f"import {{ graphVerdict }} from {json.dumps(str(DRIVER))};"
        "process.stdout.write(JSON.stringify(graphVerdict("
        f"{json.dumps(graph_status)}, {json.dumps(server_version)})));"
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


# ── transcribed graph statuses, from a live socraticode 1.13.1 ──────────────
# Module level because two classes read them: the #207 class that pins which
# measure rules, and the #297 class that pins staleness not deciding that.
# `cannobserv` before and after a rebuild, and its sibling
# `cannabis.observer-wordpress`. That they are transcribed rather than
# synthesized matters — the whole failure these gate is reading one of these
# shapes as another.
GRAPH_STALE = (
    "Status: READY\nFiles (nodes): 621\nDependencies (edges): 37\n"
    "Last built: 2026-08-31T03:42:35.508Z (761060s ago)\n"
    "Built by: unknown (persisted before the builder version was recorded)\n"
    "  Run codebase_graph_build to rebuild with v1.13.1 and confirm this "
    "graph reflects the current resolvers.\nUnresolved: 79.3%"
)
GRAPH_REBUILT = (
    "Status: READY\nFiles (nodes): 627\nDependencies (edges): 2156\n"
    "Built by: v1.13.1\nUnresolved: 51.1%"
)
GRAPH_ADVISORY = (
    "Status: READY\nFiles (nodes): 618\nDependencies (edges): 35\n"
    "Import resolution: 35 of 2959 captured imports resolved to project "
    "files (1.2%)\n"
    "  Most imports did not resolve, so codebase_graph_query, "
    "codebase_graph_stats and codebase_impact will under-report "
    "dependencies — an empty answer there means unresolved, not "
    "independent.\nBuilt by: v1.13.1"
)


class TestTheServerStatementRules:
    """#207: the server states the yield since 1.13.0, and it outranks ours.

    The gate reads three things, not one. `graphYield` is still our own
    edges-per-file arithmetic; `parseImportResolution` reads the advisory the
    server prints when resolution collapses; `parseGraphBuilder` reads the
    `Built by:` stamp that says whether the advisory's SILENCE can be trusted.

    That third one is the whole point of this class. Advisory-absence has three
    causes — server too old, graph too old, or genuinely fine — and only the
    stamp separates them. Reading absence as "fall back to local" in all three
    is what produced the live regression pinned below.
    """

    @requires_node
    def test_the_advisory_rules_when_the_server_states_it(self) -> None:
        v = _verdict(GRAPH_ADVISORY)
        assert v["verdict"] == "low", v
        assert v["source"] == "server", v

    @requires_node
    def test_a_certified_graph_is_ok_on_the_servers_authority(self) -> None:
        v = _verdict(GRAPH_REBUILT)
        assert (v["verdict"], v["source"]) == ("ok", "server"), v

    @requires_node
    def test_an_unstamped_graph_falls_back_to_our_arithmetic(self) -> None:
        """Cases 1 and 2: the silence carries no information."""
        v = _verdict(GRAPH_STALE)
        assert v["source"] == "local", v
        assert v["verdict"] == "low", v

    @requires_node
    def test_the_stale_regression_is_pinned(self) -> None:
        """The live miss this issue exists for.

        cannobserv served a graph at 37 edges across 621 files for 8.8 days and
        the gate called it LOW throughout. It was STALE, not broken — rebuilt on
        1.13.1 the same repo yields 2156 edges across 627 files. The fix is not
        that the first now reads `ok`; it is that a rebuild changes the answer
        and that the staleness is reported as its own repairable defect.
        """
        assert _verdict(GRAPH_STALE)["verdict"] == "low"
        assert _verdict(GRAPH_REBUILT)["verdict"] == "ok"

        script = (
            f"import {{ parseGraphBuilder, builderFinding }} from {json.dumps(str(DRIVER))};"
            f"process.stdout.write(builderFinding(parseGraphBuilder({json.dumps(GRAPH_STALE)})) || '');"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert result.returncode == 0, result.stderr
        assert "codebase_graph_build" in result.stdout, (
            "a stale or unstamped builder must name the command that repairs "
            "it — that is what makes it a defect rather than a note (#220)"
        )

    @requires_node
    def test_the_server_is_not_overruled_by_our_floor(self) -> None:
        """The hazard the composed gate exists to prevent.

        The two thresholds do not nest: ours is edges-per-file, the server's is
        resolved-over-captured. An orphan-heavy repo can clear the server's bar
        and trip ours. Letting it write the degraded policy there rewrites
        AGENTS.md to route every dependency question to grep, on a graph the
        server just certified.
        """
        orphan_heavy = (
            "Status: READY\nFiles (nodes): 400\nDependencies (edges): 12\n"
            "Built by: v1.13.1"
        )
        v = _verdict(orphan_heavy)
        assert v["verdict"] == "ok", v
        assert v["local"]["verdict"] == "low", (
            "the fixture must actually trip the local floor, or this asserts nothing"
        )
        assert v["disagreement"], (
            "the server suppresses its advisory below 20 captured imports, so "
            "silence still means 'fine OR too little signal'. The disagreement "
            "must be recorded rather than discarded"
        )

    @requires_node
    def test_an_unreadable_status_is_never_a_server_ok(self) -> None:
        """CR 1: the server certifies resolution, not our ability to read it.

        Every other assertion about an unparseable status exercises
        `graphYield`. That is precisely why this regression hid: health-check
        reports the COMPOSED verdict, and a relabelled `Dependencies (edges):`
        line plus a current builder arrived here as a confident `ok` — silently
        disarming the parser-drift tripwire (gotcha H, #85) that this file and
        `parser-selftest.mjs` exist to keep loud.
        """
        relabelled = (
            "Status: READY\nFiles (nodes): 374\nCall edges: 23237\nBuilt by: v1.13.1"
        )
        v = _verdict(relabelled)
        assert v["verdict"] == "unknown", v
        assert v["source"] == "local", (
            "an unreadable status must not be attributed to the server, which "
            "certified nothing about it"
        )

    @requires_node
    def test_a_repo_too_small_to_judge_still_defers_to_the_server(self) -> None:
        """The other `unknown`, which is not a parse failure and does defer."""
        tiny = (
            "Status: READY\nFiles (nodes): 6\nDependencies (edges): 0\n"
            "Built by: v1.13.1"
        )
        assert _verdict(tiny)["verdict"] == "ok"

    @requires_node
    def test_a_pre_advisory_server_behaves_exactly_as_before(self) -> None:
        """#107's gate must survive untouched where there is no server signal."""
        old_low = "Status: READY\nFiles (nodes): 374\nDependencies (edges): 3"
        v = _verdict(old_low)
        assert (v["verdict"], v["source"]) == ("low", "local"), v
        assert v["builder"]["state"] == "absent", v

    def test_the_doc_explains_the_advisory(self) -> None:
        """#207 acceptance: the generated doc has to say what the line means."""
        doc = DOC_REF.read_text()
        assert "Import resolution:" in doc, (
            "socraticode-doc.md must show the advisory it now tells readers to believe"
        )
        assert "Built by:" in doc, (
            "the advisory's silence is only readable beside the builder stamp — "
            "a doc that explains one without the other teaches the misread"
        )


class TestStalenessIsOursToDecide:
    """#297: a stale artifact reporting READY must be self-evident.

    #207 taught the driver to read the server's `Built by:` stamp, and with it
    the server's own `— STALE` annotation. That covered the case the server
    volunteers, and only that case: `stale` meant *the server appended STALE*,
    so every way of not appending it — a reformat, a build that stamps without
    comparing, the v1.10.0 graph below that carried no stamp at all — landed on
    `current` and certified a graph older than the resolvers answering queries
    about it.

    The cost is on the record. `CannObserv/cannabis.observer-wordpress#803`
    spent three rounds on a wrong diagnosis: the graph reported READY, the yield
    finding fired, and the conclusion — that a PSR-4 `composer.json` declaration
    "would not help" — went into the issue and then into that repo's
    `docs/SKILLS.md`. The graph had been cut by **v1.10.0**; PSR-4 resolution
    shipped in **v1.11.0**. Nothing anywhere said the artifact predated the
    feature being reasoned about, and it took a rebuild months later to notice.
    The repo ended up writing the hazard into its own `AGENTS.md` as a working
    rule, which is a tool's job leaking into thirteen consuming repos.

    So the driver now keeps `serverInfo.version` from the MCP handshake — the
    one fact that says what it is actually talking to — and does the comparison
    itself. The server's word is still believed when it speaks; what is new is
    that its silence is checked rather than trusted.

    What this must NOT do is manufacture staleness, which would be the
    accusation-on-a-healthy-repo failure #216 and #220 spent two issues
    removing. Every refusal-to-guess case below is as load-bearing as the
    detection.
    """

    # cannobserv after its rebuild, transcribed from a live 1.13.1.

    @staticmethod
    def _builder(graph_status: str, server_version) -> dict:
        script = (
            f"import {{ parseGraphBuilder, builderFinding }} from {json.dumps(str(DRIVER))};"
            f"const b = parseGraphBuilder({json.dumps(graph_status)}, "
            f"{json.dumps(server_version)});"
            "process.stdout.write(JSON.stringify({...b, finding: builderFinding(b)}));"
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
    def test_a_graph_older_than_the_server_is_stale_unprompted(self) -> None:
        """The gap #207 left: staleness the server did not volunteer."""
        b = self._builder(GRAPH_REBUILT, "1.14.0")
        assert b["state"] == "stale", (
            "a graph cut by v1.13.1 and served by v1.14.0 is stale whether or "
            "not the server chose to say so — taking that on the server's word "
            "is what let a v1.10.0 graph be reasoned about on a v1.11.0 server"
        )

    @requires_node
    def test_the_finding_names_both_versions_and_the_repair(self) -> None:
        """The bare phrase, without the numbers, is still a hunt.

        The whole issue is that the reader should not have to go and find out
        which two versions are in play. In the case on record, nobody did.
        """
        finding = self._builder(GRAPH_REBUILT, "1.14.0")["finding"]
        assert "v1.13.1" in finding and "v1.14.0" in finding, finding
        assert "codebase_graph_build" in finding, (
            "a defect names the action that repairs it (#220)"
        )

    @requires_node
    def test_the_servers_own_word_still_rules(self) -> None:
        """#207's path must survive: STALE is believed even with nothing to compare."""
        b = self._builder(
            GRAPH_STALE.replace(
                "Built by: unknown (persisted before the builder version was recorded)",
                "Built by: v1.12.0 — STALE, this server is v1.13.1",
            ),
            None,
        )
        assert b["state"] == "stale", b
        assert b["serverVersion"] == "1.13.1", (
            "with no handshake version the STALE line names the server itself, "
            "and the finding should still be able to print both numbers"
        )

    @requires_node
    def test_the_handshake_version_outranks_the_printed_one(self) -> None:
        """This host resolves the plugin to `npx socraticode@latest`.

        The version cached under `plugins/cache` and the version that actually
        answers can differ by a release — measured, not supposed: the cache held
        1.13.2 while the handshake returned 1.14.0. What the driver is talking
        to is the authority.
        """
        b = self._builder(
            GRAPH_REBUILT.replace(
                "Built by: v1.13.1", "Built by: v1.13.1 — STALE, this server is v1.13.2"
            ),
            "1.14.0",
        )
        assert b["serverVersion"] == "1.14.0", b

    @requires_node
    @pytest.mark.parametrize(
        "server_version, why",
        [
            ("1.13.1", "a graph cut by the running server is not stale"),
            (
                "1.12.0",
                "a builder NEWER than the server is a downgrade or a lagging "
                "plugin cache: the artifact is at least as good as anything the "
                "running resolvers would cut, and no action repairs it",
            ),
            ("nightly", "an unreadable server version compares to nothing"),
            (None, "a server that declared no version compares to nothing"),
        ],
    )
    def test_staleness_is_never_manufactured(self, server_version, why) -> None:
        b = self._builder(GRAPH_REBUILT, server_version)
        assert b["state"] == "current", f"{why}\n{b}"
        assert b["finding"] is None, f"{why}\n{b}"

    @requires_node
    def test_staleness_does_not_decide_which_measure_rules(self) -> None:
        """The regression #297 nearly shipped, and the reason the two are separate.

        `graphVerdict` used to ask "can I trust the advisory's silence?" by
        testing `builder.state === 'current'`. That worked only while `current`
        meant *the server did not append STALE*. The moment #297 made staleness
        ours to compute, every graph a release behind its server fell off the
        server's ruling and onto our edges/file floor — and an orphan-heavy repo
        the server had just certified trips that floor, earning `low`, which is
        what writes the degraded Code Exploration Policy (variant B) into its
        AGENTS.md. #207's own false accusation, re-entering through the door
        #297 opened, and firing on every repo in the window between a
        SocratiCode upgrade and the next rebuild.

        So the trust predicate asks what the graph CARRIES — a builder stamp at
        or past the release that records import counts — and staleness is
        reported separately by `builderFinding`. Both facts, neither deciding
        the other.
        """
        orphan_heavy = (
            "Status: READY\nFiles (nodes): 400\nDependencies (edges): 12\n"
            "Built by: v1.13.1"
        )
        script = (
            f"import {{ graphVerdict, builderFinding }} from {json.dumps(str(DRIVER))};"
            f"const v = graphVerdict({json.dumps(orphan_heavy)}, '1.14.0');"
            "process.stdout.write(JSON.stringify("
            "{verdict: v.verdict, source: v.source, finding: builderFinding(v.builder)}));"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert result.returncode == 0, result.stderr
        got = json.loads(result.stdout)
        assert (got["verdict"], got["source"]) == ("ok", "server"), (
            "a graph one release behind still carries the import counts the "
            "running server read, so its ruling stands — being older than the "
            "server is a separate defect, not a reason to overrule it\n"
            f"{got}"
        )
        assert got["finding"] and "codebase_graph_build" in got["finding"], (
            "…and that separate defect must still be reported, or the split "
            "loses the very finding #297 asked for\n"
            f"{got}"
        )

    @requires_node
    def test_a_builder_predating_the_advisory_still_falls_back(self) -> None:
        """The other half of the split: #207's case 2, unchanged.

        A graph cut before the advisory shipped records no import counts, so the
        running server has nothing to compute a ratio from and its silence
        proves nothing. That graph must still fall back to our arithmetic —
        widening the server's authority to cover it would be the mirror-image
        error.
        """
        pre_advisory = (
            "Status: READY\nFiles (nodes): 400\nDependencies (edges): 12\n"
            "Built by: v1.12.0 — STALE, this server is v1.13.1"
        )
        v = _verdict(pre_advisory)
        assert (v["verdict"], v["source"]) == ("low", "local"), v
        assert "predates the import-resolution advisory" in v["reason"], (
            "the reason must name why there was no advisory to read — a stamped "
            "graph reaching the fallback did so because its BUILDER is too old, "
            "not because the server is\n"
            f"{v}"
        )

    @requires_node
    def test_the_comparison_refuses_to_guess(self) -> None:
        """`null`, never `0`.

        "Could not compare" rendered as "same version" is the certificate this
        exists to withhold — the assert-from-a-string-we-could-not-read error
        `graphYield` and `parseImportResolution` both refuse to make.
        """
        script = (
            f"import {{ compareVersions }} from {json.dumps(str(DRIVER))};"
            "process.stdout.write(JSON.stringify(["
            "compareVersions('1.12.0','1.13.1'), compareVersions('1.13.1','1.13.1'),"
            "compareVersions('1.14.0','1.13.1'), compareVersions('1.9.0','1.10.0'),"
            "compareVersions('nightly','1.13.1'), compareVersions('1.13.1',null),"
            "compareVersions('1.14.0-rc.2','1.14.0')]));"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == [-1, 0, 1, -1, None, None, 0], (
            "`1.9.0 < 1.10.0` pins numeric ordering rather than string ordering; "
            "the two nulls pin the refusal; the prerelease compares equal to its "
            "release because ordering those is semver's problem, not this gate's"
        )

    @requires_node
    def test_the_driver_keeps_the_handshakes_server_version(self) -> None:
        """The plumbing, pinned where it would otherwise rot silently.

        Every assertion above hands the version in by hand. If the handshake
        stopped keeping it, they would all still pass and the live check would
        compare against `null` forever — the pre-#297 behaviour, restored
        invisibly.

        Matched by shape, not by spelling. These are source-text assertions
        standing in for a check that would otherwise need a live server, and a
        literal `in src` on a whole call expression fails on a rewrap or an
        argument rename while the behaviour is untouched. A tripwire that fires
        on formatting teaches its reader to reach for `--no-verify`, so each
        pattern below pins the fact (serverInfo is kept; the gate is handed a
        server version) and tolerates how it is written.
        """
        src = DRIVER.read_text()
        assert re.search(r"this\.serverInfo\s*=\s*\(?\s*res\b", src), (
            "RpcClient.handshake() must keep the initialize result's serverInfo; "
            "it is the only place the running server names its own version"
        )
        assert re.search(
            r"graphVerdict\(\s*graph\.text\s*,\s*client\.serverVersion\s*\)", src
        ), (
            "health-check must hand the running server's version to the gate, "
            "or the comparison never happens on the path that matters"
        )
        assert re.search(r"report\.server\s*=", src), (
            "the JSON report must record the server it measured against — a "
            "report carrying the graph's builder but not the server's version "
            "cannot be re-read later to settle the question, which is exactly "
            "what nobody could do in the case #297 records"
        )


class TestTheHookSaysWhatItReports:
    """#297's other half: a contract that does not mention the check.

    The consuming repo wrote "Rebuild the graph after a SocratiCode upgrade — a
    stored graph has no version stamp and still reports READY" into its own
    `AGENTS.md` because the tooling would not say it. The hook now does say it
    when the defect fires — but a maintainer deciding whether that hand-written
    rule is still needed reads `--help`, and `--help` enumerated everything the
    hook reports except this. A check nobody knows about does not retire the
    working rule it replaces.
    """

    @staticmethod
    def _help(*cmd: str) -> str:
        result = subprocess.run(
            [*cmd, "--help"],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert result.returncode == 0, f"{cmd} --help exited {result.returncode}"
        return result.stdout

    def test_the_hook_help_names_the_builder_check(self) -> None:
        flowed = _flowed(self._help("bash", str(HOOK)))
        assert "codebase_graph_build" in flowed, (
            "socraticode-health.sh --help lists what the hook reports; the "
            "builder-staleness defect belongs on that list with the command "
            "that repairs it (#297)"
        )
        assert "#297" in flowed, (
            "every other finding in that block carries the issue that put it "
            "there — the block is the record as much as the contract"
        )

    @requires_node
    def test_the_driver_help_no_longer_says_edge_yield_alone(self) -> None:
        """The contract drifted at #207 and nobody noticed for two months.

        `health-check` stopped gating on our edges/file floor when the server
        started stating the resolution itself; `--help` went on describing the
        pre-#207 gate, so a reader debugging a verdict was told the wrong
        measure had produced it.
        """
        flowed = _flowed(self._help("node", str(DRIVER)))
        assert "measured by EDGE YIELD rather than by READY" not in flowed, (
            "since #207 the server's import-resolution advisory rules where it "
            "speaks and edges/file is the fallback; --help must not still "
            "describe the old single-measure gate"
        )
        assert "import-resolution advisory" in flowed, flowed
        assert "#297" in flowed, (
            "the builder comparison is part of what health-check does, so it "
            "belongs in the command's own description"
        )


class TestUnresolvedFindingIsVerdictAware:
    """#216, #308: the figure is worded for what it counts, on every verdict.

    The finding fires whenever the figure exceeds the threshold, *outside* the
    verdict branches — correct, because the statistic is worth reporting either
    way. But `corroborates a resolver problem` beside `verdict: "ok"` had no
    verdict to corroborate, and one cohort repo read it as a standing accusation
    against a provably exact import graph, paying an `rg` round-trip on every
    dependency question for weeks (#216).

    #308 took the other branch too. Since v1.14.0 the server explains the
    number itself: the share of *captured symbol edges* — calls, imports,
    re-exports, type or value references — that matched no project symbol,
    with edges into builtins and external libraries counted by construction,
    so that it "is not a resolver failure rate". The gloss said "call edges",
    which undercounts the denominator, and beside `low`/`unknown` it still
    offered the figure as a corroborating witness — the reading that let a
    cohort repo cite 70% as the cause of a `codebase_impact` under-report in
    its own docs. The verdict stands on the yield arithmetic and the server's
    advisory; the figure is reported beside it.

    So the text is selected from the verdict while the line itself stays
    unconditional: data is never suppressed, only worded for what it is.
    """

    @staticmethod
    def _finding(unresolved_pct: str, verdict: str) -> str:
        script = (
            f"import {{ unresolvedFinding }} from {json.dumps(str(DRIVER))};"
            f"process.stdout.write(unresolvedFinding("
            f"{json.dumps(unresolved_pct)}, {json.dumps(verdict)}));"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    @requires_node
    @pytest.mark.parametrize("verdict", ["low", "unknown"])
    def test_an_unhealthy_verdict_is_not_offered_evidence(self, verdict: str) -> None:
        """`low`/`unknown` stand on the yield arithmetic and the advisory (#308).

        The figure cannot corroborate a resolver failure: builtins and external
        libraries land in it by construction, so on a healthy repo with a lot
        of external surface it would read as a second witness against the
        resolver. It is reported beside the verdict, and says so.
        """
        finding = self._finding("61.7", verdict)
        assert "corrobo" not in finding, (
            f"beside verdict {verdict!r} the unresolvedPct line still offers "
            "itself as corroboration — the reading SocratiCode v1.14.0 added a "
            f"paragraph to prevent (#308): {finding!r}"
        )
        assert "not as evidence" in finding, (
            "the line must say it is reported beside the verdict, not for it, "
            f"or a reader supplies the causal claim themselves: {finding!r}"
        )

    @requires_node
    def test_an_ok_verdict_does_not_accuse(self) -> None:
        finding = self._finding("61.7", "ok")
        assert "corrobo" not in finding, (
            'beside `verdict: "ok"` there is no finding for the statistic to '
            "corroborate, and the corroboration wording is then read as the "
            "accusation #216 was filed about"
        )
        assert "statistic, not a defect" in finding, finding
        assert "builtins and external libraries" in finding, (
            "the ok gloss must say WHY the share runs high on healthy code, or "
            f"the number is read as a failure rate (#308): {finding!r}"
        )

    @requires_node
    @pytest.mark.parametrize("verdict", ["low", "unknown", "ok"])
    def test_the_denominator_is_the_servers(self, verdict: str) -> None:
        """Captured symbol edges, not call edges (#308).

        v1.14.0 states its denominator as calls, imports, re-exports and type
        or value references. Saying "call edges" undercounts what is counted,
        and an operator reading the daily hook — the surface most of them read
        — gets a smaller number in their head than the one on the screen.
        """
        finding = self._finding("61.7", verdict)
        assert "captured symbol edges" in finding, finding
        assert "call edges" not in finding, (
            f"the {verdict!r} gloss still names the pre-v1.14.0 denominator: "
            f"{finding!r}"
        )

    @requires_node
    def test_the_statistic_is_reported_on_every_verdict(self) -> None:
        """Wording changes; the number does not disappear.

        The rejected alternative was to move the line inside the verdict
        branches, which would have hidden a genuinely useful figure from every
        healthy repo. Both readings must still carry the measurement and the
        threshold it was compared against.
        """
        for verdict in ("low", "unknown", "ok"):
            finding = self._finding("61.7", verdict)
            assert "61.7%" in finding and "50%" in finding, (
                f"the {verdict!r} wording dropped the statistic or the "
                f"threshold: {finding!r}"
            )

    @requires_node
    @pytest.mark.parametrize("verdict", ["low", "unknown", "ok"])
    def test_the_doc_quotes_what_the_driver_emits(self, verdict: str) -> None:
        """The pin `test_graph_health_explains_unresolved_pct` cannot be (#216).

        That test pins the **Graph health** section as *concepts* — deliberately,
        because a sentence-level pin fights every legitimate rewording. The cost
        is that rewording the driver's string leaves it green while the doc's
        verbatim quotation of that string goes stale, and a reader who diffs the
        doc against the finding they were just shown has no way to tell which of
        the two is lying.

        Asserted as *agreement*, not as a sentence: the driver renders the
        finding and the doc must contain what it rendered. Reword the driver
        however you like — this stays green as long as the doc moves with it,
        which is the whole property that was missing.

        Rendered with a literal `N` for the percentage, because that is the
        shape the doc quotes: a real figure there would be repo- and
        day-specific, which the section says in as many words.
        """
        finding = self._finding("N", verdict)
        section = _flowed(_graph_health(DOC_REF.read_text()))
        assert _flowed(finding) in section, (
            f"references/{DOC_REF.name}'s **Graph health** section does not "
            f"quote what `mcp-driver.mjs` emits on verdict {verdict!r}:\n"
            f"  driver: {_flowed(finding)}\n"
            "The doc is the only place a consumer can look the finding up; a "
            "quotation that no longer matches is worse than none (#216)."
        )


# ── the severity harness (#220) ──────────────────────────────────────────────
# A stub MCP server, scripted per tool. Deliberately a local copy rather than an
# import from `test_context_artifact_parity.py`: AGENTS.md keeps structural
# rules in separate files so parallel worktrees merge clean, which is the same
# reason `_graph_health` above is a local six-liner. The two copies pin two
# different properties and are free to drift.

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
    if (msg.method === 'initialize' && process.env.STUB_SERVER_VERSION) {
      send({ jsonrpc: '2.0', id: msg.id, result: {
        serverInfo: { name: 'socraticode', version: process.env.STUB_SERVER_VERSION } } });
      continue;
    }
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

HEALTH_OK = "Docker: ✓ running\nQdrant: ✓ healthy\nOllama: ✓ nomic-embed-text present"
HEALTH_DOWN = "Docker: ✓ running\nQdrant: ✗ container not running\nOllama: ✓ present"

STATUS_CLEAN = """Project: /repo
Status: green
Indexed chunks: 1252

Last operation: Full index — completed
"""

# `ok` on yield — 1512 edges across 374 files — and 61.7% unresolved beside it.
# That pairing is #220's whole case: a framework-heavy repo with a provably
# exact import graph, told once a day that it has "health findings".
GRAPH_OK_HIGH_UNRESOLVED = """Code Graph Status

Status: READY
Files (nodes): 374
Dependencies (edges): 1512
Symbols: 3767
Call edges: 23237
Unresolved: 61.7%
"""


def _health_check(tmp_path: Path, project: Path, replies: dict, **env: str) -> tuple:
    """Run `mcp-driver.mjs health-check` against a scripted stub server.

    `STUB_SERVER_VERSION` in `env` makes the stub name itself in the
    handshake, as a real server does; without it the stub declares no
    serverInfo, which is the shape every caller before #305 relied on.
    """
    stub = tmp_path / "stub-server.mjs"
    stub.write_text(STUB_SERVER)
    reply_file = tmp_path / "replies.json"
    reply_file.write_text(json.dumps(replies))
    result = subprocess.run(
        ["node", str(DRIVER), "health-check", str(project)],
        capture_output=True,
        text=True,
        timeout=60,
        env=_clean_env(
            SOCRATICODE_ENTRY=str(stub),
            STUB_REPLIES=str(reply_file),
            HEALTH_TIMEOUT_MS="30000",
            **env,
        ),
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        report = None
    return result, report


class TestANeutralFindingDoesNotFailTheCheck:
    """#220: #216 fixed the wording, not the envelope.

    The `unresolvedPct` line reads neutrally beside `verdict: "ok"` now — but it
    still landed in `findings`, and any non-empty `findings` set
    `report.healthy = false` and `process.exitCode = 1`. So a healthy repo was
    still handed `[driver] SocratiCode health findings:` once per UTC day by
    `socraticode-health.sh`, which keys its whole session injection on that exit
    code. The text no longer accused; the envelope still did.

    The fix keeps ONE `findings` array — a second `observations` array would be
    a JSON contract change every consumer would have to learn — and gates the
    exit code on a per-finding **severity** instead of on emptiness. A `note`
    is a measurement no action changes; a defect is a state a named action
    repairs. Suppressing the line on `ok` was rejected too: it discards a figure
    an operator may want, and #225's staleness finding needs somewhere to live.

    Severity is carried in the finding string itself (`note: …`) rather than in
    a new key or a new element type, so `findings` stays `string[]` and a
    consumer doing `jq -r '.findings[]'` keeps working.
    """

    @requires_node
    def test_a_neutral_statistic_alone_exits_zero(self, tmp_path: Path) -> None:
        project = tmp_path / "repo"
        project.mkdir()
        result, report = _health_check(
            tmp_path,
            project,
            {
                "codebase_health": HEALTH_OK,
                "codebase_status": STATUS_CLEAN,
                "codebase_graph_status": GRAPH_OK_HIGH_UNRESOLVED,
            },
        )
        assert report is not None, result.stdout + result.stderr
        assert result.returncode == 0, (
            "a verdict-`ok` graph with a high unresolvedPct still exited 1, so "
            "socraticode-health.sh still injects `SocratiCode health findings:` "
            f"into every session of a healthy repo (#220)\n{result.stderr}"
        )
        assert report["healthy"] is True, report

    @requires_node
    def test_the_statistic_is_not_discarded(self, tmp_path: Path) -> None:
        """The rejected option 3 was to drop the line on an `ok` verdict."""
        project = tmp_path / "repo"
        project.mkdir()
        _, report = _health_check(
            tmp_path,
            project,
            {
                "codebase_health": HEALTH_OK,
                "codebase_status": STATUS_CLEAN,
                "codebase_graph_status": GRAPH_OK_HIGH_UNRESOLVED,
            },
        )
        assert any("61.7%" in f for f in report["findings"]), (
            "the unresolvedPct figure vanished from the report. It is worth "
            f"having on a healthy graph too; only its cost changes: {report}"
        )

    @requires_node
    def test_the_note_says_it_is_one(self, tmp_path: Path) -> None:
        """`healthy: true` beside a populated `findings` needs an explanation.

        Without a per-entry marker a consumer reading the JSON is back where
        #220 started — a list called `findings` on a repo with nothing wrong.
        """
        project = tmp_path / "repo"
        project.mkdir()
        _, report = _health_check(
            tmp_path,
            project,
            {
                "codebase_health": HEALTH_OK,
                "codebase_status": STATUS_CLEAN,
                "codebase_graph_status": GRAPH_OK_HIGH_UNRESOLVED,
            },
        )
        line = next(f for f in report["findings"] if "61.7%" in f)
        assert line.startswith("note: "), (
            "the unresolvedPct entry carries no severity marker, so nothing in "
            f"the JSON distinguishes it from a defect: {line!r}"
        )

    @requires_node
    def test_a_real_defect_beside_it_still_exits_one(self, tmp_path: Path) -> None:
        """Severity gates the exit code; it must not soften a real finding."""
        project = tmp_path / "repo"
        project.mkdir()
        result, report = _health_check(
            tmp_path,
            project,
            {
                "codebase_health": HEALTH_DOWN,
                "codebase_status": STATUS_CLEAN,
                "codebase_graph_status": GRAPH_OK_HIGH_UNRESOLVED,
            },
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert report["healthy"] is False, report
        assert any("Qdrant" in f for f in report["findings"]), report

    @requires_node
    def test_the_note_keeps_its_marker_beside_a_defect(self, tmp_path: Path) -> None:
        """Severity is a property of the finding, not of the run."""
        project = tmp_path / "repo"
        project.mkdir()
        _, report = _health_check(
            tmp_path,
            project,
            {
                "codebase_health": HEALTH_DOWN,
                "codebase_status": STATUS_CLEAN,
                "codebase_graph_status": GRAPH_OK_HIGH_UNRESOLVED,
            },
        )
        note = next(f for f in report["findings"] if "61.7%" in f)
        defect = next(f for f in report["findings"] if "Qdrant" in f)
        assert note.startswith("note: "), note
        assert not defect.startswith("note: "), (
            f"an infrastructure failure was demoted to a note: {defect!r}"
        )

    @requires_node
    def test_the_hooks_defect_lines_exclude_the_note(self, tmp_path: Path) -> None:
        """`socraticode-health.sh` greps stderr for `  - ` and prints those.

        A note has to be legible there as a note, or the session injection
        reports a statistic under a heading that says findings — which is the
        sentence #220 was filed about, one layer down.
        """
        project = tmp_path / "repo"
        project.mkdir()
        result, _ = _health_check(
            tmp_path,
            project,
            {
                "codebase_health": HEALTH_DOWN,
                "codebase_status": STATUS_CLEAN,
                "codebase_graph_status": GRAPH_OK_HIGH_UNRESOLVED,
            },
        )
        bullets = [ln for ln in result.stderr.splitlines() if re.match(r"^\s+- ", ln)]
        assert any("Qdrant" in ln for ln in bullets), result.stderr
        stat = next(ln for ln in bullets if "61.7%" in ln)
        assert "note:" in stat, (
            "the hook would print this line under `findings from today's "
            f"once-per-day check` with nothing marking it a statistic: {stat!r}"
        )

    def test_the_doc_states_what_a_note_costs(self) -> None:
        """A reader who sees the line must be able to look up its price.

        Pinned as concepts rather than as a sentence, like every other pin on
        this section: the point is that the doc says the neutral reading is a
        note and that a note does not set the exit code, not that it says it in
        any particular words.
        """
        section = _flowed(_graph_health(DOC_REF.read_text())).lower()
        assert "note" in section and "exit code" in section, (
            f"references/{DOC_REF.name}'s **Graph health** section quotes the "
            "neutral `unresolvedPct` finding without saying it is a note and "
            "costs nothing — so a reader still cannot tell whether the daily "
            "hook will report it (#220)"
        )


# ── the builder, judged against the server answering the session (#305) ─────


def _plugin_config(tmp_path: Path, definition: dict, version: str = "1.13.1") -> Path:
    """A CLAUDE_CONFIG_DIR whose installed socraticode plugin has `definition`.

    Inline in plugin.json, the shape #309 follows and SocratiCode#180 will
    ship, so there is no second file for the fixture to keep in step.
    """
    config = tmp_path / "claude-config"
    install = config / "plugins" / "cache" / "socraticode" / "socraticode" / version
    (install / ".claude-plugin").mkdir(parents=True)
    (install / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "socraticode",
                "version": version,
                "mcpServers": {"socraticode": definition},
            }
        )
    )
    (config / "plugins" / "installed_plugins.json").write_text(
        json.dumps(
            {"plugins": {"socraticode@socraticode": [{"installPath": str(install)}]}}
        )
    )
    return config


def _graph_built_by(version: str) -> str:
    """GRAPH_REBUILT's healthy yield, stamped by `version`."""
    return GRAPH_REBUILT.replace("Built by: v1.13.1", f"Built by: v{version}")


def _builder_finding(
    graph_status: str, check: str | None, session: dict
) -> dict | None:
    """`graphBuilderFinding` over one status, a check-server version and a session."""
    script = (
        "import { parseGraphBuilder, graphBuilderFinding } from "
        f"{json.dumps(str(DRIVER))};"
        "process.stdout.write(JSON.stringify(graphBuilderFinding("
        f"parseGraphBuilder({json.dumps(graph_status)}, {json.dumps(check)}), "
        f"{json.dumps(session)})));"
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


def _session_server(
    launch: dict | None, plugin: dict | None, check: str | None
) -> dict:
    """`sessionServer` over a launch, a plugin definition and a handshake version."""
    script = (
        f"import {{ sessionServer }} from {json.dumps(str(DRIVER))};"
        "process.stdout.write(JSON.stringify(sessionServer({"
        f"launch: {json.dumps(launch)}, plugin: {json.dumps(plugin)}, "
        f"checkVersion: {json.dumps(check)}}})));"
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


FIXED_1131 = {"version": "1.13.1", "basis": "the plugin's definition fixes it"}
UNKNOWN = {"version": None, "basis": "the plugin launches 'socraticode@latest'"}
REPLIES_OK = {"codebase_health": HEALTH_OK, "codebase_status": STATUS_CLEAN}


class TestTheBuilderIsJudgedAgainstTheSessionsServer:
    """#305: the graph is rebuilt by the session's server, not by the driver's.

    #297's check compared the graph's builder against the server
    `mcp-driver.mjs` had just launched itself, and named `codebase_graph_build`.
    Under Claude Code that rebuild runs through the plugin's server, the one
    answering every `codebase_*` call in the session. On CannObserv/power-map
    the check read a graph that server had built at v1.13.1 against the
    driver's own v1.14.0 launch, called it a defect, and the rebuild — READY in
    5.8s — re-stamped v1.13.1, leaving the finding byte-identical.
    `socraticode-health.sh` keys on that exit code, so the hook stopped being
    silent-when-clean over a state no rebuild changes, and a reader who followed
    the remedy concluded the tool was broken.

    Three answers now, keyed on whether the session's server version is KNOWN:
    older than it is a defect with the rebuild; not older than it but older
    than the driver's is a note naming update → restart → rebuild; unknowable
    is a defect that says so and names the sequence that clears it either way.
    The last one must not be demoted — on today's common host the plugin's
    definition floats, and a graph cut long ago looks exactly like that.
    """

    @requires_node
    def test_plugin_lag_is_a_note_naming_the_real_remedy(self) -> None:
        """The power-map case, with the session's version known."""
        f = _builder_finding(_graph_built_by("1.13.1"), "1.14.0", FIXED_1131)
        assert f is not None and f["severity"] == "note", (
            "a graph built at exactly the session server's version is what that "
            "server would cut again: a rebuild re-stamps it, so a defect here can "
            f"never clear (#305)\n{f}"
        )
        for step in (
            "update the plugin",
            "restart Claude Code",
            "codebase_graph_build",
        ):
            assert step in f["message"], f"the note must name {step!r}: {f['message']}"
        assert "v1.13.1" in f["message"] and "v1.14.0" in f["message"], f["message"]

    @requires_node
    def test_a_graph_newer_than_the_session_is_not_a_defect_either(self) -> None:
        """Built by something newer than the session: a rebuild would go BACKWARD."""
        f = _builder_finding(_graph_built_by("1.13.2"), "1.14.0", FIXED_1131)
        assert f is not None and f["severity"] == "note", f

    @requires_node
    def test_a_graph_older_than_the_session_stays_a_defect(self) -> None:
        """#297's own case must survive: the rebuild repairs this one."""
        f = _builder_finding(_graph_built_by("1.12.0"), "1.14.0", FIXED_1131)
        assert f is not None and f["severity"] == "defect", f
        assert "codebase_graph_build" in f["message"], f["message"]
        assert "v1.13.1" in f["message"], (
            "the defect must name the version it was judged against — the "
            f"session's, not this check's: {f['message']}"
        )

    @requires_node
    def test_the_session_rules_even_where_the_check_server_is_behind(self) -> None:
        """A pin behind the session would call the graph current; the session does not.

        The check's own server is not what answers queries about the graph, so
        its opinion cannot certify one the session's server has moved past.
        """
        f = _builder_finding(
            _graph_built_by("1.13.1"),
            "1.13.1",
            {"version": "1.14.0", "basis": "the plugin's definition fixes it"},
        )
        assert f is not None and f["severity"] == "defect", f

    @requires_node
    def test_an_unknown_session_says_so_and_stays_a_defect(self) -> None:
        f = _builder_finding(_graph_built_by("1.13.1"), "1.14.0", UNKNOWN)
        assert f is not None and f["severity"] == "defect", (
            "demoting the undeterminable case would regress #297 wherever the "
            f"plugin floats, which is today's common host\n{f}"
        )
        assert "could not be determined" in f["message"], (
            "the finding asserts which server holds the graph without knowing: "
            f"{f['message']}"
        )
        assert "restart Claude Code" in f["message"], (
            "a rebuild alone cannot clear it when the session's server is the "
            f"lagging one — the sequence that can must be named: {f['message']}"
        )

    @requires_node
    @pytest.mark.parametrize(
        "built, check, session",
        [
            ("1.13.1", "1.13.1", FIXED_1131),
            ("1.13.1", "1.13.1", UNKNOWN),
            ("1.14.0", "1.13.1", FIXED_1131),
        ],
    )
    def test_a_current_graph_says_nothing(self, built, check, session) -> None:
        assert _builder_finding(_graph_built_by(built), check, session) is None

    @requires_node
    def test_an_exact_npx_spec_fixes_the_sessions_version(self) -> None:
        s = _session_server(
            {"source": "SOCRATICODE_ENTRY"},
            {"command": "npx", "args": ["-y", "socraticode@1.13.1"], "plugin": True},
            "1.14.0",
        )
        assert s["version"] == "1.13.1", s

    @requires_node
    def test_a_floating_spec_fixes_nothing(self) -> None:
        """The plugin's own version names the plugin, not what it launches."""
        s = _session_server(
            {"source": "plugin", "plugin": True},
            {
                "command": "npx",
                "args": ["-y", "--prefer-online", "socraticode@latest"],
                "plugin": True,
                "pluginVersion": "1.13.1",
            },
            "1.14.0",
        )
        assert s["version"] is None, (
            "a definition launching socraticode@latest runs whatever that "
            "resolved to when the session started — reading the plugin's "
            f"version as the server's is the misreading #305 was built on\n{s}"
        )
        assert "socraticode@latest" in s["basis"], s
        assert s["plugin"]["version"] == "1.13.1", "…still reported, as the plugin's"

    @requires_node
    def test_an_interpreter_and_path_reads_its_package(self, tmp_path: Path) -> None:
        """The pin's rule, applied to the session: the version is the package's own."""
        pkg = tmp_path / "engine" / "node_modules" / "socraticode"
        (pkg / "dist").mkdir(parents=True)
        (pkg / "dist" / "index.js").write_text("")
        (pkg / "package.json").write_text(
            json.dumps({"name": "socraticode", "version": "1.12.3"})
        )
        s = _session_server(
            {"source": "pinned install"},
            {"command": "/usr/bin/node", "args": [str(pkg / "dist" / "index.js")]},
            "1.14.0",
        )
        assert s["version"] == "1.12.3", s

    @requires_node
    def test_the_same_fixed_definition_takes_the_handshake(self) -> None:
        """When the check ran the session's own definition, the server said which."""
        s = _session_server(
            {"source": "plugin", "plugin": True},
            {"command": "npx", "args": ["-y", "socraticode@1.14.0"], "plugin": True},
            "1.14.0",
        )
        assert s["version"] == "1.14.0" and "launched too" in s["basis"], s

    @requires_node
    def test_no_plugin_is_stated_not_guessed(self) -> None:
        s = _session_server({"source": "SOCRATICODE_ENTRY"}, None, "1.14.0")
        assert s["version"] is None and "no Claude Code plugin" in s["basis"], s

    # ── end to end: the exit code, the JSON, and the hook ────────────────────

    @requires_node
    def test_plugin_lag_does_not_set_the_exit_code(self, tmp_path: Path) -> None:
        project = tmp_path / "repo"
        project.mkdir()
        config = _plugin_config(
            tmp_path, {"command": "npx", "args": ["-y", "socraticode@1.13.1"]}
        )
        result, report = _health_check(
            tmp_path,
            project,
            {**REPLIES_OK, "codebase_graph_status": _graph_built_by("1.13.1")},
            STUB_SERVER_VERSION="1.14.0",
            CLAUDE_CONFIG_DIR=str(config),
        )
        assert report is not None, result.stdout + result.stderr
        assert result.returncode == 0, (
            "a graph built by the session's own server version, behind only the "
            "driver's, still exits 1 — so socraticode-health.sh reports it every "
            f"day and no rebuild clears it (#305)\n{result.stderr}"
        )
        assert report["healthy"] is True, report
        note = next((f for f in report["findings"] if "built by v1.13.1" in f), None)
        assert note and note.startswith("note: "), report["findings"]

    @requires_node
    def test_the_json_names_both_servers_and_which_ruled(self, tmp_path: Path) -> None:
        project = tmp_path / "repo"
        project.mkdir()
        config = _plugin_config(
            tmp_path, {"command": "npx", "args": ["-y", "socraticode@1.13.1"]}
        )
        _, report = _health_check(
            tmp_path,
            project,
            {**REPLIES_OK, "codebase_graph_status": _graph_built_by("1.13.1")},
            STUB_SERVER_VERSION="1.14.0",
            CLAUDE_CONFIG_DIR=str(config),
        )
        assert report["server"]["version"] == "1.14.0", report["server"]
        assert report["sessionServer"]["version"] == "1.13.1", report["sessionServer"]
        assert report["graph"]["builderCheck"] == {
            "builtBy": "1.13.1",
            "checkServer": "1.14.0",
            "sessionServer": "1.13.1",
            "ruledBy": "sessionServer",
        }, report["graph"]

    @requires_node
    def test_a_genuinely_stale_graph_still_exits_one(self, tmp_path: Path) -> None:
        project = tmp_path / "repo"
        project.mkdir()
        config = _plugin_config(
            tmp_path, {"command": "npx", "args": ["-y", "socraticode@1.14.0"]}
        )
        result, report = _health_check(
            tmp_path,
            project,
            {**REPLIES_OK, "codebase_graph_status": _graph_built_by("1.13.1")},
            STUB_SERVER_VERSION="1.14.0",
            CLAUDE_CONFIG_DIR=str(config),
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert report["healthy"] is False, report

    @requires_node
    @pytest.mark.parametrize("lagging", [True, False], ids=["plugin-lag", "stale"])
    def test_the_hook_is_silent_on_plugin_lag_only(
        self, tmp_path: Path, lagging: bool
    ) -> None:
        """What #305 is about, measured at the surface an operator sees.

        `socraticode-health.sh` injects findings into the session only when the
        driver reports a defect. A plugin that lags the driver is a note, so the
        hook says nothing; a graph older than the session's own server is still
        reported, so the split has not silenced #297.
        """
        repo = _repo(tmp_path)
        # A manifest the real driver accepts, with its one artifact indexed and
        # fresh: `_repo`'s empty list is enough for the hook's gate but is a
        # defect of its own to the driver, which would speak for it.
        (repo / "README.md").write_text("readme\n")
        (repo / ".socraticodecontextartifacts.json").write_text(
            json.dumps(
                {
                    "artifacts": [
                        {"name": "readme", "path": "README.md", "description": "d"}
                    ]
                }
            )
        )
        stub = tmp_path / "stub-server.mjs"
        stub.write_text(STUB_SERVER)
        replies = tmp_path / "replies.json"
        replies.write_text(
            json.dumps(
                {
                    **REPLIES_OK,
                    "codebase_graph_status": _graph_built_by("1.13.1"),
                    "codebase_context": (
                        "━━━ readme ━━━\n  Path: ./README.md\n  Description: d\n"
                        "  Status: ✓ indexed (1 chunks, 2099-01-01T00:00:00.000Z)\n"
                    ),
                }
            )
        )
        session = "1.13.1" if lagging else "1.14.0"
        config = _plugin_config(
            tmp_path, {"command": "npx", "args": ["-y", f"socraticode@{session}"]}
        )
        result = _run_hook(
            repo,
            SOCRATICODE_DRIVER=str(DRIVER),
            SOCRATICODE_ENTRY=str(stub),
            STUB_REPLIES=str(replies),
            STUB_SERVER_VERSION="1.14.0",
            CLAUDE_CONFIG_DIR=str(config),
        )
        assert result.returncode == 0, result.stderr
        if lagging:
            assert result.stdout == "", (
                "the hook injected a plugin-lag note into the session as a "
                f"finding (#305):\n{result.stdout}"
            )
        else:
            assert "built by v1.13.1" in result.stdout, (
                "a graph older than the session's own server must still reach "
                f"the session (#297):\n{result.stdout}\n{result.stderr}"
            )


class TestSkillGatesOnYield:
    """Phase 6 must stop declaring victory on a status token."""

    def test_phase_six_names_yield(self) -> None:
        body = SKILL_MD.read_text()
        assert "health-check" in body, (
            "SKILL.md must run `mcp-driver.mjs health-check` — Phase 6's graph "
            "gate is a yield measurement now, not a READY check"
        )
        assert "yield" in body.lower(), "SKILL.md must name the yield gate"

    def test_ready_is_qualified_wherever_it_is_claimed(self) -> None:
        """`graph READY` unqualified is the defect; it must not stand alone."""
        body = SKILL_MD.read_text()
        assert "READY is a status, not a result" in body or (
            "READY" in body and "yield" in body.lower()
        ), (
            "SKILL.md still presents `graph READY` as a completion signal with "
            "no mention of yield (#107)"
        )

    def test_degraded_policy_is_reachable_from_the_gate(self) -> None:
        body = SKILL_MD.read_text()
        assert "variant B" in body or "degraded" in body.lower(), (
            "the yield gate has to lead somewhere: on a LOW verdict Phase 6 "
            "must re-run Phase 3 with the degraded policy variant"
        )
        assert "Variant B — degraded" in POLICY_REF.read_text(), (
            "the degraded variant the SKILL.md gate routes to must exist in "
            "references/code-exploration-policy.md"
        )

    def test_failed_last_operation_is_surfaced(self) -> None:
        body = SKILL_MD.read_text()
        assert "last operation" in body.lower() and "fail" in body.lower(), (
            "#107 found an 'Incremental update — FAILED (fetch failed)' sitting "
            "unreported for ~21h behind three green lights; Phase 6 must read "
            "codebase_status for it"
        )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=t",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )


def _repo(tmp_path: Path, *, manifest: bool = True, commit: bool = False) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "init", "-q"],
        check=True,
        capture_output=True,
        env=_clean_env(),
    )
    if manifest:
        (repo / ".socraticodecontextartifacts.json").write_text('{"artifacts": []}')
    if commit:
        # The manifest is TRACKED, which is the whole reason the `-f` guard
        # cannot tell a worktree apart from an unindexed repo (#180).
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
    return repo


def _worktree(repo: Path, tmp_path: Path, name: str = "wt") -> Path:
    path = tmp_path / name
    _git(repo, "worktree", "add", "-q", "-b", name, str(path))
    return path


def _arg_recording_driver(repo: Path) -> Path:
    """A stub that records the argv the hook handed it, and reports nothing."""
    stub = repo / "record-args.mjs"
    stub.write_text(
        "import { writeFileSync } from 'node:fs';\n"
        "writeFileSync(process.env.HEALTH_ARGS_OUT, "
        "process.argv.slice(2).join('\\n'));\n"
        "process.exit(0);\n"
    )
    return stub


def _stub_driver(repo: Path, *, exit_code: int, findings: str = "") -> Path:
    """A node script standing in for mcp-driver.mjs health-check."""
    stub = repo / "stub-driver.mjs"
    stub.write_text(
        "process.stdout.write(JSON.stringify({healthy: false}));\n"
        f"process.stderr.write({json.dumps(findings)});\n"
        f"process.exit({exit_code});\n"
    )
    return stub


def _run_hook(repo: Path, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HOOK)],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=60,
        env=_clean_env(**env),
    )


class TestHealthHook:
    """Contract of the once-per-day SessionStart hook."""

    FINDINGS = (
        "[driver] SocratiCode health findings:\n"
        "  - graph yield LOW — 3 edge(s) across 374 files = 0.008 edges/file\n"
        "  - last operation FAILED: fetch failed\n"
    )

    def test_help_exits_zero(self) -> None:
        result = subprocess.run(
            ["bash", str(HOOK), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            env=_clean_env(),
        )
        assert result.returncode == 0
        assert "once-per-day" in result.stdout.lower()

    def test_silent_when_repo_was_never_indexed(self, tmp_path: Path) -> None:
        """No manifest means init-socraticode never ran here."""
        repo = _repo(tmp_path, manifest=False)
        result = _run_hook(repo)
        assert result.returncode == 0
        assert result.stdout == "", (
            "a repo that never adopted SocratiCode must hear nothing from this "
            f"hook; got {result.stdout!r}"
        )

    # A missing driver was pinned silent here, as a condition the hook cannot
    # judge. Past the manifest gate it can, and it now reports it (#281) — see
    # test_health_configured_gaps.py, which also keeps the no-manifest case
    # above silent under a missing driver and a missing node.

    @requires_node
    def test_reports_findings_once_per_day(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        stub = _stub_driver(repo, exit_code=1, findings=self.FINDINGS)

        first = _run_hook(repo, SOCRATICODE_DRIVER=str(stub))
        assert first.returncode == 0, first.stderr
        assert "graph yield LOW" in first.stdout, first.stdout
        assert "last operation FAILED" in first.stdout, first.stdout
        assert "reports only" in first.stdout, (
            "the hook must say it will not act — an agent that reads a finding "
            "and starts a two-hour re-index at session start is worse than the "
            "finding"
        )

        second = _run_hook(repo, SOCRATICODE_DRIVER=str(stub))
        assert second.returncode == 0
        assert second.stdout == "", (
            "the UTC-day lock must suppress the second run of the same day; "
            f"got {second.stdout!r}"
        )

    @requires_node
    def test_silent_when_healthy(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        stub = _stub_driver(repo, exit_code=0)
        result = _run_hook(repo, SOCRATICODE_DRIVER=str(stub))
        assert result.returncode == 0
        assert result.stdout == "", (
            f"a healthy check must add nothing to session context; got {result.stdout!r}"
        )

    @requires_node
    def test_exits_zero_when_the_driver_crashes(self, tmp_path: Path) -> None:
        """A SessionStart hook that fails closed takes the session with it."""
        repo = _repo(tmp_path)
        stub = repo / "boom.mjs"
        stub.write_text("throw new Error('boom');\n")
        result = _run_hook(repo, SOCRATICODE_DRIVER=str(stub))
        assert result.returncode == 0, (
            f"hook exited {result.returncode} on a crashing driver: {result.stderr}"
        )

    @requires_node
    def test_lock_is_stamped_even_when_the_check_fails(self, tmp_path: Path) -> None:
        """Same trade the submodule hook makes: a transient failure defers to
        tomorrow rather than re-running on every session today."""
        repo = _repo(tmp_path)
        stub = repo / "boom.mjs"
        stub.write_text("process.exit(3);\n")
        _run_hook(repo, SOCRATICODE_DRIVER=str(stub))
        lock = repo / ".git" / "socraticode-health.lock"
        assert lock.exists() and lock.read_text().strip(), (
            "the lock must be stamped before the check runs"
        )

    @requires_node
    @pytest.mark.parametrize(
        "body, id_",
        [("process.exit(1);\n", "clean-exit"), ("throw new Error('boom');\n", "crash")],
    )
    def test_the_findings_scratch_file_never_survives(
        self, tmp_path: Path, body: str, id_: str
    ) -> None:
        """It lives in the COMMON git dir now (#180), shared by every checkout.

        A leftover is not cosmetic there: `git status` does not see inside
        `.git`, so an orphan from a crashed run accumulates unnoticed in the
        directory every worktree of the repo also writes to.
        """
        repo = _repo(tmp_path)
        stub = repo / "stub.mjs"
        stub.write_text(body)
        _run_hook(repo, SOCRATICODE_DRIVER=str(stub))
        leftovers = list((repo / ".git").glob("socraticode-health.findings*"))
        assert leftovers == [], f"{id_}: left {leftovers} behind in .git"

    @requires_node
    def test_force_bypasses_the_lock(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        stub = _stub_driver(repo, exit_code=1, findings=self.FINDINGS)
        _run_hook(repo, SOCRATICODE_DRIVER=str(stub))
        forced = _run_hook(
            repo, SOCRATICODE_DRIVER=str(stub), SOCRATICODE_HEALTH_FORCE="1"
        )
        assert "graph yield LOW" in forced.stdout


class TestHookMeasuresTheIndexedProject:
    """The hook must ask about the path SocratiCode actually indexed (#180).

    SocratiCode indexes by ABSOLUTE project path, and a `git worktree` is a
    different absolute path. The hook passed the literal `.`, so from any
    worktree it asked about a project that was never indexed and reported
    `graph is not READY` on a repo whose index is perfectly healthy — verified
    on CannObserv/replicator, same index and same day, `ok` from the main
    checkout and broken from a worktree.

    The `-f .socraticodecontextartifacts.json` guard does not catch it: the
    manifest is tracked, so it is present in every worktree. And this lands on
    the workflow the cohort is pushed toward — repos that deploy from their
    main checkout are told to do feature work in worktrees, so the false report
    is the COMMON case. A once-per-day reporter that cries wolf on most
    sessions gets tuned out, and then the one true finding scrolls past too.

    **Three halves of one property, pinned together on purpose (#226).** #180
    fixed the hook. It left `references/socraticode-doc.md` handing a reader
    `health-check .` two sections above the hook it describes — the literal
    #180 removed — and left every consumer who had already copied that line
    into their own `docs/` broken. Fixing only the doc leaves the copies; fixing
    only the driver leaves the doc teaching a spelling that happens to work for
    reasons the reader cannot see. So the driver resolves a relative argument
    the way the hook does, the doc shows the explicit spelling, and both are
    asserted here against the same worktree fixtures rather than against a
    second set that could drift from these.

    The failure is worse under a hand-run than under the hook: the hook is
    unattended and silent when clean, whereas a human runs the documented
    command precisely when they already suspect the graph — and is handed
    confirmation of a problem that does not exist.
    """

    @staticmethod
    def _validated(cwd: Path, *args: str) -> tuple:
        """`validate-manifest` names the path it resolved, with no server.

        The cheapest observation of the driver's own resolution: it prints the
        manifest path it is about to stat, needs no Docker, no network and no
        MCP server, and shares its argv handling with every other command.
        """
        result = subprocess.run(
            ["node", str(DRIVER), "validate-manifest", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(),
        )
        return result, json.loads(result.stdout)

    @staticmethod
    def _measured(cwd: Path, stub: Path, out: Path, **env: str) -> str:
        result = subprocess.run(
            ["bash", str(HOOK)],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
            env=_clean_env(
                SOCRATICODE_DRIVER=str(stub), HEALTH_ARGS_OUT=str(out), **env
            ),
        )
        assert result.returncode == 0, result.stderr
        assert out.exists(), (
            f"the driver never ran: {result.stdout!r} / {result.stderr!r}"
        )
        return out.read_text().splitlines()[-1]

    @requires_node
    def test_a_worktree_session_measures_the_main_checkout(
        self, tmp_path: Path
    ) -> None:
        repo = _repo(tmp_path, commit=True)
        wt = _worktree(repo, tmp_path)
        stub = _arg_recording_driver(repo)
        measured = self._measured(wt, stub, tmp_path / "args.txt")
        assert Path(measured).resolve() == repo.resolve(), (
            "from a worktree the hook measured the worktree's own path, which "
            "SocratiCode never indexed, so a healthy index reports as broken "
            f"(#180). Measured {measured!r}, expected {str(repo.resolve())!r}"
        )

    @requires_node
    def test_the_main_checkout_still_measures_itself(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, commit=True)
        stub = _arg_recording_driver(repo)
        measured = self._measured(repo, stub, tmp_path / "args.txt")
        assert Path(measured).resolve() == repo.resolve(), (
            f"the main checkout must measure itself; got {measured!r}"
        )

    @requires_node
    def test_the_probe_flag_survives_the_path_change(self, tmp_path: Path) -> None:
        """projectPath is positional; --probe must still precede it."""
        repo = _repo(tmp_path, commit=True)
        stub = _arg_recording_driver(repo)
        out = tmp_path / "args.txt"
        self._measured(repo, stub, out, SOCRATICODE_PROBE_FILE="src/app.py")
        assert out.read_text().splitlines()[:3] == [
            "health-check",
            "--probe",
            "src/app.py",
        ], out.read_text()

    @requires_node
    def test_the_daily_lock_is_shared_with_the_main_checkout(
        self, tmp_path: Path
    ) -> None:
        """One project, one report per day — not one per checkout of it.

        Once every worktree measures the SAME project, a per-worktree lock
        turns one finding into N identical reports a day, which is the
        tuned-out failure this fix exists to stop.
        """
        repo = _repo(tmp_path, commit=True)
        wt = _worktree(repo, tmp_path)
        stub = _stub_driver(repo, exit_code=1, findings=TestHealthHook.FINDINGS)

        first = _run_hook(repo, SOCRATICODE_DRIVER=str(stub))
        assert "graph yield LOW" in first.stdout, first.stdout
        second = _run_hook(wt, SOCRATICODE_DRIVER=str(stub))
        assert second.stdout == "", (
            "a worktree session re-reported a finding the main checkout had "
            f"already reported today; got {second.stdout!r}"
        )

    # ── the driver half (#226) ───────────────────────────────────────────────

    @requires_node
    def test_a_relative_argument_resolves_to_the_main_checkout(
        self, tmp_path: Path
    ) -> None:
        """`health-check .` from a worktree must not name the worktree.

        This is the line consumers copied out of the doc before #180, and it is
        still live in their `docs/`. The hook can only fix its own invocation;
        the driver fixes theirs.
        """
        repo = _repo(tmp_path, commit=True)
        wt = _worktree(repo, tmp_path)
        _, report = self._validated(wt, ".")
        assert Path(report["manifest"]).parent.resolve() == repo.resolve(), (
            "a relative path argument was resolved against the worktree, which "
            "SocratiCode never indexed — the confident wrong answer #180 "
            f"removed from the hook (#226). Got {report['manifest']!r}"
        )

    @requires_node
    def test_no_argument_resolves_the_same_way(self, tmp_path: Path) -> None:
        """`projectPath defaults to the current working directory` is `.`."""
        repo = _repo(tmp_path, commit=True)
        wt = _worktree(repo, tmp_path)
        _, report = self._validated(wt)
        assert Path(report["manifest"]).parent.resolve() == repo.resolve(), (
            "an omitted argument defaults to cwd and must take the same route "
            f"as an explicit `.`; got {report['manifest']!r}"
        )

    @requires_node
    def test_an_absolute_argument_is_taken_verbatim(self, tmp_path: Path) -> None:
        """The escape hatch, and the hook's own contract.

        `socraticode-health.sh` resolves the main checkout itself and passes it
        absolute. If the driver remapped absolute paths too the hook would
        still be right by luck — and an operator deliberately asking about a
        worktree would have no way to say so.
        """
        repo = _repo(tmp_path, commit=True)
        wt = _worktree(repo, tmp_path)
        _, report = self._validated(repo, str(wt))
        assert Path(report["manifest"]).parent.resolve() == wt.resolve(), (
            "an absolute argument was rewritten. It is the only spelling that "
            f"can name a worktree on purpose; got {report['manifest']!r}"
        )

    @requires_node
    def test_the_main_checkout_still_resolves_to_itself(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, commit=True)
        _, report = self._validated(repo, ".")
        assert Path(report["manifest"]).parent.resolve() == repo.resolve(), (
            f"the main checkout must resolve to itself; got {report['manifest']!r}"
        )

    @requires_node
    def test_a_directory_outside_a_repo_is_left_alone(self, tmp_path: Path) -> None:
        """No git, no remap. The driver is not only ever run inside a repo."""
        plain = tmp_path / "plain"
        plain.mkdir()
        _, report = self._validated(plain, ".")
        assert Path(report["manifest"]).parent.resolve() == plain.resolve(), (
            f"a non-repo directory was rewritten; got {report['manifest']!r}"
        )

    @requires_node
    def test_a_subdirectory_resolves_to_the_checkout_root(self, tmp_path: Path) -> None:
        """`.` inside `src/` is the same class of wrong answer as `.` in a worktree.

        SocratiCode indexes the project root; a subdirectory is a path it never
        saw, and `resolve()` alone would hand it over intact.
        """
        repo = _repo(tmp_path, commit=True)
        (repo / "src").mkdir()
        _, report = self._validated(repo / "src", ".")
        assert Path(report["manifest"]).parent.resolve() == repo.resolve(), (
            f"a subdirectory was measured as its own project; got {report['manifest']!r}"
        )

    @requires_node
    def test_the_substitution_is_announced(self, tmp_path: Path) -> None:
        """A silent path rewrite is the same disease in the other direction.

        The driver would then be answering about a path the caller did not
        name, with nothing in the output saying so.
        """
        repo = _repo(tmp_path, commit=True)
        wt = _worktree(repo, tmp_path)
        result, _ = self._validated(wt, ".")
        assert str(repo.resolve()) in result.stderr, (
            "the driver silently measured a different path than the one it was "
            f"given; stderr said: {result.stderr!r}"
        )

    @requires_node
    def test_no_announcement_when_nothing_moved(self, tmp_path: Path) -> None:
        """A line printed on every run is a line nobody reads."""
        repo = _repo(tmp_path, commit=True)
        result, _ = self._validated(repo, ".")
        assert "worktree" not in result.stderr.lower(), (
            f"the no-op resolution announced itself; stderr: {result.stderr!r}"
        )

    # ── the doc half (#226) ──────────────────────────────────────────────────

    def test_the_doc_does_not_hand_a_reader_the_literal_dot(self) -> None:
        section = _graph_health(DOC_REF.read_text())
        assert not re.search(r"health-check\s+\.\s*$", section, re.M), (
            f"references/{DOC_REF.name}'s **Graph health** section still "
            "documents `health-check .` — the exact argument #180 removed from "
            "socraticode-health.sh two sections below it. From a worktree that "
            "asks about a project SocratiCode never indexed and reports a "
            "healthy index as broken (#226)."
        )

    def test_the_doc_shows_the_resolution_the_hook_uses(self) -> None:
        """`--show-toplevel` is the near miss, and it is wrong in a worktree.

        It yields the worktree root, not the main checkout, so a doc that
        reached for the obvious spelling would still name an unindexed path.
        """
        section = _graph_health(DOC_REF.read_text())
        assert "--git-common-dir" in section, (
            f"references/{DOC_REF.name}'s **Graph health** section must show "
            "the same resolution `socraticode-health.sh` uses — dirname of "
            "`git rev-parse --path-format=absolute --git-common-dir`. "
            "`--show-toplevel` is the plausible-looking wrong answer: in a "
            "worktree it names the worktree (#226)."
        )


class TestHookPrefersTheRealDriver:
    """Resolution must prefer `skills-vendor/*/…` over the symlink dirs (#177).

    `skills/init-socraticode/scripts/mcp-driver.mjs` and
    `.claude/skills/init-socraticode/scripts/mcp-driver.mjs` are both symlinks
    into `skills-vendor/`. They resolve to the same file, so preferring the
    vendor path costs nothing — and it keeps the hook working against a
    consumer whose vendored driver predates the #177 fix, which is exactly the
    population that cannot report its own silence.
    """

    @staticmethod
    def _plant(repo: Path, rel: str, marker: str) -> Path:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"process.stderr.write({json.dumps(f'  - {marker}' + chr(10))});\n"
            "process.exit(1);\n"
        )
        return path

    @requires_node
    def test_vendor_wins_over_the_symlink_dirs(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        self._plant(
            repo,
            "skills-vendor/gregoryfoster-skills/skills/init-socraticode/scripts/mcp-driver.mjs",
            "resolved via skills-vendor",
        )
        for rel in (
            "skills/init-socraticode/scripts/mcp-driver.mjs",
            ".claude/skills/init-socraticode/scripts/mcp-driver.mjs",
        ):
            self._plant(repo, rel, "resolved via a symlink dir")

        result = _run_hook(repo)
        assert result.returncode == 0, result.stderr
        assert "resolved via skills-vendor" in result.stdout, (
            "the hook resolved a symlink-dir candidate ahead of the real "
            f"skills-vendor path (#177); got {result.stdout!r}"
        )

    @requires_node
    def test_env_override_still_wins(self, tmp_path: Path) -> None:
        """Reordering must not demote the one-off override to second place."""
        repo = _repo(tmp_path)
        self._plant(
            repo,
            "skills-vendor/gregoryfoster-skills/skills/init-socraticode/scripts/mcp-driver.mjs",
            "resolved via skills-vendor",
        )
        stub = _stub_driver(repo, exit_code=1, findings="  - resolved via env\n")
        result = _run_hook(repo, SOCRATICODE_DRIVER=str(stub))
        assert "resolved via env" in result.stdout, result.stdout

    def test_help_documents_the_order_it_uses(self) -> None:
        """The --help block is the only place the order is stated in prose."""
        body = HOOK.read_text()
        start = body.index("Resolution of the driver")
        block = [
            line.split(". ", 1)[-1].strip()
            for line in body[start : body.index("Env:", start)].splitlines()
        ]
        vendor = block.index(
            "skills-vendor/*/skills/init-socraticode/scripts/mcp-driver.mjs"
        )
        symlinked = block.index("skills/init-socraticode/scripts/mcp-driver.mjs")
        assert vendor < symlinked, (
            "socraticode-health.sh --help still lists the symlink candidates "
            "ahead of skills-vendor/*/ — the documented order and the loop "
            "must agree, and both must prefer the real path (#177)"
        )


def _health_hook_install_step() -> str:
    """Step C of the policy reference — where the install is actually written.

    #179 attributes this prose to `SKILL.md` Phase 3 step C. SKILL.md has no
    lettered steps; Phase 3 item 3 delegates to
    `references/code-exploration-policy.md`, which is where Step C lives.
    """
    body = POLICY_REF.read_text()
    start = body.index("**Step C —")
    return body[start : body.index("**It reports; it does not repair.**", start)]


class TestHookIsInstalled:
    """A hook nothing installs is a file, not a cadence."""

    def test_skill_md_installs_it(self) -> None:
        body = SKILL_MD.read_text()
        assert "socraticode-health.sh" in body, (
            "SKILL.md Phase 3 must install .claude/hooks/socraticode-health.sh "
            "— #107 ask 2 is a cadence, and a script the skill never wires up "
            "runs zero times"
        )

    def test_it_is_installed_as_a_symlink_not_a_copy(self) -> None:
        """#179: two vendored hooks in one `.claude/hooks/` installed by
        opposite mechanisms.

        `managing-skills` installs its sibling refresh hook as a symlink into
        the vendor, so upstream fixes arrive on the normal submodule refresh.
        This skill said *copy*, which freezes at the day of install and drifts
        silently — and `.skills/doctor.sh` scans for DANGLING symlinks, so a
        copy is a valid regular file it can never see. On a hook that is silent
        when clean, a stale copy that has stopped detecting something is
        indistinguishable from a healthy install.
        """
        step = _health_hook_install_step()
        assert "ln -s" in step, (
            "the health hook install step must create a symlink into "
            "skills-vendor/, the way managing-skills installs its sibling "
            f"refresh hook (#179).\n---\n{step}"
        )
        assert not re.search(r"^\*\*Step C[^*]*\*\*\s*Copy", step), (
            "the install step still leads with an unconditional Copy (#179)"
        )

    def test_the_copy_is_retained_as_the_fallback(self) -> None:
        """A consumer with no `skills-vendor/` tree has nothing to point at.

        The hook's own driver resolution already makes exactly this branch, so
        the shape is established rather than invented here.
        """
        step = _health_hook_install_step()
        assert "copy" in step.lower(), (
            "the copy must survive as the fallback for a consumer that does "
            f"not vendor via managing-skills (#179).\n---\n{step}"
        )

    def test_skill_md_does_not_contradict_the_reference(self) -> None:
        """The contradiction is what let one cohort repo end up with one hook
        of each kind in the same directory."""
        body = SKILL_MD.read_text()
        idx = body.index(".claude/hooks/socraticode-health.sh")
        window = body[idx : idx + 500]
        assert "symlink" in window.lower(), (
            "SKILL.md Phase 3 still describes the health hook as a copy while "
            f"the reference installs a symlink (#179).\n---\n{window}"
        )

    def test_managing_skills_still_states_the_rule_being_matched(self) -> None:
        """Read-only anchor. If the sibling ever stops installing a symlink,
        this alignment is stale and the failure should say so here rather than
        surface as two skills disagreeing again."""
        ms = (REPO_ROOT / "skills" / "managing-skills" / "SKILL.md").read_text()
        assert "a symlink into the vendor" in ms, (
            "managing-skills no longer states the symlink rule this skill was "
            "aligned to (#179) — re-check both before trusting either"
        )

    def test_dedupe_marker_is_distinct_from_the_prefetch_hook(self) -> None:
        """Both hooks land in the same SessionStart array."""
        body = SKILL_MD.read_text()
        assert "socraticode-health" in body and "socraticode-prefetch" in body, (
            "the two SessionStart entries need distinct dedupe markers or the "
            "prefetch hook's scan will match the health hook and skip one"
        )
