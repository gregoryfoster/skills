"""This repo's own `scripts/` must override exactly one skill script, and no more.

[#318](https://github.com/gregoryfoster/skills/issues/318) made this repo a
consumer of its own `shipping-work` skill: `scripts/pre-ship.sh` at the repo
root is the ship gate, because the skill's own copy is a stub that cannot know
a project's test runner.

That works because of [#301](https://github.com/gregoryfoster/skills/issues/301):
Step 1 resolves each script separately, probing `scripts/` before
`.claude/skills/<skill>/scripts/`. The probe order is what makes a one-file
override possible — and it is also the hazard. Any file dropped into repo-root
`scripts/` whose basename matches a script some skill resolves silently wins
for that script, everywhere, with no error and no signal. Here that is sharper
than in an ordinary consumer, because `.claude/skills` is a symlink to
`skills/`: the file it would shadow is this repo's own source.

Two rules, and they fail in opposite directions:

- **Nothing shadows by accident.** The override list is exactly
  `pre-ship.sh`. A future `scripts/doc-check.sh` would shadow the skill's for
  every run in this repo — the #301 bug arriving from the other side, since
  #301 was about a project `scripts/` capturing scripts it did NOT contain.
- **The intended override still resolves.** #318's acceptance asks for this
  to be asserted rather than assumed. `test_per_script_resolution.py` pins the
  behaviour generically, by running the published block in a synthetic project
  under bash and zsh; this pins it against the real repo layout, which is what
  actually decides whether a ship works here.

The resolvable set is derived from the published blocks, never hardcoded: a
hardcoded list is one rename away from enforcing nothing while reading as
coverage (#252).
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "skills"
ROOT_SCRIPTS = REPO_ROOT / "scripts"

# `for S in a.sh b.sh; do SD=` in a SKILL.md publishing block.
_FOR_S_IN = re.compile(r"^for S in ([^;]+); do", re.M)

# The one basename repo-root scripts/ is allowed to own, with the reason.
# docs/STYLE.md, "Project-local overrides: wrap, don't fork": the bare
# shipping-work variant ships a stub with nothing to delegate to, so the
# project's own file IS the gate. Every other name must keep resolving to the
# skill.
INTENDED_OVERRIDES = {
    "pre-ship.sh": (
        "this repo's ship gate (#318); the skill's copy is a stub that exits 1"
    ),
}


def _resolvable_script_names() -> dict[str, set[str]]:
    """basename -> the skills whose published block resolves it."""
    out: dict[str, set[str]] = {}
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        for match in _FOR_S_IN.finditer(skill_md.read_text()):
            for name in match.group(1).split():
                out.setdefault(name, set()).add(skill_md.parent.name)
    return out


def _root_script_names() -> set[str]:
    return {p.name for p in ROOT_SCRIPTS.glob("*.sh")}


def test_the_resolvable_set_is_not_empty():
    """A parse that matches nothing would make every rule below vacuous."""
    names = _resolvable_script_names()
    assert len(names) >= 6, (
        "parsed fewer than six resolvable script names from skills/*/SKILL.md "
        f"publishing blocks: {sorted(names)}. The block's shape changed, so "
        "the shadowing rule below is now checking an empty set and passing "
        "for that reason."
    )


def test_every_intended_override_is_actually_resolvable():
    """An exemption for a name no skill resolves protects nothing."""
    resolvable = _resolvable_script_names()
    stale = sorted(set(INTENDED_OVERRIDES) - set(resolvable))
    assert not stale, (
        f"INTENDED_OVERRIDES names {stale}, which no skill's publishing block "
        "resolves. Either the script was renamed upstream — in which case the "
        "override no longer overrides anything and this repo's ship gate is "
        "not being run — or the entry is dead. Remove it or fix the name."
    )


def test_repo_root_scripts_shadow_nothing_unintended():
    resolvable = _resolvable_script_names()
    shadowed = sorted(
        (name, sorted(resolvable[name]))
        for name in _root_script_names() & set(resolvable)
        if name not in INTENDED_OVERRIDES
    )
    assert not shadowed, (
        "repo-root scripts/ silently shadows skill script(s):\n"
        + "\n".join(f"  scripts/{n} -> shadows {s}" for n, s in shadowed)
        + "\n\nStep 1 probes scripts/ before .claude/skills/<skill>/scripts/, "
        "so these now win for every run in this repo — and .claude/skills is "
        "a symlink to skills/, so the file being shadowed is our own source. "
        "Rename the repo-root script, or add it to INTENDED_OVERRIDES with "
        "the reason it is a deliberate override."
    )


def _shipping_work_scripts_not_overridden() -> list[str]:
    """Every script shipping-work's block resolves, minus the one we override.

    Derived, not listed. The module docstring says the resolvable set is never
    hardcoded, and this parametrization was a hardcoded copy of it until CR 6 —
    the principle contradicted six lines under its own statement. A rename
    upstream now changes what is tested instead of leaving a list testing a
    name nothing resolves.
    """
    resolvable = _resolvable_script_names()
    return sorted(
        name
        for name, skills in resolvable.items()
        if "shipping-work" in skills and name not in INTENDED_OVERRIDES
    )


@pytest.mark.parametrize("script", _shipping_work_scripts_not_overridden())
def test_shipping_work_non_gate_scripts_resolve_to_the_skill(script):
    """#318 acceptance: the other five still resolve to the skill, here.

    Replicates Step 1's documented probe order against the real layout. The
    third candidate (`~/.claude/skills/`) is deliberately not consulted: if
    resolution ever reached it for this repo, the answer would depend on the
    operator's home directory, which is itself the failure.
    """
    assert not (ROOT_SCRIPTS / script).exists(), (
        f"scripts/{script} exists at the repo root and would win over the "
        "skill's copy — see test_repo_root_scripts_shadow_nothing_unintended."
    )
    skill_copy = REPO_ROOT / ".claude" / "skills" / "shipping-work" / "scripts" / script
    assert skill_copy.is_file(), (
        f"{script} does not resolve to .claude/skills/shipping-work/scripts/. "
        "Either the self-discovery symlink is broken (docs/SKILLS.md) or the "
        "script was renamed; Step 1 would stop on this name."
    )


def test_the_derived_parametrization_is_not_empty():
    """A derived list that derives to nothing passes every case it has (#252)."""
    derived = _shipping_work_scripts_not_overridden()
    assert len(derived) >= 5, (
        "shipping-work's publishing block resolved "
        f"{len(derived)} non-overridden script(s): {derived}. Fewer than five "
        "means the block's shape changed and the resolution test above is now "
        "asserting almost nothing."
    )
    assert "pre-ship.sh" not in derived, (
        "pre-ship.sh must be excluded by INTENDED_OVERRIDES — it is the one "
        "script this repo deliberately owns."
    )


def test_pre_ship_resolves_to_the_repo_root_copy():
    """The other half: the intended override actually wins."""
    local = ROOT_SCRIPTS / "pre-ship.sh"
    assert local.is_file(), (
        "scripts/pre-ship.sh is missing, so Step 1 falls through to the "
        "skill's stub, which exits 1 with 'the consuming project must supply "
        "a ship gate'. That is #318 reopening."
    )
    stub = (
        REPO_ROOT / ".claude" / "skills" / "shipping-work" / "scripts" / "pre-ship.sh"
    )
    assert stub.is_file(), (
        "the skill's stub vanished; the override has nothing to win over"
    )
    assert local.read_text() != stub.read_text(), (
        "scripts/pre-ship.sh is byte-identical to the skill's stub — it would "
        "exit 1 on every ship. The repo-root copy must BE the gate."
    )
