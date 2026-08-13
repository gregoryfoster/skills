"""Every `shipping-work*` variant must carry the project-local env-loading
override block, and it must recommend a wrapper rather than a fork.

Background ([#105](https://github.com/gregoryfoster/skills/issues/105)): the
block existed in exactly one of four variants and told consumers to "keep a
thin local fork." A fork copies the whole gate to add four lines and then
drifts silently on every submodule update — a consumer that forked before an
upstream fix keeps running the pre-fix script with no signal that it does.

The supported shape is a wrapper: the skill's resolution loop probes `scripts/`
first, so a project-local `scripts/pre-ship.sh` wins, loads its env, and
delegates to the vendored script through the stable symlink path.

`shipping-work` (the bare variant) is deliberately classified apart: its
`pre-ship.sh` is a stub that exits 1 before doing any work, so there is nothing
for a wrapper to delegate *to*. Its block says so and puts the env loading in
the project's own override instead. Asserting the wrapper recipe there would
enshrine advice that cannot work.
"""

from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

HEADER = "# --- Project-local env loading (optional override point) ---"

# Variants shipping a real gate: a project-local override should wrap and
# delegate, so the full recipe applies.
DELEGATING_VARIANTS = [
    "shipping-work-php",
    "shipping-work-python-click",
    "shipping-work-python-fastapi",
]

# Variants whose pre-ship.sh is a stub with nothing to delegate to.
STUB_VARIANTS = ["shipping-work"]

ALL_VARIANTS = sorted(DELEGATING_VARIANTS + STUB_VARIANTS)


def _script(variant: str) -> Path:
    return SKILLS_DIR / variant / "scripts" / "pre-ship.sh"


def _block(variant: str) -> str:
    """The override block: the header line plus the comment run beneath it."""
    lines = _script(variant).read_text().splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.startswith(HEADER)]
    assert len(starts) == 1, (
        f"{variant}/scripts/pre-ship.sh must carry exactly one "
        f"'{HEADER}…' block; found {len(starts)}. Every shipping-work variant "
        "publishes the same override point so a consumer hitting the env wall "
        "gets the same named remedy regardless of which variant they vendored."
    )
    out = []
    for ln in lines[starts[0] :]:
        if not ln.startswith("#"):
            break
        out.append(ln)
    return "\n".join(out)


class TestOverrideBlockCoverage:
    def test_variant_inventory_is_exhaustive(self):
        """If a fifth variant appears, classify it here rather than letting it
        ship without an override block."""
        discovered = sorted(
            p.parent.parent.name
            for p in SKILLS_DIR.glob("shipping-work*/scripts/pre-ship.sh")
        )
        assert discovered == ALL_VARIANTS, (
            f"shipping-work* variants on disk {discovered} do not match the "
            f"classified set {ALL_VARIANTS}. Add the new variant to "
            "DELEGATING_VARIANTS (it ships a real gate) or STUB_VARIANTS (its "
            "pre-ship.sh exits before doing work), and give it an override "
            "block — the block drifting to a subset of variants is the "
            "regression this file exists to prevent."
        )

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_block_present(self, variant):
        _block(variant)  # raises with the diagnostic if absent or duplicated

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_does_not_recommend_a_fork(self, variant):
        block = _block(variant).lower()
        assert "local fork" not in block, (
            f"{variant}/scripts/pre-ship.sh still recommends a local fork. A "
            "fork copies the whole gate to add a few lines and drifts silently "
            "on every submodule update. Recommend a wrapper instead."
        )

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_guards_the_unquoted_expansion(self, variant):
        block = _block(variant)
        assert "set -f" in block, (
            f"{variant}/scripts/pre-ship.sh env recipe must disable globbing "
            "around the unquoted `export $(…)` expansion — a `*` or `?` inside "
            "a secret otherwise expands against the cwd."
        )

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_guards_the_empty_expansion(self, variant):
        block = _block(variant)
        assert 'if [ -n "$ENV_KV" ]; then' in block, (
            f"{variant}/scripts/pre-ship.sh env recipe must skip the export "
            "when the substitution is empty. A bare `export $(...)` with both "
            "env files absent degenerates to plain `export`, which prints "
            "every exported variable — secrets included — into the ship-gate "
            "transcript."
        )
        assert "| xargs) || true" in block, (
            f"{variant}/scripts/pre-ship.sh env recipe must tolerate absent "
            "env files: `cat` on a missing file fails, and under "
            "`set -o pipefail` the assignment inherits that status and aborts "
            "the gate before a single check runs."
        )

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_states_the_parse_dont_source_rule(self, variant):
        block = _block(variant)
        assert "never source it" in block, (
            f"{variant}/scripts/pre-ship.sh env recipe must state the "
            "parse-don't-source house rule (see "
            "skills/curating-context/scripts/measure-context.sh) rather than "
            "leaving `set -a; . file` as the obvious reach."
        )


class TestDelegatingVariantsCarryTheWrapperRecipe:
    @pytest.mark.parametrize("variant", DELEGATING_VARIANTS)
    def test_delegate_points_at_its_own_symlink_path(self, variant):
        block = _block(variant)
        expected = f'DELEGATE="skills/{variant}/scripts/pre-ship.sh"'
        assert expected in block, (
            f"{variant}/scripts/pre-ship.sh wrapper recipe must name its own "
            f"skill: expected `{expected}`. A recipe copied between variants "
            "without renaming sends the consumer to a sibling skill's gate."
        )

    @pytest.mark.parametrize("variant", DELEGATING_VARIANTS)
    def test_warns_against_the_vendor_path(self, variant):
        block = _block(variant)
        assert "skills-vendor/" in block, (
            f"{variant}/scripts/pre-ship.sh wrapper recipe must warn against "
            "delegating through skills-vendor/… — the symlink under skills/ is "
            "the stable interface; the vendor layout is an implementation "
            "detail of the submodule."
        )

    @pytest.mark.parametrize("variant", DELEGATING_VARIANTS)
    def test_execs_with_forwarded_arguments(self, variant):
        block = _block(variant)
        assert 'exec bash "$DELEGATE" "$@"' in block, (
            f"{variant}/scripts/pre-ship.sh wrapper recipe must `exec` (so the "
            "exit code the Iron Law gates on propagates unchanged) and forward "
            '"$@" (so `--help` still reaches this script).'
        )

    @pytest.mark.parametrize("variant", DELEGATING_VARIANTS)
    def test_missing_delegate_guard_uses_the_infra_exit_code(self, variant):
        block = _block(variant)
        assert '[[ -f "$DELEGATE" ]] ||' in block, (
            f"{variant}/scripts/pre-ship.sh wrapper recipe must guard a "
            "missing delegate. An unpopulated submodule (clone without "
            "--recurse-submodules, fresh `git worktree add`) otherwise fails "
            'as bash\'s generic "No such file or directory".'
        )
        assert "exit 2" in block, (
            f"{variant}/scripts/pre-ship.sh missing-delegate guard must exit 2 "
            "to match this script's own tooling/infra code, so operators read "
            "one exit-code table rather than two."
        )
        # The guard's exit code must agree with what --help publishes.
        text = _script(variant).read_text()
        assert "2" in text and "tooling/infra" in text, (
            f"{variant}/scripts/pre-ship.sh must document exit 2 as its "
            "tooling/infra code in --help for the recipe's `exit 2` to mean "
            "anything to an operator."
        )


class TestStubVariantDoesNotRecommendDelegation:
    @pytest.mark.parametrize("variant", STUB_VARIANTS)
    def test_no_delegate_recipe(self, variant):
        block = _block(variant)
        assert "$DELEGATE" not in block, (
            f"{variant}/scripts/pre-ship.sh is a stub that exits before doing "
            "work — a wrapper delegating to it would exec a script that "
            "immediately errors. Its block must put the env loading in the "
            "project's own override instead."
        )

    @pytest.mark.parametrize("variant", STUB_VARIANTS)
    def test_says_why_the_wrapper_shape_does_not_apply(self, variant):
        block = _block(variant)
        assert "stub" in block.lower(), (
            f"{variant}/scripts/pre-ship.sh block must say that this script is "
            "a stub, so a reader who saw the wrapper recipe in a sibling "
            "variant knows why this one differs."
        )
