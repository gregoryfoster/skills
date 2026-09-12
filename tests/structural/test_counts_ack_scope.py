"""#279 — an entry pinned to one file was told to prune on a run against another.

`.skills/context-counts-ok` is per-repo while `check-counts.sh --file` is
per-target, and the `PATH :: WARRANT :: CONTENT` form exists to pin an entry to
one file. The matching honoured the pin; the stale-entry report did not. So the
default run against `AGENTS.md` listed every entry pinned to a reference doc
under "matched nothing — the text each warranted has changed or gone; re-judge
and prune". On CannObserv/cannobserv#414 that was six entries judged for
`docs/STYLE.md` in the same run, none of them changed, and pruning on that advice
deletes live warrants. It is the defect #139 fixed for `prove-no-loss.sh` and
`.skills/context-loss-ok`, still live in the sibling with the same grammar.

The fix mirrors #139, and #251's refinement with it:

- **An entry scoped to another file sits the run out.** It warrants nothing
  here and is accused of nothing here. One line says how many did, so a file
  whose entries quietly stop applying can still be audited.
- **"Re-judge and prune" is said of one case only**: an entry pinned to this
  file whose text is gone from it. That is the expiry content-matching promises.
- **An unpinned entry whose text is not in this file is ambiguous**, and the run
  says so instead of guessing: the text was re-worded, or the entry was judged
  for another file. There is no `--base` here, so #251's second fact — is the
  CONTENT in this target? — is read against the file as it stands.
- **An entry whose text is still here was never "changed or gone".** Its clause
  stopped reporting, or an earlier entry took the hit first.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CHECK = REPO_ROOT / "skills" / "curating-context" / "scripts" / "check-counts.sh"

# One count in docs/X.md, none in AGENTS.md: a run against either file is clean
# unless the ack file makes it otherwise.
DOC = "# X\n\nThe merge produces two alphabetized sub-runs.\n"
PINNED = "docs/X.md :: stable :: produces two alphabetized sub-runs"
STALE_ADVICE = "has changed or gone; re-judge and prune"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — a linked worktree shares .git/config
    with its main checkout, so a fixture-creating git command that inherits
    them reaches out of the fixture and writes the wrong repo (#189)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _repo(tmp_path: Path, ack: str, policy: str = "# P\n\nNothing here.\n") -> Path:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    subprocess.run(
        ["git", "-C", str(repo), "init", "-q"],
        check=True,
        capture_output=True,
        env=_clean_env(),
        timeout=60,
    )
    (repo / "AGENTS.md").write_text(policy)
    (repo / "docs" / "X.md").write_text(DOC)
    (repo / ".skills").mkdir()
    (repo / ".skills" / "context-counts-ok").write_text(ack + "\n")
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(CHECK), *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=120,
    )


def _counts(result: subprocess.CompletedProcess) -> tuple[int, int]:
    """The machine-readable trailer, read by anchored prefix as the caller does."""
    new = acked = None
    for line in result.stdout.splitlines():
        if line.startswith("counts: "):
            new = int(line.split(": ", 1)[1])
        elif line.startswith("counts_acked: "):
            acked = int(line.split(": ", 1)[1])
    assert new is not None and acked is not None, result.stdout
    return new, acked


class TestAnEntryScopedToAnotherFile:
    def test_it_warrants_its_hit_on_its_own_file(self, tmp_path: Path) -> None:
        """The fixture's premise: the entry is live, and judged for docs/X.md."""
        result = _run(_repo(tmp_path, PINNED), "--file", "docs/X.md")
        assert result.returncode == 0, result.stdout + result.stderr
        assert _counts(result) == (0, 1)
        assert "matched nothing" not in result.stdout, result.stdout

    def test_it_is_not_called_stale_on_a_run_against_the_policy_file(
        self, tmp_path: Path
    ) -> None:
        """Acceptance 1: the reported defect, on the default run."""
        result = _run(_repo(tmp_path, PINNED))
        assert result.returncode == 0, result.stdout + result.stderr
        assert _counts(result) == (0, 0)
        assert "matched nothing" not in result.stdout, (
            "an entry pinned to docs/X.md was accused of going stale on a run "
            "that never consulted it:\n" + result.stdout
        )
        assert (
            "1 entry(ies) in .skills/context-counts-ok scoped to another target "
            "— not consulted for AGENTS.md." in result.stdout
        ), result.stdout

    def test_the_report_is_a_count_not_a_listing(self, tmp_path: Path) -> None:
        """Existence stays visible in one line. The entries are reported in full
        on their own file's run, and listing them on every other run is noise a
        repo with many pinned entries pays on each one."""
        result = _run(_repo(tmp_path, PINNED))
        assert "alphabetized" not in result.stdout, result.stdout

    def test_it_does_not_warrant_the_same_text_here(self, tmp_path: Path) -> None:
        """Scoping only ever NARROWS what an entry can reach (#139)."""
        repo = _repo(tmp_path, PINNED, policy=DOC.replace("# X", "# P"))
        result = _run(repo)
        assert result.returncode == 3, result.stdout + result.stderr
        assert _counts(result) == (1, 0)


class TestAnEntryThatMatchedNothing:
    def test_a_pinned_entry_whose_text_is_gone_is_stale(self, tmp_path: Path) -> None:
        """Acceptance 2, and the direction that must not regress: where the run
        CAN judge, the prune advice stands."""
        repo = _repo(tmp_path, PINNED)
        (repo / "docs" / "X.md").write_text(
            "# X\n\nThe merge produces three alphabetized sub-runs.\n"
        )
        result = _run(repo, "--file", "docs/X.md")
        assert _counts(result) == (1, 0)
        assert STALE_ADVICE in result.stdout, result.stdout
        assert PINNED in result.stdout, result.stdout
        assert "Do not prune" not in result.stdout, result.stdout

    def test_an_unpinned_entry_whose_text_is_not_here_is_not_called_stale(
        self, tmp_path: Path
    ) -> None:
        """#251: with neither a matched PATH nor its CONTENT in this file, the
        run cannot tell a re-worded line from an entry judged for another file,
        and pruning on the second reading discards a live warrant."""
        unpinned = PINNED.split(" :: ", 1)[1]
        result = _run(_repo(tmp_path, unpinned))
        assert result.returncode == 0, result.stdout + result.stderr
        assert STALE_ADVICE not in result.stdout, result.stdout
        assert "Do not prune on this run alone" in result.stdout, result.stdout
        assert unpinned in result.stdout, result.stdout

    @pytest.mark.parametrize(
        ("policy", "ack"),
        [
            pytest.param(
                "# P\n\nEight timers run (`systemctl list-timers | wc -l`).\n",
                "enumerated :: Eight timers run",
                id="the-clause-gained-its-command",
            ),
            pytest.param(
                "# P\n\nEight timers keep the tree fresh.\n",
                "pointer :: Eight timers keep",
                id="the-warrant-is-for-the-other-class",
            ),
        ],
    )
    def test_an_entry_whose_text_is_still_here_was_not_changed(
        self, tmp_path: Path, policy: str, ack: str
    ) -> None:
        """Its text is right there, so "changed or gone" is false of it — and
        being here says the entry IS about this file, pinned or not."""
        result = _run(_repo(tmp_path, ack, policy=policy))
        assert STALE_ADVICE not in result.stdout, result.stdout
        assert "Do not prune" not in result.stdout, result.stdout
        assert "though the text each names is still in AGENTS.md" in result.stdout
        assert ack in result.stdout, result.stdout

    def test_a_second_entry_for_one_hit_is_redundant(self, tmp_path: Path) -> None:
        """A hit is charged to the FIRST entry that matches it, so the second
        matched nothing while its hit sits in the report acknowledged."""
        first = "enumerated :: Eight timers keep"
        second = "stable :: timers keep the tree fresh"
        repo = _repo(
            tmp_path,
            f"{first}\n{second}",
            policy="# P\n\nEight timers keep the tree fresh.\n",
        )
        result = _run(repo)
        assert _counts(result) == (0, 1)
        assert "1 entry(ies) redundant" in result.stdout, result.stdout
        assert STALE_ADVICE not in result.stdout, result.stdout
        redundant = result.stdout.split("redundant", 1)[1]
        assert second in redundant, result.stdout
        assert first not in redundant, result.stdout
