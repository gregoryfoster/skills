"""The release deploy's contract, held in this repo (deploying-releases, #372).

Copied in by deploying-releases' fresh mode; the repo owns it after. It reads
PROJECT from scripts/deploy_hooks.sh, so it needs no editing.

- scripts/deploy.sh is the installed core, unedited: its sha256 marker matches.
  A change belongs in scripts/deploy_hooks.sh, or upstream.
- scripts/deploy_hooks.sh parses, sets PROJECT, and defines no function but the
  six hooks (a helper of its own is a hook's inner function, or a name the core
  may one day take).
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "scripts" / "deploy.sh"
HOOKS = REPO / "scripts" / "deploy_hooks.sh"
MARK_SHA = "# deploying-releases-core-sha256: "
HOOK_NAMES = {
    "build_extra",
    "post_build_check",
    "pre_switch_check",
    "migrate",
    "verify",
    "post_verify",
}


def sourced(expression: str) -> str:
    """What bash prints after sourcing the hooks file."""
    result = subprocess.run(
        ["bash", "-c", f'source "$1"; {expression}', "_", str(HOOKS)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_the_core_is_unedited():
    text = CORE.read_text()
    match = re.search(rf"^{re.escape(MARK_SHA)}(\w+)$", text, flags=re.M)
    assert match, (
        "scripts/deploy.sh has no deploying-releases marker: reinstall it with install.sh"
    )
    zeroed = text.replace(match.group(0), MARK_SHA + "0" * 64, 1)
    assert hashlib.sha256(zeroed.encode()).hexdigest() == match.group(1), (
        "scripts/deploy.sh was edited by hand. Put the change in scripts/deploy_hooks.sh "
        "(or raise it on gregoryfoster/skills), then reinstall the core with install.sh"
    )


def test_the_core_is_executable():
    assert CORE.stat().st_mode & 0o111


def test_the_hooks_parse_and_name_the_project():
    project = sourced('printf %s "$PROJECT"')
    assert re.fullmatch(r"[a-z][a-z0-9-]*", project), (
        f"PROJECT={project!r} is not a unit prefix"
    )


def test_the_hooks_define_only_the_six_hooks():
    defined = set(sourced("declare -F | awk '{print $3}'").split())
    assert defined <= HOOK_NAMES, f"not hooks: {sorted(defined - HOOK_NAMES)}"
