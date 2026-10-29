"""Every `verify-facts.sh` row has five fields, whatever the doc holds (#462).

The header promises `verdict<TAB>class<TAB>location<TAB>claim<TAB>evidence`.
`check_paths` excluded `[ <>*$|(){}]` from a backticked path, and a tab is not
in that set, so `` `src/a<TAB>b.py` `` was printed with the tab intact and its
row split into six. A consumer holding rows to five fields refuses the whole
file over one row, which #438's `stale-issue-prose.sh` did until CR 422.

Two layers: `check_paths` excludes any whitespace, so a token holding a tab or
a CR is prose, not a path; and `emit()` folds a tab, CR or newline in any
field to a space, as `check_commands` already did for its claims, so no other
class can break the row either (a link target holding a tab did too).
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
VERIFY = ROOT / "skills" / "curating-context" / "scripts" / "verify-facts.sh"


def _clean_env() -> dict:
    """STYLE.md § 'A repo-creating git command must scrub GIT_DIR'."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _rows(tmp_path: Path, policy: bytes) -> list[str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "init", "-q"],
        check=True,
        capture_output=True,
        env=_clean_env(),
    )
    (repo / "AGENTS.md").write_bytes(policy)
    r = subprocess.run(
        ["bash", str(VERIFY)],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=_clean_env(),
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


class TestEveryRowHasFiveFields:
    def test_a_backticked_path_holding_a_tab(self, tmp_path: Path):
        """The issue's measurement: six fields before the fix."""
        rows = _rows(tmp_path, b"see `src/a\tb.py` and `src/c.py`\n")
        assert rows, "the fixture must produce rows"
        assert all(len(r.split("\t")) == 5 for r in rows), rows
        assert not any("a\tb.py" in r or "a b.py" in r for r in rows), rows
        assert any(r.split("\t")[3] == "src/c.py" for r in rows), rows

    def test_a_backticked_path_holding_a_cr(self, tmp_path: Path):
        rows = _rows(tmp_path, b"see `src/a\rb.py` and `src/c.py`\n")
        assert all(len(r.split("\t")) == 5 for r in rows), rows
        assert not any("\r" in r for r in rows), rows
        assert not any("a\rb.py" in r or "a b.py" in r for r in rows), rows

    def test_a_link_target_holding_a_tab(self, tmp_path: Path):
        """Not a path claim at all, so only emit()'s backstop holds it."""
        rows = _rows(tmp_path, b"see [the doc](docs/a\tb.md)\n")
        links = [r for r in rows if r.split("\t")[1:2] == ["link"]]
        assert links, rows
        assert all(len(r.split("\t")) == 5 for r in rows), rows
        assert links[0].split("\t")[3] == "docs/a b.md", rows
