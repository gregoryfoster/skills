"""The `pr` render's PR discovery is written once (#683, finding 3).

The take-in step and the commit step each carried the same block, about 20
lines: `gh pr list`, the `ls-remote` tip, the OPEN/ENDED loop and the
keep-the-branch condition (CannObserv/watcher#445's review). A fix to one had
to be repeated by hand in the other, and two copies that drifted would choose
different PRs. It is now one fragment in `install-cadence.sh`, rendered into
both steps. Both still run it: a PR can merge between the two.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.structural.test_cadence_merge_mode import (
    COMMIT_STEP,
    INSTALL_CADENCE,
    TAKE_STEP,
    _render,
    _steps,
)

BEGIN = "# >>> which measurement PR (#683)"
END = "# <<< which measurement PR"


def _fragment(script: str) -> list[str]:
    lines = script.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.strip() == BEGIN]
    ends = [i for i, ln in enumerate(lines) if ln.strip() == END]
    assert len(starts) == 1 and len(ends) == 1, "one discovery per step"
    block = lines[starts[0] : ends[0] + 1]
    indent = len(block[0]) - len(block[0].lstrip())
    assert all(not ln[:indent].strip() for ln in block), "a line left the fragment"
    return [ln[indent:] for ln in block]


class TestTheDiscoveryIsWrittenOnce:
    def test_both_steps_render_the_same_fragment(self, tmp_path: Path):
        steps = _steps(_render(tmp_path, "pr\n"))
        take, push = _fragment(steps[TAKE_STEP]), _fragment(steps[COMMIT_STEP])
        assert take == push
        assert any("isCrossRepository" in ln for ln in take)

    def test_the_installer_writes_it_once(self):
        text = INSTALL_CADENCE.read_text()
        assert len(re.findall(r"PRS=\$\(gh pr list", text)) == 1
        assert text.count(BEGIN) == 1
