"""One archival list, read one way, by every surface that reads it (#465).

`_context-lib.sh` resolves `CTX_ARCHIVAL` (else its default), and the write
guard, `check-seams.sh` and `stale-issue-prose.sh` read it. `measure-context.sh`,
which runs Phase 1, kept its own copy of the default and took only
`--archival`, so `CTX_ARCHIVAL=history` moved every surface but the one that
measures the budget. Now the flag wins, then `CTX_ARCHIVAL`, then the library's
default — the order `--docs-dir` / `CONTEXT_DOCS_DIR` already follows — and an
empty `CTX_ARCHIVAL` means the default there as it does in the library, while
`--archival ""` still means "measure everything".

#463 pinned the code copies of the default. The prose copies — help text,
docstrings, a reference doc — were not, and two spell it comma-separated, so a
grep for the default string missed them. The scan below finds every spelling
under the skill and holds each to the library's default.
"""

import re
import subprocess
from pathlib import Path

from .test_context_anchors import _clean_env, _measure, _repo

ROOT = Path(__file__).resolve().parent.parent.parent
SKILL = ROOT / "skills" / "curating-context"
LIB = SKILL / "scripts" / "_context-lib.sh"
MEASURE = SKILL / "scripts" / "measure-context.sh"


def _default() -> list[str]:
    m = re.search(r'^CTX_ARCHIVAL_DEFAULT="([^"]*)"$', LIB.read_text(), re.M)
    assert m, "the library's default moved"
    return m.group(1).split()


def _two_trees(tmp_path: Path) -> Path:
    repo = _repo(tmp_path, "# P\n\n- [g](docs/GUIDE.md)\n")
    (repo / "docs" / "GUIDE.md").write_text("# G\n")
    for sub in ("history", "plans"):
        (repo / "docs" / sub).mkdir()
        (repo / "docs" / sub / "old.md").write_text(f"# {sub}\n")
    return repo


def _live(data: dict) -> list[str]:
    return sorted(d["path"] for d in data["docs"])


class TestMeasureContextHonoursCtxArchival:
    def test_the_env_var_moves_phase_1(self, tmp_path: Path):
        """The issue's case: a repo whose archive lives in docs/history/."""
        env = {**_clean_env(), "CTX_ARCHIVAL": "history"}
        data = _measure(_two_trees(tmp_path), env=env)
        assert _live(data) == ["docs/GUIDE.md", "docs/plans/old.md"], data["docs"]
        assert data["totals"]["archival_skipped"] == 1

    def test_the_flag_wins_over_the_env_var(self, tmp_path: Path):
        env = {**_clean_env(), "CTX_ARCHIVAL": "history"}
        data = _measure(_two_trees(tmp_path), "--archival", "plans", env=env)
        assert _live(data) == ["docs/GUIDE.md", "docs/history/old.md"]

    def test_an_empty_flag_still_measures_everything(self, tmp_path: Path):
        env = {**_clean_env(), "CTX_ARCHIVAL": "history"}
        data = _measure(_two_trees(tmp_path), "--archival", "", env=env)
        assert data["totals"]["archival_skipped"] == 0

    def test_unset_is_the_default(self, tmp_path: Path):
        env = _clean_env()
        env.pop("CTX_ARCHIVAL", None)
        data = _measure(_two_trees(tmp_path), env=env)
        assert _live(data) == ["docs/GUIDE.md", "docs/history/old.md"]

    def test_an_empty_env_var_is_the_default_as_in_the_library(self, tmp_path: Path):
        """`${CTX_ARCHIVAL:-default}`: the continuous surfaces read an empty
        value as unset, so Phase 1 must too or the two disagree again."""
        env = {**_clean_env(), "CTX_ARCHIVAL": ""}
        data = _measure(_two_trees(tmp_path), env=env)
        assert _live(data) == ["docs/GUIDE.md", "docs/history/old.md"]

    def test_help_names_the_env_var(self):
        r = subprocess.run(
            ["bash", str(MEASURE), "--help"], capture_output=True, text=True
        )
        assert "CTX_ARCHIVAL" in r.stdout.split("--archival", 1)[1].split("--gate")[0]


# Every spelling of the list: `plans specs …` or `plans, specs, …`, wrapped
# across lines or not, inside a shell or Python comment or not.
_LIST = re.compile(r"\bplans,?\s+specs\b(?:,?\s+(?:and\s+)?[a-z]+)*")


def _flatten(text: str) -> str:
    """Lines joined with their comment markers and indentation dropped, so a
    list wrapped inside a `#` comment reads as one run of words."""
    return " ".join(re.sub(r"^\s*#*\s*", "", line) for line in text.splitlines())


def _copies() -> dict[str, list[list[str]]]:
    found = {}
    for path in sorted(SKILL.rglob("*")):
        if not path.is_file() or path.suffix not in {".sh", ".py", ".md"}:
            continue
        lists = [
            re.findall(r"[a-z]+", m.group())
            for m in _LIST.finditer(_flatten(path.read_text()))
        ]
        if lists:
            found[str(path.relative_to(ROOT))] = lists
    return found


class TestEveryCopyOfTheListIsTheDefault:
    def test_every_copy_matches_the_library(self):
        default = _default()
        drifted = {
            path: words
            for path, lists in _copies().items()
            for words in lists
            # Exact: a list ends at punctuation, so a copy whose next words
            # run on as prose reads as drift, and wants a comma or a bracket.
            if [w for w in words if w != "and"] != default
        }
        assert not drifted, (default, drifted)

    def test_the_scan_sees_the_known_copies(self):
        """So the check above can't pass by finding nothing. The inventory at
        efa94991, the comma-separated help-text copies included."""
        copies = _copies()
        for rel in (
            "references/fact-verification.md",
            "scripts/_archival.py",
            "scripts/_bare_digit_counts.py",
            "scripts/_context-lib.sh",
            "scripts/_stale_issue_prose.py",
            "scripts/_tightened_rules.py",
            "scripts/context-budget-guard.sh",
            "scripts/context-delta.sh",
            "scripts/measure-context.sh",
        ):
            assert f"skills/curating-context/{rel}" in copies, sorted(copies)
