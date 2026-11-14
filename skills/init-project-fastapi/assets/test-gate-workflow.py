"""Pin ci.yml's `gate` job to the repo's own pre-commit definition.

Written by init-project-fastapi under GITHUB_CI=pre-commit (skills#598, from
CannObserv/power-map#761). CI runs `pre-commit run --all-files`, the definition
every commit runs, never a hand-copied job list: a list that drifts from
.pre-commit-config.yaml checks something other than what a commit checked, and
still shows green. Derived from the repo, so these fail when the two drift:

- a local `system` hook whose tool no step in the gate job provisions;
- a second gate command, a check run beside it, or a `SKIP=`;
- a gate job that lets uv re-resolve a stale uv.lock;
- a job with no timeout, or write permissions beyond co-pypi's `id-token`;
- job names that differ from scripts/deploy_hooks.sh's CI_JOBS, which makes
  deploy.sh refuse every deploy with "<name> (not in the run)".

`yaml` is pre-commit's own dependency, so the dev group already carries it.
"""

import re
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
PRE_COMMIT = REPO / ".pre-commit-config.yaml"
HOOKS = REPO / "scripts" / "deploy_hooks.sh"

GATE = "uv run pre-commit run --all-files --show-diff-on-failure"
# A local hook's first entry word -> the step that puts it on the runner's PATH.
# A remote hook's tool is pre-commit's to install, so only local hooks map.
PROVIDERS = {
    "uv": "astral-sh/setup-uv",
    "npm": "actions/setup-node",
    "npx": "actions/setup-node",
}
# pre-commit 4.4 renamed `system` to `unsupported`; both mean "on the PATH".
SYSTEM = {"system", "unsupported"}
# What may run before the gate: installs, never a check. The WIF assert is
# PRIVATE_INDEX=co-pypi's step.
PROVISIONING = re.compile(r"^(uv sync( --[\w-]+( [\w.-]+)?)*|npm ci)$")
PROVISIONING_NAMES = {"Assert WIF is configured"}


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _jobs() -> dict[str, dict]:
    return _workflow()["jobs"]


def _run(step: dict) -> str:
    return " ".join(str(step.get("run", "")).split())


def _gate() -> dict:
    """The one job whose steps run pre-commit."""
    gates = [
        job
        for job in _jobs().values()
        if any("pre-commit" in _run(step) for step in job.get("steps", []))
    ]
    assert len(gates) == 1, f"expected one job running pre-commit, found {len(gates)}"
    return gates[0]


def test_ci_runs_the_local_definition_after_provisioning_only() -> None:
    gate_runs = [
        _run(step)
        for job in _jobs().values()
        for step in job.get("steps", [])
        if "pre-commit" in _run(step)
    ]
    assert gate_runs == [GATE], f"expected exactly one `{GATE}`, found {gate_runs}"
    *before, last = _gate()["steps"]
    assert _run(last) == GATE, "the gate command is the job's last step"
    checks = [
        _run(step)
        for step in before
        if "run" in step
        and not PROVISIONING.match(_run(step))
        and step.get("name") not in PROVISIONING_NAMES
    ]
    assert not checks, f"not provisioning, so a second gate: {checks}"


def test_no_hook_is_skipped() -> None:
    """`SKIP=` is a second, hand-kept list of what CI leaves out."""
    assert not re.search(r"\bSKIP\b", WORKFLOW.read_text(encoding="utf-8"))


def test_every_local_system_hook_tool_is_provisioned() -> None:
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    uses = {str(step.get("uses", "")).split("@")[0] for step in _gate()["steps"]}
    missing = []
    for repo in config["repos"]:
        if repo["repo"] != "local":
            continue
        for hook in repo["hooks"]:
            if hook.get("language") not in SYSTEM:
                continue
            tool = shlex.split(hook["entry"])[0]
            if (REPO / tool).is_file():
                continue  # a script in this repo
            if PROVIDERS.get(tool) not in uses:
                step = PROVIDERS.get(tool, "a setup step, and a PROVIDERS entry")
                missing.append(f"{hook['id']}: `{tool}` needs {step}")
    assert not missing, "; ".join(missing)


def test_the_gate_asserts_the_lock() -> None:
    """UV_LOCKED=1 (or `uv sync --locked`) fails on a stale uv.lock. `--frozen`
    doesn't: it installs the stale lock, and a later `uv run` re-resolves."""
    env = {**(_workflow().get("env") or {}), **(_gate().get("env") or {})}
    syncs = [_run(s) for s in _gate()["steps"] if _run(s).startswith("uv sync")]
    locked = syncs and all("--locked" in sync.split() for sync in syncs)
    assert str(env.get("UV_LOCKED")) == "1" or locked, "set UV_LOCKED: '1' on the gate"


def test_jobs_are_bounded_and_read_only() -> None:
    assert _workflow().get("permissions") == {"contents": "read"}
    allowed = {("contents", "read"), ("id-token", "write")}  # id-token: co-pypi
    for job_id, job in _jobs().items():
        assert job.get("timeout-minutes"), f"{job_id}: no timeout-minutes"
        granted = set((job.get("permissions") or {}).items())
        assert granted <= allowed, f"{job_id}: grants {sorted(granted - allowed)}"


def test_job_names_are_the_deploy_gates_ci_jobs() -> None:
    """deploy.sh's ci_gate refuses a run missing any CI_JOBS name."""
    if not HOOKS.is_file():
        pytest.skip("no scripts/deploy_hooks.sh: nothing deploys on CI's verdict")
    # GitHub Actions exports CI=true: unset it, or a hooks file without CI= reads it.
    script = (
        'unset CI CI_WORKFLOW CI_JOBS; source "$1"; '
        'printf "%s\\n" "${CI:-github}" "${CI_WORKFLOW:-ci.yml}" "${CI_JOBS[@]}"'
    )
    ci, workflow, *ci_jobs = subprocess.run(
        ["bash", "-c", script, "_", str(HOOKS)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    if ci == "none":
        pytest.skip("CI=none in deploy_hooks.sh: deploys don't ask CI")
    assert workflow == WORKFLOW.name, f"CI_WORKFLOW is {workflow}, not {WORKFLOW.name}"
    names = {job.get("name", job_id) for job_id, job in _jobs().items()}
    assert set(ci_jobs) == names, f"CI_JOBS {sorted(ci_jobs)}, jobs {sorted(names)}"
