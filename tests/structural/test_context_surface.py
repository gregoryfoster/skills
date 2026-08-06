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
    return subprocess.run(
        ["bash", str(SCORE), "--cohort-file", str(roster),
         "--treatment", "b", "--control", "a", *args],
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
        as a rejection of the thing it never tested."""
        pairs = [(52000, 12000, 49000, 20000), (28000, 8000, 26000, 12000),
                 (19000, 7000, 14000, 9000)]
        spec = []
        for i, (cb, ca, tb, ta) in enumerate(pairs, start=1):
            _arm(tmp_path, f"ctl{i}", cb, ca, "1.1")
            _arm(tmp_path, f"trt{i}", tb, ta, "1.1")
            spec += [(f"ctl{i}", "a", str(i)), (f"trt{i}", "b", str(i))]
        r = _score(_roster(tmp_path, spec))
        assert r.returncode == 5, r.stdout
        assert "both arms ran the same version" in r.stdout

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
        """An empty comparison must not read as an experiment that found nothing."""
        path = tmp_path / "cohort"
        path.write_text("CannObserv/archiver\nCannObserv/notifier\n")
        r = subprocess.run(
            ["bash", str(SCORE), "--cohort-file", str(path)],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert r.returncode == 1
        assert "no wave assignment" in r.stderr
        assert "wave:a pair:1" in r.stderr

    def test_same_wave_for_both_arms_is_a_usage_error(self, tmp_path: Path):
        r = subprocess.run(
            ["bash", str(SCORE), "--treatment", "a", "--control", "a"],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert r.returncode == 1
        assert "same wave" in r.stderr

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
        """The split is a property of the cohort, so it belongs in the roll-up
        and not only inside the gate."""
        _arm(tmp_path, "one", 9000, 5000, "1.1")
        _arm(tmp_path, "two", 9000, None, "1.1")
        roster = _roster(tmp_path, [("one", "a", "1"), ("two", "b", "1")])
        r = subprocess.run(
            ["bash", str(COHORT), "--cohort-file", str(roster)],
            capture_output=True, text=True, env=_clean_env(), timeout=30,
        )
        assert r.returncode == 0, r.stderr
        assert "validation split" in r.stdout
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
        ctl = next(x for x in json.loads(r.stdout)["repos"] if x["repo"] == "ctl1")
        assert ctl["before"] == 50000, ctl
        # 50,000 -> 9,000 against a 6,000 budget is 93.2% closure, so the
        # control wins this pair and the treatment must not be adopted.
        assert round(ctl["closure"], 3) == round((44000 - 3000) / 44000, 3)
        assert json.loads(r.stdout)["verdict"] == "REJECT"

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

    def test_arm_split_across_versions_is_refused(self, tmp_path: Path):
        """'Adopt only if strictly better' presumes ONE proposal. A sweep could
        otherwise be carried by whichever version drew the easier pairs."""
        for i, (cb, ca, tb, ta) in enumerate(
                [(50000, 20000, 49000, 12000), (30000, 14000, 29000, 9000)],
                start=1):
            _arm(tmp_path, f"ctl{i}", cb, ca, "1.1")
            _arm(tmp_path, f"trt{i}", tb, ta, "1.2" if i == 1 else "1.9")
        r = _score(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1"),
                                      ("ctl2", "a", "2"), ("trt2", "b", "2")]),
                   "--min-pairs", "2")
        assert r.returncode == 5, r.stdout
        assert "split across versions" in r.stdout
        assert "no single change to adopt" in r.stdout
        assert "verdict: ADOPT" not in r.stdout

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
        """Wave A adopts first and holds the OLDER version, so running the
        script bare during round one inverts the comparison.

        Detection alone was not enough: the WARN printed at the top and the
        verdict then rejected the winning change and told the reader to file it
        in rejected-changes.md, twenty lines below the warning saying not to
        trust the result. A rejection entry is permanent and shapes future
        proposals, so recording a *winning* change as refuted is the worst
        single output this script can produce."""
        roster = _three_good_pairs(tmp_path)
        r = subprocess.run(
            ["bash", str(SCORE), "--cohort-file", str(roster),
             "--treatment", "a", "--control", "b"],
            capture_output=True, text=True, env=_clean_env(), timeout=60,
        )
        assert "arms look" in r.stdout, r.stdout
        assert "--treatment b --control a" in r.stdout
        assert r.returncode == 5
        assert "verdict: INCONCLUSIVE" in r.stdout
        assert "verdict: REJECT" not in r.stdout
        assert "record this in references/rejected-changes.md" not in r.stdout

    def test_correctly_ordered_arms_are_not_warned_about(self, tmp_path: Path):
        r = _score(_three_good_pairs(tmp_path))
        assert "arms look" not in r.stdout

    def test_version_comparison_is_numeric_not_lexical(self, tmp_path: Path):
        """1.10 is newer than 1.9. A string compare says otherwise, which is
        why the verdict never uses this ordering and the warning does."""
        _arm(tmp_path, "ctl1", 50000, 20000, "1.9")
        _arm(tmp_path, "trt1", 49000, 12000, "1.10")
        r = _score(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")]),
                   "--min-pairs", "1")
        assert "arms look" not in r.stdout, r.stdout
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
        assert cells["runs"] == "2", cells


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
        by = {x["repo"]: x for x in json.loads(r.stdout)["repos"]}
        assert by["ctl1"]["file"] == "AGENTS.md", by["ctl1"]
        assert by["ctl1"]["before"] == 50000
        assert by["ctl1"]["after"] == 7000
        assert by["trt1"]["after"] == 9000
        # The control did the better job on the primary file, so no adoption.
        assert json.loads(r.stdout)["verdict"] == "REJECT"

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
        assert int(cells["runs"]) == 2      # AGENTS.md rows only

    def test_uncurated_primary_file_names_the_file_and_the_others(
            self, tmp_path: Path):
        """Scoring a secondary file instead would be the bug this replaced; the
        honest answer names what was skipped rather than dropping the repo."""
        d = tmp_path / "one" / ".skills"
        d.mkdir(parents=True)
        (d / "context-metrics.jsonl").write_text("\n".join([
            _ledger_row(repo="one", ts="2026-08-01", file="sub/AGENTS.md",
                        tokens=9000, actions=["baseline:exact"]),
            _ledger_row(repo="one", ts="2026-08-02", file="sub/AGENTS.md",
                        tokens=7000, actions=["demote:X"], skill_version="1.1",
                        no_loss="ok"),
            _ledger_row(repo="one", ts="2026-08-03", tokens=50000,
                        actions=["baseline:exact"]),
        ]) + "\n")
        _arm(tmp_path, "two", 49000, 12000, "1.2")
        r = _score(_roster(tmp_path, [("one", "a", "1"), ("two", "b", "1")]),
                   "--min-pairs", "1")
        assert "no attributed curation run for AGENTS.md" in r.stdout, r.stdout
        assert "1 other file(s) in this ledger were not scored" in r.stdout

    def test_same_version_plus_failure_is_not_a_rejection(self, tmp_path: Path):
        """There is no proposal to reject, so the entry would name no change.
        The failure is real and must stay visible — it is a finding about the
        shipped version, the same distinction drawn for the control arm."""
        _arm(tmp_path, "ctl1", 52000, 20000, "1.1")
        _arm(tmp_path, "trt1", 49000, 12000, "1.1", no_loss="failed")
        r = _score(_roster(tmp_path, [("ctl1", "a", "1"), ("trt1", "b", "1")]),
                   "--min-pairs", "1")
        assert r.returncode == 5, r.stdout
        assert "both arms ran the same version" in r.stdout
        assert "not a rejection of anything proposed" in r.stdout
        assert "record this in references/rejected-changes.md" not in r.stdout
        # Still visible, not masked by the reordering.
        assert "treatment-arm safety failures:" in r.stdout
        assert "no_loss=failed" in r.stdout

    def test_real_failure_still_rejects_when_there_is_a_proposal(
            self, tmp_path: Path):
        """The reordering must not have disarmed the veto."""
        r = _score(_three_good_pairs(tmp_path, no_loss="failed"))
        assert r.returncode == 3, r.stdout
        assert "verdict: REJECT" in r.stdout
        assert "treatment-arm safety failures:" in r.stdout

    def test_out_of_arm_entries_are_reported(self, tmp_path: Path):
        """A typo'd wave: value removed a repo from the experiment with no trace
        anywhere in the output — a gate that quietly shrinks its own sample."""
        roster = _three_good_pairs(tmp_path)
        _arm(tmp_path, "stray", 9000, 7000, "1.2")
        with roster.open("a") as fh:
            fh.write(f"{tmp_path / 'stray'}  wave:x pair:9\n")
        r = _score(roster)
        assert "not in either arm" in r.stdout, r.stdout
        assert "stray" in r.stdout
        assert "wave x" in r.stdout

    def test_out_of_arm_appears_in_json(self, tmp_path: Path):
        roster = _three_good_pairs(tmp_path)
        _arm(tmp_path, "stray", 9000, 7000, "1.2")
        with roster.open("a") as fh:
            fh.write(f"{tmp_path / 'stray'}  wave:x pair:9\n")
        payload = json.loads(_score(roster, "--format", "json").stdout)
        assert payload["out_of_arm"] == [
            {"entry": str(tmp_path / "stray"), "wave": "x"}]

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
