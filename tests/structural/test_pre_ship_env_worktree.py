"""The ship gate's env contract must hold in a linked worktree (#497).

Two independent causes let a gate run that skipped every env-dependent test
read as a pass, and then bless the commit:

1. The env-loading recipe in every `shipping-work*/scripts/pre-ship.sh` loaded
   `"$PROJECT_ROOT/.env"`, and `PROJECT_ROOT` is the linked worktree. A
   gitignored `.env` lives only in the primary checkout, and `load_env`
   returns 0 on a missing file, so nothing was said. Seen on
   CannObserv/wslcb-licensing-tracker: `1164 passed, 347 skipped` and
   `Pre-ship checks passed.` against `1511 passed` with the env loaded.
2. The two `uv` gates keyed their per-SHA stamp on basename and SHA alone, so
   the run with no env blessed the commit and the corrected re-run was then
   skipped: `Test suite already passed for commit 968542e`.

The recipe now falls back to the primary checkout's `.env` (found through
`git rev-parse --git-common-dir`), warns on stderr when neither exists, and
exports the names (never the values) it loaded as `PRE_SHIP_ENV_NAMES`. The
stamped gates fold a hash of those names into the stamp key, and write no
stamp when the wrapper found no env file.

This file pins the recipe's half. The stamp's half moved with #537's release
2, which deleted the per-SHA stamp's two gates: test_unified_pre_ship.py holds
the tree stamp to the same rules.

The recipe ships as a comment, so these tests lift it out and run it: the
text-only suite is how #144's recipe passed while aborting on a comment line.
No test here prints a value from an env file.
"""

import os
import subprocess
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

HEADER = "# --- Project-local env loading (optional override point) ---"

# Every variant ships a real gate since #537, so every recipe is a wrapper.
# One variant since its release 2 deleted the `shipping-work-*` copies.
DELEGATING_VARIANTS = ["shipping-work"]
ALL_VARIANTS = sorted(DELEGATING_VARIANTS)

# The recipes that export PRE_SHIP_ENV_NAMES: every gate keyed on them.
# shipping-work keys its tree stamp on the names (gate-stamp.sh); that is
# pinned in test_unified_pre_ship.py. The per-SHA /tmp stamp the fastapi and
# click variants kept, and the tests that read it here, went with them.
NAME_EXPORTING = ["shipping-work"]

# A value no assertion may ever see in output. If it shows up, the recipe or
# the gate printed a secret.
SECRET = "sk-do-not-print-0b1c"


def _clean_env() -> dict:
    """The caller's environment without GIT_* (docs/STYLE.md, #189) and without
    a PRE_SHIP_ENV_NAMES the operator's own shell might carry."""
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_") and k != "PRE_SHIP_ENV_NAMES"
    }


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True, env=_clean_env())


def _recipe(variant: str, etc_env: str = "/nonexistent-497/.env") -> str:
    """The runnable recipe: the first contiguous run of `#   ` code lines in
    the override block, uncommented: the whole wrapper.

    `etc_env` stands in for the machine-wide file. The default does not exist;
    pass a real file to exercise a project whose env lives only there (CR 695).
    """
    lines = (SKILLS_DIR / variant / "scripts" / "pre-ship.sh").read_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(HEADER))
    out = []
    for ln in lines[start + 1 :]:
        if ln.startswith("#   "):
            out.append(ln[4:])
        elif out:
            break
        elif not ln.startswith("#"):
            break
    assert out, f"no runnable recipe found in {variant}'s override block"
    program = "\n".join(out)
    # The machine-wide file is a placeholder path whose `<` would parse as a
    # redirect; point it at the stand-in.
    assert "/etc/<project>/.env" in program, program
    return program.replace("/etc/<project>/.env", etc_env)


# What the probe reports: names only, never values.
PROBE = """
for n in PRIMARY_ONLY WT_ONLY ETC_ONLY; do
  if [ -n "${!n+x}" ]; then echo "HAS_$n"; fi
done
if [ -n "${PRE_SHIP_ENV_NAMES+x}" ]; then
  echo "NAMES=[$PRE_SHIP_ENV_NAMES]"
else
  echo "NAMES_UNSET"
fi
echo REACHED
"""


@pytest.fixture
def checkouts(tmp_path: Path):
    """A primary checkout with one commit, and a linked worktree of it."""
    primary = tmp_path / "primary"
    primary.mkdir()
    _git("-C", str(primary), "init", "-q")
    _git("-C", str(primary), "config", "user.email", "t@example.com")
    _git("-C", str(primary), "config", "user.name", "t")
    (primary / ".gitignore").write_text(".env\n")
    _git("-C", str(primary), "add", ".gitignore")
    _git("-C", str(primary), "commit", "-q", "-m", "init")
    worktree = tmp_path / "wt"
    _git("-C", str(primary), "worktree", "add", "-q", "-b", "wt", str(worktree))
    return primary, worktree


def _run_recipe(
    variant: str, cwd: Path, etc_env: str = "/nonexistent-497/.env"
) -> subprocess.CompletedProcess:
    program = _recipe(variant, etc_env)
    # The wrapper execs the delegate through its symlink path; put the probe
    # there so the exec lands on it.
    delegate = cwd / "skills" / variant / "scripts" / "pre-ship.sh"
    delegate.parent.mkdir(parents=True, exist_ok=True)
    delegate.write_text(PROBE)
    return subprocess.run(
        ["bash", "-c", program],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=30,
        env=_clean_env(),
    )


def _no_secret(r: subprocess.CompletedProcess) -> None:
    assert SECRET not in r.stdout + r.stderr, "a value from the env file was printed"


class TestTheRecipeFollowsWorktrees:
    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_a_linked_worktree_loads_the_primary_checkouts_env(
        self, variant, checkouts
    ):
        primary, worktree = checkouts
        (primary / ".env").write_text(f"PRIMARY_ONLY={SECRET}\n")
        r = _run_recipe(variant, worktree)
        _no_secret(r)
        assert r.returncode == 0, r.stderr
        assert "REACHED" in r.stdout, r.stdout
        assert "HAS_PRIMARY_ONLY" in r.stdout, (
            f"{variant}: in a linked worktree with no .env of its own, the "
            "recipe did not fall back to the primary checkout's .env. A "
            "gitignored .env exists only there, so the gate ran with no env "
            "and its env-dependent tests skipped as a pass (#497)."
        )
        assert "WARN" not in r.stderr, r.stderr

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_the_worktrees_own_env_wins(self, variant, checkouts):
        primary, worktree = checkouts
        (primary / ".env").write_text(f"PRIMARY_ONLY={SECRET}\n")
        (worktree / ".env").write_text(f"WT_ONLY={SECRET}\n")
        r = _run_recipe(variant, worktree)
        _no_secret(r)
        assert r.returncode == 0, r.stderr
        assert "HAS_WT_ONLY" in r.stdout, r.stdout
        assert "HAS_PRIMARY_ONLY" not in r.stdout, (
            f"{variant}: the primary checkout's .env is a fallback, not a "
            "second layer; a worktree that has its own must not get both."
        )

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_no_env_anywhere_warns_on_stderr(self, variant, checkouts):
        _, worktree = checkouts
        r = _run_recipe(variant, worktree)
        assert r.returncode == 0, (
            f"{variant}: a missing .env must warn, not abort — the gate still "
            f"runs. stderr: {r.stderr}"
        )
        assert "REACHED" in r.stdout, r.stdout
        warns = [ln for ln in r.stderr.splitlines() if ln.startswith("WARN")]
        assert warns, (
            f"{variant}: no .env in the worktree or the primary checkout, and "
            "the recipe said nothing. A missing secrets file must never be "
            "silent in a gate that exists to load it (#497)."
        )
        assert str(worktree / ".env") in r.stderr, (
            f"{variant}: the WARN must name the path it looked for. stderr: {r.stderr}"
        )

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_the_primary_checkout_itself_still_loads(self, variant, checkouts):
        primary, _ = checkouts
        (primary / ".env").write_text(f"PRIMARY_ONLY={SECRET}\n")
        r = _run_recipe(variant, primary)
        _no_secret(r)
        assert r.returncode == 0, r.stderr
        assert "HAS_PRIMARY_ONLY" in r.stdout, r.stdout
        assert "WARN" not in r.stderr, r.stderr


class TestTheRecipeExportsTheNames:
    @pytest.mark.parametrize("variant", NAME_EXPORTING)
    def test_the_names_loaded_reach_the_gate(self, variant, checkouts):
        primary, worktree = checkouts
        (primary / ".env").write_text(
            f"# a comment\nPRIMARY_ONLY={SECRET}\nexport WT_ONLY='{SECRET}'\n"
        )
        r = _run_recipe(variant, worktree)
        _no_secret(r)
        assert r.returncode == 0, r.stderr
        line = next(
            (ln for ln in r.stdout.splitlines() if ln.startswith("NAMES=")), None
        )
        assert line is not None, (
            f"{variant}: the wrapper exported no PRE_SHIP_ENV_NAMES, so the "
            "gate cannot key its stamp on the environment it ran in (#497)."
        )
        assert set(line[len("NAMES=[") : -1].split()) == {"PRIMARY_ONLY", "WT_ONLY"}

    @pytest.mark.parametrize("variant", NAME_EXPORTING)
    def test_no_env_file_exports_an_empty_list(self, variant, checkouts):
        _, worktree = checkouts
        r = _run_recipe(variant, worktree)
        assert r.returncode == 0, r.stderr
        assert "NAMES=[]" in r.stdout, (
            f"{variant}: with no env file the wrapper must export "
            "PRE_SHIP_ENV_NAMES set but empty — the gate's signal to write no "
            f"stamp. stdout: {r.stdout}"
        )


class TestAnEnvOnlyInEtc:
    """CR 695: a host-deployed service keeps its env in /etc/<project>/.env
    and has no repo .env at all. The recipe loaded it, then reset the names
    and warned that tests would skip: a false WARN on every run, and a gate
    that never stamps."""

    @pytest.mark.parametrize("variant", ALL_VARIANTS)
    def test_no_warn_when_the_machine_wide_file_loaded(
        self, variant, checkouts, tmp_path
    ):
        _, worktree = checkouts
        etc = tmp_path / "etc.env"
        etc.write_text(f"ETC_ONLY={SECRET}\n")
        r = _run_recipe(variant, worktree, str(etc))
        _no_secret(r)
        assert r.returncode == 0, r.stderr
        assert "HAS_ETC_ONLY" in r.stdout, r.stdout
        assert "WARN" not in r.stderr, (
            f"{variant}: the env loaded from the machine-wide file, and the "
            f"recipe still warned that tests needing it will skip:\n{r.stderr}"
        )

    @pytest.mark.parametrize("variant", NAME_EXPORTING)
    def test_its_names_reach_the_gate(self, variant, checkouts, tmp_path):
        _, worktree = checkouts
        etc = tmp_path / "etc.env"
        etc.write_text(f"ETC_ONLY={SECRET}\nAPI_KEY={SECRET}\n")
        r = _run_recipe(variant, worktree, str(etc))
        _no_secret(r)
        line = next((ln for ln in r.stdout.splitlines() if ln.startswith("NAMES=")), "")
        names = line[len("NAMES=[") : -1]
        assert set(names.split()) == {"ETC_ONLY", "API_KEY"}, (
            f"{variant}: the recipe discarded the names the machine-wide file "
            f"set, so the gate reads 'no env file' and never stamps. {line!r}"
        )


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_the_warn_names_each_path_it_tried_once(variant, checkouts):
    """CR 697: in a primary checkout the fallback resolves to the same file,
    and the WARN printed it twice. It names each path tried, once."""
    primary, _ = checkouts
    r = _run_recipe(variant, primary)
    assert r.returncode == 0, r.stderr
    local = str(primary / ".env")
    assert r.stderr.count(local) == 1, (
        f"{variant}: the WARN should name {local} once:\n{r.stderr}"
    )
    assert "/nonexistent-497/.env" in r.stderr, (
        f"{variant}: the WARN must name the machine-wide path it tried too:\n{r.stderr}"
    )
