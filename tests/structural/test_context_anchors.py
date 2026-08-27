"""Anchor resolution and per-row exactness in measure-context.sh (#120, #124, #123).

Two defects, one script, both found on real cohort runs:

- `extract_links()` stripped the `#fragment` before resolving, so a link whose
  file exists and whose heading does not was invisible. That is exactly the shape
  of the operation this skill encourages — splitting an over-budget doc moves
  headings out of a file while leaving the file in place — so the gate was blind
  precisely where the advice points. Misses are reported as `links.dead_anchors`,
  their own class, so `dead` keeps its meaning for existing consumers.
- `tokens_exact` was emitted run-wide only, so one transient `count_tokens`
  failure disowned every row in the payload. Rows now carry their own flag; the
  `policy` flag keeps its run-wide meaning.

No API calls: the exactness tests substitute a `python3` that answers without a
network.
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
MEASURE = SCRIPTS / "measure-context.sh"

POLICY_LINE = "- a policy line naming `some/path.py` and explaining why\n"


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

    def test_a_nested_shorter_fence_does_not_close_the_block(self, tmp_path: Path):
        """A ```bash example inside a ````markdown block is content, not a closer.

        A tracker keyed on the fence character alone inverts fence state for
        the whole nested span: the inner opener "closes" the outer block, a
        `# comment` in the gap mints an anchor that masks a real miss, and the
        inner closer "re-opens" it, swallowing nothing that follows. CommonMark
        closes only on a run of the same character at least as long as the
        opener (#232). Fixture files, deliberately: the repo's one 4-backtick
        document must not be pinned here.
        """
        repo = _repo(
            tmp_path,
            "# P\n\n[a](docs/GUIDE.md#leaked)\n"
            "[b](docs/GUIDE.md#swallowed)\n"
            "[c](docs/GUIDE.md#real)\n",
        )
        (repo / "docs" / "GUIDE.md").write_text(
            "# G\n\n"
            "````markdown\n"
            "```bash\n"
            "# leaked\n"
            "```\n"
            "## swallowed\n"
            "````\n\n"
            "## Real\n"
        )
        assert _measure(repo)["links"]["dead_anchors"] == [
            "AGENTS.md -> docs/GUIDE.md#leaked",
            "AGENTS.md -> docs/GUIDE.md#swallowed",
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


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="chmod 000 does not restrict root, so the unreadable file is readable",
)
class TestUncheckedLinksAreReportedHonestly:
    """`dead: []` on a file nothing could read reports the repo clean on evidence
    nobody gathered. `extract_links` records the path in `links.unchecked` so an
    empty `dead` can be read honestly (#147) — and this is the run in which that
    is observable end-to-end, which #157 claimed was impossible.

    It is observable because the two halves of that claim come apart. An
    unreadable LIVE doc is fatal: the inventory reads it, cannot, and exits 2
    (see TestUnreadableDocInTheInventory in test_context_surface.py). An
    unreadable ARCHIVAL doc is not: it is excluded from the inventory by design,
    contributes no number to defend, and is only ever read as a source of
    anchors — so the honest thing is a completed run that says which file went
    unchecked, not a refusal to measure the rest of the tree.
    """

    def _repo_with_unreadable_plan(self, tmp_path: Path) -> Path:
        repo = _repo(tmp_path, "# P\n\n[g](docs/GUIDE.md)\n[p](docs/plans/old.md)\n")
        (repo / "docs" / "GUIDE.md").write_text("# G\n\n## Kept\n")
        (repo / "docs" / "plans").mkdir()
        plan = repo / "docs" / "plans" / "old.md"
        plan.write_text("# Plan\n\n[g](../GUIDE.md#kept)\n")
        plan.chmod(0o000)
        return repo

    def test_the_run_completes_and_names_the_unchecked_file(self, tmp_path: Path):
        data = _measure(self._repo_with_unreadable_plan(tmp_path))
        assert data["links"]["unchecked"] == ["docs/plans/old.md"]

    def test_dead_is_empty_but_not_unqualified(self, tmp_path: Path):
        """The pairing is the point: `dead: []` is only readable as "clean" when
        `unchecked` is empty too."""
        data = _measure(self._repo_with_unreadable_plan(tmp_path))
        assert data["links"]["dead"] == []
        assert data["links"]["unchecked"], (
            "a file whose links nobody could read must not be folded into a "
            "clean `dead` report"
        )

    def test_a_readable_plan_leaves_unchecked_empty(self, tmp_path: Path):
        """The control: `unchecked` is populated by failure, not by archival."""
        repo = self._repo_with_unreadable_plan(tmp_path)
        (repo / "docs" / "plans" / "old.md").chmod(0o644)
        data = _measure(repo)
        assert data["links"]["unchecked"] == []
        assert data["links"]["dead"] == []


def _bin_with_real_tools(bin_dir: Path) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    for tool in ("git", "python3", "bash", "awk", "sed", "grep", "wc", "sort",
                 "find", "head", "tr", "dirname", "basename", "mktemp", "date",
                 "cat", "rm", "mkdir", "printf", "ls", "cut", "tail", "uniq"):
        real = shutil.which(tool)
        if real and not (bin_dir / tool).exists():
            (bin_dir / tool).symlink_to(real)
    return bin_dir


class TestPerRowExactness:
    """One transient count_tokens failure used to disown every row in the payload:
    a downstream gate reading a run-wide `tokens_exact: false` can only suppress
    all 29 docs, including the 28 that were counted exactly."""

    @pytest.fixture
    def env_with_selective_counter(self, tmp_path: Path) -> dict:
        """A `python3` that answers a token count for every file except FLAKY.md.

        count.py is invoked as `python3 <count.py> <file> <model>`, so the file
        under measurement is $2.
        """
        bin_dir = _bin_with_real_tools(tmp_path / "bin")
        (bin_dir / "python3").unlink()
        (bin_dir / "python3").write_text(
            "#!/bin/sh\n"
            'case "$2" in *FLAKY.md) echo "boom" >&2; exit 1 ;; esac\n'
            "echo 1000\n"
        )
        (bin_dir / "python3").chmod(0o755)
        env = _clean_env()
        env["PATH"] = str(bin_dir)
        env["ANTHROPIC_API_KEY"] = "sk-ant-test-not-used-offline"
        return env

    def _repo_with_two_docs(self, tmp_path: Path) -> Path:
        repo = _repo(tmp_path, POLICY_LINE * 50)
        (repo / "docs" / "GOOD.md").write_text("# Good\n\nbody\n")
        (repo / "docs" / "FLAKY.md").write_text("# Flaky\n\nbody\n")
        return repo

    def _rows(self, data: dict) -> dict:
        return {d["path"]: d for d in data["docs"]}

    def test_an_estimate_run_marks_every_row_inexact(self, tmp_path: Path):
        repo = self._repo_with_two_docs(tmp_path)
        data = _measure(repo)
        assert data["policy"]["tokens_exact"] is False
        assert all(d["tokens_exact"] is False for d in data["docs"]), data["docs"]

    def test_one_failure_leaves_the_other_rows_exact(
        self, tmp_path: Path, env_with_selective_counter: dict
    ):
        repo = self._repo_with_two_docs(tmp_path)
        data = _measure(repo, "--exact", env=env_with_selective_counter)
        rows = self._rows(data)
        assert rows["docs/GOOD.md"]["tokens_exact"] is True
        assert rows["docs/GOOD.md"]["tokens"] == 1000
        assert rows["docs/FLAKY.md"]["tokens_exact"] is False
        assert rows["docs/FLAKY.md"]["tokens"] != 1000

    def test_the_run_wide_flag_keeps_its_meaning(
        self, tmp_path: Path, env_with_selective_counter: dict
    ):
        """Backward compatibility: `policy.tokens_exact` is still true only when
        every count in the run was exact."""
        repo = self._repo_with_two_docs(tmp_path)
        data = _measure(repo, "--exact", env=env_with_selective_counter)
        assert data["policy"]["tokens_exact"] is False
        assert any(d["tokens_exact"] is True for d in data["docs"])

    def test_a_fully_exact_run_marks_every_row_exact(
        self, tmp_path: Path, env_with_selective_counter: dict
    ):
        repo = _repo(tmp_path, POLICY_LINE * 50)
        (repo / "docs" / "GOOD.md").write_text("# Good\n\nbody\n")
        data = _measure(repo, "--exact", env=env_with_selective_counter)
        assert data["policy"]["tokens_exact"] is True
        assert [d["tokens_exact"] for d in data["docs"]] == [True]
