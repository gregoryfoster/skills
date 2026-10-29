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

The recipe ships as a comment, so these tests lift it out and run it: the
text-only suite is how #144's recipe passed while aborting on a comment line.
No test here prints a value from an env file.
"""

import os
import subprocess
import uuid
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

HEADER = "# --- Project-local env loading (optional override point) ---"

DELEGATING_VARIANTS = [
    "shipping-work-php",
    "shipping-work-python-click",
    "shipping-work-python-fastapi",
]
ALL_VARIANTS = sorted(DELEGATING_VARIANTS + ["shipping-work"])

# The variants whose gate keeps a per-SHA stamp, and so reads the names.
STAMPED_VARIANTS = ["shipping-work-python-click", "shipping-work-python-fastapi"]

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


def _recipe(variant: str) -> str:
    """The runnable recipe: the first contiguous run of `#   ` code lines in
    the override block, uncommented. For the delegating variants that is the
    whole wrapper; for the stub it is the loader and the calls to it."""
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
    # redirect; point it somewhere that does not exist.
    assert "/etc/<project>/.env" in program, program
    return program.replace("/etc/<project>/.env", "/nonexistent-497/.env")


# What the probe reports: names only, never values.
PROBE = """
for n in PRIMARY_ONLY WT_ONLY; do
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


def _run_recipe(variant: str, cwd: Path) -> subprocess.CompletedProcess:
    program = _recipe(variant)
    if variant in DELEGATING_VARIANTS:
        # The wrapper execs the delegate through its symlink path; put the
        # probe there so the exec lands on it.
        delegate = cwd / "skills" / variant / "scripts" / "pre-ship.sh"
        delegate.parent.mkdir(parents=True, exist_ok=True)
        delegate.write_text(PROBE)
    else:
        # The stub's recipe runs inside the scaffolding, which has already set
        # PROJECT_ROOT under the script's own `set -euo pipefail`.
        program = (
            "set -euo pipefail\n"
            "PROJECT_ROOT=$(git rev-parse --show-toplevel)\n" + program + "\n" + PROBE
        )
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
    @pytest.mark.parametrize("variant", STAMPED_VARIANTS)
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

    @pytest.mark.parametrize("variant", STAMPED_VARIANTS)
    def test_no_env_file_exports_an_empty_list(self, variant, checkouts):
        _, worktree = checkouts
        r = _run_recipe(variant, worktree)
        assert r.returncode == 0, r.stderr
        assert "NAMES=[]" in r.stdout, (
            f"{variant}: with no env file the wrapper must export "
            "PRE_SHIP_ENV_NAMES set but empty — the gate's signal to write no "
            f"stamp. stdout: {r.stdout}"
        )


# --- the stamp ---------------------------------------------------------------

# Records argv; reports pytest-cov absent so no --no-cov is added; passes
# everything else. Same stub as test_pre_ship_unresolved_head.py.
STUB_UV = """#!/bin/sh
printf '%s\\n' "$*" >>"$UV_LOG"
case "$*" in *"import pytest_cov"*) exit 1 ;; esac
exit 0
"""


@pytest.fixture
def project(tmp_path: Path):
    # A basename no other run shares, because the stamp lives in /tmp/.
    root = tmp_path / f"proj-{uuid.uuid4().hex[:12]}"
    root.mkdir()
    _git("-C", str(root), "init", "-q")
    _git("-C", str(root), "config", "user.email", "t@example.com")
    _git("-C", str(root), "config", "user.name", "t")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("def test_x():\n    pass\n")
    _git("-C", str(root), "add", ".")
    _git("-C", str(root), "commit", "-q", "-m", "init")
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    (fakebin / "uv").write_text(STUB_UV)
    (fakebin / "uv").chmod(0o755)
    try:
        yield root
    finally:
        for stamp in Path("/tmp").glob(f"{root.name}-tests-clean-*"):
            stamp.unlink(missing_ok=True)


def _stamps(root: Path) -> list:
    return sorted(Path("/tmp").glob(f"{root.name}-tests-clean-*"))


def _gate(variant: str, root: Path, names) -> tuple:
    """Run the gate with PRE_SHIP_ENV_NAMES as given (None = unset); return
    the process and whether pytest ran."""
    env = _clean_env()
    env["PATH"] = f"{root.parent / 'fakebin'}{os.pathsep}{env['PATH']}"
    log = root.parent / "uv.log"
    log.unlink(missing_ok=True)
    env["UV_LOG"] = str(log)
    if names is not None:
        env["PRE_SHIP_ENV_NAMES"] = names
    r = subprocess.run(
        ["bash", str(SKILLS_DIR / variant / "scripts" / "pre-ship.sh")],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    ran = log.exists() and any(
        "pytest" in ln.split() for ln in log.read_text().splitlines()
    )
    return r, ran


class TestTheStampKnowsItsEnvironment:
    @pytest.mark.parametrize("variant", STAMPED_VARIANTS)
    def test_a_run_with_no_env_file_writes_no_stamp(self, variant, project):
        r, ran = _gate(variant, project, "")
        assert ran, r.stdout
        assert _stamps(project) == [], (
            f"{variant}: the wrapper found no env file, and the gate still "
            f"stamped the commit: {_stamps(project)}. That run skipped every "
            "env-dependent test, so its pass vouches for nothing (#497)."
        )
        assert "no stamp" in r.stderr, (
            f"{variant}: an unstamped run must say why on stderr. stderr: {r.stderr}"
        )
        _, ran = _gate(variant, project, "")
        assert ran, f"{variant}: the second env-less run was skipped"

    @pytest.mark.parametrize("variant", STAMPED_VARIANTS)
    def test_a_run_in_another_environment_is_not_suppressed(self, variant, project):
        """The #497 sequence with a partial env: the machine-wide file loaded,
        the project's did not. The corrected re-run must run."""
        _, ran = _gate(variant, project, "SHARED")
        assert ran
        r, ran = _gate(variant, project, "SHARED DSN")
        assert ran, (
            f"{variant}: a run with a different set of env names reused the "
            f"stamp of the run before it. stdout={r.stdout}"
        )

    @pytest.mark.parametrize("variant", STAMPED_VARIANTS)
    def test_the_same_names_in_any_order_reuse_the_stamp(self, variant, project):
        _, ran = _gate(variant, project, "B_KEY A_KEY B_KEY")
        assert ran
        r, ran = _gate(variant, project, "A_KEY B_KEY")
        assert not ran, (
            f"{variant}: the same set of names, reordered or repeated, must "
            f"hit the same stamp. stdout={r.stdout}"
        )
        assert "already passed" in r.stdout

    @pytest.mark.parametrize("variant", STAMPED_VARIANTS)
    def test_a_gate_run_with_no_wrapper_keeps_its_stamp(self, variant, project):
        """No PRE_SHIP_ENV_NAMES at all: a project with no env contract, or a
        wrapper not yet refreshed. The stamp works as it did, and it is not
        the slot an env-keyed run reads."""
        _, ran = _gate(variant, project, None)
        assert ran
        r, ran = _gate(variant, project, None)
        assert not ran, r.stdout
        _, ran = _gate(variant, project, "DSN")
        assert ran, (
            f"{variant}: an env-keyed run reused the stamp of a run with no "
            "env contract."
        )
