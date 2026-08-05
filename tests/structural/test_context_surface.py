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
