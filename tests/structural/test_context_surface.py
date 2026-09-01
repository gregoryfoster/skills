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
import re
import shutil
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
SCORE = SCRIPTS / "score-cohort.sh"
INSTALL = SCRIPTS / "install-guard.sh"
LIB = SCRIPTS / "_context-lib.sh"
RECORD = SCRIPTS / "record-telemetry.sh"
REFERENCES = SCRIPTS.parent / "references"

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
        # Assert the relationship, not a threshold derived from a hardcoded
        # bytes/token divisor: a second copy of the ratio here would be the very
        # duplication the shared library exists to remove, and it would drift
        # silently rather than fail if the default moved. The message carries
        # both numbers, so compare them directly — the file grew by a fifth, so a
        # delta anywhere near the total means the previous size was read as ~0,
        # which is precisely the symlink bug.
        msg = messages["AGENTS.md"]
        now = int(msg.split("is now ~")[1].split(" ")[0])
        delta = int(msg.split("(+")[1].split(" ")[0])
        assert 0 < delta < now // 2, (
            f"delta {delta} against a total of {now} looks like the whole file "
            "rather than the change since HEAD"
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


class TestCredentialParity:
    """An interactive Claude Code session exports no ANTHROPIC_API_KEY and often
    has no `ant` CLI, so without a third credential source an interactive run
    records estimate rows while the scheduled run records exact ones — and the
    two cannot be compared."""

    def _env_without_key(self, bin_dir: Path | None = None) -> dict:
        """No API key, and — when bin_dir is given — a PATH with no `ant` on it.

        The credential order is env key, then secrets file, then `ant auth`. A
        test asserting the estimate fallback has to close all three, or it passes
        only on machines without the ant CLI installed and fails elsewhere for a
        reason unrelated to what it tests.
        """
        env = _clean_env()
        env.pop("ANTHROPIC_API_KEY", None)
        if bin_dir is not None:
            bin_dir.mkdir(parents=True, exist_ok=True)
            # Keep the real tools the script needs; drop everything else.
            for tool in ("git", "python3", "bash", "awk", "sed", "grep", "wc",
                         "sort", "find", "head", "tr", "dirname", "basename",
                         "mktemp", "date", "cat", "rm", "mkdir", "printf"):
                real = shutil.which(tool)
                if real and not (bin_dir / tool).exists():
                    (bin_dir / tool).symlink_to(real)
            env["PATH"] = str(bin_dir)
        return env

    def test_key_is_parsed_from_the_secrets_file_not_sourced(self, tmp_path: Path):
        """Sourcing a secrets file executes whatever it contains. The canary is a
        command substitution that would create a file if the value were ever run
        through the shell."""
        repo = _repo(tmp_path, policy_lines=50)
        canary = tmp_path / "canary"
        (repo / ".env").write_text(
            "# a comment\n"
            f"OTHER=$(touch {canary})\n"
            "export ANTHROPIC_API_KEY=sk-ant-from-dotenv\n"
        )
        script = (
            f'set -euo pipefail\n. "{LIB}"\n'
            f'ctx_api_key_from_env_file "{repo}"\n'
        )
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True,
            env=self._env_without_key(), timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "sk-ant-from-dotenv", repr(result.stdout)
        assert not canary.exists(), (
            "the secrets file was sourced, not parsed — it executed a substitution"
        )

    def test_dotenv_wins_over_the_legacy_name(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=50)
        (repo / "env").write_text("ANTHROPIC_API_KEY=sk-legacy\n")
        (repo / ".env").write_text("ANTHROPIC_API_KEY=sk-current\n")
        script = f'set -euo pipefail\n. "{LIB}"\nctx_api_key_from_env_file "{repo}"\n'
        result = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True,
            env=self._env_without_key(), timeout=30,
        )
        assert result.stdout == "sk-current", repr(result.stdout)

    def test_legacy_name_still_read(self, tmp_path: Path):
        """The cohort used a bare `env` before 2026-08-05; an older checkout must
        still work."""
        repo = _repo(tmp_path, policy_lines=50)
        (repo / "env").write_text("ANTHROPIC_API_KEY='sk-legacy'\n")
        script = f'set -euo pipefail\n. "{LIB}"\nctx_api_key_from_env_file "{repo}"\n'
        result = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True,
            env=self._env_without_key(), timeout=30,
        )
        assert result.stdout == "sk-legacy", repr(result.stdout)

    def test_no_env_file_refuses_that_source(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=50)
        (repo / ".env").write_text("ANTHROPIC_API_KEY=sk-unused\n")
        result = subprocess.run(
            ["bash", str(MEASURE), "--exact", "--no-write", "--no-env-file"],
            capture_output=True, text=True, cwd=str(repo),
            env=self._env_without_key(tmp_path / "bin"), timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["policy"]["tokens_exact"] is False
        assert "using offline estimate" in result.stderr, result.stderr

    def test_a_value_with_whitespace_is_rejected(self, tmp_path: Path):
        """A placeholder or a mangled line is not a usable key."""
        repo = _repo(tmp_path, policy_lines=50)
        (repo / ".env").write_text("ANTHROPIC_API_KEY=your key here\n")
        script = f'set -euo pipefail\n. "{LIB}"\nctx_api_key_from_env_file "{repo}"\n'
        result = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True,
            env=self._env_without_key(), timeout=30,
        )
        assert result.stdout == "", repr(result.stdout)


class TestLedgerStaysSingleMethod:
    """One credential-less run appended to a ledger of exact rows nulls its own
    delta, resets the trend baseline, and blanks `net` in the roll-up. Refuse it
    at the source instead."""

    def _repo_with_ledger(self, tmp_path: Path, exact: bool) -> Path:
        repo = _repo(tmp_path, policy_lines=50)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-metrics.jsonl").write_text(json.dumps({
            "ts": "2026-08-01", "repo": "repo", "file": "AGENTS.md",
            "tokens": 5000, "tokens_exact": exact, "budget": 6000,
        }) + "\n")
        return repo

    def _measure(self, repo: Path) -> str:
        """An estimate measurement — no credential available."""
        result = subprocess.run(
            ["bash", str(MEASURE), "--no-write"],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["policy"]["tokens_exact"] is False
        return result.stdout

    def _record(self, repo: Path, measurement: str, *extra: str):
        return subprocess.run(
            ["bash", str(SCRIPTS / "record-telemetry.sh"), *extra],
            input=measurement, capture_output=True, text=True,
            cwd=str(repo), env=_clean_env(), timeout=30,
        )

    def test_refuses_an_estimate_row_after_an_exact_row(self, tmp_path: Path):
        repo = self._repo_with_ledger(tmp_path, exact=True)
        ledger = repo / ".skills" / "context-metrics.jsonl"
        before = ledger.read_text()
        result = self._record(repo, self._measure(repo))
        assert result.returncode == 4, (
            f"expected exit 4, got {result.returncode}: {result.stderr}"
        )
        assert "refusing to append" in result.stderr
        assert "--allow-method-change" in result.stderr, (
            "the refusal must name its own override"
        )
        assert ledger.read_text() == before, "a refused append still wrote"

    def test_allow_method_change_records_a_new_baseline(self, tmp_path: Path):
        repo = self._repo_with_ledger(tmp_path, exact=True)
        ledger = repo / ".skills" / "context-metrics.jsonl"
        result = self._record(repo, self._measure(repo), "--allow-method-change")
        assert result.returncode == 0, result.stderr
        rows = [json.loads(ln) for ln in ledger.read_text().splitlines() if ln.strip()]
        assert len(rows) == 2
        assert rows[-1]["delta_tokens"] is None
        assert "method changed" in rows[-1]["delta_unavailable"]

    def test_same_method_append_is_unaffected(self, tmp_path: Path):
        repo = self._repo_with_ledger(tmp_path, exact=False)
        result = self._record(repo, self._measure(repo))
        assert result.returncode == 0, result.stderr
        rows = [
            json.loads(ln)
            for ln in (repo / ".skills" / "context-metrics.jsonl").read_text().splitlines()
            if ln.strip()
        ]
        assert isinstance(rows[-1]["delta_tokens"], int), rows[-1]

    def test_dry_run_previews_without_refusing(self, tmp_path: Path):
        """A preview writes nothing, so it has nothing to protect."""
        repo = self._repo_with_ledger(tmp_path, exact=True)
        result = self._record(repo, self._measure(repo), "--dry-run")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["tokens_exact"] is False


class TestRepoCommitBackfill:
    """`repo_commit` named the parent of the tree the row describes (#206).

    Phase 7 measures, records, and only then commits the ledger alongside the
    edits — so the hash the append could see is the commit *before* the one that
    ships the curation. Everything else on the row (`tokens`, `seams`,
    `no_loss`) describes the shipped tree; `repo_commit` alone pointed a commit
    behind. The field carries two documented meanings — which state of this tree
    the row describes, and where the next scheduled seam sweep starts — and they
    were being satisfied by two different commits, so a wired cadence re-swept
    the run's own relocations and re-reported seams the run had already judged.

    `--repo-commit REV` backfills the row after the commit. It rewrites, never
    appends: a rewrite *within* a run is what `telemetry.md` sanctions, and a
    third row for an intermediate state nobody can check out is what it forbids.
    """

    LEDGER = ".skills/context-metrics.jsonl"

    def _rev(self, repo: Path, ref: str = "HEAD", *flags: str) -> str:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", *flags, ref],
            check=True, capture_output=True, text=True, env=_clean_env(),
        )
        return out.stdout.strip()

    def _measure(self, repo: Path) -> str:
        result = subprocess.run(
            ["bash", str(MEASURE), "--no-write"],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=60,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    def _record(self, repo: Path, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(RECORD), *extra],
            input=self._measure(repo), capture_output=True, text=True,
            cwd=str(repo), env=_clean_env(), timeout=60,
        )

    def _backfill(self, repo: Path, *extra: str) -> subprocess.CompletedProcess:
        """Run the backfill against a stdin that is open, silent and never closed.

        The append path reads stdin to exhaustion. If the backfill did too it
        would hang here rather than fail an assertion, so this is the shape that
        actually catches it — `stdin=DEVNULL` would read EOF and pass.
        """
        r_fd, w_fd = os.pipe()
        try:
            return subprocess.run(
                ["bash", str(RECORD), *extra], stdin=r_fd,
                capture_output=True, text=True, cwd=str(repo),
                env=_clean_env(), timeout=60,
            )
        finally:
            os.close(r_fd)
            os.close(w_fd)

    def _rows(self, repo: Path) -> list[dict]:
        """The rows a reader can use, skipping a malformed line as every script
        in this chain skips it. Parseability is asserted on its own below."""
        rows = []
        for line in (repo / self.LEDGER).read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def _through_phase_seven(self, tmp_path: Path) -> tuple[Path, str, str]:
        """Phase 7's ordering: measure, record, then commit ledger and edits.

        Returns the repo, the commit the append could see, and the commit that
        actually ships the tree the row describes.
        """
        repo = _repo(tmp_path, policy_lines=50)
        before = self._rev(repo, "HEAD", "--short")
        result = self._record(repo, "--actions", "demote:Project Layout")
        assert result.returncode == 0, result.stderr
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "the curation, ledger and all")
        return repo, before, self._rev(repo, "HEAD", "--short")

    def test_the_append_alone_names_the_parent_of_the_shipped_tree(
        self, tmp_path: Path
    ):
        """The reproduction, pinned so the backfill has something to fix."""
        repo, before, shipped = self._through_phase_seven(tmp_path)
        assert before != shipped, "the fixture did not actually commit"
        assert self._rows(repo)[-1]["repo_commit"] == before

    def test_backfill_puts_the_shipping_commit_on_the_row(self, tmp_path: Path):
        repo, before, shipped = self._through_phase_seven(tmp_path)
        result = self._backfill(repo, "--repo-commit", "HEAD")
        assert result.returncode == 0, result.stderr
        row = self._rows(repo)[-1]
        # Present, non-null, and the right commit — three assertions because a
        # field that merely "changed" can change to null, and a field compared
        # against a snapshot of itself passes while verifying nothing.
        assert "repo_commit" in row, row
        assert row["repo_commit"] is not None, row
        assert row["repo_commit"] == shipped, row
        assert row["repo_commit"] != before, row

    def test_backfill_rewrites_and_never_appends(self, tmp_path: Path):
        repo, _, _ = self._through_phase_seven(tmp_path)
        before = len(self._rows(repo))
        assert self._backfill(repo, "--repo-commit", "HEAD").returncode == 0
        assert len(self._rows(repo)) == before, (
            "the backfill appended a row for an intermediate state"
        )

    def test_backfill_is_idempotent(self, tmp_path: Path):
        """A re-run must be a no-op, not a second row and not a second write."""
        repo, _, shipped = self._through_phase_seven(tmp_path)
        assert self._backfill(repo, "--repo-commit", "HEAD").returncode == 0
        once = (repo / self.LEDGER).read_text()
        again = self._backfill(repo, "--repo-commit", "HEAD")
        assert again.returncode == 0, again.stderr
        assert (repo / self.LEDGER).read_text() == once
        assert self._rows(repo)[-1]["repo_commit"] == shipped

    def test_a_run_that_died_before_the_backfill_leaves_a_parseable_row(
        self, tmp_path: Path
    ):
        """Crash-safety: the interrupted state is the OLD behaviour, not a
        broken ledger. Every line still parses and the field is still a commit,
        one behind — recoverable by running the backfill later."""
        repo, before, _ = self._through_phase_seven(tmp_path)
        lines = [ln for ln in (repo / self.LEDGER).read_text().splitlines()
                 if ln.strip()]
        assert lines, "the record step wrote nothing"
        for line in lines:
            json.loads(line)  # a half-written row would raise here
        assert self._rows(repo)[-1]["repo_commit"] == before

    def test_backfill_refuses_a_commit_this_repo_does_not_have(
        self, tmp_path: Path
    ):
        """Null already means 'cannot name an interval'. A fabricated revision
        sends the next sweep to a tree nobody measured, which is worse."""
        repo, _, shipped = self._through_phase_seven(tmp_path)
        untouched = (repo / self.LEDGER).read_text()
        result = self._backfill(repo, "--repo-commit", "deadbee")
        assert result.returncode == 1, result.stderr
        assert "deadbee" in result.stderr
        assert (repo / self.LEDGER).read_text() == untouched
        assert self._rows(repo)[-1]["repo_commit"] != "deadbee"
        assert self._rows(repo)[-1]["repo_commit"] != shipped

    def test_backfill_normalises_a_long_revision_to_the_short_form(
        self, tmp_path: Path
    ):
        """The writer and `check-seams.sh --base-ledger` are joined by a field
        name and a revision format. Recorded long and read short is the shape
        that would join nothing."""
        repo, _, shipped = self._through_phase_seven(tmp_path)
        full = self._rev(repo)
        assert len(full) == 40
        assert self._backfill(repo, "--repo-commit", full).returncode == 0
        assert self._rows(repo)[-1]["repo_commit"] == shipped

    def test_backfill_preserves_a_malformed_line(self, tmp_path: Path):
        """record-telemetry.sh skips a malformed line so one interrupted run
        cannot poison the ledger. A rewrite that dropped it would do the
        poisoning itself, on a line no reader can get back."""
        repo, _, shipped = self._through_phase_seven(tmp_path)
        ledger = repo / self.LEDGER
        ledger.write_text('{"ts": "2026-08-01", "file": "AGE\n' + ledger.read_text())
        result = self._backfill(repo, "--repo-commit", "HEAD")
        assert result.returncode == 0, result.stderr
        text = ledger.read_text()
        assert '{"ts": "2026-08-01", "file": "AGE\n' in text, text
        assert "malformed" in result.stderr.lower()
        assert self._rows(repo)[-1]["repo_commit"] == shipped

    def test_backfill_refuses_when_the_newest_row_is_a_baseline(
        self, tmp_path: Path
    ):
        """The baseline row records a state that has already passed, so a late
        commit cannot change what it describes. telemetry.md exempts it from the
        rewrite rule in both directions."""
        repo = _repo(tmp_path, policy_lines=50)
        assert self._record(repo, "--baseline").returncode == 0
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "baseline only")
        untouched = (repo / self.LEDGER).read_text()
        result = self._backfill(repo, "--repo-commit", "HEAD")
        assert result.returncode == 1, result.stderr
        assert "unknown argument" not in result.stderr, (
            "the flag is not parsed at all, so this refusal is the usage error "
            "and not the rule under test"
        )
        assert "baseline" in result.stderr
        assert (repo / self.LEDGER).read_text() == untouched

    def test_backfill_refuses_an_empty_ledger(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=50)
        (repo / ".skills").mkdir()
        (repo / self.LEDGER).write_text("")
        result = self._backfill(repo, "--repo-commit", "HEAD")
        assert result.returncode == 1, result.stderr
        assert "unknown argument" not in result.stderr, result.stderr
        assert self.LEDGER in result.stderr

    def test_backfill_refuses_the_flags_that_only_make_sense_on_an_append(
        self, tmp_path: Path
    ):
        """`--repo-commit` reads no measurement, so `--actions` on it would
        silently discard the tags rather than record them."""
        repo, _, _ = self._through_phase_seven(tmp_path)
        result = self._backfill(
            repo, "--repo-commit", "HEAD", "--actions", "demote:Layout")
        assert result.returncode == 1, result.stderr
        assert "unknown argument" not in result.stderr, result.stderr
        assert "--actions" in result.stderr

    def test_dry_run_backfill_previews_without_writing(self, tmp_path: Path):
        repo, before, shipped = self._through_phase_seven(tmp_path)
        untouched = (repo / self.LEDGER).read_text()
        result = self._backfill(repo, "--repo-commit", "HEAD", "--dry-run")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["repo_commit"] == shipped
        assert (repo / self.LEDGER).read_text() == untouched
        assert self._rows(repo)[-1]["repo_commit"] == before


def _bin_with_real_tools(bin_dir: Path) -> Path:
    """A PATH directory holding the real tools measure-context.sh needs, so a
    caller can then override exactly one of them."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    for tool in ("git", "python3", "bash", "awk", "sed", "grep", "wc", "sort",
                 "find", "head", "tr", "dirname", "basename", "mktemp", "date",
                 "cat", "rm", "mkdir", "printf", "ls", "cut", "tail", "uniq"):
        real = shutil.which(tool)
        if real and not (bin_dir / tool).exists():
            (bin_dir / tool).symlink_to(real)
    return bin_dir


class TestExactFlagReflectsCountsNotCredentials:
    """Holding a credential is not the same as having counted.

    The `ant auth` path authenticates and then count_tokens answers
    401 "jwt auth is not yet supported on count_tokens", so every per-file count
    fell back to the estimate while the run still reported tokens_exact=true —
    labelling pure estimates as exact, which is the one lie the comparability
    chain cannot survive. Forced here offline with a python3 that always fails,
    which is the only thing count.py needs and nothing else in the script does.
    """

    @pytest.fixture
    def env_with_failing_counter(self, tmp_path: Path) -> dict:
        bin_dir = _bin_with_real_tools(tmp_path / "bin")
        (bin_dir / "python3").unlink()
        (bin_dir / "python3").write_text("#!/bin/sh\necho 'boom' >&2\nexit 1\n")
        (bin_dir / "python3").chmod(0o755)
        env = _clean_env()
        env["PATH"] = str(bin_dir)
        env["ANTHROPIC_API_KEY"] = "sk-ant-test-not-used-offline"
        return env

    def test_tokens_exact_is_false_when_every_count_fell_back(
        self, tmp_path: Path, env_with_failing_counter: dict
    ):
        repo = _repo(tmp_path, policy_lines=200)
        result = subprocess.run(
            ["bash", str(MEASURE), "--exact"],
            capture_output=True, text=True, cwd=str(repo),
            env=env_with_failing_counter, timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["policy"]["tokens_exact"] is False, (
            "a credential was accepted but no count succeeded — reporting exact "
            "would label an estimate as exact"
        )
        assert "at least one count_tokens call failed" in result.stderr, result.stderr

    def test_no_ratio_is_persisted_from_a_fallback_run(
        self, tmp_path: Path, env_with_failing_counter: dict
    ):
        """The ratio would be derived from the divisor it was computed with — a
        self-confirming 2.70 that then poisons every later offline estimate."""
        repo = _repo(tmp_path, policy_lines=200)
        result = subprocess.run(
            ["bash", str(MEASURE), "--exact"],
            capture_output=True, text=True, cwd=str(repo),
            env=env_with_failing_counter, timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert not (repo / ".skills" / "context-token-ratio").exists(), (
            "persisted a calibration derived from estimates"
        )

    def test_such_a_row_cannot_be_appended_to_an_exact_ledger(
        self, tmp_path: Path, env_with_failing_counter: dict
    ):
        """The two halves meeting: an honest tokens_exact=false is what lets the
        ledger refuse the row. Mislabelled as exact, it would have been accepted
        and silently compared against real counts."""
        repo = _repo(tmp_path, policy_lines=200)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-metrics.jsonl").write_text(json.dumps({
            "ts": "2026-08-01", "file": "AGENTS.md", "tokens": 5000,
            "tokens_exact": True, "budget": 6000,
        }) + "\n")
        measured = subprocess.run(
            ["bash", str(MEASURE), "--exact", "--no-write"],
            capture_output=True, text=True, cwd=str(repo),
            env=env_with_failing_counter, timeout=60,
        )
        assert measured.returncode == 0, measured.stderr
        recorded = subprocess.run(
            ["bash", str(SCRIPTS / "record-telemetry.sh")],
            input=measured.stdout, capture_output=True, text=True,
            cwd=str(repo), env=_clean_env(), timeout=30,
        )
        assert recorded.returncode == 4, (
            f"expected the ledger to refuse it, got {recorded.returncode}"
        )


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="chmod 000 does not restrict root, so the unreadable file is readable",
)
class TestUnreadableDocInTheInventory:
    """The doc inventory read every discovered .md through a bare redirect, so a
    file it had just FOUND but could not READ killed the run in bash's own words
    — `measure-context.sh: line 956: docs/D.md: Permission denied` — with exit 1,
    no JSON, and nothing naming the inventory as the stage that failed (#157).

    Exit 2 and a named file, because this output is not reporting-only: it drives
    budget decisions and telemetry appends, so a measurement that cannot see part
    of the tree must not report a number as if it could.
    """

    def _repo_with_unreadable_doc(self, tmp_path: Path) -> Path:
        repo = _repo(tmp_path, policy_lines=50)
        (repo / "AGENTS.md").write_text(
            POLICY_LINE * 50 + "\n[live](docs/D.md)\n"
        )
        (repo / "docs").mkdir()
        doc = repo / "docs" / "D.md"
        doc.write_text("# D\n\nsome live reference prose\n")
        doc.chmod(0o000)
        return repo

    def _measure(self, repo: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(MEASURE), "--no-write"],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=60,
        )

    def test_exits_two_with_no_partial_json(self, tmp_path: Path):
        result = self._measure(self._repo_with_unreadable_doc(tmp_path))
        assert result.returncode == 2, (
            f"expected exit 2 (infrastructure failure), got {result.returncode}: "
            f"{result.stderr}"
        )
        assert result.stdout.strip() == "", (
            f"emitted partial JSON before failing: {result.stdout!r}"
        )

    def test_the_diagnosis_names_the_file_and_the_stage(self, tmp_path: Path):
        result = self._measure(self._repo_with_unreadable_doc(tmp_path))
        assert "ERROR could not read docs/D.md" in result.stderr, result.stderr
        assert "doc inventory" in result.stderr, result.stderr

    def test_bashs_own_words_appear_only_as_the_quoted_cause(self, tmp_path: Path):
        """`line NNN: <path>: Permission denied` standing alone leaves the
        operator to work out which script, which stage, and whether a number was
        lost. Quoted inside the ERROR it is the cause, the way `find.err` and
        `ct.err` are already carried; on a line of its own it is the defect."""
        result = self._measure(self._repo_with_unreadable_doc(tmp_path))
        stray = [
            line for line in result.stderr.splitlines()
            if re.search(r"measure-context\.sh: line \d+:", line)
            and not line.startswith(("ERROR", "WARN", "INFO"))
        ]
        assert stray == [], result.stderr


class TestDryRunDescribesTheRealCommand:
    def test_dry_run_announces_the_refusal_it_would_hit(self, tmp_path: Path):
        """A preview consulted about a decision must answer for the branch the
        real command takes, not for the one --allow-method-change would take."""
        repo = _repo(tmp_path, policy_lines=50)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-metrics.jsonl").write_text(json.dumps({
            "ts": "2026-08-01", "file": "AGENTS.md", "tokens": 5000,
            "tokens_exact": True, "budget": 6000,
        }) + "\n")
        measured = subprocess.run(
            ["bash", str(MEASURE), "--no-write"],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=60,
        )
        result = subprocess.run(
            ["bash", str(SCRIPTS / "record-telemetry.sh"), "--dry-run"],
            input=measured.stdout, capture_output=True, text=True,
            cwd=str(repo), env=_clean_env(), timeout=30,
        )
        # A preview is not a failure, so it still exits 0 …
        assert result.returncode == 0, result.stderr
        # … but it must say what the real append would do, and mark the row.
        assert "would be REFUSED" in result.stderr, result.stderr
        assert "--allow-method-change" in result.stderr, result.stderr
        assert "would exit 4" in json.loads(result.stdout)["would_be_refused"]

    def test_dry_run_is_silent_about_refusal_when_methods_match(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=50)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-metrics.jsonl").write_text(json.dumps({
            "ts": "2026-08-01", "file": "AGENTS.md", "tokens": 5000,
            "tokens_exact": False, "budget": 6000,
        }) + "\n")
        measured = subprocess.run(
            ["bash", str(MEASURE), "--no-write"],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=60,
        )
        result = subprocess.run(
            ["bash", str(SCRIPTS / "record-telemetry.sh"), "--dry-run"],
            input=measured.stdout, capture_output=True, text=True,
            cwd=str(repo), env=_clean_env(), timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "would be REFUSED" not in result.stderr, result.stderr
        assert "would_be_refused" not in result.stdout


class TestProveNoLoss:
    """prove-no-loss.sh exists because the obvious check is not strong enough.

    Phase 6 originally said "grep a distinctive phrase from each moved block".
    On the first real run of the skill that check PASSED over a real defect: a
    line had been moved and simultaneously recombined into a longer sentence, so
    the phrase was present and the line was not. The fixture below is that exact
    text, not an invented one.
    """

    PROVE = SCRIPTS / "prove-no-loss.sh"

    ORIGINAL = (
        "The [`managing-skills`](skills/managing-skills/) skill teaches agents "
        "how to perform these operations."
    )
    # What the paraphrase-in-transit actually produced.
    RECOMBINED = (
        "The [`managing-skills`](../skills/managing-skills/) skill teaches agents "
        "how to perform these operations; this file is the reference a human or "
        "an audit needs."
    )

    def _repo(self, tmp_path: Path, policy_body: str) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        (repo / "AGENTS.md").write_text(policy_body)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "before")
        return repo

    def _run(self, repo: Path, *extra: str):
        return subprocess.run(
            ["bash", str(self.PROVE), "--base", "HEAD", *extra],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=30,
        )

    def test_clean_relocation_passes(self, tmp_path: Path):
        repo = self._repo(tmp_path, f"# P\n\n## A\n\nkeep me\n\n### B\n\n{self.ORIGINAL}\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n\nkeep me\n\nSee [docs/SKILLS.md](docs/SKILLS.md).\n")
        (repo / "docs").mkdir()
        # Heading promoted ### -> ##, link depth adjusted: both normalised away.
        (repo / "docs" / "SKILLS.md").write_text(f"# S\n\n## B\n\n{self.RECOMBINED.replace('; this file is the reference a human or an audit needs', '')}\n")
        result = self._run(repo)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "UNACCOUNTED FOR:            0" in result.stdout, result.stdout

    def test_paraphrase_in_transit_is_caught(self, tmp_path: Path):
        """The defect from the first real run, reproduced verbatim."""
        repo = self._repo(tmp_path, f"# P\n\n## A\n\n{self.ORIGINAL}\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n\nSee [docs/SKILLS.md](docs/SKILLS.md).\n")
        (repo / "docs").mkdir()
        (repo / "docs" / "SKILLS.md").write_text(f"# S\n\n{self.RECOMBINED}\n")
        result = self._run(repo)
        assert result.returncode == 3, (
            f"the paraphrase was not caught (exit {result.returncode})"
        )
        # The whole report, LOST list included, is on stdout — see the
        # one-stream fix, so a piped report stays in order.
        assert "LOST" in result.stdout and "managing-skills" in result.stdout

    def test_a_phrase_grep_would_have_passed_the_same_input(self, tmp_path: Path):
        """Pins the reason this script exists. If this ever fails, the phrase-grep
        method became sufficient and Phase 6 could be simplified."""
        assert "teaches agents how to perform these operations" in self.RECOMBINED
        assert self.ORIGINAL not in self.RECOMBINED

    def test_append_after_the_sentence_terminator_is_caught(self, tmp_path: Path):
        """The variant substring matching could not see.

        RECOMBINED above changes `operations.` to `operations;`, so the original
        line stopped being a substring and the old implementation caught it by
        luck. Appending a whole new sentence after the period leaves the original
        line intact as a substring — that passed until matching became
        whole-line.
        """
        appended = (
            "The [`managing-skills`](../skills/managing-skills/) skill teaches "
            "agents how to perform these operations. This file is the reference "
            "a human needs."
        )
        assert self.ORIGINAL.replace("](skills/", "](../skills/") in appended, (
            "fixture must keep the original line as a substring, or it proves nothing"
        )
        repo = self._repo(tmp_path, f"# P\n\n## A\n\n{self.ORIGINAL}\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n\nSee [docs/S.md](docs/S.md).\n")
        (repo / "docs").mkdir()
        (repo / "docs" / "S.md").write_text(f"# S\n\n{appended}\n")
        result = self._run(repo)
        assert result.returncode == 3, (
            f"append-after-terminator not caught (exit {result.returncode})"
        )

    def test_a_fragment_inside_unrelated_prose_is_not_a_relocation(self, tmp_path: Path):
        """Short and common lines — fence markers, numbered list items — were
        effectively unchecked under substring matching. Measured on this exact
        input, four of five dropped lines reported as "relocated verbatim"."""
        repo = self._repo(
            tmp_path,
            "# P\n\n## A\n\n```bash\nrun the thing\n```\n\n## B\n\n1. Commit and push\n",
        )
        (repo / "AGENTS.md").write_text("# P\n\n## A\n\nSee [docs/X.md](docs/X.md).\n")
        (repo / "docs").mkdir()
        (repo / "docs" / "X.md").write_text(
            "# X\n\nYou should always run the thing carefully.\n"
            "Step 9: 1. Commit and push when ready.\n"
            "Inline ```bash``` is fine.\n"
        )
        result = self._run(repo)
        assert result.returncode == 3, result.stdout
        for dropped in ("```bash", "run the thing", "## B", "1. Commit and push"):
            assert dropped in result.stdout, (
                f"{dropped!r} was dropped but not reported: {result.stdout}"
            )
        assert "relocated verbatim" not in result.stdout, (
            "a fragment match was still counted as a relocation"
        )

    def test_a_code_comment_does_not_match_a_prose_line(self, tmp_path: Path):
        """Heading text is tagged, not merely stripped of its hashes: stripping
        alone lets `# cleanup` in a fenced block satisfy the prose line
        `cleanup`, a false match in the direction that hides loss."""
        repo = self._repo(tmp_path, "# P\n\n## A\n\ncleanup\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n\nSee [docs/X.md](docs/X.md).\n")
        (repo / "docs").mkdir()
        (repo / "docs" / "X.md").write_text("# X\n\n```bash\n# cleanup\n```\n")
        assert self._run(repo).returncode == 3

    def test_report_is_ordered_on_one_stream(self, tmp_path: Path):
        """Summary and LOST list split across stdout/stderr interleaved through a
        pipe, printing the failures above the counts that explain them."""
        repo = self._repo(tmp_path, "# P\n\n## A\n\ndropped line\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n\n")
        result = self._run(repo)
        assert result.returncode == 3
        assert "UNACCOUNTED FOR" in result.stdout and "LOST" in result.stdout
        assert result.stdout.index("UNACCOUNTED FOR") < result.stdout.index("LOST")

    def test_outright_deletion_is_caught(self, tmp_path: Path):
        repo = self._repo(tmp_path, "# P\n\n## A\n\nload-bearing constraint\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n\n")
        result = self._run(repo)
        assert result.returncode == 3, result.stdout
        assert "load-bearing constraint" in result.stdout

    def test_also_searches_an_extra_destination(self, tmp_path: Path):
        """A block demoted somewhere other than the docs tree."""
        repo = self._repo(tmp_path, "# P\n\n## A\n\nmoved into a skill reference\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n\n")
        target = repo / "skills" / "x" / "references"
        target.mkdir(parents=True)
        (target / "n.md").write_text("moved into a skill reference\n")
        assert self._run(repo).returncode == 3, "should fail without --also"
        ok = self._run(repo, "--also", "skills/x/references/n.md")
        assert ok.returncode == 0, ok.stdout + ok.stderr

    def test_archival_docs_are_not_a_valid_destination(self, tmp_path: Path):
        """Demoting live guidance into docs/plans/ would hide it in a dated
        snapshot; the archival exclusion must apply here too."""
        repo = self._repo(tmp_path, "# P\n\n## A\n\nlive guidance\n")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n\n")
        (repo / "docs" / "plans").mkdir(parents=True)
        (repo / "docs" / "plans" / "old.md").write_text("live guidance\n")
        assert self._run(repo).returncode == 3, "an archival doc was accepted"

    def test_symlink_policy_blob_at_base_is_refused(self, tmp_path: Path):
        """A symlink blob's content is a path, not the file — comparing against it
        would report the whole file as lost."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        (repo / "AGENTS.md").write_text("# P\n\n## A\n\nbody\n")
        (repo / "CLAUDE.md").symlink_to("./AGENTS.md")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "before")
        result = subprocess.run(
            ["bash", str(self.PROVE), "--base", "HEAD", "--file", "CLAUDE.md"],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=30,
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "mode 120000" in result.stderr, result.stderr


class TestFrontmatterIsNotContent:
    """Phase 7 MANDATES a frontmatter version bump, so Phase 6 must not call it
    a loss (#136).

    `version: "1.6"` becoming `version: "1.7"` is a line that existed at --base
    and exists nowhere now, and a line-based check reports it LOST — the run
    that follows the skill's own instructions cannot pass the skill's own gate.
    The warrant file cannot absorb it either: #111 shipped a CLOSED vocabulary
    and none of the five warrants means "this field is required to change".

    So a leading YAML frontmatter block is not compared at all, on either side.
    The cases below pair that with the two ways it could go wrong: body content
    must still be checked across a bump, and a `---` that is a thematic rule
    rather than a frontmatter fence must not swallow the top of a document.
    """

    PROVE = SCRIPTS / "prove-no-loss.sh"

    def _front(self, version: str) -> str:
        return (
            "---\n"
            "name: demo\n"
            "metadata:\n"
            f'  version: "{version}"\n'
            "---\n"
        )

    def _repo(self, tmp_path: Path, before: str) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        (repo / "AGENTS.md").write_text(before)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "before")
        return repo

    def _run(self, repo: Path, *extra: str):
        return subprocess.run(
            ["bash", str(self.PROVE), "--base", "HEAD", *extra],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=30,
        )

    BODY = "\n# Demo\n\nA load-bearing constraint nobody may drop.\n"

    def test_a_mandated_version_bump_is_not_a_loss(self, tmp_path: Path):
        repo = self._repo(tmp_path, self._front("1.6") + self.BODY)
        (repo / "AGENTS.md").write_text(self._front("1.7") + self.BODY)
        result = self._run(repo)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "UNACCOUNTED FOR:            0" in result.stdout, result.stdout

    def test_the_body_is_still_checked_across_a_bump(self, tmp_path: Path):
        """Skipping frontmatter must skip frontmatter and nothing else."""
        repo = self._repo(tmp_path, self._front("1.6") + self.BODY)
        (repo / "AGENTS.md").write_text(self._front("1.7") + "\n# Demo\n")
        result = self._run(repo)
        assert result.returncode == 3, result.stdout + result.stderr
        assert "load-bearing constraint" in result.stdout, result.stdout

    def test_a_thematic_rule_is_not_a_frontmatter_fence(self, tmp_path: Path):
        """`---` opening a file is a frontmatter fence only when what follows
        reads as YAML. Prose between two rules is content, and dropping it is a
        loss."""
        before = "---\n\nA rule-fenced sentence that is plainly prose.\n\n---\n\n# Demo\n"
        repo = self._repo(tmp_path, before)
        (repo / "AGENTS.md").write_text("---\n\n---\n\n# Demo\n")
        result = self._run(repo)
        assert result.returncode == 3, result.stdout + result.stderr
        assert "plainly prose" in result.stdout, result.stdout

    def test_a_destinations_frontmatter_cannot_account_for_a_body_line(
        self, tmp_path: Path
    ):
        """Frontmatter is skipped on the destination side too, so a body line
        that merely resembles a metadata field is not 'relocated' by landing
        beside one. The skip must never turn into a new way to pass."""
        repo = self._repo(tmp_path, "# Demo\n\nname: demo\n")
        (repo / "AGENTS.md").write_text("# Demo\n")
        (repo / "docs").mkdir()
        (repo / "docs" / "X.md").write_text(self._front("1.0") + "\n# X\n")
        result = self._run(repo)
        assert result.returncode == 3, result.stdout + result.stderr
        assert "name: demo" in result.stdout, result.stdout


class TestCensusInvariant:
    """`sections[]` rows must sum to the policy file's byte count — that is what
    makes `share` trustworthy, and the census comment advertises it."""

    def _measure(self, repo: Path) -> dict:
        result = subprocess.run(
            ["bash", str(MEASURE), "--no-write"],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=60,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def _repo(self, tmp_path: Path, body: str) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        (repo / "AGENTS.md").write_text(body)
        return repo

    def test_h3_before_any_h2_does_not_lose_bytes(self, tmp_path: Path):
        """A `### ` preceding both the first `## ` and the first body line used to
        add its bytes to an unnamed section, which the preamble initialiser then
        reset to zero: 71 bytes of file, 49 in the rows."""
        m = self._measure(self._repo(
            tmp_path,
            "### Orphan subsection\n\nsome body text here\n\n## Real section\n\nmore body\n",
        ))
        assert sum(s["bytes"] for s in m["sections"]) == m["policy"]["bytes"]
        assert [s["title"] for s in m["subsections"]] == ["Orphan subsection"]

    def test_normal_file_sums_exactly(self, tmp_path: Path):
        m = self._measure(self._repo(
            tmp_path,
            "# T\n\nintro\n\n## A\n\nbody\n\n### A1\n\nmore\n\n## B\n\ntail\n",
        ))
        assert sum(s["bytes"] for s in m["sections"]) == m["policy"]["bytes"]

    def test_subsection_bytes_never_exceed_the_parent(self, tmp_path: Path):
        m = self._measure(self._repo(
            tmp_path,
            "# T\n\n## A\n\nbody\n\n### A1\n\nmore text here\n\n### A2\n\nand more\n",
        ))
        parents = {s["title"]: s["bytes"] for s in m["sections"]}
        for sub in m["subsections"]:
            assert sub["bytes"] <= parents[sub["parent"]], sub

    def test_deeper_headings_are_not_reported_separately(self, tmp_path: Path):
        """`#### ` belongs to its enclosing `### ` — it is not independently
        demotable, and reporting it would invite splitting below the useful unit."""
        m = self._measure(self._repo(
            tmp_path, "# T\n\n## A\n\n### A1\n\n#### A1a\n\ndeep body\n",
        ))
        assert [s["title"] for s in m["subsections"]] == ["A1"]


class TestSkillVersionAttribution:
    """Without a version on the row, the ledger records what a repo did but not
    what made it do that — so no skill change can ever be attributed to an
    outcome, which is the precondition for gating changes on the cohort."""

    def test_measure_emits_the_declared_version(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=50)
        result = subprocess.run(
            ["bash", str(MEASURE), "--no-write"],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=60,
        )
        assert result.returncode == 0, result.stderr
        skill = json.loads(result.stdout)["skill"]
        assert skill["name"] == "curating-context"
        # Must match the frontmatter, not a hardcoded copy.
        declared = None
        for line in (SCRIPTS.parent / "SKILL.md").read_text().splitlines():
            if line.strip() == "---" and declared is not None:
                break
            if line.strip().startswith("version:"):
                declared = line.split(":", 1)[1].strip().strip('"').strip("'")
        assert skill["version"] == declared, (
            f"emitted {skill['version']!r} but SKILL.md declares {declared!r}"
        )

    def test_row_carries_the_version_through(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=50)
        measured = subprocess.run(
            ["bash", str(MEASURE), "--no-write"],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=60,
        ).stdout
        row = subprocess.run(
            ["bash", str(SCRIPTS / "record-telemetry.sh"), "--dry-run"],
            input=measured, capture_output=True, text=True,
            cwd=str(repo), env=_clean_env(), timeout=30,
        )
        assert row.returncode == 0, row.stderr
        parsed = json.loads(row.stdout)
        assert parsed["skill_version"], parsed
        assert parsed["skill_commit"], parsed

    def test_a_measurement_predating_the_field_yields_null_not_a_guess(
        self, tmp_path: Path
    ):
        """A wrong attribution is worse than a missing one when the whole point is
        to A/B skill changes."""
        repo = _repo(tmp_path, policy_lines=50)
        measured = json.loads(subprocess.run(
            ["bash", str(MEASURE), "--no-write"],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=60,
        ).stdout)
        del measured["skill"]
        row = subprocess.run(
            ["bash", str(SCRIPTS / "record-telemetry.sh"), "--dry-run"],
            input=json.dumps(measured), capture_output=True, text=True,
            cwd=str(repo), env=_clean_env(), timeout=30,
        )
        assert row.returncode == 0, row.stderr
        parsed = json.loads(row.stdout)
        assert parsed["skill_version"] is None and parsed["skill_commit"] is None

    def test_rollup_names_the_versions_in_play(self, tmp_path: Path):
        """An A/B needs at least two versions; a uniform cohort is a baseline."""
        for name, ver in (("a", "1.0"), ("b", "1.1")):
            d = tmp_path / name / ".skills"
            d.mkdir(parents=True)
            (d / "context-metrics.jsonl").write_text(json.dumps({
                "ts": "2026-08-01", "file": "AGENTS.md", "tokens": 5000,
                "tokens_exact": True, "skill_version": ver,
            }) + "\n")
        result = subprocess.run(
            ["bash", str(COHORT), "--local", f"{tmp_path/'a'} {tmp_path/'b'}"],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "skill versions in play:" in result.stdout
        assert "1.0: a" in result.stdout and "1.1: b" in result.stdout
        assert "a baseline, not a comparison" not in result.stdout

    def test_rollup_says_when_the_cohort_is_uniform(self, tmp_path: Path):
        d = tmp_path / "a" / ".skills"
        d.mkdir(parents=True)
        (d / "context-metrics.jsonl").write_text(json.dumps({
            "ts": "2026-08-01", "file": "AGENTS.md", "tokens": 5000,
            "tokens_exact": True, "skill_version": "1.1",
        }) + "\n")
        result = subprocess.run(
            ["bash", str(COHORT), "--local", str(tmp_path / "a")],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert "a baseline, not a comparison" in result.stdout, result.stdout


# ---------------------------------------------------------------------------
# The validation gate (#94)
# ---------------------------------------------------------------------------


def _ledger_row(**kw) -> str:
    row = {
        "ts": "2026-08-05", "repo": kw.get("repo", "x"), "file": "AGENTS.md",
        "tokens": None, "tokens_exact": True, "skill_version": None,
        "skill_commit": None, "budget": 6000, "docs_orphaned": 0,
        "links_dead": 0, "no_loss": None, "actions": [],
    }
    row.update(kw)
    return json.dumps(row, sort_keys=True)


def _arm(root: Path, name: str, before: int, after: int | None, version: str,
         **kw) -> None:
    """One cohort member with a baseline row and, optionally, a curation run."""
    d = root / name / ".skills"
    d.mkdir(parents=True, exist_ok=True)
    rows = [_ledger_row(repo=name, tokens=before, actions=["baseline:exact"],
                        docs_orphaned=kw.get("orph_before", 0))]
    if after is not None:
        rows.append(_ledger_row(
            repo=name, tokens=after, actions=["demote:Big"],
            skill_version=version, skill_commit="deadbee",
            no_loss=kw.get("no_loss", "ok"),
            links_dead=kw.get("links_dead", 0),
            # Passed through only when a caller asks for it, so the default
            # fixture keeps producing a row that PREDATES the field — the null
            # path score-cohort must not gate on, or every historical row in
            # the cohort would retroactively REJECT. Same for no_loss_warrants
            # (#111) and the claims pair (#253), whose null paths are the
            # entire existing cohort.
            **{k: kw[k] for k in ("links_dead_anchors", "no_loss_warrants",
                                  "claims_dropped", "claims_warranted")
               if k in kw},
            docs_orphaned=kw.get("orph_after", 0),
        ))
    (d / "context-metrics.jsonl").write_text("\n".join(rows) + "\n")


def _roster(root: Path, spec: list[tuple[str, str, str]]) -> Path:
    """spec entries are (name, wave, pair)."""
    path = root / "cohort"
    path.write_text("".join(
        f"{root / name}  wave:{wave} pair:{pair}\n" for name, wave, pair in spec
    ))
    return path


def _score(roster: Path, *args: str) -> subprocess.CompletedProcess:
    """The flags name VERSIONS, not waves (#194) — the fixtures' 1.2 treatment
    over their 1.1 control. Which arm a repo lands in is the skill_version on
    its own scored row, so the `wave:` values `_roster` writes are rollout order
    and score nothing."""
    return subprocess.run(
        ["bash", str(SCORE), "--cohort-file", str(roster),
         "--treatment", "1.2", "--control", "1.1", *args],
        capture_output=True, text=True, env=_clean_env(), timeout=60,
    )


def _three_good_pairs(root: Path, **treatment_kw) -> Path:
    """Three matched pairs where the treatment (wave b, v1.2) beats the
    control (wave a, v1.1) on every one."""
    # (control before, control after, treatment before, treatment after).
    # Closures: 69.6/86.0, 72.7/85.0, 76.9/87.5 — the treatment takes all three.
    pairs = [(52000, 20000, 49000, 12000), (28000, 12000, 26000, 9000),
             (19000, 9000, 14000, 7000)]
    spec = []
    for i, (cb, ca, tb, ta) in enumerate(pairs, start=1):
        _arm(root, f"ctl{i}", cb, ca, "1.1")
        _arm(root, f"trt{i}", tb, ta, "1.2", **treatment_kw)
        spec += [(f"ctl{i}", "a", str(i)), (f"trt{i}", "b", str(i))]
    return _roster(root, spec)


class TestValidationGate:
    """score-cohort.sh is the mechanism #94 asked for: the cohort as a held-out
    validation split, with a binary adopt/reject gate rather than judgement."""

    def test_sweep_adopts(self, tmp_path: Path):
        r = _score(_three_good_pairs(tmp_path))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "verdict: ADOPT" in r.stdout
        assert "won all 3 informative pairs" in r.stdout

    def test_one_lost_pair_rejects(self, tmp_path: Path):
        """Adoption requires a win on EVERY informative pair. A majority rule at
        this sample size is a rule for adopting noise."""
        roster = _three_good_pairs(tmp_path)
        # Make the treatment lose pair 3 outright.
        _arm(tmp_path, "trt3", 14000, 13000, "1.2")
        r = _score(roster)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "verdict: REJECT" in r.stdout
        assert "won 2 of 3" in r.stdout
        assert "pair 3 -> control" in r.stdout

    def test_a_tie_is_not_a_win(self, tmp_path: Path):
        """'No measurable difference' is a rejection, not a pass."""
        roster = _three_good_pairs(tmp_path)
        _arm(tmp_path, "ctl3", 19000, 7000, "1.1")
        _arm(tmp_path, "trt3", 19000, 7000, "1.2")
        r = _score(roster)
        assert r.returncode == 3, r.stdout
        assert "pair 3 -> tie" in r.stdout

    @pytest.mark.parametrize("kw,marker", [
        ({"no_loss": "failed"}, "no_loss=failed"),
        ({"links_dead": 2}, "links_dead=2"),
        # The anchor half of the link gate (#120/#124). A doc split moves
        # headings out of a file while leaving the file in place, so
        # links_dead stays 0 and only this catches it — without it the
        # measurement landed in Phase 6 while the gate stayed blind.
        ({"links_dead_anchors": 3}, "links_dead_anchors=3"),
        ({"orph_before": 0, "orph_after": 4}, "docs_orphaned 0->4"),
    ])
    def test_safety_gate_vetoes_a_winning_score(self, tmp_path: Path, kw, marker):
        """A change that reduces tokens by dropping content, breaking links, or
        orphaning docs is rejected however good its numbers are. There is no
        exchange rate at which that trade is acceptable, so the gate is a veto
        rather than a term in a weighted sum."""
        r = _score(_three_good_pairs(tmp_path, **kw))
        assert r.returncode == 3, r.stdout + r.stderr
        assert "verdict: REJECT" in r.stdout
        assert "safety gate tripped in the treatment arm" in r.stdout
        assert marker in r.stdout

    @pytest.mark.parametrize("verdict,marker", [
        (None, "no_loss=not recorded"),
        ("skipped", "no_loss=skipped"),
    ])
    def test_missing_no_loss_never_adopts(self, tmp_path: Path, verdict, marker):
        """A run that skipped Phase 6 must not clear a Phase 6 gate by silence.

        It blocks adoption like a failure, but it is INCONCLUSIVE rather than
        REJECT: nothing was refuted, the experiment was run without its safety
        check. Calling it a rejection would file the idea in
        rejected-changes.md as tested and beaten when it was neither."""
        r = _score(_three_good_pairs(tmp_path, no_loss=verdict))
        assert r.returncode == 5, r.stdout
        assert "verdict: ADOPT" not in r.stdout
        assert "safety could not be verified in the treatment arm" in r.stdout
        assert marker in r.stdout
        assert "re-run those curations with --no-loss" in r.stdout
        assert "record this in references/rejected-changes.md" not in r.stdout

    def test_control_arm_failure_is_reported_not_fatal(self, tmp_path: Path):
        """A gate tripping under the CURRENT version is a finding about today,
        not a reason to refuse tomorrow's proposal."""
        roster = _three_good_pairs(tmp_path)
        _arm(tmp_path, "ctl2", 28000, 12000, "1.1", no_loss="failed")
        # A genuine recorded failure, not a missing verdict — see
        # test_control_arm_missing_verdict_is_not_called_a_failure.
        # Pair 2 drops out as uninformative, so --min-pairs 2 keeps the run
        # decidable and the assertion stays on the claim being made: a failure
        # under the current version does not block adoption of the next one.
        r = _score(roster, "--min-pairs", "2")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "verdict: ADOPT" in r.stdout
        assert "control-arm safety failures" in r.stdout
        assert "ctl2" in r.stdout
        assert "not a reason to reject the proposal" in r.stdout

    def test_saturated_pair_is_uninformative_not_a_tie(self, tmp_path: Path):
        """Closure caps at 1.0, so when both arms reach budget the metric cannot
        express a difference. Scoring that as a tie would make the sweep rule
        unsatisfiable for any pair starting close to budget."""
        _arm(tmp_path, "ctl1", 6200, 5000, "1.1")
        _arm(tmp_path, "trt1", 6100, 4000, "1.2")
        roster = _roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")])
        r = _score(roster, "--min-pairs", "1")
        assert "saturates" in r.stdout, r.stdout
        assert "-> tie" not in r.stdout
        assert r.returncode == 5

    def test_no_gap_pair_is_uninformative(self, tmp_path: Path):
        """A repo already under budget has no gap to close; it is not a 0 or a 1."""
        _arm(tmp_path, "ctl1", 5400, 5200, "1.1")
        _arm(tmp_path, "trt1", 5300, 5100, "1.2")
        roster = _roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")])
        r = _score(roster, "--min-pairs", "1")
        assert "no budget gap to close" in r.stdout, r.stdout
        assert r.returncode == 5

    def test_same_version_in_both_arms_is_inconclusive(self, tmp_path: Path):
        """A uniform cohort is a baseline, not a comparison — and must not read
        as a rejection of the thing it never tested.

        Since #194 the arm IS the version, so a cohort uniformly on 1.1 cannot
        put anything in a 1.2 treatment arm: the state is reported as an empty
        treatment arm rather than as two arms that happened to match. Naming ONE
        release for both flags is the other half of the same guarantee and is a
        usage error — see test_same_version_for_both_arms_is_a_usage_error."""
        pairs = [(52000, 12000, 49000, 20000), (28000, 8000, 26000, 12000),
                 (19000, 7000, 14000, 9000)]
        spec = []
        for i, (cb, ca, tb, ta) in enumerate(pairs, start=1):
            _arm(tmp_path, f"ctl{i}", cb, ca, "1.1")
            _arm(tmp_path, f"trt{i}", tb, ta, "1.1")
            spec += [(f"ctl{i}", "a", str(i)), (f"trt{i}", "b", str(i))]
        r = _score(_roster(tmp_path, spec))
        assert r.returncode == 5, r.stdout
        assert "no scored run carries the treatment version 1.2" in r.stdout
        assert "verdict: REJECT" not in r.stdout

    def test_inconclusive_is_not_filed_as_a_rejection(self, tmp_path: Path):
        """Recording a non-result in rejected-changes.md would teach a later
        reader that the idea was tested and failed."""
        _arm(tmp_path, "ctl1", 52000, 12000, "1.1")
        _arm(tmp_path, "trt1", 49000, 20000, "1.2")
        r = _score(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")]))
        assert r.returncode == 5
        assert "does not belong in" in r.stdout
        assert "record this in references/rejected-changes.md" not in r.stdout

    def test_reject_points_at_the_rejection_buffer(self, tmp_path: Path):
        roster = _three_good_pairs(tmp_path)
        _arm(tmp_path, "trt3", 14000, 13000, "1.2")
        r = _score(roster)
        assert "references/rejected-changes.md" in r.stdout

    def test_baseline_only_repo_is_unscorable_not_scored(self, tmp_path: Path):
        """A baseline row is a measurement, not a curation."""
        _arm(tmp_path, "ctl1", 52000, None, "1.1")
        _arm(tmp_path, "trt1", 49000, 20000, "1.2")
        r = _score(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")]),
                   "--min-pairs", "1")
        assert r.returncode == 5, r.stdout
        assert "no attributed curation run" in r.stdout

    def test_unannotated_roster_refuses_rather_than_reporting_nothing(
            self, tmp_path: Path):
        """An empty comparison must not read as an experiment that found nothing.

        What the roster has to carry is `pair:` (#194). The arms come off each
        row's skill_version now, so `wave:` is rollout order and a roster
        carrying nothing but waves describes no comparison at all."""
        path = tmp_path / "cohort"
        path.write_text("CannObserv/archiver\nCannObserv/notifier\n")
        r = subprocess.run(
            ["bash", str(SCORE), "--cohort-file", str(path),
             "--treatment", "1.2", "--control", "1.1"],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert r.returncode == 1
        assert "no pair: assignment" in r.stderr
        assert "wave:a pair:1" in r.stderr

    def test_same_version_for_both_arms_is_a_usage_error(self, tmp_path: Path):
        r = subprocess.run(
            ["bash", str(SCORE), "--treatment", "1.2", "--control", "1.2"],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert r.returncode == 1
        assert "same version" in r.stderr

    def test_json_format_carries_the_verdict_and_the_pairs(self, tmp_path: Path):
        r = _score(_three_good_pairs(tmp_path), "--format", "json")
        payload = json.loads(r.stdout)
        assert payload["verdict"] == "ADOPT"
        assert payload["treatment_versions"] == ["1.2"]
        assert payload["control_versions"] == ["1.1"]
        assert payload["informative_pairs"] == 3
        assert len(payload["pairs"]) == 3

    def test_sweep_below_significance_says_so(self, tmp_path: Path):
        """Three pairs is p=0.125. The gate must not let a sweep read as proof."""
        r = _score(_three_good_pairs(tmp_path))
        assert "p=0.125" in r.stdout
        assert "suggestive rather than significant" in r.stdout


class TestRosterAnnotations:
    """The roster is parsed by one function in the library, because two parsers
    would be two opinions about the experiment's own assignment."""

    def test_empty_wave_does_not_shift_the_pair_field(self, tmp_path: Path):
        """The reason the roster is not tab-separated: `IFS=$'\\t' read` collapses
        runs of tabs, so an unassigned wave would silently slide the pair value
        into the wave variable and put a repo in the wrong arm."""
        path = tmp_path / "cohort"
        path.write_text("owner/one  pair:7\nowner/two  wave:b pair:7\n")
        out = subprocess.run(
            ["bash", "-c",
             f'. "{LIB}"; ctx_read_roster "{path}" | tr "\\037" "|"'],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert out.stdout.splitlines() == ["repo|owner/one||7", "repo|owner/two|b|7"]

    def test_unknown_annotation_warns_and_is_ignored(self, tmp_path: Path):
        path = tmp_path / "cohort"
        path.write_text("owner/one  wave:a cohort:x\n")
        out = subprocess.run(
            ["bash", "-c", f'. "{LIB}"; ctx_read_roster "{path}" | tr "\\037" "|"'],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert "unknown roster annotation" in out.stderr
        assert out.stdout.strip() == "repo|owner/one|a|"

    def test_comments_and_local_paths_still_parse(self, tmp_path: Path):
        path = tmp_path / "cohort"
        path.write_text("# a comment\n\n/abs/path  wave:a pair:1\nowner/two\n")
        out = subprocess.run(
            ["bash", "-c", f'. "{LIB}"; ctx_read_roster "{path}" | tr "\\037" "|"'],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert out.stdout.splitlines() == ["local|/abs/path|a|1", "repo|owner/two||"]

    def test_shipped_roster_is_fully_paired(self):
        """Every cohort member is in exactly one pair, each pair holds one repo
        from each arm, and the arms are the same size. A half-assigned roster
        would produce a verdict from whichever repos happened to be annotated."""
        root = Path(__file__).resolve().parent.parent.parent
        out = subprocess.run(
            ["bash", "-c",
             f'. "{LIB}"; ctx_read_roster "{root / ".skills" / "cohort"}"'],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        rows = [line.split("\x1f") for line in out.stdout.splitlines()]
        assert len(rows) == 12
        assert all(wave in ("a", "b") and pair for _, _, wave, pair in rows)
        by_pair: dict[str, list[str]] = {}
        for _, _, wave, pair in rows:
            by_pair.setdefault(pair, []).append(wave)
        assert len(by_pair) == 6
        assert all(sorted(v) == ["a", "b"] for v in by_pair.values())

    def test_rollup_reports_the_split(self, tmp_path: Path):
        """Rollout order is a property of the cohort, so it belongs in the
        roll-up and not only inside the gate.

        Labelled as rollout order rather than as a validation split: the wave
        annotation has never determined which version a repo runs, and this is
        the output a reader reaches for first (#168)."""
        _arm(tmp_path, "one", 9000, 5000, "1.1")
        _arm(tmp_path, "two", 9000, None, "1.1")
        roster = _roster(tmp_path, [("one", "a", "1"), ("two", "b", "1")])
        r = subprocess.run(
            ["bash", str(COHORT), "--cohort-file", str(roster)],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert r.returncode == 0, r.stderr
        assert "rollout waves" in r.stdout
        assert "not an arm assignment" in r.stdout
        assert "wave a: 1 repos, 1 adopted" in r.stdout
        assert "wave b: 1 repos, 0 adopted" in r.stdout


class TestNoLossOnTheRow:
    """--no-loss is what puts Phase 6's verdict where the gate can read it."""

    def test_verdict_lands_on_the_row(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=10)
        out = subprocess.run(
            ["bash", "-c",
             f'cd "{repo}" && bash "{MEASURE}" --no-write 2>/dev/null'
             f' | bash "{RECORD}" --dry-run --no-loss ok'],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        assert json.loads(out.stdout)["no_loss"] == "ok"

    def test_absent_flag_records_null_not_ok(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=10)
        out = subprocess.run(
            ["bash", "-c",
             f'cd "{repo}" && bash "{MEASURE}" --no-write 2>/dev/null'
             f' | bash "{RECORD}" --dry-run'],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        assert json.loads(out.stdout)["no_loss"] is None

    def test_unrecognised_verdict_is_refused(self, tmp_path: Path):
        """A gate reads anything but 'ok' as not-ok, so a typo would be a silent
        permanent failure — and a leniently-normalised 'OK' a silent pass."""
        repo = _repo(tmp_path, policy_lines=10)
        out = subprocess.run(
            ["bash", "-c",
             f'cd "{repo}" && bash "{MEASURE}" --no-write 2>/dev/null'
             f' | bash "{RECORD}" --dry-run --no-loss OK'],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        assert out.returncode == 1
        assert "must be ok, failed, or skipped" in out.stderr


class TestValidationGateRoundSix:
    """Regressions found reviewing the gate: each of these produced a verdict
    that was wrong rather than merely unhelpful."""

    def test_before_state_comes_from_the_same_policy_file(self, tmp_path: Path):
        """A ledger may track more than one policy file. Taking the row that
        merely happens to precede the curation fabricated the before-state: a
        repo that really went 50,000 -> 9,000 scored -2900% off an unrelated
        file's 6,100 and handed the pair to the other arm."""
        d = tmp_path / "ctl1" / ".skills"
        d.mkdir(parents=True)
        (d / "context-metrics.jsonl").write_text("\n".join([
            _ledger_row(repo="ctl1", tokens=50000, actions=["baseline:exact"]),
            _ledger_row(repo="ctl1", tokens=6100, file="sub/AGENTS.md",
                        actions=["baseline:exact"]),
            _ledger_row(repo="ctl1", tokens=9000, actions=["demote:X"],
                        skill_version="1.1", no_loss="ok"),
        ]) + "\n")
        _arm(tmp_path, "trt1", 49000, 9500, "1.2")
        r = _score(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")]),
                   "--min-pairs", "1", "--format", "json")
        out = json.loads(r.stdout)
        ctl = next(x for x in out["repos"] if x["repo"] == "ctl1")
        assert ctl["before"] == 50000, ctl
        # 50,000 -> 9,000 against a 6,000 budget is 93.2% closure, so the
        # control wins this pair and the treatment must not be adopted.
        assert round(ctl["closure"], 3) == round((44000 - 3000) / 44000, 3)
        # The pair outcome is what the fabricated before-state got wrong, so it
        # is what this pins. The VERDICT is INCONCLUSIVE rather than REJECT only
        # because one pair is below the rejection floor — a separate rule, with
        # its own test.
        assert out["pairs"][0]["winner"] == "control", out["pairs"]
        assert out["verdict"] != "ADOPT"

    def test_min_pairs_zero_is_refused(self, tmp_path: Path):
        """`--min-pairs 0` let the sweep test read `0 == 0` and adopt on no
        evidence whatever — a vacuous pass in the control that exists to
        prevent them."""
        r = _score(_three_good_pairs(tmp_path), "--min-pairs", "0")
        assert r.returncode == 1
        assert "at least 1" in r.stderr

    def test_zero_informative_pairs_never_adopts(self, tmp_path: Path):
        """Belt to --min-pairs' braces: the sweep branch is guarded on its own,
        so the two failures cannot line up again."""
        _arm(tmp_path, "ctl1", 6200, 5000, "1.1")
        _arm(tmp_path, "trt1", 6100, 4000, "1.2")
        r = _score(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")]),
                   "--min-pairs", "1")
        assert r.returncode == 5, r.stdout
        assert "no informative pairs" in r.stdout
        assert "verdict: ADOPT" not in r.stdout

    def test_control_arm_missing_verdict_is_not_called_a_failure(
            self, tmp_path: Path):
        """'Failure' in the control-arm report means the shipped version did
        something wrong. A run nobody checked is not that, and labelling it so
        is the sort of line that gets quoted in an issue."""
        roster = _three_good_pairs(tmp_path)
        _arm(tmp_path, "ctl2", 28000, 12000, "1.1", no_loss=None)
        r = _score(roster, "--min-pairs", "2")
        assert "control-arm runs with no safety verdict" in r.stdout, r.stdout
        assert "not a failure" in r.stdout
        assert "control-arm safety failures" not in r.stdout

    def test_an_arm_can_no_longer_be_split_across_versions(self, tmp_path: Path):
        """'Adopt only if strictly better' presumes ONE proposal, and a sweep
        carried by whichever version drew the easier pairs would not be one.

        Diagnosed after the fact while the arm was a wave; ruled out by
        construction since #194, because the arm IS the version. The repo on the
        third version leaves the arm instead of splitting it, and the pair it was
        carrying stops being a comparison — which is the same refusal, reached
        without needing to notice the split."""
        for i, (cb, ca, tb, ta) in enumerate(
                [(50000, 20000, 49000, 12000), (30000, 14000, 29000, 9000)],
                start=1):
            _arm(tmp_path, f"ctl{i}", cb, ca, "1.1")
            _arm(tmp_path, f"trt{i}", tb, ta, "1.2" if i == 1 else "1.9")
        r = _score(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1"),
                                      ("ctl2", "a", "2"), ("trt2", "b", "2")]),
                   "--min-pairs", "2", "--format", "json")
        payload = json.loads(r.stdout)
        assert r.returncode == 5, r.stdout
        assert payload["treatment_versions"] == ["1.2"]
        assert next(x for x in payload["repos"]
                    if x["repo"] == "trt2")["arm"] is None
        pair2 = next(p for p in payload["pairs"] if p["pair"] == "2")
        assert "0 treatment and 1 control" in pair2["why"], pair2
        assert "trt2 is in neither arm — 1.9" in pair2["why"], pair2
        assert payload["verdict"] != "ADOPT"

    def test_basename_collision_keeps_repos_distinct(self, tmp_path: Path):
        """OrgA/cli and OrgB/cli merged into one record, concatenating two
        ledgers and reporting an arm as having no attributed run when it had
        one — a diagnosis that sends someone hunting a ledger that exists."""
        (tmp_path / "OrgA").mkdir()
        (tmp_path / "OrgB").mkdir()
        _arm(tmp_path, "OrgA/cli", 50000, 9000, "1.1")
        _arm(tmp_path, "OrgB/cli", 49000, 12000, "1.2")
        roster = _roster(tmp_path, [("OrgA/cli", "a", "1"),
                                    ("OrgB/cli", "b", "1")])
        r = _score(roster, "--min-pairs", "1", "--format", "json")
        payload = json.loads(r.stdout)
        assert len(payload["repos"]) == 2
        assert payload["treatment_versions"] == ["1.2"]
        assert payload["control_versions"] == ["1.1"]
        # Ambiguous basenames are shown in full rather than identically.
        assert {x["repo"] for x in payload["repos"]} == {
            str(tmp_path / "OrgA/cli"), str(tmp_path / "OrgB/cli")}

    def test_unambiguous_basenames_stay_short(self, tmp_path: Path):
        r = _score(_three_good_pairs(tmp_path), "--format", "json")
        assert {x["repo"] for x in json.loads(r.stdout)["repos"]} == {
            "ctl1", "ctl2", "ctl3", "trt1", "trt2", "trt3"}

    def test_inverted_arms_are_detected_and_refuse_to_reject(self, tmp_path: Path):
        """In experiment 1 wave A adopted first and held the OLDER version, so
        running the script bare during that round inverted the comparison. Past
        tense twice over: a wave never held a version (#168), and since #194
        there is no bare invocation — but a caller can still type the two
        versions in the wrong order, and this is what the gate owes when they do.

        Detection alone was not enough: the WARN printed at the top and the
        verdict then rejected the winning change and told the reader to file it
        in rejected-changes.md, twenty lines below the warning saying not to
        trust the result. A rejection entry is permanent and shapes future
        proposals, so recording a *winning* change as refuted is the worst
        single output this script can produce."""
        roster = _three_good_pairs(tmp_path)
        r = subprocess.run(
            ["bash", str(SCORE), "--cohort-file", str(roster),
             "--treatment", "1.1", "--control", "1.2"],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        assert "OLDER than" in r.stdout, r.stdout
        assert "--treatment 1.2 --control 1.1" in r.stdout
        assert r.returncode == 5
        assert "verdict: INCONCLUSIVE" in r.stdout
        assert "verdict: REJECT" not in r.stdout
        assert "record this in references/rejected-changes.md" not in r.stdout

    def test_correctly_ordered_arms_are_not_warned_about(self, tmp_path: Path):
        r = _score(_three_good_pairs(tmp_path))
        assert "OLDER than" not in r.stdout

    def test_version_comparison_is_numeric_not_lexical(self, tmp_path: Path):
        """1.10 is newer than 1.9. A string compare says otherwise, which is
        why the verdict never uses this ordering and the warning does."""
        _arm(tmp_path, "ctl1", 50000, 20000, "1.9")
        _arm(tmp_path, "trt1", 49000, 12000, "1.10")
        r = subprocess.run(
            ["bash", str(SCORE), "--cohort-file",
             str(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")])),
             "--treatment", "1.10", "--control", "1.9", "--min-pairs", "1"],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        assert "OLDER than" not in r.stdout, r.stdout
        assert "verdict: ADOPT" in r.stdout

    def test_untagged_attributed_run_is_unscorable(self, tmp_path: Path):
        """record-telemetry.sh emits actions: [] when --actions was omitted.
        Scoring that as a curation attributes its near-zero closure to the
        skill version; skipping past it hides the tagging gap."""
        d = tmp_path / "trt1" / ".skills"
        d.mkdir(parents=True)
        (d / "context-metrics.jsonl").write_text("\n".join([
            _ledger_row(repo="trt1", tokens=49000, actions=["baseline:exact"]),
            _ledger_row(repo="trt1", tokens=48000, actions=[],
                        skill_version="1.2", no_loss="ok"),
        ]) + "\n")
        _arm(tmp_path, "ctl1", 50000, 20000, "1.1")
        r = _score(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")]),
                   "--min-pairs", "1")
        assert r.returncode == 5, r.stdout
        assert "no action tags" in r.stdout
        assert "tag it and re-score" in r.stdout


class TestCohortReportSingleFile:
    def test_net_does_not_span_two_policy_files(self, tmp_path: Path):
        """Same defect as the gate's before-state, in the roll-up: `net` would
        span two different files and report a change for one that never moved.
        That is the class of error the method-change anchoring exists to
        prevent, so it gets the same treatment."""
        d = tmp_path / "one" / ".skills"
        d.mkdir(parents=True)
        (d / "context-metrics.jsonl").write_text("\n".join([
            _ledger_row(repo="one", tokens=9000, actions=["baseline:exact"]),
            _ledger_row(repo="one", tokens=500, file="sub/AGENTS.md",
                        actions=["baseline:exact"]),
            _ledger_row(repo="one", tokens=9000, actions=["demote:X"],
                        skill_version="1.1"),
        ]) + "\n")
        r = subprocess.run(
            ["bash", str(COHORT), "--local", str(tmp_path / "one"),
             "--format", "tsv"],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert r.returncode == 0, r.stderr
        header, row = r.stdout.splitlines()[0].split("\t"), \
            r.stdout.splitlines()[1].split("\t")
        cells = dict(zip(header, row))
        # AGENTS.md never moved: 9000 both times. Against sub/AGENTS.md's 500 it
        # would read +8500.
        assert cells["net"] == "0", cells
        # One curation on AGENTS.md. `runs` counts curations, not rows, so
        # neither its own baseline nor sub/AGENTS.md's row is in this number.
        assert cells["runs"] == "1", cells


def _two_file_ledger(root: Path, name: str, version: str,
                     main_after: int, sub_after: int) -> None:
    """A repo whose ledger tracks two policy files: a big curation on the
    primary one, and a trivial prune on a secondary one recorded earlier."""
    d = root / name / ".skills"
    d.mkdir(parents=True)
    (d / "context-metrics.jsonl").write_text("\n".join([
        _ledger_row(repo=name, ts="2026-08-01", tokens=50000,
                    actions=["baseline:exact"]),
        _ledger_row(repo=name, ts="2026-08-01", file="sub/AGENTS.md",
                    tokens=9000, actions=["baseline:exact"]),
        _ledger_row(repo=name, ts="2026-08-02", file="sub/AGENTS.md",
                    tokens=sub_after, actions=["prune:tiny"],
                    skill_version=version, no_loss="ok"),
        _ledger_row(repo=name, ts="2026-08-03", tokens=main_after,
                    actions=["demote:Big"], skill_version=version,
                    no_loss="ok"),
    ]) + "\n")


class TestValidationGateRoundSeven:
    def test_gate_scores_the_primary_policy_file(self, tmp_path: Path):
        """The scan took the first curation across ALL files, so a trivial prune
        recorded a day earlier on a secondary file was scored instead of the
        real one: sub/AGENTS.md 9,000 -> 8,900 (3.3%) rather than AGENTS.md
        50,000 -> 7,000 (93.2%)."""
        _two_file_ledger(tmp_path, "ctl1", "1.1", main_after=7000, sub_after=8900)
        _two_file_ledger(tmp_path, "trt1", "1.2", main_after=9000, sub_after=8800)
        r = _score(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")]),
                   "--min-pairs", "1", "--format", "json")
        out = json.loads(r.stdout)
        by = {x["repo"]: x for x in out["repos"]}
        assert by["ctl1"]["file"] == "AGENTS.md", by["ctl1"]
        assert by["ctl1"]["before"] == 50000
        assert by["ctl1"]["after"] == 7000
        assert by["trt1"]["after"] == 9000
        # The control did the better job on the primary file, so no adoption.
        # Scored off sub/AGENTS.md the pair went the other way, which is the
        # regression this pins; the verdict is INCONCLUSIVE rather than REJECT
        # because one pair is below the rejection floor.
        assert out["pairs"][0]["winner"] == "control", out["pairs"]
        assert out["verdict"] != "ADOPT"

    def test_gate_and_rollup_agree_on_which_file_a_repo_is(self, tmp_path: Path):
        """One ledger produced two irreconcilable pictures of the same repo.
        The rule is duplicated in two languages, so pin them to one answer."""
        _two_file_ledger(tmp_path, "one", "1.1", main_after=7000, sub_after=8900)
        gate = _score(_roster(tmp_path, [("one", "a", "1")]),
                      "--min-pairs", "1", "--format", "json")
        rollup = subprocess.run(
            ["bash", str(COHORT), "--local", str(tmp_path / "one"),
             "--format", "tsv"],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        cells = dict(zip(*(line.split("\t")
                           for line in rollup.stdout.splitlines()[:2])))
        gate_rec = json.loads(gate.stdout)["repos"][0]
        assert gate_rec["file"] == "AGENTS.md"
        assert int(cells["tokens"]) == gate_rec["after"] == 7000
        # One curation on AGENTS.md. Counting every file's curations would
        # read 2 — sub/AGENTS.md was pruned too.
        assert int(cells["runs"]) == 1

    def test_uncurated_primary_file_names_the_file_and_the_others(
            self, tmp_path: Path):
        """Scoring a secondary file instead would be the bug this replaced; the
        honest answer names what was skipped rather than dropping the repo."""
        # AGENTS.md is the primary (3 rows) and was never curated; the curation
        # happened on a secondary file. Scoring that secondary file instead
        # would be the bug this replaced.
        d = tmp_path / "one" / ".skills"
        d.mkdir(parents=True)
        (d / "context-metrics.jsonl").write_text("\n".join([
            _ledger_row(repo="one", ts="2026-08-01", tokens=50000,
                        actions=["baseline:exact"]),
            _ledger_row(repo="one", ts="2026-08-02", tokens=50000,
                        actions=["baseline:exact"]),
            _ledger_row(repo="one", ts="2026-08-03", tokens=50000,
                        actions=["baseline:exact"]),
            _ledger_row(repo="one", ts="2026-08-04", file="sub/AGENTS.md",
                        tokens=9000, actions=["baseline:exact"]),
            _ledger_row(repo="one", ts="2026-08-05", file="sub/AGENTS.md",
                        tokens=7000, actions=["demote:X"], skill_version="1.1",
                        no_loss="ok"),
        ]) + "\n")
        _arm(tmp_path, "two", 49000, 12000, "1.2")
        r = _score(_roster(tmp_path, [("one", "a", "1"), ("two", "b", "1")]),
                   "--min-pairs", "1")
        assert "no attributed curation run for AGENTS.md" in r.stdout, r.stdout
        assert "1 other file(s) in this ledger were not scored" in r.stdout

    def test_a_failure_with_no_proposal_in_front_of_it_is_not_a_rejection(
            self, tmp_path: Path):
        """There is no proposal to reject, so the entry would name no change.
        The failure is real and must stay visible — it is a finding about the
        shipped version.

        Read off the versions since #194: both repos ran 1.1, so both are in the
        CONTROL arm however the roster labels them, the treatment arm is empty,
        and the failure is reported as what it is — the current version failing.
        Grouped by wave the same failure was a treatment-arm failure, and only
        the same-version branch kept it from rejecting a proposal that did not
        exist."""
        _arm(tmp_path, "ctl1", 52000, 20000, "1.1")
        _arm(tmp_path, "trt1", 49000, 12000, "1.1", no_loss="failed")
        r = _score(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")]),
                   "--min-pairs", "1")
        assert r.returncode == 5, r.stdout
        assert "no scored run carries the treatment version 1.2" in r.stdout
        assert "record this in references/rejected-changes.md" not in r.stdout
        # Still visible, and on the side that ran it.
        assert "control-arm safety failures" in r.stdout
        assert "not a reason to reject the proposal" in r.stdout
        assert "no_loss=failed" in r.stdout

    def test_real_failure_still_rejects_when_there_is_a_proposal(
            self, tmp_path: Path):
        """The reordering must not have disarmed the veto."""
        r = _score(_three_good_pairs(tmp_path, no_loss="failed"))
        assert r.returncode == 3, r.stdout
        assert "verdict: REJECT" in r.stdout
        assert "treatment-arm safety failures:" in r.stdout

    def test_out_of_arm_entries_are_reported(self, tmp_path: Path):
        """A repo that quietly leaves the experiment with no trace anywhere in
        the output is a gate shrinking its own sample. What puts it out of the
        arms changed with #194 — a scored run on some third version rather than
        a typo'd wave: — and the report has to survive the move."""
        roster = _three_good_pairs(tmp_path)
        _arm(tmp_path, "stray", 9000, 7000, "0.9")
        with roster.open("a") as fh:
            fh.write(f"{tmp_path / 'stray'}  wave:b pair:9\n")
        r = _score(roster)
        assert "not in either arm" in r.stdout, r.stdout
        assert "stray" in r.stdout
        assert "0.9" in r.stdout

    def test_out_of_arm_appears_in_json(self, tmp_path: Path):
        roster = _three_good_pairs(tmp_path)
        _arm(tmp_path, "stray", 9000, 7000, "0.9")
        with roster.open("a") as fh:
            fh.write(f"{tmp_path / 'stray'}  wave:b pair:9\n")
        payload = json.loads(_score(roster, "--format", "json").stdout)
        assert payload["out_of_arm"] == [
            {"entry": str(tmp_path / "stray"), "repo": "stray", "wave": "b",
             "skill_version": "0.9"}]

    def test_duplicate_rows_do_not_shift_the_before_state(self, tmp_path: Path):
        """list.index matches by dict equality, not identity, so a byte-identical
        repeat of the curation row resolved to the earlier one and took the
        before-state a row too early."""
        d = tmp_path / "one" / ".skills"
        d.mkdir(parents=True)
        dup = _ledger_row(repo="one", ts="2026-08-02", tokens=9000,
                          actions=["demote:X"], skill_version="1.1",
                          no_loss="ok")
        (d / "context-metrics.jsonl").write_text("\n".join([
            _ledger_row(repo="one", ts="2026-08-01", tokens=50000,
                        actions=["baseline:exact"]),
            dup, dup,
        ]) + "\n")
        r = _score(_roster(tmp_path, [("one", "a", "1")]), "--min-pairs", "1",
                   "--format", "json")
        rec = json.loads(r.stdout)["repos"][0]
        assert rec["before"] == 50000, rec


class TestValidationGateRoundEight:
    def test_a_stray_row_cannot_redefine_the_repo(self, tmp_path: Path):
        """Most-recent-file alone was too fragile: one incidental baseline row
        for docs/GUIDE.md re-defined a repo that had curated AGENTS.md over
        three runs, dropping it out of the experiment and collapsing the
        roll-up's headline to 4,000 tokens / no runs / no net — a number that then
        fed the cohort total. Row count is what a stray append cannot flip."""
        d = tmp_path / "one" / ".skills"
        d.mkdir(parents=True)
        (d / "context-metrics.jsonl").write_text("\n".join([
            _ledger_row(repo="one", ts="2026-08-01", tokens=50000,
                        actions=["baseline:exact"]),
            _ledger_row(repo="one", ts="2026-08-02", tokens=7000,
                        actions=["demote:Big"], skill_version="1.1",
                        no_loss="ok"),
            _ledger_row(repo="one", ts="2026-08-03", tokens=6800,
                        actions=["prune:X"], skill_version="1.1", no_loss="ok"),
            _ledger_row(repo="one", ts="2026-08-04", file="docs/GUIDE.md",
                        tokens=4000, actions=["baseline:exact"]),
        ]) + "\n")
        _arm(tmp_path, "two", 49000, 12000, "1.2")
        gate = _score(_roster(tmp_path, [("one", "a", "1"), ("two", "b", "1")]),
                      "--min-pairs", "1", "--format", "json")
        rec = next(x for x in json.loads(gate.stdout)["repos"]
                   if x["repo"] == "one")
        assert rec["file"] == "AGENTS.md", rec
        assert rec["status"] == "scored"
        assert rec["before"] == 50000 and rec["after"] == 7000
        rollup = subprocess.run(
            ["bash", str(COHORT), "--local", str(tmp_path / "one"),
             "--format", "tsv"],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        cells = dict(zip(*(line.split("\t")
                           for line in rollup.stdout.splitlines()[:2])))
        assert cells["tokens"] == "6800", cells
        # Two curations on AGENTS.md, plus a baseline. Scored off the stray
        # docs/GUIDE.md row this would read 0 runs.
        assert cells["runs"] == "2", cells
        assert cells["net"] == "-43200", cells

    def test_ties_on_row_count_fall_back_to_most_recent(self, tmp_path: Path):
        """The tie-break has to stay deterministic, and it has to be the same
        one cohort-report.sh uses."""
        _two_file_ledger(tmp_path, "one", "1.1", main_after=7000, sub_after=8900)
        gate = _score(_roster(tmp_path, [("one", "a", "1")]), "--min-pairs", "1",
                      "--format", "json")
        assert json.loads(gate.stdout)["repos"][0]["file"] == "AGENTS.md"
        rollup = subprocess.run(
            ["bash", str(COHORT), "--local", str(tmp_path / "one"),
             "--format", "tsv"],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        cells = dict(zip(*(line.split("\t")
                           for line in rollup.stdout.splitlines()[:2])))
        assert cells["tokens"] == "7000", cells

    def test_same_release_spelled_two_ways_is_not_an_experiment(
            self, tmp_path: Path):
        """1.2 and 1.2.0 are one release. Comparing the raw strings made them
        two, and the gate returned ADOPT for a release scored against itself —
        the mirror of adopting on zero evidence.

        Asked of the FLAGS since #194, and answered before any ledger is read:
        the two versions define the arms, so naming one release twice is a
        mistyped invocation rather than a finding about the rows. The
        canonicalisation being tested is the same one."""
        _arm(tmp_path, "one", 50000, 20000, "1.2")
        _arm(tmp_path, "two", 49000, 12000, "1.2.0")
        r = subprocess.run(
            ["bash", str(SCORE), "--cohort-file",
             str(_roster(tmp_path, [("one", "a", "1"), ("two", "b", "1")])),
             "--treatment", "1.2.0", "--control", "1.2", "--min-pairs", "1"],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        assert r.returncode == 1, r.stdout + r.stderr
        assert "canonicalise to the same release" in r.stderr
        assert "verdict: ADOPT" not in r.stdout

    def test_prereleases_are_not_collapsed_into_one_version(self, tmp_path: Path):
        """version_canon must not be version_key: the latter maps every
        non-numeric component to 0, which would make 2.0-alpha and 2.0-beta the
        same version and report two real changes as no experiment at all."""
        _arm(tmp_path, "one", 50000, 20000, "2.0-alpha")
        _arm(tmp_path, "two", 49000, 12000, "2.0-beta")
        r = subprocess.run(
            ["bash", str(SCORE), "--cohort-file",
             str(_roster(tmp_path, [("one", "a", "1"), ("two", "b", "1")])),
             "--treatment", "2.0-beta", "--control", "2.0-alpha",
             "--min-pairs", "1"],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        assert "same release" not in r.stderr, r.stderr
        assert "verdict: ADOPT" in r.stdout, r.stdout

    def test_empty_control_arm_says_so(self, tmp_path: Path):
        """The expected intermediate state during the first experiment: wave B
        adopts before wave A has re-run. 'No informative pairs' is true and
        sends the reader to look at pair scoring instead of adoption progress."""
        d = tmp_path / "one" / ".skills"
        d.mkdir(parents=True)
        (d / "context-metrics.jsonl").write_text(
            _ledger_row(repo="one", tokens=50000, actions=["baseline:exact"])
            + "\n")
        _arm(tmp_path, "two", 49000, 12000, "1.2")
        r = _score(_roster(tmp_path, [("one", "a", "1"), ("two", "b", "1")]),
                   "--min-pairs", "1")
        assert r.returncode == 5, r.stdout
        assert "no scored run carries the control version 1.1" in r.stdout
        assert "nothing to be compared against" in r.stdout

    def test_a_mixed_cohort_is_diagnosed_repo_by_repo_not_as_an_arm(
            self, tmp_path: Path):
        """The state the split-arm diagnosis existed for, under the new rule.

        Four repos on three versions used to produce one arm-level verdict —
        "wave b is split" — that named a wave and left the reader to work out
        which repo. Now each repo is placed by its own row: the 1.2 one is the
        treatment arm, the 1.1 one is the control arm however its wave reads,
        and the two on 1.3 are in neither and are named as such."""
        _arm(tmp_path, "c1", 50000, 20000, "1.3")
        _arm(tmp_path, "t1", 49000, 12000, "1.1")
        _arm(tmp_path, "c2", 30000, 14000, "1.3")
        _arm(tmp_path, "t2", 29000, 9000, "1.2")
        r = _score(_roster(tmp_path, [("c1", "a", "1"), ("t1", "b", "1"),
                                      ("c2", "a", "2"), ("t2", "b", "2")]),
                   "--min-pairs", "1", "--format", "json")
        payload = json.loads(r.stdout)
        arms = {x["repo"]: x["arm"] for x in payload["repos"]}
        assert arms == {"c1": None, "c2": None, "t1": "control",
                        "t2": "treatment"}, arms
        assert {x["repo"] for x in payload["out_of_arm"]} == {"c1", "c2"}
        assert "split across versions" not in r.stdout
        assert "OLDER than" not in r.stdout

    def test_scored_file_is_named_when_a_ledger_holds_several(
            self, tmp_path: Path):
        """Without this the table reads as though the whole history were in
        view — two repos at 50,000 -> 7,000 with no sign that a prune on a
        secondary file was excluded from both."""
        _two_file_ledger(tmp_path, "one", "1.1", main_after=7000, sub_after=8900)
        _two_file_ledger(tmp_path, "two", "1.2", main_after=9000, sub_after=8800)
        r = _score(_roster(tmp_path, [("one", "a", "1"), ("two", "b", "1")]),
                   "--min-pairs", "1")
        assert "multi-file ledgers" in r.stdout, r.stdout
        assert "one: AGENTS.md (+1 other file(s) not scored)" in r.stdout
        assert "two: AGENTS.md (+1 other file(s) not scored)" in r.stdout

    def test_single_file_ledgers_print_no_multi_file_block(self, tmp_path: Path):
        r = _score(_three_good_pairs(tmp_path))
        assert "multi-file ledgers" not in r.stdout

    def test_reject_does_not_enumerate_failures_twice(self, tmp_path: Path):
        """The body block is what keeps failures visible under the INCONCLUSIVE
        paths, so it must not look redundant enough to delete."""
        r = _score(_three_good_pairs(tmp_path, no_loss="failed"))
        assert r.returncode == 3
        assert "see the treatment-arm failures above" in r.stdout
        # The pair lines and the body block each have a reason to name the repos;
        # the verdict does not, and enumerating there is what made the body look
        # deletable.
        # "\nverdict: " with the newline and space, not a bare "verdict:" —
        # that would also match inside a section header ending in the word, and
        # the assertion would silently check the wrong block and pass.
        verdict_block = r.stdout.split("\nverdict: ", 1)[1]
        assert "no_loss=failed" not in verdict_block, verdict_block
        assert "treatment-arm safety failures:" in r.stdout


class TestValidationGateRoundNine:
    def test_repeated_roster_entry_is_warned_and_used_once(self, tmp_path: Path):
        """Merged silently, a repeat halved an experiment without saying so: a
        roster declaring four entries and two pairs produced one pair, no note,
        and a verdict of ADOPT."""
        path = tmp_path / "cohort"
        path.write_text("owner/one  wave:a pair:1\n"
                        "owner/two  wave:b pair:1\n"
                        "owner/one  wave:b pair:2\n")
        out = subprocess.run(
            ["bash", "-c", f'. "{LIB}"; ctx_read_roster "{path}" | tr "\\037" "|"'],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert "listed more than once" in out.stderr
        assert "owner/one" in out.stderr
        assert out.stdout.splitlines() == ["repo|owner/one|a|1", "repo|owner/two|b|1"]

    def test_duplicate_does_not_shrink_the_experiment_silently(
            self, tmp_path: Path):
        _arm(tmp_path, "c1", 50000, 20000, "1.1")
        _arm(tmp_path, "t1", 49000, 12000, "1.2")
        roster = _roster(tmp_path, [("c1", "a", "1"), ("t1", "b", "1")])
        with roster.open("a") as fh:
            fh.write(f"{tmp_path / 'c1'}  wave:b pair:2\n")
        r = _score(roster, "--min-pairs", "1")
        assert "listed more than once" in r.stderr, r.stderr
        payload = json.loads(_score(roster, "--min-pairs", "1",
                                    "--format", "json").stdout)
        # One pair, and the repo counted once — not two records and a phantom
        # pair 2 that never appears in the report.
        assert len(payload["repos"]) == 2
        assert len(payload["pairs"]) == 1

    def test_rollup_does_not_double_count_a_repeated_entry(self, tmp_path: Path):
        """The same duplication inflated `runs` to 4 for a two-row ledger —
        which is one curation, so the number to hold is 1."""
        _arm(tmp_path, "one", 50000, 20000, "1.1")
        path = tmp_path / "cohort"
        path.write_text(f"{tmp_path / 'one'}\n{tmp_path / 'one'}\n")
        r = subprocess.run(
            ["bash", str(COHORT), "--cohort-file", str(path), "--format", "tsv"],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        cells = dict(zip(*(line.split("\t")
                           for line in r.stdout.splitlines()[:2])))
        assert cells["runs"] == "1", cells

    @pytest.mark.parametrize("a,b", [("1.2", "v1.2"), ("v1.2", "1.2"),
                                     ("1.2", "1.2.0"), ("V1.2.0", "1.2")])
    def test_one_release_spelled_two_ways_is_never_an_experiment(
            self, tmp_path: Path, a, b):
        """v1.2 keyed to (0, 2) against 1.2's (1, 2), so the gate reported the
        arms as inverted for one release spelled two ways — a confidently wrong
        diagnosis pointing at the flags, which were not the problem.

        Asked of the flags since #194, and a usage error rather than a verdict:
        the flags ARE the arms now, so this never reaches the rows."""
        r = subprocess.run(
            ["bash", str(SCORE), "--cohort-file",
             str(_roster(tmp_path, [("one", "a", "1"), ("two", "b", "1")])),
             "--treatment", b, "--control", a, "--min-pairs", "1"],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        assert r.returncode == 1, r.stdout + r.stderr
        assert "same release" in r.stderr
        assert "OLDER than" not in r.stdout
        assert "verdict: ADOPT" not in r.stdout

    def test_a_release_named_vnext_is_left_alone(self, tmp_path: Path):
        """The v guard requires a digit after it, so a version that merely
        starts with v is not mangled into a different one."""
        out = subprocess.run(
            ["bash", str(SCORE), "--help"],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert out.returncode == 0
        _arm(tmp_path, "one", 50000, 20000, "vNext")
        _arm(tmp_path, "two", 49000, 12000, "1.2")
        r = subprocess.run(
            ["bash", str(SCORE), "--cohort-file",
             str(_roster(tmp_path, [("one", "a", "1"), ("two", "b", "1")])),
             "--treatment", "1.2", "--control", "vNext", "--min-pairs", "1"],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        assert "same release" not in r.stderr, r.stderr
        assert r.returncode != 1, r.stdout + r.stderr

    def test_version_ordering_still_works_after_canonicalisation(
            self, tmp_path: Path):
        """Deriving version_key from the canonical form must not break the
        older/newer test it exists for: 1.10 is still newer than 1.9."""
        _arm(tmp_path, "one", 50000, 20000, "1.10")
        _arm(tmp_path, "two", 49000, 12000, "1.9")
        r = subprocess.run(
            ["bash", str(SCORE), "--cohort-file",
             str(_roster(tmp_path, [("one", "a", "1"), ("two", "b", "1")])),
             "--treatment", "1.9", "--control", "1.10", "--min-pairs", "1"],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        # The treatment is 1.9 against a 1.10 control — genuinely backwards.
        assert "OLDER than" in r.stdout, r.stdout


SEAMS = SCRIPTS / "check-seams.sh"


def _seam_repo(tmp_path: Path) -> Path:
    """A repo curated one commit ago: `## Deployment Topology` moved from
    AGENTS.md into docs/OPS.md."""
    repo = tmp_path / "seamrepo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "AGENTS.md").write_text(
        "# Guide\n\n## Build\n\nrun make\n\n## Deployment Topology\n\n"
        "The workers connect to the bus directly.\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "pre")
    (repo / "docs").mkdir()
    (repo / "AGENTS.md").write_text(
        "# Guide\n\n## Build\n\nrun make\n\n## Detail Docs\n\n"
        "- [docs/OPS.md](docs/OPS.md) — deployment\n")
    (repo / "docs" / "OPS.md").write_text(
        "# Ops\n\n## Deployment Topology\n\n"
        "The workers connect to the bus directly.\n")
    return repo


def _run_seams(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SEAMS), "--base", "HEAD", *args],
        cwd=repo, capture_output=True, text=True, env=_clean_env(), timeout=60,
    )


class TestCheckSeams:
    def test_clean_move_reports_no_seams(self, tmp_path: Path):
        r = _run_seams(_seam_repo(tmp_path))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "OK — no unacknowledged cross-reference seams." in r.stdout
        assert r.stdout.rstrip().endswith("seams: 0")

    def test_back_reference_in_a_doc_is_reported(self, tmp_path: Path):
        """The observo 🔴: a doc whose header says its own contents live in
        AGENTS.md, after the run moved them into that very doc."""
        repo = _seam_repo(tmp_path)
        ops = repo / "docs" / "OPS.md"
        ops.write_text("# Ops\n\nBounds semantics live in AGENTS.md.\n\n"
                       "## Deployment Topology\n\n"
                       "The workers connect to the bus directly.\n")
        r = _run_seams(repo)
        assert r.returncode == 3, r.stdout
        assert "back-reference" in r.stdout
        assert "docs/OPS.md:3" in r.stdout
        assert "seams: 1" in r.stdout

    def test_reference_to_a_moved_title_is_reported(self, tmp_path: Path):
        """The observo dangling prose pointer: 'See AGENTS.md X' where X moved
        into the pointing file itself."""
        repo = _seam_repo(tmp_path)
        cmd = repo / "docs" / "COMMANDS.md"
        cmd.write_text("# Commands\n\nSee the Deployment Topology section for "
                       "canonical invocations.\n")
        r = _run_seams(repo)
        assert r.returncode == 3, r.stdout
        assert "moved-title" in r.stdout
        assert "Deployment Topology" in r.stdout

    def test_the_relocated_sections_own_heading_is_not_a_seam(
            self, tmp_path: Path):
        """docs/OPS.md's `## Deployment Topology` heading IS the moved section —
        reporting it would flag every correct demotion."""
        r = _run_seams(_seam_repo(tmp_path))
        assert "moved-title" not in r.stdout

    def test_duplicate_destination_heading_is_reported(self, tmp_path: Path):
        """The observo class 2: the destination already covered the topic and
        the demotion appended a second copy beside it."""
        repo = _seam_repo(tmp_path)
        ops = repo / "docs" / "OPS.md"
        ops.write_text(ops.read_text()
                       + "\n## Deployment Topology\n\nAppended copy.\n")
        r = _run_seams(repo)
        assert r.returncode == 3
        assert "duplicate-heading" in r.stdout
        assert "also at line" in r.stdout

    def test_provenance_in_a_heading_is_reported(self, tmp_path: Path):
        repo = _seam_repo(tmp_path)
        ops = repo / "docs" / "OPS.md"
        ops.write_text(ops.read_text()
                       + "\n## Migration workflow (from AGENTS.md, #412)\n\nx\n")
        r = _run_seams(repo)
        assert r.returncode == 3
        assert "provenance-heading" in r.stdout

    def test_archival_docs_are_not_swept(self, tmp_path: Path):
        """A dated plan legitimately says 'AGENTS.md said X at the time'."""
        repo = _seam_repo(tmp_path)
        plans = repo / "docs" / "plans"
        plans.mkdir()
        (plans / "2026-01-01-old.md").write_text("AGENTS.md carries the rules.\n")
        r = _run_seams(repo)
        assert r.returncode == 0, r.stdout

    def test_short_moved_titles_are_not_swept(self, tmp_path: Path):
        """Grepping the surface for a title like 'Build' drowns real seams in
        coincidental matches; the sweep floors title length instead."""
        repo = _seam_repo(tmp_path)
        # Move the SHORT section too.
        agents = repo / "AGENTS.md"
        agents.write_text(agents.read_text().replace(
            "## Build\n\nrun make\n\n", ""))
        (repo / "docs" / "OPS.md").write_text(
            (repo / "docs" / "OPS.md").read_text()
            + "\nUse the Build target.\n")
        r = _run_seams(repo)
        assert "moved-title" not in r.stdout, r.stdout


class TestCredentialPreflight:
    def test_env_var_answers(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=5)
        env = _clean_env()
        env["ANTHROPIC_API_KEY"] = "sk-test"
        r = subprocess.run(
            ["bash", str(MEASURE), "--check-credential"],
            cwd=repo, capture_output=True, text=True, env=env, timeout=30,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "environment" in r.stdout
        assert "sk-test" not in r.stdout + r.stderr    # never the value

    def test_secrets_file_answers(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=5)
        (repo / ".env").write_text("ANTHROPIC_API_KEY=sk-file-test\n")
        env = _clean_env()
        env.pop("ANTHROPIC_API_KEY", None)
        r = subprocess.run(
            ["bash", str(MEASURE), "--check-credential"],
            cwd=repo, capture_output=True, text=True, env=env, timeout=30,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "secrets file" in r.stdout
        assert "sk-file-test" not in r.stdout + r.stderr

    def test_no_credential_is_exit_3_with_the_fix(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=5)
        env = _clean_env()
        env.pop("ANTHROPIC_API_KEY", None)
        r = subprocess.run(
            ["bash", str(MEASURE), "--check-credential"],
            cwd=repo, capture_output=True, text=True, env=env, timeout=30,
        )
        assert r.returncode == 3, r.stdout + r.stderr
        assert "BEFORE starting the run" in r.stderr

    def test_jwt_only_profile_is_still_exit_3(self, tmp_path: Path):
        """A credential that resolves but will 401 on count_tokens is a 'no':
        the question is whether the LEDGER ROW will be exact, not whether
        something authenticated."""
        repo = _repo(tmp_path, policy_lines=5)
        stub = tmp_path / "bin"
        stub.mkdir()
        (stub / "ant").write_text("#!/bin/sh\necho fake-jwt-token\n")
        (stub / "ant").chmod(0o755)
        env = _clean_env()
        env.pop("ANTHROPIC_API_KEY", None)
        env["PATH"] = f"{stub}:{env['PATH']}"
        r = subprocess.run(
            ["bash", str(MEASURE), "--check-credential"],
            cwd=repo, capture_output=True, text=True, env=env, timeout=30,
        )
        assert r.returncode == 3, r.stdout + r.stderr
        assert "JWT" in r.stderr
        assert "fake-jwt-token" not in r.stdout + r.stderr


class TestRepoIdentity:
    def _record(self, cwd: Path, *args: str) -> dict:
        out = subprocess.run(
            ["bash", "-c",
             f'cd "{cwd}" && bash "{MEASURE}" --no-write 2>/dev/null'
             f' | bash "{RECORD}" --dry-run {" ".join(args)}'],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        return json.loads(out.stdout)

    def test_origin_basename_wins_over_directory_name(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=5)
        _git(repo, "remote", "add", "origin",
             "https://github.com/CannObserv/usa-wa.git")
        assert self._record(repo)["repo"] == "usa-wa"

    def test_worktree_records_the_repository_not_the_branch_slug(
            self, tmp_path: Path):
        """The #102 case: usa-wa mandates worktree-based feature work, and the
        row recorded `feat-161-curating-context` as the repo."""
        repo = _repo(tmp_path, policy_lines=5)
        _git(repo, "remote", "add", "origin",
             "git@github.com:CannObserv/usa-wa.git")
        wt = tmp_path / "feat-161-curating-context"
        _git(repo, "worktree", "add", "-q", str(wt), "-b", "feat-161")
        row = self._record(wt)
        assert row["repo"] == "usa-wa", row

    def test_explicit_override_wins(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=5)
        _git(repo, "remote", "add", "origin",
             "https://github.com/CannObserv/usa-wa.git")
        assert self._record(repo, "--repo", "roster-name")["repo"] == "roster-name"

    def test_no_origin_falls_back_to_directory_name(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=5)
        assert self._record(repo)["repo"] == repo.name


class TestSeamsOnTheRow:
    def test_count_lands_on_the_row(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=5)
        out = subprocess.run(
            ["bash", "-c",
             f'cd "{repo}" && bash "{MEASURE}" --no-write 2>/dev/null'
             f' | bash "{RECORD}" --dry-run --seams 4'],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        assert json.loads(out.stdout)["seams"] == 4

    def test_absent_flag_records_null_not_zero(self, tmp_path: Path):
        """'Not swept' and 'swept clean' must stay distinguishable, exactly as
        with no_loss."""
        repo = _repo(tmp_path, policy_lines=5)
        out = subprocess.run(
            ["bash", "-c",
             f'cd "{repo}" && bash "{MEASURE}" --no-write 2>/dev/null'
             f' | bash "{RECORD}" --dry-run'],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        assert json.loads(out.stdout)["seams"] is None

    def test_non_numeric_count_is_refused(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=5)
        out = subprocess.run(
            ["bash", "-c",
             f'cd "{repo}" && bash "{MEASURE}" --no-write 2>/dev/null'
             f' | bash "{RECORD}" --dry-run --seams many'],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        assert out.returncode == 1
        assert "non-negative integer" in out.stderr


class TestSeamAcknowledgement:
    """A legitimate back-reference is permanent, so without acknowledgement
    exit 3 is the steady state — alarm fatigue — and the only way to zero the
    count is to delete legitimate references: the tokens_live mistake with a
    different metric."""

    def _with_back_reference(self, tmp_path: Path) -> Path:
        repo = _seam_repo(tmp_path)
        (repo / "docs" / "OPS.md").write_text(
            "# Ops\n\nThe short rules live in AGENTS.md; this file has the "
            "rest.\n\n## Deployment Topology\n\n"
            "The workers connect to the bus directly.\n")
        return repo

    def test_acknowledged_hit_is_excluded_and_exit_is_clean(self, tmp_path: Path):
        repo = self._with_back_reference(tmp_path)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-seams-ok").write_text(
            "# judged legitimate: the short rules are still inline\n"
            "docs/OPS.md The short rules live in AGENTS.md\n")
        r = _run_seams(repo)
        assert r.returncode == 0, r.stdout
        assert "no unacknowledged cross-reference seams" in r.stdout
        assert "1 acknowledged seam(s) skipped" in r.stdout
        assert "docs/OPS.md:3" in r.stdout       # still visible, not hidden
        assert r.stdout.rstrip().endswith("seams: 0")

    def test_non_matching_pattern_does_not_acknowledge(self, tmp_path: Path):
        repo = self._with_back_reference(tmp_path)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-seams-ok").write_text(
            "docs/OTHER.md some other line entirely\n")
        r = _run_seams(repo)
        assert r.returncode == 3
        assert "seams: 1" in r.stdout

    def test_entry_expires_when_the_line_changes(self, tmp_path: Path):
        """Content matching, not line numbers: the acknowledgement stops
        applying the moment the acknowledged line is edited, which is exactly
        when it needs re-judging."""
        repo = self._with_back_reference(tmp_path)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-seams-ok").write_text(
            "docs/OPS.md The short rules live in AGENTS.md\n")
        ops = repo / "docs" / "OPS.md"
        ops.write_text(ops.read_text().replace(
            "The short rules live in AGENTS.md",
            "Everything that used to live in AGENTS.md"))
        r = _run_seams(repo)
        assert r.returncode == 3, r.stdout
        assert "seams: 1" in r.stdout

    def test_full_line_comments_and_blanks_are_ignored(self, tmp_path: Path):
        """Comments are LINE-START only. An inline `#` is part of the pattern —
        provenance-heading hits contain issue numbers, and stripping inline
        comments silently broadened exactly those entries ('Fixed in #412'
        became 'Fixed in', which matched hits nobody judged)."""
        repo = self._with_back_reference(tmp_path)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-seams-ok").write_text(
            "\n# a comment\n\ndocs/OPS.md The short rules live in AGENTS.md\n")
        r = _run_seams(repo)
        assert r.returncode == 0, r.stdout

    def test_a_hash_in_a_pattern_is_not_a_comment(self, tmp_path: Path):
        repo = _seam_repo(tmp_path)
        ops = repo / "docs" / "OPS.md"
        ops.write_text(ops.read_text() + "\n## Fixed in #412\n\nx\n")
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-seams-ok").write_text(
            "docs/OPS.md :: Fixed in #412\n")
        r = _run_seams(repo)
        assert r.returncode == 0, r.stdout
        assert "1 acknowledged seam(s) skipped" in r.stdout
        # And the pattern that did the acknowledging is charged with it.
        assert "1 hit(s): docs/OPS.md :: Fixed in #412" in r.stdout

    def test_path_anchored_entry_does_not_match_another_file(self, tmp_path: Path):
        """The :: form pins an entry to a file: the same judged content in a
        different doc is a different judgement."""
        repo = _seam_repo(tmp_path)
        for name in ("OPS.md", "OTHER.md"):
            p = repo / "docs" / name
            base = p.read_text() if p.exists() else "# X\n"
            p.write_text(base + "\nRules live in AGENTS.md.\n")
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-seams-ok").write_text(
            "docs/OPS.md :: Rules live in AGENTS.md\n")
        r = _run_seams(repo)
        assert r.returncode == 3, r.stdout
        assert "seams: 1" in r.stdout            # OTHER.md still fires
        assert "seams_acked: 1" in r.stdout      # OPS.md acknowledged

    def test_a_blanket_pattern_is_warned_about(self, tmp_path: Path):
        """One lazy line must not silently zero the count: the gaming vector
        the ack file closed for the docs would otherwise reopen inside the ack
        file itself, with no diff anywhere a review reads."""
        repo = _seam_repo(tmp_path)
        (repo / "docs" / "OPS.md").write_text(
            "# Ops\n\nRules live in AGENTS.md.\nSee AGENTS.md for style.\n"
            "And AGENTS.md for tests.\nAlso AGENTS.md for deploys.\n\n"
            "## Deployment Topology\n\nThe workers connect to the bus directly.\n")
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-seams-ok").write_text("back-reference\n")
        r = _run_seams(repo)
        assert r.returncode == 0          # acknowledged is acknowledged
        assert "4 hit(s): back-reference" in r.stdout
        assert "WARN this pattern is broad" in r.stdout
        assert "an acknowledgement should cover ONE judged line" in r.stdout

    def test_precise_entries_are_not_warned_about(self, tmp_path: Path):
        repo = self._with_back_reference(tmp_path)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-seams-ok").write_text(
            "docs/OPS.md The short rules live in AGENTS.md\n")
        r = _run_seams(repo)
        assert "WARN this pattern is broad" not in r.stdout

    def test_pattern_matches_beyond_the_display_truncation(self, tmp_path: Path):
        """Matching is against the full source line, not the truncated display:
        a pattern pasted from the actual doc must work, not only one copied
        from the report."""
        repo = _seam_repo(tmp_path)
        long_tail = "the canonical location for the full rationale and history"
        (repo / "docs" / "OPS.md").write_text(
            "# Ops\n\n" + ("x" * 130) + " AGENTS.md is " + long_tail + "\n\n"
            "## Deployment Topology\n\n"
            "The workers connect to the bus directly.\n")
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-seams-ok").write_text(long_tail + "\n")
        r = _run_seams(repo)
        assert r.returncode == 0, r.stdout

    def test_stale_entries_are_reported_for_pruning(self, tmp_path: Path):
        repo = self._with_back_reference(tmp_path)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-seams-ok").write_text(
            "docs/OPS.md The short rules live in AGENTS.md\n"
            "docs/GONE.md something that no longer exists\n")
        r = _run_seams(repo)
        assert "matched nothing" in r.stdout, r.stdout
        assert "docs/GONE.md something that no longer exists" in r.stdout

    def test_machine_lines_carry_both_counts(self, tmp_path: Path):
        repo = self._with_back_reference(tmp_path)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-seams-ok").write_text(
            "docs/OPS.md The short rules live in AGENTS.md\n")
        r = _run_seams(repo)
        lines = r.stdout.rstrip().splitlines()
        assert lines[-2] == "seams_acked: 1"
        assert lines[-1] == "seams: 0"


class TestSeamsAckedOnTheRow:
    def test_both_counts_land_on_the_row(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=5)
        out = subprocess.run(
            ["bash", "-c",
             f'cd "{repo}" && bash "{MEASURE}" --no-write 2>/dev/null'
             f' | bash "{RECORD}" --dry-run --seams 1 --seams-acked 4'],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        row = json.loads(out.stdout)
        assert row["seams"] == 1 and row["seams_acked"] == 4

    def test_absent_is_null_and_garbage_is_refused(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=5)
        out = subprocess.run(
            ["bash", "-c",
             f'cd "{repo}" && bash "{MEASURE}" --no-write 2>/dev/null'
             f' | bash "{RECORD}" --dry-run'],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        assert json.loads(out.stdout)["seams_acked"] is None
        bad = subprocess.run(
            ["bash", "-c",
             f'cd "{repo}" && bash "{MEASURE}" --no-write 2>/dev/null'
             f' | bash "{RECORD}" --dry-run --seams-acked lots'],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        assert bad.returncode == 1
        assert "--seams-acked must be a non-negative integer" in bad.stderr

    def test_this_repos_own_ack_file_keeps_the_sweep_clean(self):
        """The dogfood: the four judged-legitimate hits stay acknowledged, so
        this repo's Phase 6.5 exits 0 and records seams: 0."""
        root = Path(__file__).resolve().parent.parent.parent
        r = subprocess.run(
            ["bash", str(SEAMS), "--base", "HEAD"],
            cwd=root, capture_output=True, text=True, env=_clean_env(),
            timeout=60,
        )
        assert r.returncode == 0, (
            "an acknowledged line in this repo's own docs changed, so its "
            "entry in .skills/context-seams-ok expired — re-judge the hit and "
            "update the entry; this is the canary working, not the code "
            f"breaking:\n{r.stdout}")
        assert "acknowledged seam(s) skipped" in r.stdout


class TestSeamRenameNoise:
    def test_renamed_successor_heading_is_not_flagged(self, tmp_path: Path):
        """A rename's successor heading contains the old title; flagging it put
        a guaranteed-noise hit beside every real rename-fallout hit."""
        repo = tmp_path / "rn"
        repo.mkdir()
        _git(repo, "init", "-q")
        (repo / "AGENTS.md").write_text(
            "# G\n\n## Deployment Topology\n\nstuff\n\n## Ops Notes\n\n"
            "see the Deployment Topology section above\n")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "pre")
        (repo / "AGENTS.md").write_text(
            "# G\n\n## Deployment Topology and Rollout\n\nstuff\n\n"
            "## Ops Notes\n\nsee the Deployment Topology section above\n")
        r = _run_seams(repo)
        out = r.stdout
        # The successor heading (line 3) is not a hit; the stale prose (line 9) is.
        assert "AGENTS.md:3" not in out, out
        assert "AGENTS.md:9" in out
        assert "seams: 1" in out


class TestRelativeInvocationFromSubdir:
    """cd "$ROOT" ran before the bootstrap resolved ${BASH_SOURCE[0]}, so a
    relative invocation from a subdirectory looked for the library in the wrong
    tree and blamed the library for it. The guard is exempt: its bootstrap sits
    after log() by design, and hooks always run with cwd at the project root."""

    @pytest.mark.parametrize("script,args,ok_codes", [
        ("measure-context.sh", ["--no-write"], {0}),
        ("prove-no-loss.sh", ["--base", "HEAD"], {0, 3}),
        ("check-seams.sh", ["--base", "HEAD"], {0, 3}),
        ("context-delta.sh", [], {0}),
    ])
    def test_relative_path_from_a_subdirectory_works(
            self, tmp_path: Path, script, args, ok_codes):
        repo = _seam_repo(tmp_path)
        # Vendor the scripts into the repo the way a submodule would.
        vendor = repo / "vendor" / "scripts"
        vendor.mkdir(parents=True)
        for f in SCRIPTS.iterdir():
            shutil.copy2(f, vendor / f.name)
        sub = repo / "docs"
        r = subprocess.run(
            ["bash", f"../vendor/scripts/{script}", *args],
            cwd=sub, capture_output=True, text=True, env=_clean_env(),
            timeout=60,
        )
        assert r.returncode in ok_codes, (
            f"{script}: exit {r.returncode}\n{r.stdout}\n{r.stderr}")
        assert "_context-lib.sh not found" not in r.stderr


# ---------------------------------------------------------------------------
# The before-state a first curation never had (#116), and the rejection floor
# a permanent record deserves (#117)
# ---------------------------------------------------------------------------


class TestBaselineRow:
    """`record-telemetry.sh --baseline` is what makes a FIRST curation scorable.

    Experiment 1 scored nothing: the gate takes a run's before-state from the
    previous ledger row, and a first curation is the run that CREATES the
    ledger, so the scored run was exactly the run that could never be scored.
    Twelve repos followed the skill correctly and produced twelve unscorable
    rows."""

    def _measure(self, repo: Path) -> str:
        r = subprocess.run(
            ["bash", str(MEASURE), "--no-write"], capture_output=True,
            text=True, cwd=str(repo), env=_clean_env(), timeout=60)
        assert r.returncode == 0, r.stderr
        return r.stdout

    def _record(self, repo: Path, measurement: str, *extra: str):
        return subprocess.run(
            ["bash", str(RECORD), *extra], input=measurement,
            capture_output=True, text=True, cwd=str(repo), env=_clean_env(),
            timeout=30)

    def _rows(self, repo: Path) -> list[dict]:
        return [json.loads(ln) for ln
                in (repo / ".skills" / "context-metrics.jsonl").read_text()
                .splitlines() if ln.strip()]

    def test_baseline_row_is_tagged_and_measurement_only(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=50)
        r = self._record(repo, self._measure(repo), "--baseline")
        assert r.returncode == 0, r.stderr
        row = self._rows(repo)[-1]
        # The tag the gate already knows to skip past, so a baseline row can
        # never be mistaken for the curation it precedes.
        assert row["actions"] == ["baseline:pre-curation"], row
        assert row["no_loss"] is None
        assert row["delta_tokens"] is None
        assert "baseline" in r.stderr

    def test_the_curation_row_then_has_a_before_state(self, tmp_path: Path):
        """The whole point: Phase 1 and Phase 7 leave two rows, and the second
        one has something to be compared against."""
        repo = _repo(tmp_path, policy_lines=50)
        assert self._record(repo, self._measure(repo), "--baseline").returncode == 0
        (repo / "AGENTS.md").write_text(POLICY_LINE * 10)
        r = self._record(repo, self._measure(repo), "--actions", "demote:Big",
                         "--no-loss", "ok")
        assert r.returncode == 0, r.stderr
        rows = self._rows(repo)
        assert len(rows) == 2
        assert rows[0]["actions"] == ["baseline:pre-curation"]
        assert isinstance(rows[1]["delta_tokens"], int)
        assert rows[1]["delta_tokens"] < 0, rows[1]

    @pytest.mark.parametrize("extra,marker", [
        (("--actions", "demote:X"), "--baseline and --actions"),
        (("--no-loss", "ok"), "--baseline and --no-loss"),
    ])
    def test_flags_that_assert_a_curation_are_refused(
            self, tmp_path: Path, extra, marker):
        """A baseline row records the surface AS FOUND. --no-loss in particular
        would put a relocation verdict on a row where nothing was relocated, and
        the gate reads that field as evidence."""
        repo = _repo(tmp_path, policy_lines=50)
        r = self._record(repo, self._measure(repo), "--baseline", *extra)
        assert r.returncode == 1, r.stderr
        assert marker in r.stderr
        # The refusal lands before the ledger is created, so nothing was written
        # at all — not even an empty file.
        assert not (repo / ".skills" / "context-metrics.jsonl").exists()

    def test_pure_measurement_fields_are_still_allowed(self, tmp_path: Path):
        """--seams on a baseline row measures the surface as found, which is a
        before-state like any other and the one #117 argues the next experiment
        turns on. Not refused."""
        repo = _repo(tmp_path, policy_lines=50)
        r = self._record(repo, self._measure(repo), "--baseline",
                         "--seams", "41", "--seams-acked", "9")
        assert r.returncode == 0, r.stderr
        assert self._rows(repo)[-1]["seams"] == 41


class TestFirstCurationIsScorable:
    """With a baseline row the gate scores a first curation — and the orphan
    gate, which needs a before-row to compare against, can trip at all."""

    def _first_curation(self, root: Path, name: str, before: int, after: int,
                        version: str, **kw) -> None:
        d = root / name / ".skills"
        d.mkdir(parents=True, exist_ok=True)
        (d / "context-metrics.jsonl").write_text("\n".join([
            _ledger_row(repo=name, ts="2026-08-01", tokens=before,
                        actions=["baseline:pre-curation"],
                        docs_orphaned=kw.get("orph_before", 0)),
            _ledger_row(repo=name, ts="2026-08-02", tokens=after,
                        actions=["demote:Big"], skill_version=version,
                        no_loss=kw.get("no_loss", "ok"),
                        docs_orphaned=kw.get("orph_after", 0)),
        ]) + "\n")

    def test_a_first_curation_scores(self, tmp_path: Path):
        self._first_curation(tmp_path, "ctl1", 52000, 20000, "1.1")
        self._first_curation(tmp_path, "trt1", 49000, 12000, "1.2")
        r = _score(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")]),
                   "--min-pairs", "1", "--format", "json")
        out = json.loads(r.stdout)
        by = {x["repo"]: x for x in out["repos"]}
        assert by["trt1"]["status"] == "scored", by["trt1"]
        assert by["trt1"]["before"] == 49000
        assert out["pairs"][0]["informative"] is True
        assert out["pairs"][0]["winner"] == "treatment"

    def test_the_orphan_gate_can_now_trip_on_a_first_curation(
            self, tmp_path: Path):
        """Without a before-row `prev is None`, so the docs_orphaned comparison
        was skipped entirely — one of the three safety gates was structurally
        inert on the modal case."""
        self._first_curation(tmp_path, "ctl1", 52000, 20000, "1.1")
        self._first_curation(tmp_path, "trt1", 49000, 12000, "1.2",
                             orph_before=0, orph_after=4)
        roster = _roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")])
        r = _score(roster, "--min-pairs", "1")
        assert r.returncode == 3, r.stdout
        assert "verdict: REJECT" in r.stdout
        assert "docs_orphaned 0->4" in r.stdout

        # The contrast, and the actual defect: strip the baseline rows and the
        # same orphaning run sails through, because there is nothing to compare
        # `docs_orphaned` against. This is the state all twelve first curations
        # were scored in.
        for name in ("ctl1", "trt1"):
            led = tmp_path / name / ".skills" / "context-metrics.jsonl"
            led.write_text(led.read_text().splitlines()[1] + "\n")
        r = _score(roster, "--min-pairs", "1")
        assert "docs_orphaned" not in r.stdout, r.stdout
        assert "verdict: REJECT" not in r.stdout


class TestSystematicUnscorable:
    """Twelve repos unscorable for twelve reasons is cohort non-compliance.
    Twelve unscorable for ONE reason is a rule no repo can satisfy, and the two
    read identically from below — both arrive at 'no informative pairs'."""

    def _no_baseline(self, root: Path, name: str, version: str) -> None:
        """A first curation exactly as the skill produced it before #116: one
        row, no predecessor."""
        d = root / name / ".skills"
        d.mkdir(parents=True, exist_ok=True)
        (d / "context-metrics.jsonl").write_text(_ledger_row(
            repo=name, tokens=5900, actions=["demote:Big"],
            skill_version=version, no_loss="ok") + "\n")

    def test_one_shared_reason_is_reported_as_a_gate_defect(self, tmp_path: Path):
        spec = []
        for i in (1, 2, 3):
            self._no_baseline(tmp_path, f"ctl{i}", "1.1")
            self._no_baseline(tmp_path, f"trt{i}", "1.2")
            spec += [(f"ctl{i}", "a", str(i)), (f"trt{i}", "b", str(i))]
        r = _score(_roster(tmp_path, spec), "--min-pairs", "1")
        assert r.returncode == 5, r.stdout
        assert "GATE DEFECT" in r.stdout, r.stdout
        assert "all 6 repos in both arms" in r.stdout
        assert "no row before the first curation" in r.stdout
        # And it names the fix, rather than leaving the reader to walk the
        # scoring core the way experiment 1 required.
        assert "--baseline" in r.stdout
        # The reason is stated ONCE as a diagnosis, not implied by repetition.
        assert "no informative pairs" not in r.stdout

    def test_mixed_reasons_are_not_a_gate_defect(self, tmp_path: Path):
        """Different reasons per repo means each repo needs its own fix. That is
        a finding about the cohort, and claiming a defect in the gate would send
        the reader to the wrong file.

        Four repos, so the roster clears SYSTEMIC_MIN and the ONLY thing keeping
        this from reading as a defect is the mix of reasons."""
        spec = []
        for i in (1, 2):
            self._no_baseline(tmp_path, f"ctl{i}", "1.1")
            spec.append((f"ctl{i}", "a", str(i)))
        # No curation row at all — a different unscorable reason.
        _arm(tmp_path, "trt1", 49000, None, "1.2")
        self._no_baseline(tmp_path, "trt2", "1.2")
        spec += [("trt1", "b", "1"), ("trt2", "b", "2")]
        r = _score(_roster(tmp_path, spec), "--min-pairs", "1")
        assert "GATE DEFECT" not in r.stdout, r.stdout

    def test_two_repos_are_too_few_to_name_a_gate_defect(self, tmp_path: Path):
        """The claim is an inference from BREADTH. At one repo per arm the
        likelier reading is two non-compliant repos, which needs a different fix
        than 'the gate is broken' — so the diagnosis stays off."""
        self._no_baseline(tmp_path, "ctl1", "1.1")
        self._no_baseline(tmp_path, "trt1", "1.2")
        r = _score(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")]),
                   "--min-pairs", "1")
        assert r.returncode == 5, r.stdout
        assert "GATE DEFECT" not in r.stdout, r.stdout
        assert "no informative pairs" in r.stdout

    def test_a_lopsided_roster_does_not_clear_the_floor(self, tmp_path: Path):
        """Counted PER ARM, not over the roster. Three treatment repos and one
        control clears a roster total of four while saying nothing about whether
        the rule is satisfiable — one arm carrying a single repo is the same thin
        evidence the floor exists to refuse."""
        spec = []
        for i in (1, 2, 3):
            self._no_baseline(tmp_path, f"trt{i}", "1.2")
            spec.append((f"trt{i}", "b", str(i)))
        self._no_baseline(tmp_path, "ctl1", "1.1")
        spec.append(("ctl1", "a", "1"))
        r = _score(_roster(tmp_path, spec), "--min-pairs", "1")
        assert "GATE DEFECT" not in r.stdout, r.stdout


class TestRejectionFloor:
    """An adoption is revisited the next time the skill changes. A rejection is
    written into rejected-changes.md permanently and shapes every later
    proposal, so the two do not share a floor. Experiment 1 came within one flag
    of rejecting v1.3 on two pairs."""

    def _two_pairs_one_lost(self, root: Path) -> Path:
        # Pair 1 to the treatment, pair 2 to the control.
        _arm(root, "ctl1", 52000, 20000, "1.1")
        _arm(root, "trt1", 49000, 12000, "1.2")
        _arm(root, "ctl2", 28000, 12000, "1.1")
        _arm(root, "trt2", 26000, 20000, "1.2")
        return _roster(root, [("ctl1", "a", "1"), ("trt1", "b", "1"),
                              ("ctl2", "a", "2"), ("trt2", "b", "2")])

    def test_two_pairs_cannot_reject(self, tmp_path: Path):
        roster = self._two_pairs_one_lost(tmp_path)
        r = _score(roster, "--min-pairs", "2")
        assert r.returncode == 5, r.stdout
        assert "verdict: INCONCLUSIVE" in r.stdout
        assert "below the rejection floor" in r.stdout
        # Still blocked, and still not written down as refuted.
        assert "verdict: ADOPT" not in r.stdout
        assert "record this in references/rejected-changes.md" not in r.stdout
        # The floor a rejection had to clear, on the row, so a reader of the
        # JSON can see why an INCONCLUSIVE is not a REJECT.
        out = json.loads(_score(roster, "--min-pairs", "2",
                                "--format", "json").stdout)
        assert out["reject_floor"] == 3, out
        assert out["informative_pairs"] == 2, out

    def test_min_pairs_above_the_floor_is_the_effective_floor(self, tmp_path: Path):
        """--min-pairs gates every verdict first, so when it is set higher it is
        what a rejection actually has to clear. The JSON reports that, while the
        branch below uses the constant."""
        out = json.loads(_score(self._two_pairs_one_lost(tmp_path),
                                "--min-pairs", "5", "--format", "json").stdout)
        assert out["reject_floor"] == 5, out
        assert out["verdict"] == "INCONCLUSIVE"

    def test_three_pairs_still_reject(self, tmp_path: Path):
        """The floor bounds a rejection, it does not abolish one."""
        roster = _three_good_pairs(tmp_path)
        _arm(tmp_path, "trt3", 14000, 13000, "1.2")
        r = _score(roster)
        assert r.returncode == 3, r.stdout
        assert "verdict: REJECT" in r.stdout
        assert "below the rejection floor" not in r.stdout

    def test_a_safety_failure_rejects_on_one_repo(self, tmp_path: Path):
        """The veto is exempt. Content lost under the proposed version is lost
        whether or not that repo had a partner, so a single repo rejects on its
        own with no informative pairs at all."""
        _arm(tmp_path, "ctl1", 52000, 20000, "1.1")
        _arm(tmp_path, "trt1", 49000, 12000, "1.2", no_loss="failed")
        r = _score(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")]),
                   "--min-pairs", "1")
        assert r.returncode == 3, r.stdout
        assert "verdict: REJECT" in r.stdout
        assert "no_loss=failed" in r.stdout


class TestRunsCountsCurationsNotRows:
    """A curation run writes two rows — the Phase 1 baseline and the Phase 7
    curation — so a row count reports every repo as having run twice as often as
    it did. `runs` is the column a reader consults to answer "is this repo
    actually running?", which is #118's whole subject."""

    def _one_curation(self, root: Path) -> Path:
        d = root / "one" / ".skills"
        d.mkdir(parents=True)
        (d / "context-metrics.jsonl").write_text("\n".join([
            _ledger_row(repo="one", ts="2026-08-01", tokens=12000,
                        actions=["baseline"]),
            _ledger_row(repo="one", ts="2026-08-02", tokens=5800,
                        actions=["demote:Big"], skill_version="1.4",
                        no_loss="ok", delta_tokens=-6200),
        ]) + "\n")
        return root / "one"

    def _rollup(self, repo: Path) -> dict:
        r = subprocess.run(
            ["bash", str(COHORT), "--local", str(repo), "--format", "tsv"],
            capture_output=True, text=True, env=_clean_env(), timeout=30)
        assert r.returncode == 0, r.stderr
        head, row = (ln.split("\t") for ln in r.stdout.splitlines()[:2])
        return dict(zip(head, row))

    def test_one_curation_is_one_run(self, tmp_path: Path):
        cells = self._rollup(self._one_curation(tmp_path))
        assert cells["runs"] == "1", cells

    def test_a_baseline_only_visit_is_zero_runs(self, tmp_path: Path):
        """A run that measured and stopped. Before `runs` counted curations this
        case had exactly one row, which is why the display keyed on `runs == 1`."""
        d = tmp_path / "one" / ".skills"
        d.mkdir(parents=True)
        (d / "context-metrics.jsonl").write_text(_ledger_row(
            repo="one", tokens=12000, actions=["baseline"]) + "\n")
        cells = self._rollup(tmp_path / "one")
        assert cells["runs"] == "0", cells
        table = subprocess.run(
            ["bash", str(COHORT), "--local", str(tmp_path / "one")],
            capture_output=True, text=True, env=_clean_env(), timeout=30)
        assert "(baseline only)" in table.stdout, table.stdout

    def test_an_untagged_row_still_counts_as_a_run(self, tmp_path: Path):
        """Only an explicit `baseline*` row is a state. An untagged row is a
        tagging gap, and hiding it from the run count would hide the gap — the
        same rule score-cohort.sh applies when it refuses to score one."""
        d = tmp_path / "one" / ".skills"
        d.mkdir(parents=True)
        (d / "context-metrics.jsonl").write_text("\n".join([
            _ledger_row(repo="one", ts="2026-08-01", tokens=12000,
                        actions=["baseline"]),
            _ledger_row(repo="one", ts="2026-08-02", tokens=9000, actions=[]),
        ]) + "\n")
        assert self._rollup(tmp_path / "one")["runs"] == "1"

    def test_the_trend_reports_runs_and_rows_separately(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=50)
        measure = subprocess.run(
            ["bash", str(MEASURE), "--no-write"], capture_output=True,
            text=True, cwd=str(repo), env=_clean_env(), timeout=60).stdout
        subprocess.run(["bash", str(RECORD), "--baseline"], input=measure,
                       capture_output=True, text=True, cwd=str(repo),
                       env=_clean_env(), timeout=30)
        r = subprocess.run(
            ["bash", str(RECORD), "--actions", "demote:Big", "--print-trend"],
            input=measure, capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=30)
        assert r.returncode == 0, r.stderr
        assert "1 run over 2 rows" in r.stderr, r.stderr


class TestCurationRuleIsOneRule:
    """Three scripts decide independently whether a ledger row records a RUN or
    a state — score-cohort.sh's classify_run(), cohort-report.sh's and
    record-telemetry.sh's is_curation_row(). Each comment says the rule must
    stay identical; this is what makes that true rather than asserted.

    The precedent is the neighbouring primary-file rule, which diverged between
    the first two of these and produced two irreconcilable pictures of one repo:
    the gate scoring a 100-token prune while the roll-up reported a
    43,000-token curation."""

    #  1  baseline            state  — plain tag
    #  2  baseline:exact      state  — qualified tag, same prefix
    #  3  demote:Big          RUN
    #  4  (untagged)          RUN    — a tagging gap, not a measurement
    # Every row carries skill_version, so a script that mistook a baseline for a
    # curation would score row 1 rather than skipping to row 3.
    def _mixed_ledger(self, root: Path, name: str, exact: bool = True) -> Path:
        d = root / name / ".skills"
        d.mkdir(parents=True, exist_ok=True)
        (d / "context-metrics.jsonl").write_text("\n".join([
            _ledger_row(repo=name, ts="2026-08-01", tokens=52000,
                        tokens_exact=exact, actions=["baseline"],
                        skill_version="1.4"),
            _ledger_row(repo=name, ts="2026-08-02", tokens=50000,
                        tokens_exact=exact, actions=["baseline:exact"],
                        skill_version="1.4"),
            _ledger_row(repo=name, ts="2026-08-03", tokens=7000,
                        tokens_exact=exact, actions=["demote:Big"],
                        skill_version="1.4", no_loss="ok"),
            _ledger_row(repo=name, ts="2026-08-04", tokens=6900,
                        tokens_exact=exact, actions=[], skill_version="1.4"),
        ]) + "\n")
        return root / name

    def test_the_rollup_sees_two_runs(self, tmp_path: Path):
        r = subprocess.run(
            ["bash", str(COHORT), "--local", str(self._mixed_ledger(tmp_path, "one")),
             "--format", "tsv"],
            capture_output=True, text=True, env=_clean_env(), timeout=30)
        assert r.returncode == 0, r.stderr
        cells = dict(zip(*(ln.split("\t") for ln in r.stdout.splitlines()[:2])))
        # 4 if baselines counted, 1 if the untagged row did not.
        assert cells["runs"] == "2", cells

    def test_the_gate_skips_both_baselines_to_the_curation(self, tmp_path: Path):
        """Row 3 is the scored run and row 2 is its before-state. A script that
        read `baseline`/`baseline:exact` as curations would stop at row 1, which
        has no predecessor, and report the repo unscorable instead."""
        self._mixed_ledger(tmp_path, "ctl1")
        _arm(tmp_path, "trt1", 49000, 12000, "1.5")
        r = _score(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")]),
                   "--min-pairs", "1", "--format", "json")
        rec = next(x for x in json.loads(r.stdout)["repos"] if x["repo"] == "ctl1")
        assert rec["status"] == "scored", rec
        assert rec["before"] == 50000 and rec["after"] == 7000, rec

    def test_the_gate_still_refuses_an_untagged_run_it_reaches_first(
            self, tmp_path: Path):
        """The other half of the rule: an untagged row counts as a run, and when
        it is the FIRST run it cannot be told from a baseline, so the gate says
        so rather than scoring it. Same classification, opposite consequence."""
        d = tmp_path / "ctl1" / ".skills"
        d.mkdir(parents=True)
        (d / "context-metrics.jsonl").write_text("\n".join([
            _ledger_row(repo="ctl1", ts="2026-08-01", tokens=52000,
                        actions=["baseline"], skill_version="1.4"),
            _ledger_row(repo="ctl1", ts="2026-08-02", tokens=7000, actions=[],
                        skill_version="1.4"),
        ]) + "\n")
        _arm(tmp_path, "trt1", 49000, 12000, "1.5")
        r = _score(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")]),
                   "--min-pairs", "1", "--format", "json")
        rec = next(x for x in json.loads(r.stdout)["repos"] if x["repo"] == "ctl1")
        assert rec["why_code"] == "untagged_run", rec

    def test_the_trend_header_sees_the_same_two_runs(self, tmp_path: Path):
        """Recorded through the script itself, so the third copy of the rule is
        exercised rather than read."""
        repo = _repo(tmp_path, policy_lines=50)
        self._mixed_ledger(tmp_path, "repo", exact=False)
        measure = subprocess.run(
            ["bash", str(MEASURE), "--no-write"], capture_output=True,
            text=True, cwd=str(repo), env=_clean_env(), timeout=60).stdout
        r = subprocess.run(
            ["bash", str(RECORD), "--actions", "prune:X", "--print-trend"],
            input=measure, capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=30)
        assert r.returncode == 0, r.stderr
        # Two runs in the fixture plus the one just recorded, over five rows.
        assert "3 runs over 5 rows" in r.stderr, r.stderr

    def test_a_baseline_only_trend_reads_grammatically(self, tmp_path: Path):
        repo = _repo(tmp_path, policy_lines=50)
        measure = subprocess.run(
            ["bash", str(MEASURE), "--no-write"], capture_output=True,
            text=True, cwd=str(repo), env=_clean_env(), timeout=60).stdout
        r = subprocess.run(
            ["bash", str(RECORD), "--baseline", "--print-trend"], input=measure,
            capture_output=True, text=True, cwd=str(repo), env=_clean_env(),
            timeout=30)
        assert "0 runs over 1 row" in r.stderr, r.stderr


INSTALL_CADENCE = SCRIPTS / "install-cadence.sh"


class TestCadenceInstaller:
    """#118's blocking prerequisite: the skill named "the scheduled weekly run"
    in six places and shipped no way to schedule anything, so ten of twelve
    cohort repos held exactly one ledger row and the longitudinal design had no
    series to read."""

    def _run(self, repo: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(INSTALL_CADENCE), *args], capture_output=True,
            text=True, cwd=str(repo), env=_clean_env(), timeout=30)

    def _repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "r"
        repo.mkdir()
        _git(repo, "init", "-q")
        return repo

    def test_rendered_workflow_is_valid_yaml_with_the_right_triggers(
            self, tmp_path: Path):
        yaml = pytest.importorskip("yaml")
        r = self._run(self._repo(tmp_path), "--print")
        assert r.returncode == 0, r.stderr
        doc = yaml.safe_load(r.stdout)
        # PyYAML parses a bare `on:` key as the boolean True.
        triggers = doc[True] if True in doc else doc["on"]
        assert set(triggers) == {"schedule", "workflow_dispatch"}, triggers
        # It must never gate a merge. That is #88, with its own sequencing rule.
        assert "pull_request" not in triggers
        assert doc["permissions"] == {"contents": "write"}
        # NOT continue-on-error: a red run means "this repo is not measuring",
        # which is exactly what somebody needs to see. Swallowing it would undo
        # the credential preflight, whose whole purpose is to make that loud.
        # Drift is a ::warning:: and never fails the job, so red always means
        # the mechanism broke rather than that the surface grew.
        assert "continue-on-error" not in doc["jobs"]["measure"]

    def test_rendering_executes_nothing(self, tmp_path: Path):
        """The template lives in an unquoted heredoc, so an unescaped backtick
        or $( ) is COMMAND SUBSTITUTION at render time — it runs, and its output
        replaces the text in the generated workflow. A comment reading
        `git push origin ""` did exactly that, printing
        `fatal: invalid refspec ''` and rendering the comment empty.

        A clean render writes nothing to stderr."""
        r = self._run(self._repo(tmp_path), "--print")
        assert r.returncode == 0, r.stderr
        assert r.stderr == "", (
            "render-time command substitution leaked:\n" + r.stderr)
        # And the text that triggered it survives as text.
        assert 'git push origin ""` fails opaquely' in r.stdout

    def test_the_credential_is_preflighted_before_any_work(self, tmp_path: Path):
        """Without the secret, --exact degrades to an estimate and
        record-telemetry.sh refuses the append — the job records NOTHING,
        silently. Failing at second zero is the whole point of the ordering."""
        yaml = pytest.importorskip("yaml")
        doc = yaml.safe_load(self._run(self._repo(tmp_path), "--print").stdout)
        names = [s.get("name", s.get("uses", ""))
                 for s in doc["jobs"]["measure"]["steps"]]
        assert "Preflight the credential" in names, names
        assert names.index("Preflight the credential") < names.index("Measure and record")

    def test_checkout_takes_submodules(self, tmp_path: Path):
        """The skill is vendored under skills-vendor/ and reached through a
        symlink. Without submodules the link dangles and every step fails."""
        yaml = pytest.importorskip("yaml")
        doc = yaml.safe_load(self._run(self._repo(tmp_path), "--print").stdout)
        checkout = doc["jobs"]["measure"]["steps"][0]
        assert checkout["uses"].startswith("actions/checkout@")
        assert checkout["with"]["submodules"] == "recursive"

    def test_it_records_a_baseline_row_not_a_curation(self, tmp_path: Path):
        """What goes on the clock is a measurement. A curation needs judgement,
        and judgement on a timer is what this skill avoids everywhere else."""
        out = self._run(self._repo(tmp_path), "--print").stdout
        assert 'record-telemetry.sh" --baseline' in out, out
        # The two flags --baseline refuses. Their absence is the assertion: a
        # scheduled job that recorded a relocation verdict, or tagged edits it
        # never made, would be claiming a curation happened.
        assert "--no-loss" not in out
        assert "--actions " not in out

    def test_the_cohort_is_staggered_and_stable(self, tmp_path: Path):
        """Twelve repos on one cron produce twelve simultaneous count_tokens
        bursts and twelve commits in a minute. The offset comes from the repo
        name, so it needs no per-repo decision and does not move on a re-run."""
        crons = set()
        for name in ("usa-wa", "observo", "watcher", "power-map", "cli"):
            repo = tmp_path / name
            repo.mkdir()
            _git(repo, "init", "-q")
            out = self._run(repo, "--print").stdout
            cron = next(ln for ln in out.splitlines() if "- cron:" in ln)
            crons.add(cron)
            assert self._run(repo, "--print").stdout == out, "not stable"
        assert len(crons) > 1, f"every repo drew the same slot: {crons}"

    def test_install_check_uninstall_round_trip(self, tmp_path: Path):
        repo = self._repo(tmp_path)
        wf = repo / ".github" / "workflows" / "context-cadence.yml"
        assert self._run(repo, "--check").returncode == 3
        assert self._run(repo).returncode == 0
        assert wf.exists()
        assert self._run(repo, "--check").returncode == 0
        # Idempotent: a second install reports no change rather than churning.
        again = self._run(repo)
        assert "unchanged" in again.stdout, again.stdout
        changed = self._run(repo, "--cron", "0 15 * * 1")
        assert "updated" in changed.stdout, changed.stdout
        assert "0 15 * * 1" in wf.read_text()
        assert self._run(repo, "--uninstall").returncode == 0
        assert not wf.exists()

    def test_a_malformed_cron_is_refused(self, tmp_path: Path):
        r = self._run(self._repo(tmp_path), "--cron", "every monday")
        assert r.returncode == 1
        assert "five fields" in r.stderr, r.stderr

    def test_it_refuses_outside_a_git_repo(self, tmp_path: Path):
        d = tmp_path / "bare"
        d.mkdir()
        r = subprocess.run(
            ["bash", str(INSTALL_CADENCE)], capture_output=True, text=True,
            cwd=str(d), env=_clean_env(), timeout=30)
        assert r.returncode == 1
        assert "not inside a git repository" in r.stderr


class TestCadenceTemplateMatchesTheRenderer:
    """references/cadence.md carries the workflow as an annotated block and says
    it is what install-cadence.sh renders. It was not: `fetch-depth` and
    `if: always()` were in the doc and absent from the rendered file, and
    `if: always()` is load-bearing — without it a failed push swallows the drift
    warnings.

    This is the third copy-divergence in this skill, so it gets a pin rather
    than another comment asserting one."""

    def test_the_documented_block_is_the_rendered_file(self, tmp_path: Path):
        import re
        doc = (REFERENCES / "cadence.md").read_text()
        block = re.search(r"```yaml\n(.*?)```", doc, re.S)
        assert block, "cadence.md no longer carries a yaml block"
        repo = tmp_path / "r"
        repo.mkdir()
        _git(repo, "init", "-q")
        rendered = subprocess.run(
            ["bash", str(INSTALL_CADENCE), "--print", "--cron", "0 15 * * 1"],
            capture_output=True, text=True, cwd=str(repo), env=_clean_env(),
            timeout=30).stdout.replace("- cron: '0 15 * * 1'", "- cron: '<CRON>'")
        assert block.group(1) == rendered, (
            "cadence.md's yaml block has drifted from install-cadence.sh --print")


class TestCadenceShellActuallyRuns:
    """The two real bugs in the first draft of this workflow — parsing a
    nonexistent `acknowledged:` line, and measuring twice — were both inside
    `run:` blocks, and neither would have been caught by asserting on the YAML
    structure. Execute the shell."""

    def _step(self, tmp_path: Path, name: str) -> str:
        yaml = pytest.importorskip("yaml")
        repo = tmp_path / "render"
        repo.mkdir()
        _git(repo, "init", "-q")
        doc = yaml.safe_load(subprocess.run(
            ["bash", str(INSTALL_CADENCE), "--print"], capture_output=True,
            text=True, cwd=str(repo), env=_clean_env(), timeout=30).stdout)
        return next(s["run"] for s in doc["jobs"]["measure"]["steps"]
                    if s.get("name") == name)

    def test_the_seam_extraction_parses_real_check_seams_output(
            self, tmp_path: Path):
        """The counts are named exactly as record-telemetry's flags, and the
        first draft parsed `acknowledged:`, which check-seams.sh never emits."""
        repo = _repo(tmp_path, policy_lines=5)
        (repo / "docs").mkdir()
        # A back-reference: a live doc naming the policy file is a seam.
        (repo / "docs" / "guide.md").write_text("See AGENTS.md for the overview.\n")
        (repo / "AGENTS.md").write_text("# A\n\nSee [guide](docs/guide.md).\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "seed")
        env = _clean_env()
        env["SKILL_SCRIPTS"] = str(SCRIPTS)
        env["GITHUB_ENV"] = str(tmp_path / "gh_env")
        (tmp_path / "gh_env").write_text("")
        r = subprocess.run(["bash", "-e", "-c", self._step(tmp_path, "Sweep the seams and the counts")],
                           capture_output=True, text=True, cwd=str(repo),
                           env=env, timeout=60)
        assert r.returncode == 0, r.stderr
        written = (tmp_path / "gh_env").read_text()
        assert re.search(r"^SEAMS=\d+$", written, re.M), written
        assert re.search(r"^SEAMS_ACKED=\d+$", written, re.M), written

    def test_the_commit_step_stages_the_row_without_the_ratio_file(
            self, tmp_path: Path):
        """A single `git add` over both paths stages NOTHING when either is
        missing — it exits 128 on the unmatched pathspec — so the row was
        discarded silently. measure-context.sh does not persist the ratio when
        any count falls back, which makes that reachable on a first run."""
        repo = _repo(tmp_path, policy_lines=5)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-metrics.jsonl").write_text(
            _ledger_row(repo="r", tokens=100) + "\n")
        assert not (repo / ".skills" / "context-token-ratio").exists()
        # Split on a stable sentinel rather than a variable name: renaming the
        # variable used to make the split find nothing and silently change what
        # this test exercised.
        step = self._step(tmp_path, "Commit the row")
        assert "# --- push ---" in step, step
        r = subprocess.run(["bash", "-e", "-c", step.split("# --- push ---")[0]],
                           capture_output=True, text=True, cwd=str(repo),
                           env=_clean_env(), timeout=30)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "nothing to commit" not in r.stdout, (
            "the row was silently dropped: " + r.stdout)
        # env=_clean_env() is not optional here. Git exports GIT_DIR to hook
        # processes, so when the suite runs under the pre-commit hook this call
        # inherits it. From the main checkout GIT_DIR is the relative ".git",
        # which -C re-resolves against the temp repo by accident and the test
        # passes; from a linked worktree it is absolute, so the log read comes
        # from the SHARED repo and the assertion fails on a diff that never
        # touched this code. The only call in this file that was missing it.
        log = subprocess.run(["git", "-C", str(repo), "log", "--oneline"],
                             capture_output=True, text=True,
                             env=_clean_env()).stdout
        assert "weekly context measurement" in log, log

    def test_a_human_commit_during_the_measurement_does_not_lose_the_row(
            self, tmp_path: Path):
        """The whole push path, against a real remote, in the race it exists
        for. Without `merge=union` on the ledger the rebase halts on a conflict
        — two appends land on the same last line — and the week's row is lost
        with markers left in the file. Verified end to end rather than reasoned
        about, because the first version of this retry loop did not work."""
        origin = tmp_path / "o.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)],
                       check=True, env=_clean_env())

        def clone(name: str) -> Path:
            d = tmp_path / name
            subprocess.run(["git", "clone", "-q", str(origin), str(d)],
                           check=True, env=_clean_env())
            _git(d, "config", "user.email", "t@t")
            _git(d, "config", "user.name", "t")
            return d

        seed = clone("seed")
        (seed / ".skills").mkdir()
        (seed / ".skills" / "context-metrics.jsonl").write_text(
            _ledger_row(repo="r", ts="2026-08-01", tokens=100) + "\n")
        # The attribute has to be in the BASE commit: git resolves using the
        # attributes in the tree being replayed onto, so adding it after the
        # conflict does not rescue the conflict.
        (seed / ".gitattributes").write_text(
            ".skills/context-metrics.jsonl merge=union\n")
        _git(seed, "add", "-A")
        _git(seed, "commit", "-qm", "seed")
        _git(seed, "push", "-q", "origin", "HEAD:main")

        bot = clone("bot")
        human = clone("human")

        # The human lands first, while the bot is still measuring.
        led = human / ".skills" / "context-metrics.jsonl"
        led.write_text(led.read_text() + _ledger_row(
            repo="r", ts="2026-08-07", tokens=120) + "\n")
        _git(human, "commit", "-qam", "human edit")
        _git(human, "push", "-q", "origin", "HEAD:main")

        # The bot appends its weekly row on the now-stale checkout and runs the
        # rendered step verbatim.
        led = bot / ".skills" / "context-metrics.jsonl"
        led.write_text(led.read_text() + _ledger_row(
            repo="r", ts="2026-08-08", tokens=130) + "\n")
        env = {**_clean_env(), "GITHUB_REF_NAME": "main"}
        r = subprocess.run(
            ["bash", "-e", "-c", self._step(tmp_path, "Commit the row")],
            capture_output=True, text=True, cwd=str(bot), env=env, timeout=60)
        assert r.returncode == 0, (
            "the retry did not recover the push:\n" + r.stdout + r.stderr)

        final = subprocess.run(
            ["git", "-C", str(origin), "show", "main:.skills/context-metrics.jsonl"],
            capture_output=True, text=True, env=_clean_env()).stdout
        assert "<<<<<<<" not in final, "conflict markers reached the remote:\n" + final
        stamps = [json.loads(ln)["ts"] for ln in final.splitlines() if ln.strip()]
        # Both survive, in order. The human's row is not clobbered and the
        # bot's is not lost.
        assert stamps == ["2026-08-01", "2026-08-07", "2026-08-08"], stamps

    def test_the_drift_report_warns_only_when_over_budget(self, tmp_path: Path):
        step = self._step(tmp_path, "Report drift")
        for tokens, expect in ((99_000, True), (100, False)):
            ctx = tmp_path / "ctx.json"
            ctx.write_text(json.dumps({"policy": {
                "path": "AGENTS.md", "tokens": tokens, "budget": 6000,
                "over_budget": tokens > 6000}}))
            r = subprocess.run(
                ["bash", "-e", "-c", step.replace("/tmp/ctx.json", str(ctx))],
                capture_output=True, text=True, cwd=str(tmp_path),
                env={**_clean_env(), "SEAMS": "0"}, timeout=30)
            assert r.returncode == 0, r.stderr
            assert ("::warning::AGENTS.md is" in r.stdout) is expect, r.stdout


class TestCadenceIsTwoArtifacts:
    """The installer's contract is a workflow AND a union-merge attribute. An
    early `exit 0` on "the workflow is already current" skipped the attribute
    entirely, so every repo that adopted before the attribute existed re-ran the
    installer, was told "unchanged", and stayed one race away from losing a row
    — which is exactly the population --check tells to re-run."""

    def _repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "r"
        repo.mkdir()
        _git(repo, "init", "-q")
        return repo

    def _run(self, repo: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(INSTALL_CADENCE), *args], capture_output=True,
            text=True, cwd=str(repo), env=_clean_env(), timeout=30)

    def test_rerunning_retrofits_a_missing_attribute(self, tmp_path: Path):
        repo = self._repo(tmp_path)
        assert self._run(repo).returncode == 0
        (repo / ".gitattributes").unlink()          # the pre-fix adopter
        r = self._run(repo)
        assert r.returncode == 0, r.stderr
        assert "unchanged" in r.stdout, "the workflow should not have churned"
        assert (repo / ".gitattributes").exists(), (
            "re-running did not restore the attribute — the remediation "
            "--check advertises does nothing:\n" + r.stdout)
        assert "merge=union" in (repo / ".gitattributes").read_text()

    def test_check_reports_both_independently(self, tmp_path: Path):
        repo = self._repo(tmp_path)
        self._run(repo)
        both = self._run(repo, "--check")
        assert both.returncode == 0, both.stdout
        assert "ledger union merge: yes" in both.stdout

        (repo / ".gitattributes").unlink()
        no_attr = self._run(repo, "--check")
        assert no_attr.returncode == 3, no_attr.stdout
        # The workflow is still reported — gating one on the other hid whichever
        # you were not looking for.
        assert "context-cadence.yml" in no_attr.stdout
        assert "ledger union merge: MISSING" in no_attr.stdout

        (repo / ".github" / "workflows" / "context-cadence.yml").unlink()
        neither = self._run(repo, "--check")
        assert neither.returncode == 3
        assert "workflow:           MISSING" in neither.stdout
        assert "ledger union merge: MISSING" in neither.stdout

    def test_the_ledger_path_agrees_everywhere(self, tmp_path: Path):
        """Three places must name the same file: the merge attribute, the
        workflow's git add, and the recorder's --ledger. A cadence that measures
        into one path and stages another records nothing."""
        repo = self._repo(tmp_path)
        r = self._run(repo, "--ledger", "telemetry/ctx.jsonl")
        assert r.returncode == 0, r.stderr
        assert "telemetry/ctx.jsonl merge=union" in (
            repo / ".gitattributes").read_text()
        wf = (repo / ".github" / "workflows" / "context-cadence.yml").read_text()
        assert 'git add -- "telemetry/ctx.jsonl"' in wf, wf
        assert '--ledger "telemetry/ctx.jsonl"' in wf, wf
        assert ".skills/context-metrics.jsonl" not in wf, (
            "the default ledger leaked into a --ledger install:\n" + wf)

    def test_an_existing_gitattributes_is_extended_not_replaced(
            self, tmp_path: Path):
        repo = self._repo(tmp_path)
        (repo / ".gitattributes").write_text("*.png binary\n")
        assert self._run(repo).returncode == 0
        text = (repo / ".gitattributes").read_text()
        assert "*.png binary" in text, "an unrelated rule was clobbered"
        assert "merge=union" in text
        # Idempotent: a second run neither duplicates nor churns.
        self._run(repo)
        assert (repo / ".gitattributes").read_text().count("merge=union") == 1


class TestCadenceDescribesTheRepoNotTheInvocation:
    """Deriving the ledger from the flag alone meant every mode assumed the
    caller repeated --ledger. `--check` on a repo installed with a custom ledger
    reported the attribute MISSING and said to re-run; doing so appended a second
    attribute for the default path and rewrote the workflow back to the default.
    Following the tool's own advice broke a correct install."""

    def _repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "r"
        repo.mkdir()
        _git(repo, "init", "-q")
        return repo

    def _run(self, repo: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(INSTALL_CADENCE), *args], capture_output=True,
            text=True, cwd=str(repo), env=_clean_env(), timeout=30)

    def test_check_without_the_flag_reads_the_installed_ledger(
            self, tmp_path: Path):
        repo = self._repo(tmp_path)
        self._run(repo, "--ledger", "telemetry/ctx.jsonl")
        r = self._run(repo, "--check")
        assert r.returncode == 0, r.stdout
        assert "telemetry/ctx.jsonl merge=union" in r.stdout, r.stdout

    def test_a_bare_rerun_does_not_revert_a_custom_ledger(self, tmp_path: Path):
        repo = self._repo(tmp_path)
        self._run(repo, "--ledger", "telemetry/ctx.jsonl")
        self._run(repo)                       # no flag — the advertised remedy
        wf = (repo / ".github" / "workflows" / "context-cadence.yml").read_text()
        attrs = (repo / ".gitattributes").read_text()
        assert 'git add -- "telemetry/ctx.jsonl"' in wf, wf
        assert ".skills/context-metrics.jsonl" not in wf, wf
        assert attrs.count("merge=union") == 1, attrs

    def test_changing_the_ledger_supersedes_the_old_attribute(
            self, tmp_path: Path):
        repo = self._repo(tmp_path)
        self._run(repo, "--ledger", "telemetry/ctx.jsonl")
        r = self._run(repo, "--ledger", "other/l.jsonl")
        assert "superseded" in r.stdout, r.stdout
        attrs = (repo / ".gitattributes").read_text()
        assert "other/l.jsonl merge=union" in attrs
        assert "telemetry/ctx.jsonl" not in attrs, attrs
        assert attrs.count("merge=union") == 1, attrs

    def test_a_commented_out_attribute_is_not_present(self, tmp_path: Path):
        """Commenting the line out is how somebody disables it. A substring
        grep called that 'yes' and asserted a guarantee that was switched off."""
        repo = self._repo(tmp_path)
        (repo / ".gitattributes").write_text(
            "# .skills/context-metrics.jsonl merge=union\n")
        r = self._run(repo, "--check")
        assert "ledger union merge: MISSING" in r.stdout, r.stdout
        assert r.returncode == 3

    def test_uninstall_does_not_claim_an_attribute_it_never_wrote(
            self, tmp_path: Path):
        r = self._run(self._repo(tmp_path), "--uninstall")
        assert r.returncode == 0
        assert "removed the .gitattributes entry" not in r.stdout
        assert "recorded rows were left in place" in r.stdout

    def test_uninstall_removes_the_attributes_it_installed(self, tmp_path: Path):
        """The installer's contract is two artifacts, so uninstall reverses
        both. The rows stay — removing the mechanism that adds to the series is
        not a reason to discard what it already collected.

        All THREE attribute lines, not just the ledger's: an uninstall that
        leaves the calibration entries behind is the same half-state --check
        exists to catch (#173)."""
        repo = self._repo(tmp_path)
        self._run(repo)
        assert (repo / ".gitattributes").exists()
        r = self._run(repo, "--uninstall")
        assert r.returncode == 0, r.stderr
        assert r.stdout.count("removed the .gitattributes entry") == 3, r.stdout
        # The file was ours, so it goes with it.
        assert not (repo / ".gitattributes").exists(), (
            repo / ".gitattributes").read_text()

    def test_uninstall_leaves_unrelated_gitattributes_rules(self, tmp_path: Path):
        repo = self._repo(tmp_path)
        (repo / ".gitattributes").write_text("*.png binary\n")
        self._run(repo)
        self._run(repo, "--uninstall")
        text = (repo / ".gitattributes").read_text()
        assert "*.png binary" in text, text
        assert "merge=union" not in text, text
        # And our explanatory comments went with the line they explained.
        assert "Append-only telemetry" not in text, text


class TestBudgetKnobIsOneAnswer:
    """The budget was resolved through the shared library by
    context-budget-guard.sh and context-delta.sh, and HARDCODED at 6000 by
    measure-context.sh — which is the script that puts `budget` and
    `over_budget` on the ledger row, the denominator score-cohort.sh divides by
    and the field #118 proposes as the adherence metric.

    So a repo configuring a budget got warnings at N from two surfaces and rows
    recorded against 6000 forever, and `install-guard.sh --budget` — the
    documented way to set it — was what produced the disagreement (#126)."""

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        repo = _repo(tmp_path, policy_lines=100)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-budget").write_text("200\n")
        return repo

    def _measured(self, repo: Path, *args: str, env: dict | None = None) -> dict:
        r = subprocess.run(
            ["bash", str(MEASURE), "--no-write", *args], capture_output=True,
            text=True, cwd=str(repo), env={**_clean_env(), **(env or {})},
            timeout=60)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)["policy"]

    def test_the_row_is_measured_against_the_configured_budget(self, repo: Path):
        p = self._measured(repo)
        assert p["budget"] == 200, p
        assert p["over_budget"] is True, p

    def test_all_three_surfaces_agree_on_one_knob(self, repo: Path):
        """The pin. One knob file, one answer, across every script that reads a
        budget — the same shape as TestCurationRuleIsOneRule and for the same
        reason: this is the third rule duplicated across these scripts."""
        assert self._measured(repo)["budget"] == 200

        # The guard and the delta both report on GROWTH against HEAD, so the
        # edit has to be real for either to speak.
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "seed")
        (repo / "AGENTS.md").write_text(POLICY_LINE * 300)

        guard = _advisory(_run_guard(repo, repo / "AGENTS.md"))
        assert guard is not None, "guard stayed silent on an over-budget policy"
        assert "200 budget" in guard, guard

        delta = subprocess.run(
            ["bash", str(DELTA)], capture_output=True, text=True,
            cwd=str(repo), env=_clean_env(), timeout=60).stdout
        # The delta prints a table; read the budget column off the AGENTS.md row
        # rather than substring-matching a number that appears in several.
        lines = delta.splitlines()
        # Locate the column from the HEADER rather than a fixed index, so a
        # reordered table fails pointing at the table instead of at the budget.
        header = next(ln for ln in lines if ln.split()[:2] == ["file", "tokens"])
        col = header.split().index("budget")
        row = next(ln for ln in lines if ln.startswith("AGENTS.md"))
        assert row.split()[col] == "200", (header, row)
        assert "OVER" in row, row

    @pytest.mark.parametrize("args,env,expected", [
        ((), {}, 200),                                   # the knob file
        ((), {"CONTEXT_BUDGET": "999"}, 999),            # env beats the file
        (("--budget", "4242"), {"CONTEXT_BUDGET": "999"}, 4242),  # flag beats both
    ])
    def test_the_precedence_matches_the_other_surfaces(
            self, repo: Path, args, env, expected):
        assert self._measured(repo, *args, env=env)["budget"] == expected

    def test_no_knob_still_defaults(self, tmp_path: Path):
        """The flag stops being the only source without becoming optional."""
        plain = _repo(tmp_path, policy_lines=100)
        assert self._measured(plain)["budget"] == 6000

    @pytest.mark.parametrize("args,env,expected", [
        ((), {}, 300),                                        # the knob file
        ((), {"CONTEXT_DOC_BUDGET": "700"}, 700),              # env beats it
        (("--doc-budget", "900"), {"CONTEXT_DOC_BUDGET": "700"}, 900),  # flag wins
    ])
    def test_the_doc_budget_has_the_same_three_rungs(
            self, tmp_path: Path, args, env, expected):
        """The less-used half, parametrised like the policy budget. The
        asymmetry is where a copy-paste slip in the second ctx_read_num_knob
        call would have hidden."""
        repo = _repo(tmp_path, policy_lines=10)
        (repo / ".skills").mkdir()
        (repo / ".skills" / "context-doc-budget").write_text("300\n")
        (repo / "docs").mkdir()
        (repo / "docs" / "BIG.md").write_text(POLICY_LINE * 400)
        r = subprocess.run(
            ["bash", str(MEASURE), "--no-write", *args], capture_output=True,
            text=True, cwd=str(repo), env={**_clean_env(), **env}, timeout=60)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        big = next(d for d in out["docs"] if d["path"].endswith("BIG.md"))
        # ~1000 tokens of doc: over 300 and 700, under 900.
        assert big["over_budget"] is (big["tokens"] > expected), (expected, big)

    @pytest.mark.parametrize("flag", ["--budget", "--doc-budget"])
    def test_a_malformed_budget_flag_is_refused(self, tmp_path: Path, flag):
        """ctx_read_num_knob returns the fallback for anything unparseable —
        right for a knob file, wrong for a flag, where silence means the run
        measures against 6000 and records that."""
        r = subprocess.run(
            ["bash", str(MEASURE), "--no-write", flag, "4,000"],
            capture_output=True, text=True, cwd=str(_repo(tmp_path)),
            env=_clean_env(), timeout=60)
        assert r.returncode == 1, r.stdout
        assert f"{flag} must be a non-negative integer (got '4,000')" in r.stderr


class TestDeadAnchorsReachTheLedgerAndTheGate:
    """CR round 1, finding 2.

    #120/#124 taught measure-context.sh to see an anchor whose file resolves
    but whose #fragment names no heading. The ledger row and score-cohort.sh
    were not part of that fence, so the number was computed and then dropped:
    a curation that orphaned every anchor into a split file recorded
    `links_dead: 0` and scored clean. #120 named links_dead "a safety gate in
    score-cohort.sh" — that is the whole reason anchor blindness mattered.
    """

    def _payload_with(self, dead_anchors: list[str] | None) -> str:
        links = {"dead": [], "orphans": []}
        if dead_anchors is not None:
            links["dead_anchors"] = dead_anchors
        return json.dumps({
            "policy": {"path": "AGENTS.md", "lines": 10, "bytes": 100,
                       "tokens": 40, "tokens_exact": True, "bytes_per_token": 2.5,
                       "budget": 6000, "over_budget": False},
            "totals": {"tokens_live": 40, "files_docs": 0},
            "docs": [], "links": links, "sections": [],
        })

    def _row(self, tmp_path: Path, payload: str) -> dict:
        repo = _repo(tmp_path)
        r = subprocess.run(
            ["bash", str(RECORD), "--dry-run"], input=payload,
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=30,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        line = [x for x in r.stdout.splitlines() if x.strip().startswith("{")][-1]
        return json.loads(line)

    def test_a_broken_anchor_lands_on_the_row(self, tmp_path: Path):
        row = self._row(tmp_path, self._payload_with(
            ["AGENTS.md -> docs/API.md#gone", "AGENTS.md -> docs/API.md#also-gone"]))
        assert row["links_dead"] == 0, "the files resolved; only the anchors are dead"
        assert row["links_dead_anchors"] == 2, row

    def test_a_payload_predating_the_field_records_null_not_zero(
            self, tmp_path: Path):
        """Null and 0 are different claims: a run that never measured anchors
        has not shown there are none. The ledger already draws this line for
        no_loss and seams."""
        row = self._row(tmp_path, self._payload_with(None))
        assert row["links_dead_anchors"] is None, row

    def test_a_null_does_not_trip_the_gate(self, tmp_path: Path):
        """Every row written before the field exists carries null. Gating on
        it would retroactively REJECT the entire cohort."""
        r = _score(_three_good_pairs(tmp_path))
        assert "links_dead_anchors" not in r.stdout, r.stdout
        assert "verdict: REJECT" not in r.stdout, r.stdout
