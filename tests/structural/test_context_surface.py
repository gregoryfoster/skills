"""Behavioral tests for curating-context's measurement scripts (#91).

Exercises the scripts end-to-end against throwaway git repos. Every case here
is a regression for a defect found in review, not a hypothetical:

- A symlinked CLAUDE.md (the cohort norm) made `git show HEAD:CLAUDE.md` return
  the link target string, eleven bytes, so PREV sat near zero, the
  quiet-on-reduction branch was unreachable, and a measured 60% reduction was
  reported as "+17,181 since HEAD".
- The mirror case: a path that was a symlink at HEAD and is a real file now.
- The docs-dir knob, without which a repo not using docs/ gets a correct weekly
  measurement and two continuous surfaces that silently classify nothing.
- An empty policy file divided by zero, emitted a bare "{" on stdout, and exited
  1 — documented as a usage error for what is an infrastructure failure.
- cohort-report.sh computed `net` across a measurement-method change, reporting
  +2743 for a file whose rows record an identical byte count.
- The guard is installed as a symlink, so it must resolve the link chain to find
  _context-lib.sh; dirname "$0" yields .claude/hooks/, which holds no library.

No API calls: every path here uses the offline estimate.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "curating-context"
    / "scripts"
)
GUARD = SCRIPTS / "context-budget-guard.sh"
DELTA = SCRIPTS / "context-delta.sh"
MEASURE = SCRIPTS / "measure-context.sh"
COHORT = SCRIPTS / "cohort-report.sh"
INSTALL = SCRIPTS / "install-guard.sh"
LIB = SCRIPTS / "_context-lib.sh"

# ~2.7 bytes/token, so this is comfortably over the 6000 policy budget.
POLICY_LINE = "- a policy line naming `some/path.py` and explaining why\n"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — the same precaution the doctor and
    worktree tests take. Pre-commit sets GIT_INDEX_FILE and friends, which leak
    into the scripts' own git calls and confuse them."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    # These knobs are read from the environment ahead of the .skills files, so a
    # developer with them exported would otherwise change the assertions.
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env=_clean_env(),
    )


def _repo(tmp_path: Path, policy_lines: int = 2000) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "AGENTS.md").write_text(POLICY_LINE * policy_lines)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _run_guard(repo: Path, file_path: Path) -> str:
    """Feed the guard a PostToolUse payload; return its stdout."""
    payload = json.dumps(
        {"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}
    )
    result = subprocess.run(
        ["bash", str(GUARD)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=30,
    )
    # The guard's contract is exit 0 on every path, including internal failure.
    assert result.returncode == 0, f"guard exited {result.returncode}: {result.stderr}"
    return result.stdout.strip()


def _advisory(stdout: str) -> str | None:
    if not stdout:
        return None
    return json.loads(stdout)["systemMessage"]


class TestSymlinkedPolicyFile:
    """CLAUDE.md -> ./AGENTS.md is uniform across the twelve cohort members, and
    Claude Code's `#` memory shortcut writes by the CLAUDE.md name."""

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        repo = _repo(tmp_path)
        (repo / "CLAUDE.md").symlink_to("./AGENTS.md")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "symlink")
        return repo

    def test_reduction_is_never_flagged_through_either_name(self, repo: Path):
        """The guard's central promise: curating is never nagged. The file stays
        over budget after the cut, so only the NOW<=PREV branch can keep it
        quiet — which is exactly the branch the symlink bug made unreachable."""
        (repo / "AGENTS.md").write_text(POLICY_LINE * 800)
        for name in ("AGENTS.md", "CLAUDE.md"):
            assert _advisory(_run_guard(repo, repo / name)) is None, (
                f"a 60% reduction was flagged when reported as {name}"
            )

    def test_growth_delta_is_the_real_delta(self, repo: Path):
        """Growth must still be flagged, and the delta must be the change since
        HEAD — not the whole file measured against an 11-byte symlink blob."""
        (repo / "AGENTS.md").write_text(POLICY_LINE * 2400)
        messages = {
            name: _advisory(_run_guard(repo, repo / name))
            for name in ("AGENTS.md", "CLAUDE.md")
        }
        assert all(m is not None for m in messages.values()), messages
        # Both names describe the same file, so both must report the same numbers.
        assert messages["AGENTS.md"] == messages["CLAUDE.md"], messages
        # 400 added lines at ~2.7 bytes/token is ~8.6k, nowhere near the ~51k the
        # whole file measures. The bug reported the latter.
        whole_file = len((repo / "AGENTS.md").read_text().encode()) // 3
        delta = int(messages["AGENTS.md"].split("(+")[1].split(" ")[0])
        assert delta < whole_file // 2, (
            f"delta {delta} looks like the whole file, not the change since HEAD"
        )

    def test_symlink_redirect_is_logged(self, repo: Path):
        (repo / "AGENTS.md").write_text(POLICY_LINE * 2400)
        _run_guard(repo, repo / "CLAUDE.md")
        log = (repo / ".git" / "context-budget.log").read_text()
        assert "is a symlink; measuring AGENTS.md" in log, log

    def test_symlink_at_head_now_a_real_file(self, repo: Path):
        """The mirror case. A 120000-mode blob's content is a path, not a file,
        so it must count as no comparable committed version."""
        (repo / "CLAUDE.md").unlink()
        (repo / "CLAUDE.md").write_text(POLICY_LINE * 900)
        msg = _advisory(_run_guard(repo, repo / "CLAUDE.md"))
        assert msg is not None
        log = (repo / ".git" / "context-budget.log").read_text()
        assert "mode 120000" in log and "treating as uncommitted" in log, log
        assert "prev=0" in log, log

    def test_delta_reports_one_row_not_two(self, repo: Path):
        """AGENTS.md and a CLAUDE.md pointing at it are one file."""
        (repo / "AGENTS.md").write_text(POLICY_LINE * 2400)
        result = subprocess.run(
            ["bash", str(DELTA)],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=30,
        )
        assert result.returncode == 0, result.stderr
        rows = [ln for ln in result.stdout.splitlines() if ".md" in ln and "tokens" not in ln]
        assert len(rows) == 1, f"expected one row, got {rows}"
        assert "AGENTS.md" in rows[0]


class TestDocsDirKnob:
    """Without the knob a repo keeping references outside docs/ gets a correct
    weekly measurement and two continuous surfaces that classify nothing."""

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        repo = _repo(tmp_path, policy_lines=100)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-docs-dir").write_text("documentation\n")
        (repo / "documentation").mkdir()
        # Comfortably over the 10k per-doc budget.
        (repo / "documentation" / "BIG.md").write_text(POLICY_LINE * 1200)
        return repo

    def test_guard_sees_the_configured_root(self, repo: Path):
        msg = _advisory(_run_guard(repo, repo / "documentation" / "BIG.md"))
        assert msg is not None, "guard stayed silent on an over-budget doc"
        assert "documentation/BIG.md" in msg and "10000 budget" in msg, msg

    def test_guard_ignores_docs_when_the_root_moved(self, repo: Path):
        """The knob repoints the surface; it does not widen it."""
        (repo / "docs").mkdir()
        (repo / "docs" / "BIG.md").write_text(POLICY_LINE * 1200)
        assert _advisory(_run_guard(repo, repo / "docs" / "BIG.md")) is None

    def test_delta_sees_the_configured_root(self, repo: Path):
        result = subprocess.run(
            ["bash", str(DELTA)],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "documentation/BIG.md" in result.stdout, result.stdout

    def test_measure_sees_the_configured_root(self, repo: Path):
        result = subprocess.run(
            ["bash", str(MEASURE)],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=60,
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert [d["path"] for d in data["docs"]] == ["documentation/BIG.md"]
        assert data["docs"][0]["over_budget"] is True

    def test_archival_subtrees_still_excluded_under_a_moved_root(self, repo: Path):
        (repo / "documentation" / "plans").mkdir()
        (repo / "documentation" / "plans" / "old.md").write_text(POLICY_LINE * 1200)
        assert _advisory(
            _run_guard(repo, repo / "documentation" / "plans" / "old.md")
        ) is None


class TestEmptyPolicyFile:
    def test_exits_two_with_no_partial_json(self, tmp_path: Path):
        repo = tmp_path / "empty"
        repo.mkdir()
        _git(repo, "init", "-q")
        (repo / "AGENTS.md").write_text("")
        result = subprocess.run(
            ["bash", str(MEASURE)],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=30,
        )
        assert result.returncode == 2, (
            f"expected exit 2 (infrastructure failure), got {result.returncode}"
        )
        assert result.stdout.strip() == "", (
            f"emitted partial JSON before failing: {result.stdout!r}"
        )
        assert "no measurable content" in result.stderr, result.stderr


class TestCohortReportNet:
    """`net` must obey the same comparability rule as delta_tokens."""

    def _ledger(self, tmp_path: Path, rows: list[dict]) -> Path:
        repo = tmp_path / "member"
        (repo / ".skills").mkdir(parents=True)
        (repo / ".skills" / "context-metrics.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows)
        )
        return repo

    def _report(self, repo: Path) -> dict:
        result = subprocess.run(
            ["bash", str(COHORT), "--local", str(repo), "--format", "json"],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)[0]

    def test_net_ignores_rows_from_the_other_method(self, tmp_path: Path):
        """The reproduction: an estimate row then two exact rows for a file whose
        byte count never changed. Anchoring at row 0 reported +2743."""
        repo = self._ledger(tmp_path, [
            {"ts": "2026-08-01", "file": "AGENTS.md", "tokens": 5633,
             "tokens_exact": False, "bytes": 22533},
            {"ts": "2026-08-02", "file": "AGENTS.md", "tokens": 8376,
             "tokens_exact": True, "bytes": 22533},
            {"ts": "2026-08-03", "file": "AGENTS.md", "tokens": 8376,
             "tokens_exact": True, "bytes": 22533},
        ])
        rec = self._report(repo)
        assert rec["net"] == 0, f"net spanned the method change: {rec}"
        assert rec["net_from"] == "2026-08-02"

    def test_net_suppressed_when_the_method_just_changed(self, tmp_path: Path):
        repo = self._ledger(tmp_path, [
            {"ts": "2026-08-01", "file": "AGENTS.md", "tokens": 5633,
             "tokens_exact": False},
            {"ts": "2026-08-02", "file": "AGENTS.md", "tokens": 8376,
             "tokens_exact": True},
        ])
        rec = self._report(repo)
        assert rec["net"] is None
        assert "method changed" in rec["net_why"]

    def test_row_missing_tokens_degrades_one_cell(self, tmp_path: Path):
        """record-telemetry.sh tolerates a malformed line so one interrupted run
        cannot block every future measurement; the roll-up must match that."""
        repo = self._ledger(tmp_path, [
            {"ts": "2026-08-01", "file": "AGENTS.md", "tokens": 8376,
             "tokens_exact": True},
            {"ts": "2026-08-02", "file": "AGENTS.md", "tokens_exact": True},
        ])
        rec = self._report(repo)
        assert rec["net"] is None
        assert rec["net_why"] == "latest row has no token count"

    def test_net_reported_across_same_method_rows(self, tmp_path: Path):
        repo = self._ledger(tmp_path, [
            {"ts": "2026-08-01", "file": "AGENTS.md", "tokens": 9000,
             "tokens_exact": True},
            {"ts": "2026-08-08", "file": "AGENTS.md", "tokens": 5800,
             "tokens_exact": True},
        ])
        rec = self._report(repo)
        assert rec["net"] == -3200
        assert rec["net_why"] is None


class TestSharedLibrary:
    def test_lib_is_a_no_op_when_sourced_with_help_in_argv(self):
        """The library honours --help only when run directly. Sourced, $1 belongs
        to the caller, so an unguarded check would exit the caller whenever its
        own first argument happened to be --help."""
        script = f'set -euo pipefail\n. "{LIB}"\necho SOURCED_OK\n'
        result = subprocess.run(
            ["bash", "-c", script, "caller", "--help"],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "SOURCED_OK" in result.stdout, result.stdout
        assert "library" not in result.stdout.lower(), (
            "sourcing printed the library's usage text"
        )

    def test_guard_resolves_the_library_through_a_symlinked_install(
        self, tmp_path: Path
    ):
        """install-guard.sh symlinks the guard into .claude/hooks/, so
        dirname "$0" is .claude/hooks — which holds no library."""
        repo = _repo(tmp_path)
        hooks = repo / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "context-budget-guard.sh").symlink_to(GUARD)
        (repo / "AGENTS.md").write_text(POLICY_LINE * 2400)

        payload = json.dumps(
            {"tool_name": "Edit",
             "tool_input": {"file_path": str(repo / "AGENTS.md")}}
        )
        result = subprocess.run(
            ["bash", ".claude/hooks/context-budget-guard.sh"],
            input=payload, capture_output=True, text=True,
            cwd=str(repo), env=_clean_env(), timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip(), (
            "the guard found no library through the symlink and stayed silent"
        )
        log = (repo / ".git" / "context-budget.log").read_text()
        assert "not found" not in log, log

    def test_install_refuses_when_the_library_is_absent(self, tmp_path: Path):
        """A guard installed without its library wires up cleanly and then does
        nothing forever, logging nothing — logging starts after the source."""
        repo = _repo(tmp_path)
        vendored = repo / "vendor" / "scripts"
        vendored.mkdir(parents=True)
        (vendored / "context-budget-guard.sh").write_text(GUARD.read_text())
        (vendored / "install-guard.sh").write_text(INSTALL.read_text())
        result = subprocess.run(
            ["bash", str(vendored / "install-guard.sh")],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=30,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "_context-lib.sh not found" in result.stderr, result.stderr
        assert not (repo / ".claude" / "hooks").exists(), (
            "a refused install still created the hook directory"
        )

    def test_check_reports_a_missing_library(self, tmp_path: Path):
        repo = _repo(tmp_path)
        hooks = repo / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        orphan = repo / "orphan-guard.sh"
        orphan.write_text(GUARD.read_text())
        (hooks / "context-budget-guard.sh").symlink_to(orphan)
        (repo / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {"PostToolUse": [{
                "matcher": "Edit|Write|MultiEdit",
                "hooks": [{"type": "command",
                           "command": "bash .claude/hooks/context-budget-guard.sh"}],
            }]}
        }))
        result = subprocess.run(
            ["bash", str(INSTALL), "--check"],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=30,
        )
        assert result.returncode == 3, result.stdout
        assert "library beside target: no" in result.stdout, result.stdout
