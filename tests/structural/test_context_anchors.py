"""Anchor resolution in measure-context.sh (#120, #124).

A defect found on real cohort runs:

- `extract_links()` stripped the `#fragment` before resolving, so a link whose
  file exists and whose heading does not was invisible. That is exactly the shape
  of the operation this skill encourages — splitting an over-budget doc moves
  headings out of a file while leaving the file in place — so the gate was blind
  precisely where the advice points. Misses are reported as `links.dead_anchors`,
  their own class, so `dead` keeps its meaning for existing consumers.

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
MEASURE = SCRIPTS / "measure-context.sh"


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CONTEXT_BUDGET", "CONTEXT_DOC_BUDGET", "CONTEXT_DOCS_DIR",
              "ANTHROPIC_API_KEY"):
        env.pop(k, None)
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, env=_clean_env(),
    )


def _repo(tmp_path: Path, policy: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "AGENTS.md").write_text(policy)
    (repo / "docs").mkdir()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _measure(repo: Path, *args: str, env: dict | None = None) -> dict:
    result = subprocess.run(
        ["bash", str(MEASURE), "--no-write", *args],
        capture_output=True, text=True, cwd=str(repo),
        env=env if env is not None else _clean_env(), timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class TestAnchorsResolveAgainstHeadings:
    """A link whose file resolves and whose fragment names no heading lands the
    reader at the top of a file that no longer holds what they were sent for."""

    def test_a_resolvable_anchor_is_not_reported(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\n[g](docs/GUIDE.md#adding-a-new-stage)\n")
        (repo / "docs" / "GUIDE.md").write_text("# G\n\n## Adding a new stage\n\nx\n")
        data = _measure(repo)
        assert data["links"]["dead_anchors"] == []
        assert data["links"]["dead"] == []

    def test_a_missing_anchor_is_reported_as_its_own_class(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\n[g](docs/GUIDE.md#adding-a-new-stage)\n")
        (repo / "docs" / "GUIDE.md").write_text("# G\n\n## Adding a stage\n\nx\n")
        data = _measure(repo)
        assert data["links"]["dead_anchors"] == [
            "AGENTS.md -> docs/GUIDE.md#adding-a-new-stage"
        ]
        assert data["links"]["dead"] == [], (
            "`dead` must keep its meaning — a resolvable file is not a dead link"
        )

    def test_the_split_case(self, tmp_path: Path):
        """The operation the skill exists to encourage: a section moves to a new
        file and the file it left behind still exists."""
        repo = _repo(tmp_path, "# P\n\n[c](docs/CONSUMERS.md#adding-a-new-analysis-stage)\n")
        (repo / "docs" / "CONSUMERS.md").write_text("# C\n\n## Overview\n\nx\n")
        (repo / "docs" / "CONSUMERS-STAGES.md").write_text(
            "# C\n\n## Adding a new analysis stage\n\nx\n"
        )
        data = _measure(repo)
        assert data["links"]["dead"] == []
        assert data["links"]["dead_anchors"] == [
            "AGENTS.md -> docs/CONSUMERS.md#adding-a-new-analysis-stage"
        ]

    def test_a_same_file_fragment_is_checked(self, tmp_path: Path):
        repo = _repo(
            tmp_path,
            "# P\n\n## Setup\n\n[here](#setup) and [gone](#teardown)\n",
        )
        data = _measure(repo)
        assert data["links"]["dead_anchors"] == ["AGENTS.md -> AGENTS.md#teardown"]
        assert data["links"]["dead"] == []

    def test_a_missing_file_still_reports_dead_without_its_fragment(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\n[g](docs/GONE.md#whatever)\n")
        data = _measure(repo)
        assert data["links"]["dead"] == ["AGENTS.md -> docs/GONE.md"]
        assert data["links"]["dead_anchors"] == [], (
            "a missing file is one defect, not two"
        )

    def test_fragments_do_not_disturb_refs_or_reachability(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\n[g](docs/GUIDE.md#h)\n")
        (repo / "docs" / "GUIDE.md").write_text("# G\n\n## H\n\nx\n")
        data = _measure(repo)
        assert data["links"]["refs"] == ["docs/GUIDE.md"]
        assert data["links"]["orphans"] == []
        assert data["docs"][0]["linked"] is True


class TestSlugRules:
    """GitHub's rules: lowercase, drop everything outside [a-z0-9 _-], each space
    becomes a hyphen (not a run of spaces — one hyphen each)."""

    def _anchors(self, tmp_path: Path, heading: str, *fragments: str) -> list[str]:
        links = "\n".join(f"[l{i}](docs/GUIDE.md#{f})" for i, f in enumerate(fragments))
        # A fresh parent per call, so one test may make two independent probes.
        parent = tmp_path / f"case{len(list(tmp_path.iterdir()))}"
        parent.mkdir()
        repo = _repo(parent, f"# P\n\n{links}\n")
        (repo / "docs" / "GUIDE.md").write_text(f"# G\n\n{heading}\n\nx\n")
        return _measure(repo)["links"]["dead_anchors"]

    def test_punctuation_is_dropped_and_case_folded(self, tmp_path: Path):
        assert self._anchors(
            tmp_path, "## The `count_tokens` fallback: why?", "the-count_tokens-fallback-why"
        ) == []

    def test_a_stripped_character_leaves_its_spaces(self, tmp_path: Path):
        """`Tranche 5h3 — 2026-06-15` slugs to `...5h3--2026-06-15`: the em dash
        is dropped and both of its spaces still become hyphens. Collapsing runs
        of spaces would validate against a slug GitHub never mints."""
        assert self._anchors(
            tmp_path, "## Segments tranche 5h3 — 2026-06-15",
            "segments-tranche-5h3--2026-06-15",
        ) == []
        assert self._anchors(
            tmp_path, "## Segments tranche 5h3 — 2026-06-15",
            "segments-tranche-5h3-2026-06-15",
        ) == ["AGENTS.md -> docs/GUIDE.md#segments-tranche-5h3-2026-06-15"]

    def test_a_heading_link_slugs_on_its_text(self, tmp_path: Path):
        assert self._anchors(
            tmp_path, "## See [the rubric](keep-cut-rubric.md)", "see-the-rubric"
        ) == []

    def test_headings_inside_fences_do_not_count(self, tmp_path: Path):
        """A `# comment` in a bash fence otherwise manufactures an anchor that
        masks a real miss — and this cohort's docs are full of bash fences."""
        repo = _repo(tmp_path, "# P\n\n[l](docs/GUIDE.md#cleanup)\n")
        (repo / "docs" / "GUIDE.md").write_text(
            "# G\n\n```bash\n# cleanup\nrm -rf x\n```\n\n## Real\n"
        )
        data = _measure(repo)
        assert data["links"]["dead_anchors"] == [
            "AGENTS.md -> docs/GUIDE.md#cleanup"
        ]

    def test_headings_in_an_indented_code_block_do_not_count(self, tmp_path: Path):
        """Four columns of indent is a code block, fence or no fence."""
        repo = _repo(tmp_path, "# P\n\n[l](docs/GUIDE.md#cleanup)\n")
        (repo / "docs" / "GUIDE.md").write_text(
            "# G\n\ntext:\n\n    # cleanup\n    rm -rf x\n\n## Real\n"
        )
        assert _measure(repo)["links"]["dead_anchors"] == [
            "AGENTS.md -> docs/GUIDE.md#cleanup"
        ]

    def test_a_heading_after_a_fence_still_counts(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\n[l](docs/GUIDE.md#real)\n")
        (repo / "docs" / "GUIDE.md").write_text(
            "# G\n\n```bash\n# cleanup\n```\n\n## Real\n"
        )
        assert _measure(repo)["links"]["dead_anchors"] == []

    def test_duplicates_are_numbered_per_file(self, tmp_path: Path):
        """A split moves repeated headings into separate files, so a global
        `php-layers-2` becomes a per-file `php-layers`. The suffix is computed
        over the destination file, never over the pre-split document."""
        repo = _repo(
            tmp_path,
            "# P\n\n[a](docs/GUIDE.md#php-layers)\n"
            "[b](docs/GUIDE.md#php-layers-1)\n"
            "[c](docs/GUIDE.md#php-layers-2)\n"
            "[d](docs/OTHER.md#php-layers)\n",
        )
        (repo / "docs" / "GUIDE.md").write_text(
            "# G\n\n### PHP layers\n\nx\n\n### PHP layers\n\ny\n"
        )
        (repo / "docs" / "OTHER.md").write_text("# O\n\n### PHP layers\n\nz\n")
        assert _measure(repo)["links"]["dead_anchors"] == [
            "AGENTS.md -> docs/GUIDE.md#php-layers-2"
        ]


class TestProseGuardAppliesToFragments:
    """Targets holding `<`, `>`, `*` or a comma-space are prose in link clothing.
    A fragment shaped that way is dropped, and the path around it is still
    checked — reporting prose as a defect trains the reader to ignore the list."""

    @pytest.mark.parametrize("fragment", ["<name>", "a*b", "one, two"])
    def test_a_prose_fragment_is_dropped(self, tmp_path: Path, fragment: str):
        repo = _repo(tmp_path, f"# P\n\n[l](docs/GUIDE.md#{fragment})\n")
        (repo / "docs" / "GUIDE.md").write_text("# G\n\n## H\n")
        data = _measure(repo)
        assert data["links"]["dead_anchors"] == []
        assert data["links"]["dead"] == []

    def test_a_prose_path_is_still_dropped_whole(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\n[l](references/<name>.md#h)\n")
        data = _measure(repo)
        assert data["links"]["dead"] == []
        assert data["links"]["dead_anchors"] == []


class TestArchivalSubtreesAreScannedAsSources:
    """A dated plan pointing into a live doc is navigation, and it goes stale the
    same way — so archival docs are scanned as *sources* even though they are
    excluded from the doc inventory."""

    def _repo_with_plan(self, tmp_path: Path, plan_body: str) -> Path:
        repo = _repo(tmp_path, "# P\n\n[g](docs/GUIDE.md)\n")
        (repo / "docs" / "GUIDE.md").write_text("# G\n\n## Kept\n")
        (repo / "docs" / "plans").mkdir()
        (repo / "docs" / "plans" / "2026-01-01-old.md").write_text(plan_body)
        return repo

    def test_an_archival_source_reports_its_anchor_miss(self, tmp_path: Path):
        repo = self._repo_with_plan(tmp_path, "# Plan\n\n[g](../GUIDE.md#gone)\n")
        data = _measure(repo)
        assert data["links"]["dead_anchors"] == [
            "docs/plans/2026-01-01-old.md -> docs/GUIDE.md#gone"
        ]

    def test_an_archival_sources_dead_path_is_still_not_reported(self, tmp_path: Path):
        """Only the anchor half changes. A stale *path* inside a dated snapshot
        is a correct historical record, and reporting it buries the live signal."""
        repo = self._repo_with_plan(tmp_path, "# Plan\n\n[m](../MISSING.md)\n")
        data = _measure(repo)
        assert data["links"]["dead"] == []
        assert data["links"]["dead_anchors"] == []

    def test_archival_docs_stay_out_of_the_inventory(self, tmp_path: Path):
        repo = self._repo_with_plan(tmp_path, "# Plan\n\n[g](../GUIDE.md#kept)\n")
        data = _measure(repo)
        assert [d["path"] for d in data["docs"]] == ["docs/GUIDE.md"]
        assert data["totals"]["archival_skipped"] == 1

    def test_no_archival_scan_when_archival_is_disabled(self, tmp_path: Path):
        """With `--archival ""` the plan is a live doc, traversed by the ordinary
        walk — the miss is reported once, not twice."""
        repo = self._repo_with_plan(tmp_path, "# Plan\n\n[g](../GUIDE.md#gone)\n")
        data = _measure(repo, "--archival", "")
        assert data["links"]["dead_anchors"] == []
        assert data["links"]["orphans"] == ["docs/plans/2026-01-01-old.md"]
