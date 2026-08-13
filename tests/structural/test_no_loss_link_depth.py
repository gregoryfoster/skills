"""prove-no-loss.sh must normalise link depth at any depth, in either direction (#119).

The normaliser erased exactly one `../` level with `str.replace("](../", "](")`.
`str.replace` scans the original string and resumes past each replacement, so
`](../../plugins/x)` lost its first level and kept its second. That is the exact
shape a doc split produces — `docs/API.md` -> `docs/api/conventions.md` — where
the base link is already one level deep and the destination sits two levels
below the link target.

Measured on a real split of four reference docs into 38 parts: 172 lines
reported UNACCOUNTED FOR, all 172 false, verified against a byte-for-byte
reconstruction of every part from the base revision. A false-positive rate that
high is worse than no check at all, because a reader who learns to ignore this
output will ignore a real loss in it.

The property under test is narrow and has two halves, and only both halves
together are worth having:

  depth-agnostic     a line whose links moved any number of levels deeper OR
                     shallower still compares equal.
  not target-blind   a changed link target, changed prose, or a `../` outside a
                     link is still a difference, and still reports as LOST.

A fix that made everything compare equal would satisfy the first half and
destroy the check, so every relocation case below is paired with a loss case.
"""

import os
import subprocess
from pathlib import Path

import pytest

PROVE = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "curating-context"
    / "scripts"
    / "prove-no-loss.sh"
)


def _clean_env() -> dict:
    """Env without inherited GIT_* vars or the context knobs — pre-commit exports
    GIT_INDEX_FILE and friends, which leak into the script's own git calls."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR"):
        env.pop(k, None)
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, env=_clean_env(),
    )


def _split_repo(tmp_path: Path, base_line: str, moved_line: str) -> Path:
    """A doc split, the shape that defeated the one-level normaliser.

    `docs/API.md` carries the line at base and becomes a stub index; the content
    lands in `docs/api/conventions.md`, one directory below the docs root — so
    `find` locates it (that part always worked) and the comparison is what has
    to hold.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "AGENTS.md").write_text("# P\n\nSee [docs/API.md](docs/API.md).\n")
    (repo / "docs").mkdir()
    (repo / "docs" / "API.md").write_text(f"# API\n\n## Hooks\n\n{base_line}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "before")

    (repo / "docs" / "API.md").write_text(
        "# API\n\n- [Hooks](api/conventions.md)\n"
    )
    (repo / "docs" / "api").mkdir()
    (repo / "docs" / "api" / "conventions.md").write_text(
        f"# Hooks\n\n## Hooks\n\n{moved_line}\n"
    )
    return repo


def _run(repo: Path, *extra: str):
    return subprocess.run(
        ["bash", str(PROVE), "--base", "HEAD", "--file", "docs/API.md", *extra],
        capture_output=True, text=True, cwd=str(repo),
        env=_clean_env(), timeout=30,
    )


def _link(depth: int) -> str:
    """The reported line with its link target `depth` levels up."""
    return f"See [the hook]({'../' * depth}plugins/x.php) before editing."


class TestLinkDepthIsNormalisedAtAnyDepth:
    """The relocation half: link depth is a sanctioned transform, so any amount
    of it in either direction must compare equal."""

    @pytest.mark.parametrize(
        ("base_depth", "dest_depth"),
        [
            (1, 2),  # the reported case: docs/API.md -> docs/api/conventions.md
            (2, 3),  # the same split one level further down
            (0, 3),  # a policy-file line demoted three levels at once
            (2, 1),  # the mirror: content moving SHALLOWER, e.g. a doc merge
            (3, 0),  # all the way back inline
            (2, 2),  # unchanged depth still matches, the trivial guard
        ],
    )
    def test_a_line_is_accounted_for_at_any_depth(
        self, tmp_path: Path, base_depth: int, dest_depth: int
    ):
        repo = _split_repo(tmp_path, _link(base_depth), _link(dest_depth))
        result = _run(repo)
        assert result.returncode == 0, (
            f"depth {base_depth} -> {dest_depth} reported lost:\n"
            f"{result.stdout}{result.stderr}"
        )
        assert "UNACCOUNTED FOR:            0" in result.stdout, result.stdout

    def test_every_link_on_a_line_is_normalised_not_just_the_first(
        self, tmp_path: Path
    ):
        """Two links at different depths on one line, each moving by a different
        amount. Erasing one level per line — or one level per string — leaves
        one of them behind."""
        repo = _split_repo(
            tmp_path,
            "Read [a](../plugins/a.php) then [b](../../lib/b.php).",
            "Read [a](../../../plugins/a.php) then [b](lib/b.php).",
        )
        result = _run(repo)
        assert result.returncode == 0, result.stdout + result.stderr


class TestDepthAgnosticIsNotTargetBlind:
    """The loss half. Each case is a relocation case from above with one
    non-depth difference added, and each must still be reported."""

    def test_a_changed_link_target_is_still_lost(self, tmp_path: Path):
        """The failure mode a too-eager normaliser would introduce: `alpha` and
        `beta` are the same line but for the target, and a curation that
        repointed a link changed the content."""
        repo = _split_repo(
            tmp_path,
            "See [the hook](../plugins/alpha.php) before editing.",
            "See [the hook](../../plugins/beta.php) before editing.",
        )
        result = _run(repo)
        assert result.returncode == 3, (
            f"a repointed link compared equal:\n{result.stdout}{result.stderr}"
        )
        assert "alpha.php" in result.stdout, result.stdout

    def test_a_reworded_link_carrying_line_is_still_lost(self, tmp_path: Path):
        """Paraphrase-in-transit, the defect this whole script exists for, in the
        shape that the depth fix touches."""
        repo = _split_repo(
            tmp_path,
            "See [the hook](../plugins/x.php) before editing.",
            "See [the hook](../../plugins/x.php) before editing anything here.",
        )
        result = _run(repo)
        assert result.returncode == 3, (
            f"a reworded line compared equal:\n{result.stdout}{result.stderr}"
        )

    def test_a_dropped_link_carrying_line_is_still_lost(self, tmp_path: Path):
        """The split happened, the destination exists, and this line simply did
        not make the trip."""
        repo = _split_repo(
            tmp_path,
            "See [the hook](../plugins/x.php) before editing.",
            "Some other prose entirely.",
        )
        result = _run(repo)
        assert result.returncode == 3, result.stdout
        assert "LOST" in result.stdout and "plugins/x.php" in result.stdout

    def test_dot_dot_outside_a_link_is_not_normalised(self, tmp_path: Path):
        """Normalisation is anchored to `](`. A relative path in a shell command
        is content, not link depth — erasing it there would let a changed command
        pass as relocated."""
        repo = _split_repo(
            tmp_path,
            "Run `cd ../../scripts && ./build.sh` first.",
            "Run `cd scripts && ./build.sh` first.",
        )
        result = _run(repo)
        assert result.returncode == 3, (
            f"a `../` outside a link was normalised away:\n{result.stdout}"
        )


def _demote_repo(tmp_path: Path, base_line: str, moved_line: str) -> Path:
    """A DEMOTION, the other direction: a bullet moves out of the policy file at
    the repo root and into `docs/STYLE.md`.

    A link that was aimed from the root at `docs/OTHER.md` is aimed from inside
    `docs/` as `OTHER.md` — the move REMOVES a directory prefix rather than
    adding `../`, which is what #119's fix could not see.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "AGENTS.md").write_text(f"# P\n\n## Rules\n\n{base_line}\n")
    (repo / "docs").mkdir()
    (repo / "docs" / "OTHER.md").write_text("# Other\n\nthe rules\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "before")

    (repo / "AGENTS.md").write_text("# P\n\nSee [docs/STYLE.md](docs/STYLE.md).\n")
    (repo / "docs" / "STYLE.md").write_text(f"# Style\n\n## Rules\n\n{moved_line}\n")
    return repo


def _run_policy(repo: Path, *extra: str):
    """A policy-file run — the default target, which is what a demotion proves."""
    return subprocess.run(
        ["bash", str(PROVE), "--base", "HEAD", *extra],
        capture_output=True, text=True, cwd=str(repo),
        env=_clean_env(), timeout=30,
    )


class TestARemovedDirectoryPrefixIsNormalised:
    """The demotion half of the same transform (#137).

    A demotion is the operation this skill recommends most often, and every
    link-carrying bullet it moved reported LOST: one real run needed 12
    `retarget` warrants for nothing but this. The prefix erased is the docs
    root, because that is the directory the content moved INTO — anything else
    still discriminates, which is the point of the class below.
    """

    def test_a_demoted_sibling_link_is_accounted_for(self, tmp_path: Path):
        repo = _demote_repo(
            tmp_path,
            "- See [other](docs/OTHER.md) for the rules.",
            "- See [other](OTHER.md) for the rules.",
        )
        result = _run_policy(repo)
        assert result.returncode == 0, (
            f"a demoted sibling link reported lost:\n{result.stdout}{result.stderr}"
        )
        assert "UNACCOUNTED FOR:            0" in result.stdout, result.stdout

    def test_the_promotion_direction_matches_too(self, tmp_path: Path):
        """Erased in BOTH directions, like depth: content coming back up to the
        root re-acquires the prefix."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        (repo / "AGENTS.md").write_text("# P\n")
        (repo / "docs").mkdir()
        (repo / "docs" / "STYLE.md").write_text(
            "# Style\n\n- See [other](OTHER.md) for the rules.\n")
        (repo / "docs" / "OTHER.md").write_text("# Other\n\nthe rules\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "before")
        (repo / "docs" / "STYLE.md").write_text("# Style\n")
        (repo / "AGENTS.md").write_text(
            "# P\n\n- See [other](docs/OTHER.md) for the rules.\n")
        result = subprocess.run(
            ["bash", str(PROVE), "--base", "HEAD", "--file", "docs/STYLE.md",
             "--also", "AGENTS.md"],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(), timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_prefix_is_the_configured_docs_root_not_the_literal_docs(
        self, tmp_path: Path
    ):
        """A repo keeping its references elsewhere gets the same fix — the
        prefix erased is whatever --docs-dir names, or the check would work
        only for repos that spell it `docs`."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        (repo / "AGENTS.md").write_text(
            "# P\n\n- See [other](reference/OTHER.md) for the rules.\n")
        (repo / "reference").mkdir()
        (repo / "reference" / "OTHER.md").write_text("# Other\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "before")
        (repo / "AGENTS.md").write_text("# P\n")
        (repo / "reference" / "STYLE.md").write_text(
            "# Style\n\n- See [other](OTHER.md) for the rules.\n")
        result = _run_policy(repo, "--docs-dir", "reference")
        assert result.returncode == 0, result.stdout + result.stderr


class TestPrefixErasureIsNotTargetBlind:
    """Every relaxation of whole-line matching is paid out of the strength of
    the only gate that can see content loss, so the erasure is anchored to one
    prefix and one position. Each case below is a demotion with one non-depth
    difference added, and each must still be reported."""

    def test_a_prefix_that_is_not_the_docs_root_is_kept(self, tmp_path: Path):
        """`](lib/OTHER.md)` becoming `](OTHER.md)` is a repoint at a directory
        the run relocated nothing into, not a re-aim."""
        repo = _demote_repo(
            tmp_path,
            "- See [other](lib/OTHER.md) for the rules.",
            "- See [other](OTHER.md) for the rules.",
        )
        result = _run_policy(repo)
        assert result.returncode == 3, (
            f"a non-docs prefix was erased:\n{result.stdout}{result.stderr}"
        )
        assert "lib/OTHER.md" in result.stdout, result.stdout

    def test_a_changed_target_under_the_docs_root_is_still_lost(
        self, tmp_path: Path
    ):
        repo = _demote_repo(
            tmp_path,
            "- See [other](docs/ALPHA.md) for the rules.",
            "- See [other](BETA.md) for the rules.",
        )
        result = _run_policy(repo)
        assert result.returncode == 3, (
            f"a repointed link compared equal:\n{result.stdout}{result.stderr}"
        )
        assert "ALPHA.md" in result.stdout, result.stdout

    def test_only_the_leading_prefix_is_erased(self, tmp_path: Path):
        """Anchored to the start of the target. A `docs/` deeper in the path is
        part of what the link points at."""
        repo = _demote_repo(
            tmp_path,
            "- See [other](vendor/docs/OTHER.md) for the rules.",
            "- See [other](vendor/OTHER.md) for the rules.",
        )
        result = _run_policy(repo)
        assert result.returncode == 3, (
            f"a docs/ inside the target was erased:\n{result.stdout}"
        )

    def test_the_docs_root_outside_a_link_is_untouched(self, tmp_path: Path):
        """Normalisation is anchored to `](`, here as much as for depth. A path
        written in prose or in a command is content."""
        repo = _demote_repo(
            tmp_path,
            "- Run `cat docs/OTHER.md` before editing the rules.",
            "- Run `cat OTHER.md` before editing the rules.",
        )
        result = _run_policy(repo)
        assert result.returncode == 3, (
            f"a docs/ outside a link was erased:\n{result.stdout}"
        )

    def test_a_reworded_demoted_line_is_still_lost(self, tmp_path: Path):
        """Paraphrase-in-transit, in the shape the prefix fix touches."""
        repo = _demote_repo(
            tmp_path,
            "- See [other](docs/OTHER.md) for the rules.",
            "- See [other](OTHER.md) for the rules, all of them.",
        )
        assert _run_policy(repo).returncode == 3
