"""The gate's decision table is whole: every row once, in order (#537).

`skills/shipping-work/references/gate-topology.md` holds one decision per
check, and the parity harness cites its rows by number. A splice once fused
row 20 with a copy of row 23 and dropped row 20's ending, and the table still
rendered — so this reads the rows the way a reader does, one per line, and
checks the sequence.

No API calls.
"""

import re
from pathlib import Path

TABLE = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "shipping-work"
    / "references"
    / "gate-topology.md"
)

EXPECTED_ROWS = ["1", "1b"] + [str(n) for n in range(2, 25)]


def _rows() -> list[str]:
    return re.findall(r"^\| (\d+b?) \|", TABLE.read_text(), re.M)


def test_every_row_once_in_order():
    assert _rows() == EXPECTED_ROWS


def test_no_row_runs_into_another():
    """A row that swallowed the next one still starts a line; its cells give
    it away: a decision row has exactly four."""
    for line in TABLE.read_text().splitlines():
        if re.match(r"^\| \d+b? \|", line):
            cells = [c for c in re.split(r"(?<!\\)\|", line)[1:-1]]
            assert len(cells) == 4, f"not a four-cell row:\n{line[:200]}"
