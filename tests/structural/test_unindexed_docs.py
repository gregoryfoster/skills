"""A doc reached only through another doc is linked, not indexed (#274).

#274 asked whether the `## Detail Docs` index could nest — list a child doc
under its parent instead of on a line of its own — and whether `docs_orphaned`
would still work if it did. It would: `measure-context.sh` computes reachability
transitively, so a doc linked only from its parent is not an orphan. Four
cohort members already rely on that for 67 of their 258 live docs.

That is also why nesting was not adopted. A routing probe found such a doc 1
time in 24 where a line of its own was found 13 times, and a doc whose only
policy-file line was removed fell from 12 in 12 to 2 in 12: an agent routes by
the policy file's words, not by the link graph. The gate cannot see that loss —
it counts the doc linked — so the measurement grew a second list,
`links.unindexed`, for live docs a chain reaches that the policy file never
links itself. The measurements are in
`skills/curating-context/references/cohort-patterns.md`.

These tests pin both halves: reachability stays transitive (what the orphan
gate needs), and a doc reached only through another doc is reported as
unindexed rather than passing as indexed. Neither pin existed — every earlier
reachability test used a doc the policy file links directly.

No API calls required.
"""

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "skills" / "curating-context" / "scripts"
MEASURE = SCRIPTS / "measure-context.sh"
RECORD = SCRIPTS / "record-telemetry.sh"


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for key in (
        "CONTEXT_BUDGET",
        "CONTEXT_DOC_BUDGET",
        "CONTEXT_DOCS_DIR",
        "ANTHROPIC_API_KEY",
    ):
        env.pop(key, None)
    return env


def _repo(tmp_path: Path, policy: str, docs: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, env=_clean_env())
    (repo / "AGENTS.md").write_text(policy)
    for rel, text in docs.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(MEASURE), "--no-write", "--no-env-file", *args],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=60,
    )


def _measure(repo: Path, *args: str) -> dict:
    result = _run(repo, *args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _linked(data: dict) -> dict[str, bool]:
    return {doc["path"]: doc["linked"] for doc in data["docs"]}


INDEX = "# P\n\n## Detail Docs\n\n- [docs/STORAGE.md](docs/STORAGE.md) — storage\n"
PARENT = (
    "# S\n\nSplit out of this doc:\n\n- [STORAGE_VARS.md](STORAGE_VARS.md) — Vars\n"
)


class TestReachabilityStaysTransitive:
    """What `docs_orphaned` needs, and what #274's first question asked."""

    def test_a_doc_linked_only_by_its_parent_is_not_an_orphan(self, tmp_path: Path):
        repo = _repo(
            tmp_path,
            INDEX,
            {"docs/STORAGE.md": PARENT, "docs/STORAGE_VARS.md": "# V\n"},
        )
        data = _measure(repo)
        assert data["links"]["orphans"] == []
        assert _linked(data)["docs/STORAGE_VARS.md"] is True
        # Reached, not referenced: `refs` stays the policy file's own links.
        assert data["links"]["refs"] == ["docs/STORAGE.md"]

    def test_a_subdirectory_behind_a_contents_table_is_reached(self, tmp_path: Path):
        """The layout `cannabis.observer-wordpress` converged on for its split
        `API.md`: a contents table over `docs/api/*.md`, each link resolved
        against the parent rather than the repo root."""
        repo = _repo(
            tmp_path,
            "# P\n\n## Detail Docs\n\n- [docs/API.md](docs/API.md) — REST API\n",
            {
                "docs/API.md": "# API\n\n| Part | Covers |\n|---|---|\n"
                "| [Auth](api/auth.md) | tokens |\n| [Reads](api/reads.md) | lists |\n",
                "docs/api/auth.md": "# Auth\n",
                "docs/api/reads.md": "# Reads\n",
            },
        )
        data = _measure(repo)
        assert data["links"]["orphans"] == []
        assert data["links"]["dead"] == []

    def test_a_grandchild_is_reached(self, tmp_path: Path):
        repo = _repo(
            tmp_path,
            INDEX,
            {
                "docs/STORAGE.md": "# S\n\n- [STORAGE_VARS.md](STORAGE_VARS.md)\n",
                "docs/STORAGE_VARS.md": "# V\n\n- [VARS_ROSTER.md](VARS_ROSTER.md)\n",
                "docs/VARS_ROSTER.md": "# R\n",
            },
        )
        assert _measure(repo)["links"]["orphans"] == []

    def test_a_subtree_whose_parent_line_went_is_orphaned_whole(self, tmp_path: Path):
        """The failure the gate must still see: a run drops the parent's index
        line. The parent links the child, but a link from an unreachable doc
        reaches nothing, so both are orphans — the child is not vouched for by
        a parent nobody can find."""
        repo = _repo(
            tmp_path,
            "# P\n\n## Detail Docs\n\n- [docs/STYLE.md](docs/STYLE.md) — style\n",
            {
                "docs/STYLE.md": "# Style\n",
                "docs/STORAGE.md": "# S\n\n- [STORAGE_VARS.md](STORAGE_VARS.md)\n",
                "docs/STORAGE_VARS.md": "# V\n\nFor the resolver, see [STORAGE.md](STORAGE.md).\n",
            },
        )
        data = _measure(repo)
        assert data["links"]["orphans"] == ["docs/STORAGE.md", "docs/STORAGE_VARS.md"]
        assert data["links"]["unindexed"] == [], "an orphan is not also unindexed"

    def test_a_pointer_inside_a_code_fence_reaches_nothing(self, tmp_path: Path):
        """A contents line quoted in a fence renders as text, not a link."""
        repo = _repo(
            tmp_path,
            INDEX,
            {
                "docs/STORAGE.md": "# S\n\n```markdown\n"
                "- [STORAGE_VARS.md](STORAGE_VARS.md)\n```\n",
                "docs/STORAGE_VARS.md": "# V\n",
            },
        )
        assert _measure(repo)["links"]["orphans"] == ["docs/STORAGE_VARS.md"]


class TestReachedIsNotIndexed:
    def test_a_doc_reached_only_through_its_parent_is_unindexed(self, tmp_path: Path):
        repo = _repo(
            tmp_path,
            INDEX,
            {"docs/STORAGE.md": PARENT, "docs/STORAGE_VARS.md": "# V\n"},
        )
        assert _measure(repo)["links"]["unindexed"] == ["docs/STORAGE_VARS.md"]

    def test_every_part_behind_a_contents_table_is_unindexed(self, tmp_path: Path):
        """The production shape the probe measured at 1 in 24."""
        repo = _repo(
            tmp_path,
            "# P\n\n## Detail Docs\n\n- [docs/API.md](docs/API.md) — REST API\n",
            {
                "docs/API.md": "# API\n\n| [Auth](api/auth.md) | tokens |\n"
                "| [Reads](api/reads.md) | lists |\n",
                "docs/api/auth.md": "# Auth\n",
                "docs/api/reads.md": "# Reads\n",
            },
        )
        assert _measure(repo)["links"]["unindexed"] == [
            "docs/api/auth.md",
            "docs/api/reads.md",
        ]

    def test_a_link_anywhere_in_the_policy_file_indexes_it(self, tmp_path: Path):
        """Not only the index section: a pointer inline in another section
        routes too — the probe's `STORAGE_VARS.md` stayed 12 in 12 with its
        index line gone, because a Conventions paragraph still named it."""
        repo = _repo(
            tmp_path,
            "# P\n\n## Conventions\n\nVars classes: [docs/STORAGE_VARS.md](docs/STORAGE_VARS.md).\n\n"
            + INDEX.removeprefix("# P\n\n"),
            {"docs/STORAGE.md": PARENT, "docs/STORAGE_VARS.md": "# V\n"},
        )
        assert _measure(repo)["links"]["unindexed"] == []

    def test_an_indented_sub_bullet_indexes_it(self, tmp_path: Path):
        """The nested shape #274 proposed is still a policy-file link: the
        indentation is list structure, not code."""
        repo = _repo(
            tmp_path,
            INDEX + "  - [docs/STORAGE_VARS.md](docs/STORAGE_VARS.md) — Vars\n",
            {"docs/STORAGE.md": "# S\n", "docs/STORAGE_VARS.md": "# V\n"},
        )
        data = _measure(repo)
        assert data["links"]["unindexed"] == []
        assert data["links"]["refs"] == ["docs/STORAGE.md", "docs/STORAGE_VARS.md"]

    def test_a_policy_file_inside_the_docs_dir_is_not_its_own_gap(self, tmp_path: Path):
        """CR 1. With the policy file under `--docs-dir` the inventory held
        it, reached and never linked by itself — so it was reported unindexed,
        and Phase 5 would have asked a run to index the policy file in itself.

        The property, not the path to it (CR 9). CR 1 kept the policy out with
        a term in the `unindexed` filter; #277 keeps it out of the inventory,
        dropped that term, and this passes unchanged. What the inventory holds
        is `test_policy_inside_docs_dir.py`'s to pin."""
        repo = _repo(
            tmp_path,
            "# unused root policy\n",
            {"docs/AGENTS.md": "# P\n\n- [A.md](A.md) — a\n", "docs/A.md": "# A\n"},
        )
        data = _measure(repo, "--file", "docs/AGENTS.md", "--docs-dir", "docs")
        assert data["links"]["unindexed"] == []

    def test_a_policy_file_linking_nothing_reaches_nothing(self, tmp_path: Path):
        """The boundary: every doc is an orphan, so none is unindexed."""
        repo = _repo(tmp_path, "# P\n\nNo links.\n", {"docs/A.md": "# A\n"})
        data = _measure(repo)
        assert data["links"]["refs"] == []
        assert data["links"]["orphans"] == ["docs/A.md"]
        assert data["links"]["unindexed"] == []

    def test_the_count_reaches_the_ledger_row(self, tmp_path: Path):
        repo = _repo(
            tmp_path,
            INDEX,
            {"docs/STORAGE.md": PARENT, "docs/STORAGE_VARS.md": "# V\n"},
        )
        measured = _run(repo)
        assert measured.returncode == 0, measured.stderr
        recorded = subprocess.run(
            ["bash", str(RECORD), "--dry-run"],
            input=measured.stdout,
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=_clean_env(),
            timeout=30,
        )
        assert recorded.returncode == 0, recorded.stdout + recorded.stderr
        line = [x for x in recorded.stdout.splitlines() if x.strip().startswith("{")][
            -1
        ]
        row = json.loads(line)
        assert row["docs_unindexed"] == 1, row
        assert row["docs_orphaned"] == 0, row

    def test_a_payload_predating_the_field_records_null(self, tmp_path: Path):
        """Null, not 0: a measurement that never looked has not shown the index
        complete — the line `links_dead_anchors` already draws."""
        repo = _repo(tmp_path, INDEX, {"docs/STORAGE.md": "# S\n"})
        payload = _measure(repo)
        del payload["links"]["unindexed"]
        recorded = subprocess.run(
            ["bash", str(RECORD), "--dry-run"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=_clean_env(),
            timeout=30,
        )
        assert recorded.returncode == 0, recorded.stdout + recorded.stderr
        line = [x for x in recorded.stdout.splitlines() if x.strip().startswith("{")][
            -1
        ]
        assert json.loads(line)["docs_unindexed"] is None
