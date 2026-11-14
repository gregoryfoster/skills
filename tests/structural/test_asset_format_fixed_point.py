"""Python assets format the same at a consumer's line length (#643, #601).

A skill's `assets/**/*.py` is copied into a consumer repo and runs there under
that repo's ruff, and the cohort formats at `line-length = 100`
(init-project-fastapi's profiles both set it) while this repo formats at
ruff's default 88. A statement whose joined form lands between 89 and 100
columns is split here and joined there, so a fresh copy failed the
consumer's `ruff format --check .` until pre-commit rewrote it on the first
commit, and from then on every "is my copy current?" diff carried formatting
noise that hid real upstream changes (#601, from a power-map adoption).

The fix is for each asset to be a fixed point at both lengths: `ruff format`
at 88 and at 100 leave it byte for byte alone. 88 is already held by
`test_python_lint.py`'s repo-wide `ruff format --check .`; this file holds
100, with `--isolated` so the repo's own config cannot stand in for the
consumer's. When it fails, rewrite the statement rather than reformat the
file at 100, which would break 88: a magic trailing comma where the construct
takes one, an intermediate name, an early return, or a message that fits in
88 or stays split past 100. A `# fmt:` pragma is the wrong fix, since the
consumer's copy would carry it.

The ruff build is `test_python_lint.py`'s own pin and probe, imported rather
than restated, because `ruff format`'s output is version-defined and two
pins could drift apart. Absent or wrong-version ruff is the same loud skip
there, and `RUFF_REQUIRED=1` makes it a failure.

No API calls.
"""

import re
import subprocess
import warnings
from pathlib import Path

import pytest

from tests.structural import test_python_lint as lint
from tests.utils.skill_loader import SKILLS_DIR

REPO_ROOT = SKILLS_DIR.parent
CONSUMER_LINE_LENGTH = 100

# Every Python asset, found by glob so a new one is held the day it lands.
ASSETS = sorted(SKILLS_DIR.glob("*/assets/**/*.py"))

# An asset whose bytes a consumer checks against a sha256 marker is copied
# verbatim and excluded from the consumer's ruff, so its formatting there is
# never in question, and reformatting it here would mean a version bump of
# everything the marker pins. Each entry must still exist and still carry a
# marker line (test_every_exemption_still_has_its_reason), so an exemption
# cannot outlive its reason.
EXEMPT = {
    "skills/deploying-releases/assets/co-pypi/co_pypi_token.py": (
        "the minter: test_co_pypi.py checks its sha256 marker, and has the "
        "consumer's [tool.ruff] exclude it"
    ),
}

# A marker line as deploying-releases writes them, e.g.
# `# deploying-releases-co-pypi-sha256: <64 hex>`. Anchored to a whole comment
# line, so a test that only names the marker in a string does not count.
_MARKER_RE = re.compile(r"^# [a-z0-9-]+-sha256: [0-9a-f]{64}$", re.MULTILINE)


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _ruff_problem() -> str | None:
    problem = lint._ruff_problem()
    if problem is None:
        return None
    return f"The asset fixed-point check (#643) DID NOT RUN either. {problem}"


def _require_ruff() -> str:
    problem = _ruff_problem()
    if problem is not None:
        if lint._RUFF_REQUIRED:
            pytest.fail(problem)
        pytest.skip(problem)
    return lint._RUFF_BIN


@pytest.mark.parametrize(
    "asset",
    [pytest.param(p, id=_rel(p)) for p in ASSETS if _rel(p) not in EXEMPT],
)
def test_asset_is_a_fixed_point_at_the_consumers_line_length(asset: Path) -> None:
    ruff = _require_ruff()
    result = subprocess.run(
        [
            ruff,
            "format",
            "--isolated",
            "--line-length",
            str(CONSUMER_LINE_LENGTH),
            "--diff",
            str(asset),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"{_rel(asset)} would be reformatted at line-length "
        f"{CONSUMER_LINE_LENGTH}, so a consumer's copy fails `ruff format "
        "--check` until its first commit rewrites it. Make each statement "
        "below a fixed point at both 88 and 100 (see #643 and this file's "
        f"docstring), not reformatted at 100:\n{result.stdout}{result.stderr}"
    )


def test_ruff_is_available() -> None:
    """Warn once, so a skipped gate shows in the summary, not just among skips."""
    problem = _ruff_problem()
    if problem is not None:
        warnings.warn(problem, UserWarning, stacklevel=2)
    _require_ruff()


def test_the_glob_finds_the_assets() -> None:
    """An empty glob would parametrize nothing and pass."""
    assert ASSETS, f"no Python assets under {SKILLS_DIR}/*/assets/"


@pytest.mark.parametrize("rel", sorted(EXEMPT))
def test_every_exemption_still_has_its_reason(rel: str) -> None:
    path = REPO_ROOT / rel
    assert path in ASSETS, f"{rel} is exempt but is no Python asset; drop its entry"
    assert _MARKER_RE.search(path.read_text()), (
        f"{rel} is exempt because a sha256 marker covers its bytes, but it has "
        "no marker line any more; drop the exemption and make it a fixed point"
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        (f"# deploying-releases-co-pypi-sha256: {'a' * 64}\n", True),
        (f"x = 1\n# deploying-releases-core-sha256: {'0' * 64}\n", True),
        ('MARK_SHA = "# deploying-releases-co-pypi-sha256: "\n', False),
        ("# deploying-releases-co-pypi-sha256: abc\n", False),
    ],
)
def test_the_marker_check_wants_a_marker_line(text: str, expected: bool) -> None:
    """A file that only names the marker, as test_co_pypi.py does, is not exempt."""
    assert bool(_MARKER_RE.search(text)) is expected
