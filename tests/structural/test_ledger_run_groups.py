"""A run's warrants, stamped with the run they judged (#579).

`prove-no-loss.sh` and `check-seams.sh` judged every entry in
`.skills/context-loss-ok` and `.skills/context-seams-ok` against the CURRENT
sweep's base. An entry records a judgement about one run's diff, but nothing
tied it to that run, so once the run merged, every later sweep reported the
entry as "matched nothing" — the line it warranted is gone, which is what the
run did. CannObserv/wslcb-licensing-tracker#242 pruned 7 dead loss entries and
18 dead seam acks by hand, and a "0 matched-nothing on main" ratchet could not
hold after any run that wrote a warrant.

Worse than the report: an unpruned entry is still CONSULTED. A later run that
loses a line the entry's CONTENT reaches is warranted by a judgement that was
never about it.

So a group header stamps the base, the target, or both:

    # @run base=<sha> file=<target>
    retarget :: ...
    # @run end

A group stamped for another base is HISTORICAL: not consulted, counted under
its own line, never "matched nothing". A group scoped to another target sits
out the way a loss entry's `PATH ::` does. Every unstamped entry reads exactly
as before — the header is a comment to any reader that predates it.

And on the seam side, without any syntax: an ack whose class could not run on
this sweep — a source ack when nothing left the policy file — is DORMANT, not
stale.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "skills" / "curating-context" / "scripts"
PROVE = SCRIPTS / "prove-no-loss.sh"
SEAMS = SCRIPTS / "check-seams.sh"
LOSS_ACK = ".skills/context-loss-ok"
SEAM_ACK = ".skills/context-seams-ok"

# The line a run drops, and the substring its warrant names.
LOST = "Full naming rules live in [docs/STYLE.md](docs/STYLE.md) §32 — read that first."
WARRANT = "retarget :: Full naming rules live in [docs/STYLE.md]"
KEPT = "Run make before every commit, and never skip the hooks."


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    return env


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_clean_env(),
    ).stdout.strip()


def _write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _init(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    return repo


def _commit(repo: Path, msg: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", msg)
    return _git(repo, "rev-parse", "HEAD")


def _run(script: Path, repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=60,
    )


# --- the loss ledger ---------------------------------------------------------


def _loss_repo(tmp_path: Path) -> tuple[Path, str]:
    """AGENTS.md holds LOST at the base; the working tree has dropped it."""
    repo = _init(tmp_path)
    _write(repo, "AGENTS.md", f"# Guide\n\n{KEPT}\n\n{LOST}\n")
    base = _commit(repo, "base")
    _write(repo, "AGENTS.md", f"# Guide\n\n{KEPT}\n")
    return repo, base


def _merged_repo(tmp_path: Path) -> tuple[Path, str]:
    """The run that dropped LOST has merged: the stamp names its base, and
    every later sweep's base is past it. wslcb's #242, in miniature."""
    repo, base = _loss_repo(tmp_path)
    _commit(repo, "the curation run")
    return repo, base


class TestLossGroups:
    def test_a_stamp_matching_the_base_warrants_as_before(self, tmp_path: Path):
        repo, base = _loss_repo(tmp_path)
        _write(repo, LOSS_ACK, f"# @run base={base}\n{WARRANT}\n")
        r = _run(PROVE, repo, "--base", base)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "loss_warranted: 1" in r.stdout

    def test_an_abbreviated_stamp_matches(self, tmp_path: Path):
        repo, base = _loss_repo(tmp_path)
        _write(repo, LOSS_ACK, f"# @run base={base[:7]} file=AGENTS.md\n{WARRANT}\n")
        r = _run(PROVE, repo, "--base", "HEAD")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_an_unstamped_entry_still_warrants(self, tmp_path: Path):
        """Additivity: a ledger written before the header existed."""
        repo, _ = _loss_repo(tmp_path)
        _write(repo, LOSS_ACK, f"# a plain comment\n{WARRANT}\n")
        r = _run(PROVE, repo, "--base", "HEAD")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_a_merged_runs_group_is_historical_not_matched_nothing(
        self, tmp_path: Path
    ):
        """The issue's symptom: against any later base, the entry was
        reported as matched nothing."""
        repo, base = _merged_repo(tmp_path)
        _write(repo, LOSS_ACK, f"# @run base={base[:12]}\n{WARRANT}\n")
        r = _run(PROVE, repo, "--base", "HEAD")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "matched nothing" not in r.stdout, r.stdout
        assert "1 entry(ies) stamped for another base" in r.stdout, r.stdout

    def test_a_historical_group_cannot_warrant_a_later_loss(self, tmp_path: Path):
        """The hazard under the symptom. The judged run's base still held
        LOST, an unrelated commit followed, and a later run drops LOST again:
        the old judgement must not wave it through."""
        repo = _init(tmp_path)
        _write(repo, "AGENTS.md", f"# Guide\n\n{KEPT}\n\n{LOST}\n")
        judged = _commit(repo, "the judged run's base")
        _write(repo, "README.md", "unrelated\n")
        _commit(repo, "later")
        _write(repo, LOSS_ACK, f"# @run base={judged}\n{WARRANT}\n")
        _write(repo, "AGENTS.md", f"# Guide\n\n{KEPT}\n")
        r = _run(PROVE, repo, "--base", "HEAD")
        assert r.returncode == 3, r.stdout + r.stderr
        assert "LOST" in r.stdout
        assert "re-stamp" in r.stdout, r.stdout

    def test_run_end_returns_to_unstamped(self, tmp_path: Path):
        repo, _ = _loss_repo(tmp_path)
        _write(
            repo,
            LOSS_ACK,
            "# @run base=0000000\nduplicate :: some other line entirely\n"
            f"# @run end\n{WARRANT}\n",
        )
        r = _run(PROVE, repo, "--base", "HEAD")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_file_scopes_a_loss_group(self, tmp_path: Path):
        repo, _ = _loss_repo(tmp_path)
        _write(repo, LOSS_ACK, f"# @run file=docs/OTHER.md\n{WARRANT}\n")
        r = _run(PROVE, repo, "--base", "HEAD")
        assert r.returncode == 3, r.stdout + r.stderr
        assert "scoped to another target" in r.stdout
        _write(repo, LOSS_ACK, f"# @run file=AGENTS.md\n{WARRANT}\n")
        r = _run(PROVE, repo, "--base", "HEAD")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_a_malformed_header_warns_and_reads_as_a_comment(self, tmp_path: Path):
        """A `# @run` line was a legal comment before this existed, so it is
        never refused: WARN, then read the entries as if it were not there."""
        repo, _ = _loss_repo(tmp_path)
        _write(repo, LOSS_ACK, f"# @run base=not-a-sha\n{WARRANT}\n")
        r = _run(PROVE, repo, "--base", "HEAD")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "WARN" in r.stderr and "@run" in r.stderr, r.stderr

    def test_the_report_names_the_header_to_stamp_with(self, tmp_path: Path):
        repo, base = _loss_repo(tmp_path)
        r = _run(PROVE, repo, "--base", "HEAD")
        assert r.returncode == 3
        assert f"# @run base={base[:12]} file=AGENTS.md" in r.stdout, r.stdout

    def test_a_claim_entry_takes_the_same_header(self, tmp_path: Path):
        """parse_ack is shared, so context-claims-ok reads groups for free."""
        repo, base = _merged_repo(tmp_path)
        _write(
            repo,
            ".skills/context-claims-ok",
            f"# @run base={base}\nretarget :: docs/STYLE.md\n",
        )
        r = _run(PROVE, repo, "--base", "HEAD", "--claims")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "matched nothing" not in r.stdout, r.stdout


def _old_script(tmp_path: Path, name: str) -> Path:
    """The script as it stood before #579, with its library beside it."""
    try:
        for f in (name, "_context-lib.sh"):
            blob = subprocess.run(
                [
                    "git",
                    "-C",
                    str(ROOT),
                    "show",
                    f"bd6aaa2c:skills/curating-context/scripts/{f}",
                ],
                check=True,
                capture_output=True,
                env=_clean_env(),
            ).stdout
            (tmp_path / "old").mkdir(exist_ok=True)
            (tmp_path / "old" / f).write_bytes(blob)
    except subprocess.CalledProcessError:
        pytest.skip("bd6aaa2c is not in this clone (shallow checkout)")
    return tmp_path / "old" / name


class TestAnOlderReaderSeesAComment:
    """A cohort repo stamps its ledger; a sibling still vendors the old
    scripts. The header must read there as the comment it always was."""

    def test_the_old_prove_no_loss_reads_a_stamped_group_as_unstamped(
        self, tmp_path: Path
    ):
        old = _old_script(tmp_path, "prove-no-loss.sh")
        repo, base = _loss_repo(tmp_path)
        _write(repo, LOSS_ACK, f"# @run base={base} file=AGENTS.md\n{WARRANT}\n")
        r = _run(old, repo, "--base", "HEAD")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_the_old_check_seams_reads_a_stamped_group_as_unstamped(
        self, tmp_path: Path
    ):
        old = _old_script(tmp_path, "check-seams.sh")
        repo = _seam_repo(tmp_path)
        _write(
            repo,
            SEAM_ACK,
            "# @run base=0000000 file=AGENTS.md\n"
            "docs/A.md :: See AGENTS.md\ndocs/B.md :: Also AGENTS.md\n",
        )
        r = _run(old, repo, "--base", "HEAD")
        assert r.returncode == 0, r.stdout + r.stderr


# --- the seam ledger ---------------------------------------------------------


def _seam_repo(tmp_path: Path) -> Path:
    """Two standing back-references and one tracked source mention. Nothing
    leaves the policy file, so the source classes cannot run."""
    repo = _init(tmp_path, "seams")
    _write(repo, "AGENTS.md", "# Guide\n\n## Build\n\nrun make\n")
    _write(repo, "docs/A.md", "# A\n\nSee AGENTS.md for the build.\n")
    _write(repo, "docs/B.md", "# B\n\nAlso AGENTS.md covers the rest.\n")
    _write(repo, "src/app.py", '"""Reads AGENTS.md at startup."""\n')
    _commit(repo, "base")
    return repo


BOTH_ACKS = "docs/A.md :: See AGENTS.md\ndocs/B.md :: Also AGENTS.md\n"


class TestSeamGroups:
    def test_file_scopes_a_seam_ack(self, tmp_path: Path):
        """A seam ack's `PATH ::` names the HIT's file, so it could never say
        which sweep it was judged for (#139's problem, on the seam side)."""
        repo = _seam_repo(tmp_path)
        _write(repo, SEAM_ACK, f"# @run file=docs/OTHER.md\n{BOTH_ACKS}")
        r = _run(SEAMS, repo, "--base", "HEAD")
        assert r.returncode == 3, r.stdout + r.stderr
        assert "scoped to another target" in r.stdout, r.stdout
        _write(repo, SEAM_ACK, f"# @run file=AGENTS.md\n{BOTH_ACKS}")
        r = _run(SEAMS, repo, "--base", "HEAD")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_a_matching_stamp_acks_as_before(self, tmp_path: Path):
        repo = _seam_repo(tmp_path)
        head = _git(repo, "rev-parse", "HEAD")
        _write(repo, SEAM_ACK, f"# @run base={head[:9]}\n{BOTH_ACKS}")
        r = _run(SEAMS, repo, "--base", "HEAD")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_a_group_for_another_base_is_historical(self, tmp_path: Path):
        repo = _seam_repo(tmp_path)
        _write(
            repo,
            SEAM_ACK,
            "docs/A.md :: See AGENTS.md\n"
            "# @run base=0000000\ndocs/B.md :: Also AGENTS.md\n",
        )
        r = _run(SEAMS, repo, "--base", "HEAD")
        assert r.returncode == 3, r.stdout + r.stderr
        assert "docs/B.md:3" in r.stdout
        assert "matched nothing" not in r.stdout, r.stdout
        assert "1 entry(ies) stamped for another base" in r.stdout, r.stdout

    def test_a_malformed_header_warns_and_reads_as_a_comment(self, tmp_path: Path):
        repo = _seam_repo(tmp_path)
        _write(repo, SEAM_ACK, f"# @run nonsense\n{BOTH_ACKS}")
        r = _run(SEAMS, repo, "--base", "HEAD")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "WARN" in r.stderr and "@run" in r.stderr, r.stderr

    def test_a_mentions_group_is_untouched_by_a_run_header(self, tmp_path: Path):
        """`@mentions` already names its swept file and never expires; a
        stamp around it must not retire it."""
        repo = _seam_repo(tmp_path)
        _write(
            repo,
            SEAM_ACK,
            f"{BOTH_ACKS}# @run base=0000000\n"
            "@mentions AGENTS.md src :: the app reads the policy file\n",
        )
        r = _run(SEAMS, repo, "--base", "HEAD")
        assert r.returncode == 0, r.stdout + r.stderr


class TestDormantSeamAcks:
    """#208's 9 source acks read stale on every sweep that relocated nothing:
    the source classes never ran, so the acks could not have matched."""

    def test_a_source_ack_is_dormant_when_nothing_left(self, tmp_path: Path):
        repo = _seam_repo(tmp_path)
        _write(repo, SEAM_ACK, f"{BOTH_ACKS}src/app.py :: Reads AGENTS.md\n")
        r = _run(SEAMS, repo, "--base", "HEAD")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "matched nothing" not in r.stdout, r.stdout
        assert "dormant" in r.stdout and "src/app.py :: Reads" in r.stdout

    def test_a_source_ack_is_dormant_under_no_source(self, tmp_path: Path):
        repo = _seam_repo(tmp_path)
        _write(repo, SEAM_ACK, f"{BOTH_ACKS}src/app.py :: Reads AGENTS.md\n")
        r = _run(SEAMS, repo, "--base", "HEAD", "--no-source")
        assert "matched nothing" not in r.stdout, r.stdout
        assert "--no-source" in r.stdout and "dormant" in r.stdout

    def test_a_class_named_moved_title_ack_is_dormant_when_nothing_moved(
        self, tmp_path: Path
    ):
        repo = _seam_repo(tmp_path)
        _write(
            repo,
            SEAM_ACK,
            f"{BOTH_ACKS}moved-title docs/A.md references 'Deploy Topology'\n",
        )
        r = _run(SEAMS, repo, "--base", "HEAD")
        assert "matched nothing" not in r.stdout, r.stdout
        assert "dormant" in r.stdout

    def test_a_doc_ack_that_matched_nothing_is_still_stale(self, tmp_path: Path):
        """Dormancy is only for a class that did not run. A back-reference
        ack whose line changed is the expiry the file promises."""
        repo = _seam_repo(tmp_path)
        _write(repo, SEAM_ACK, f"{BOTH_ACKS}docs/A.md :: a line long since gone\n")
        r = _run(SEAMS, repo, "--base", "HEAD")
        assert "1 entry(ies) matched nothing" in r.stdout, r.stdout
        assert "dormant" not in r.stdout
