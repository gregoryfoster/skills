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
  narrow and worth pinning: silent when there is nothing to say, silent when it
  cannot judge, exit 0 on every path including the ones that fail.

The node tests skip loudly when node is absent, the way `TestShellcheck` skips
on a missing binary. No network, no Docker, no MCP server: the driver is
imported for its parsers, and the hook is pointed at a stub.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "skills" / "init-socraticode" / "scripts"
DRIVER = SCRIPTS / "mcp-driver.mjs"
SELFTEST = SCRIPTS / "parser-selftest.mjs"
HOOK = SCRIPTS / "socraticode-health.sh"
SKILL_MD = REPO_ROOT / "skills" / "init-socraticode" / "SKILL.md"
POLICY_REF = (
    REPO_ROOT / "skills" / "init-socraticode" / "references" / "code-exploration-policy.md"
)

requires_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is required to exercise mcp-driver.mjs's parsers",
)


def _clean_env(**extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("SOCRATICODE_DRIVER", "SOCRATICODE_PROBE_FILE",
              "HEALTH_TIMEOUT_MS", "SOCRATICODE_HEALTH_FORCE"):
        env.pop(k, None)
    env.update(extra)
    return env


class TestParserSelftestRuns:
    """The fixture tripwire is now pulled automatically."""

    @requires_node
    def test_selftest_passes(self) -> None:
        result = subprocess.run(
            ["node", str(SELFTEST)],
            capture_output=True, text=True, timeout=60, env=_clean_env(),
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
            capture_output=True, text=True, timeout=60, env=_clean_env(),
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
            capture_output=True, text=True, timeout=60, env=_clean_env(),
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
            capture_output=True, text=True, timeout=60, env=_clean_env(),
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
            capture_output=True, text=True, timeout=60, env=_clean_env(),
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
            capture_output=True, text=True, timeout=60, env=_clean_env(),
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
            capture_output=True, text=True, timeout=60, env=_clean_env(),
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
            pytest.param("Status: READY\nFiles (nodes): 6\nDependencies (edges): 0",
                         id="too-few-files-to-judge"),
            pytest.param("Status: BUILDING", id="unparseable"),
        ],
    )
    def test_unknown_is_not_folded_into_low(self, graph_status: str) -> None:
        """Writing the degraded policy asserts a repo's graph is broken.

        Asserting that from a status we could not read, or from a repo too small
        to judge, is the same class of error the gate exists to catch.
        """
        assert self._yield(graph_status)["verdict"] == "unknown"


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


def _repo(tmp_path: Path, *, manifest: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"],
                   check=True, capture_output=True, env=_clean_env())
    if manifest:
        (repo / ".socraticodecontextartifacts.json").write_text('{"artifacts": []}')
    return repo


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
        cwd=str(repo), capture_output=True, text=True, timeout=60,
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
            capture_output=True, text=True, timeout=30, env=_clean_env(),
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

    def test_silent_when_the_driver_is_missing(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = _run_hook(repo, SOCRATICODE_DRIVER="/nonexistent/driver.mjs")
        assert result.returncode == 0
        assert result.stdout == "", (
            "an unresolvable driver is a condition the hook cannot judge, not a "
            "finding to announce at session start"
        )

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
    def test_force_bypasses_the_lock(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        stub = _stub_driver(repo, exit_code=1, findings=self.FINDINGS)
        _run_hook(repo, SOCRATICODE_DRIVER=str(stub))
        forced = _run_hook(
            repo, SOCRATICODE_DRIVER=str(stub), SOCRATICODE_HEALTH_FORCE="1"
        )
        assert "graph yield LOW" in forced.stdout


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
            for line in body[start:body.index("Env:", start)].splitlines()
        ]
        vendor = block.index("skills-vendor/*/skills/init-socraticode/scripts/mcp-driver.mjs")
        symlinked = block.index("skills/init-socraticode/scripts/mcp-driver.mjs")
        assert vendor < symlinked, (
            "socraticode-health.sh --help still lists the symlink candidates "
            "ahead of skills-vendor/*/ — the documented order and the loop "
            "must agree, and both must prefer the real path (#177)"
        )


class TestHookIsInstalled:
    """A hook nothing installs is a file, not a cadence."""

    def test_skill_md_installs_it(self) -> None:
        body = SKILL_MD.read_text()
        assert "socraticode-health.sh" in body, (
            "SKILL.md Phase 3 must install .claude/hooks/socraticode-health.sh "
            "— #107 ask 2 is a cadence, and a script the skill never wires up "
            "runs zero times"
        )

    def test_dedupe_marker_is_distinct_from_the_prefetch_hook(self) -> None:
        """Both hooks land in the same SessionStart array."""
        body = SKILL_MD.read_text()
        assert "socraticode-health" in body and "socraticode-prefetch" in body, (
            "the two SessionStart entries need distinct dedupe markers or the "
            "prefetch hook's scan will match the health hook and skip one"
        )
