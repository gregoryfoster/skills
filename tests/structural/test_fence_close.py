"""A fence closes on the marker that opened it, in every script that walks one (#275).

Three scripts in `curating-context` walk markdown fences — `prove-no-loss.sh`,
`check-seams.sh` and `check-counts.sh` — each with its own copy of `FENCE`. Two
of the three toggled on EITHER marker, so a `~~~` line inside a ``` block — a
gate's own output quoted in a doc, a doc showing example markdown — flipped the
state, and everything after the real close was keyed as fenced content.

`check-seams.sh` was corrected first, under #272 CR 13, and its case lives in
test_seam_relocation_gate.py (`test_a_marker_of_the_other_kind_does_not_close_
the_fence`). That left the three gates in one phase chain disagreeing about
where a fenced block ends. The two cases here bring the other two scripts to
the same answer, one in each direction the old toggle got wrong:

  prove-no-loss  a span in prose AFTER a stray-tilde block was read as fenced
                 in the destination, so its whole line became the atom and the
                 span `make check` was reported DROPPED — a false claim loss on
                 a verbatim relocation.
  check-counts   a count in prose after the block was skipped as fenced and
                 never judged; a count INSIDE the fence after the tilde was
                 judged as prose.

The constant itself is pinned identical across the three by
test_heredoc_twins.py; this file pins what the constant is for.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "skills" / "curating-context" / "scripts"
PROVE = SCRIPTS / "prove-no-loss.sh"
COUNTS = SCRIPTS / "check-counts.sh"

# A fenced block carrying a marker of the other kind as CONTENT.
TILDE_BLOCK = "```text\nseams: 0\n~~~ not a fence, just output ~~~\n```\n"


def _clean_env() -> dict:
    """STYLE.md § 'A repo-creating git command must scrub GIT_DIR'."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
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


def _write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _run(script: Path, repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=60,
    )


class TestProveNoLoss:
    """`--claims` extracts a fenced line WHOLE and a prose line by its spans. A
    destination read with the wrong fence state extracts the wrong one."""

    def test_a_span_after_a_stray_tilde_block_is_still_a_span(self, tmp_path: Path):
        repo = tmp_path / "claims"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _write(
            repo, "AGENTS.md", "# P\n\n## Ship\n\nRun `make check` before shipping.\n"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "pre")
        # The line relocates VERBATIM, so whole-line matching is satisfied and the
        # only thing left to disagree about is the atom. In the destination it
        # sits after a block whose content includes `~~~`: read with the old
        # toggle, that line is fenced, its atom is the whole line, and the span
        # `make check` is reported dropped.
        _write(
            repo, "AGENTS.md", "# P\n\n## Ship\n\nSee [docs/SHIP.md](docs/SHIP.md).\n"
        )
        _write(
            repo,
            "docs/SHIP.md",
            "# Ship\n\n" + TILDE_BLOCK + "\nRun `make check` before shipping.\n",
        )
        r = _run(PROVE, repo, "--base", "HEAD", "--claims")
        assert r.returncode == 0, (
            f"a verbatim relocation reported a dropped claim:\n{r.stdout}{r.stderr}"
        )


class TestCheckCounts:
    """A count is judged where it is prose and skipped where it is code, and a
    stray tilde must not swap the two."""

    @staticmethod
    def _repo(tmp_path: Path, name: str, policy: str) -> Path:
        repo = tmp_path / name
        repo.mkdir()
        _git(repo, "init", "-q")
        _write(repo, "AGENTS.md", policy)
        return repo

    def test_a_count_in_prose_after_the_block_is_judged(self, tmp_path: Path):
        """Under the old toggle the closing ``` re-OPENED a fence, and the
        cardinal below it was skipped as code."""
        repo = self._repo(
            tmp_path,
            "after",
            "# P\n\n" + TILDE_BLOCK + "\nEight scheduled timers keep the tree fresh.\n",
        )
        r = _run(COUNTS, repo)
        assert r.returncode == 3, f"a count in prose was not judged:\n{r.stdout}"
        assert "Eight scheduled timers" in r.stdout, r.stdout

    def test_a_count_inside_the_block_after_the_tilde_is_still_code(
        self, tmp_path: Path
    ):
        """The mirror: under the old toggle the tilde CLOSED the fence, and a
        cardinal still inside it was judged as prose."""
        repo = self._repo(
            tmp_path,
            "inside",
            "# P\n\n```text\nseams: 0\n~~~ output ~~~\n"
            "Eight scheduled timers keep the tree fresh.\n```\n",
        )
        r = _run(COUNTS, repo)
        assert r.returncode == 0, f"a fenced line was judged as prose:\n{r.stdout}"
