"""The default pin path is written in three files; they must agree.

`init-socraticode` grew a pinned pre-install in
[#295](https://github.com/gregoryfoster/skills/issues/295), and its default
location — `~/.socraticode/pin` — is spelled independently in three places that
no import or symlink binds together:

* `scripts/mcp-driver.mjs`, as `pinDir()`'s fallback, which decides where the
  driver actually looks;
* `scripts/preflight.sh`, as `SC_PIN_DIR`'s fallback, which decides which build
  the Node 26 gate judges and which path the low-memory hint prints;
* `references/host-memory.md`, in the `npm install --prefix` line an
  operator copies (in `troubleshooting.md` until
  [#307](https://github.com/gregoryfoster/skills/issues/307) moved row U's
  procedures into their own reference).

Drift is silent and asymmetric: an operator installs where the doc says, the
driver looks somewhere else, and the result is not an error but a host that
quietly keeps installing at launch — the exact failure the pin exists to stop.
That is the shape [#234](https://github.com/gregoryfoster/skills/issues/234) and
[#209](https://github.com/gregoryfoster/skills/issues/209) already name
elsewhere in this skill: a value transcribed into a second place goes stale
without anything noticing.

The env var that overrides it is held to the same rule — three files naming two
different variables would fail in the same silent direction.
"""

import re
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "skills" / "init-socraticode"
DRIVER = SKILL / "scripts" / "mcp-driver.mjs"
PREFLIGHT = SKILL / "scripts" / "preflight.sh"
DOC = SKILL / "references" / "host-memory.md"

# The one value under test. A change here is a deliberate move of the default,
# and it must land in all three files in the same commit.
DEFAULT_TAIL = (".socraticode", "pin")
ENV_VAR = "SOCRATICODE_PIN_DIR"


@pytest.fixture(scope="module")
def sources() -> dict[str, str]:
    missing = [p.name for p in (DRIVER, PREFLIGHT, DOC) if not p.is_file()]
    if missing:
        pytest.fail(f"init-socraticode is missing {', '.join(missing)}")
    return {p.name: p.read_text(encoding="utf-8") for p in (DRIVER, PREFLIGHT, DOC)}


def test_driver_default_is_the_expected_path(sources: dict[str, str]) -> None:
    """`pinDir()` builds the default from path segments, not a literal."""
    m = re.search(
        r"function pinDir\(\)\s*\{[^}]*?joinPath\(\s*homedir\(\)\s*,\s*"
        r"'([^']+)'\s*,\s*'([^']+)'\s*\)",
        sources["mcp-driver.mjs"],
        re.S,
    )
    assert m, (
        "could not read pinDir()'s default out of mcp-driver.mjs. It is the "
        "path the driver actually searches, so this test cannot compare the "
        "other two against anything until it parses again."
    )
    assert m.groups() == DEFAULT_TAIL


def test_preflight_default_matches_the_driver(sources: dict[str, str]) -> None:
    """`SC_PIN_DIR` must fall back to the same place the driver looks."""
    m = re.search(
        rf'SC_PIN_DIR="\$\{{{ENV_VAR}:-\$HOME/([^"]+)}}"', sources["preflight.sh"]
    )
    assert m, (
        f"preflight.sh no longer sets SC_PIN_DIR from ${ENV_VAR} with a $HOME fallback"
    )
    assert m.group(1) == "/".join(DEFAULT_TAIL), (
        f"preflight.sh defaults the pin to ~/{m.group(1)} while mcp-driver.mjs "
        f"looks in ~/{'/'.join(DEFAULT_TAIL)}. The Node 26 gate would then judge "
        "a build the driver never launches."
    )


def test_the_documented_install_writes_where_the_driver_looks(
    sources: dict[str, str],
) -> None:
    """Every `npm install --prefix` in the doc targets the same default."""
    prefixes = re.findall(r"npm install --prefix (\S+)", sources[DOC.name])
    assert prefixes, (
        f"{DOC.name} no longer shows an `npm install --prefix` line. "
        "That command is how an operator creates the pin; without it the "
        "feature is undiscoverable from the docs."
    )
    expected = "~/" + "/".join(DEFAULT_TAIL)
    # A `<dir>`/`$SC_PIN_DIR` placeholder is fine — it names no competing path.
    literal = [p for p in prefixes if not p.startswith(("<", "$"))]
    assert literal, f"no concrete install path in {DOC.name} among {prefixes}"
    for got in literal:
        assert got == expected, (
            f"{DOC.name} tells the operator to install into {got}, but "
            f"the driver looks in {expected}. Following the doc would leave the "
            "pin unused and the host still installing at every launch."
        )


def test_all_three_name_the_same_override_variable(sources: dict[str, str]) -> None:
    """One env var, or the override works in one file and not the others."""
    for name, text in sources.items():
        assert ENV_VAR in text, (
            f"{name} does not mention {ENV_VAR}. All three have to honour the "
            "same override, or moving the pin fixes one reader and breaks another."
        )
