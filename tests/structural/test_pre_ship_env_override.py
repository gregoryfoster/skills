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

import shlex
import subprocess
import tempfile
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
    def test_exports_are_quoted(self, variant):
        """The old recipe word-split its expansion on purpose and paid for it
        with `set -f` plus two shellcheck suppressions. `export "$key=$val"`
        makes spaces, globs and quoted values survive with no dance at all, so
        the presence of the old machinery is now the regression signal."""
        block = _block(variant)
        assert 'export "$key=$val"' in block, (
            f"{variant}/scripts/pre-ship.sh env recipe must export through a "
            'quoted `export "$key=$val"`. An unquoted expansion word-splits '
            "`PW=two words` into a wrong value and exits 0 — silent, which is "
            "worse than the crash it replaced (#144)."
        )
        recipe_cmds = [
            ln.lstrip("#").strip() for ln in block.splitlines()
        ]
        assert not any(c.startswith(("set -f", "set +f")) for c in recipe_cmds), (
            f"{variant}/scripts/pre-ship.sh still disables globbing around an "
            "unquoted expansion. With a quoted export there is nothing to "
            "protect, and leaving the dance in implies the unsafe form. "
            "(Prose *mentioning* `set -f` to explain its removal is fine — "
            "this checks for it as an instruction.)"
        )

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_skips_comments_blanks_and_malformed_keys(self, variant):
        """The three defects that made `export $(cat … | xargs)` unsafe. A
        comment line is the one that bit hardest: it reached `export` as
        `'#': not a valid identifier`, and `set -e` killed the caller BEFORE
        the gate ran (#144)."""
        block = _block(variant)
        assert "\\#*) continue" in block, (
            f"{variant}/scripts/pre-ship.sh env recipe must skip comment and "
            "blank lines. A `#` reaching `export` aborts the caller under "
            "`set -e`, so the gate never runs — and `.env` comments are "
            "universal."
        )
        assert "*[!A-Za-z0-9_]*) continue" in block, (
            f"{variant}/scripts/pre-ship.sh env recipe must skip a key that is "
            "not a plain identifier rather than aborting. A malformed line in "
            "a secrets file must not decide whether the gate runs — that is "
            "exactly the environmental-vs-real judgement call a gate should "
            "never put in front of an operator."
        )
        # Target the construct, not the word: the prose deliberately names
        # `export $(cat … | xargs)` to explain why it is gone.
        assert not any(
            c.startswith(("export $(", "ENV_KV="))
            for c in (ln.lstrip("#").strip() for ln in block.splitlines())
        ), (
            f"{variant}/scripts/pre-ship.sh env recipe still reaches for "
            "`export $(cat … | xargs)`, which strips quotes, word-splits on "
            "whitespace, and degenerates to a bare `export` — dumping every "
            "exported variable — when both files are absent. Parse line by "
            "line instead."
        )

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_states_the_parse_dont_source_rule(self, variant):
        block = _block(variant)
        assert "never source" in block, (
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


def _extract_loader(variant: str) -> str:
    """The runnable `load_env` definition, lifted out of the comment block.

    The recipe ships as a comment, so nothing executes it and every property
    below was asserted purely as text until #144 — which is exactly how a
    recipe that aborted on a `.env` comment line, and silently truncated
    values containing spaces, passed a 12-test suite.
    """
    out, seen = [], False
    for ln in _block(variant).splitlines():
        body = ln[1:] if ln.startswith("#") else ln
        if body.lstrip().startswith("load_env() {"):
            seen = True
        if seen:
            out.append(body[2:] if body.startswith("  ") else body.lstrip())
            if body.lstrip() == "}":
                break
    assert seen and out[-1].strip() == "}", (
        f"could not lift a complete load_env() out of {variant}'s block"
    )
    return "\n".join(out)


def _run_loader(variant: str, env_text: str, probe: str) -> subprocess.CompletedProcess:
    """Run the variant's own recipe against an env file, then echo `probe`."""
    with tempfile.TemporaryDirectory() as td:
        envfile = Path(td) / ".env"
        envfile.write_text(env_text)
        script = (
            "set -euo pipefail\n"
            + _extract_loader(variant)
            + f'\nload_env {shlex.quote(str(Path(td) / "absent.env"))}\n'
            + f"load_env {shlex.quote(str(envfile))}\n"
            + f"{probe}\n"
        )
        return subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, cwd=td
        )


class TestTheRecipeActuallyRuns:
    """Execution coverage. Every assertion here maps to a defect the
    text-only suite could not see (#144)."""

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_a_comment_line_does_not_abort_the_gate(self, variant):
        """The regression that mattered most. `xargs` passed `#` through, and
        `export '#'` fails with "not a valid identifier" — under the wrapper's
        own `set -e` that killed it BEFORE `exec`, so the gate never ran and
        the operator got a bare shell error to adjudicate. That is precisely
        the environmental-vs-real judgement call #105 was filed to remove."""
        r = _run_loader(
            variant,
            "# deployment credentials\n\n  # indented\nAPI_KEY=sk-abc\n",
            'echo "REACHED:${API_KEY}"',
        )
        assert r.returncode == 0, (
            f"{variant}: a comment line in .env aborted the recipe "
            f"(rc={r.returncode}). stderr: {r.stderr.strip()}"
        )
        assert "REACHED:sk-abc" in r.stdout

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_values_with_whitespace_survive_intact(self, variant):
        """Silent corruption, which is worse than the crash above: `xargs`
        split `PW=two words` into `export PW=two` plus a stray `words`, and
        exited 0. The gate then ran against the wrong credentials, green."""
        r = _run_loader(variant, "PW=two words\n", 'echo "PW=[${PW}]"')
        assert r.returncode == 0, r.stderr
        assert "PW=[two words]" in r.stdout, (
            f"{variant}: a value containing a space was corrupted. "
            f"stdout: {r.stdout.strip()}"
        )

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_quotes_are_stripped_and_globs_are_literal(self, variant):
        r = _run_loader(
            variant,
            "Q=\"quoted val\"\nS='single val'\nG=a*b?c\n",
            'echo "Q=[${Q}] S=[${S}] G=[${G}]"',
        )
        assert r.returncode == 0, r.stderr
        assert "Q=[quoted val] S=[single val] G=[a*b?c]" in r.stdout, (
            f"{variant}: quoting or globbing mishandled. stdout: {r.stdout.strip()}"
        )

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_absent_env_file_leaks_nothing_and_does_not_abort(self, variant):
        """The disclosure bug. With both files absent the old substitution was
        empty and `export $(...)` degenerated to a bare `export`, printing
        every exported variable — secrets included — into the transcript."""
        r = _run_loader(variant, "", "echo DONE")
        assert r.returncode == 0, r.stderr
        assert "declare -x" not in r.stdout, (
            f"{variant}: the recipe dumped the environment to stdout — this is "
            "the secret-disclosure regression."
        )
        assert "DONE" in r.stdout

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_a_malformed_key_is_skipped_not_fatal(self, variant):
        r = _run_loader(
            variant,
            "BAD KEY=x\nnoequals\nGOOD=y\n",
            'echo "GOOD=[${GOOD}]"',
        )
        assert r.returncode == 0, (
            f"{variant}: a malformed line aborted the recipe. A secrets file "
            f"typo must not decide whether the gate runs. stderr: {r.stderr.strip()}"
        )
        assert "GOOD=[y]" in r.stdout

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_the_second_file_wins(self, variant):
        """Precedence is load-order, and the recipe loads the project file
        last so a repo-local value overrides the machine-wide one."""
        with tempfile.TemporaryDirectory() as td:
            first, second = Path(td) / "a.env", Path(td) / "b.env"
            first.write_text("K=from-etc\n")
            second.write_text("K=from-project\n")
            script = (
                "set -euo pipefail\n"
                + _extract_loader(variant)
                + f"\nload_env {shlex.quote(str(first))}\n"
                + f"load_env {shlex.quote(str(second))}\n"
                + 'echo "K=[${K}]"\n'
            )
            r = subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True, cwd=td
            )
        assert r.returncode == 0, r.stderr
        assert "K=[from-project]" in r.stdout
