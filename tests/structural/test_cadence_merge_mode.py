"""The cadence workflow reads #342's `.skills/merge_mode` (#560).

A consumer whose default branch carries a PR-only ruleset with no bypass
refuses the weekly measurement's direct push, and the GitHub Actions app
cannot be made a ruleset bypass actor, so that week's row is lost after three
attempts. Decided on #560 (comment 6605837550): no new knob. With
`merge_mode` `pr`, the workflow pushes `context/weekly-measurement` and opens
or updates ONE PR. Absent or `direct`, it is today's workflow, byte for byte.

How the knob reaches the workflow (the call #560's brief left open):

- **At install time it picks the shape.** `install-cadence.sh` reads the
  primary checkout's knob with merge-mode.sh's grammar. `direct` or absent
  renders today's bytes; `pr` renders today's bytes plus five insertions:
  `pull-requests: write`, a `Read the merge mode` step, a step that merges
  the open PR's rows in before the sweep (CR 1803), `GH_TOKEN` on the
  commit step, and the PR path after `# --- push ---`. Widening the token for
  every consumer was the other option, and it would have changed every
  direct repo's workflow, which the decision rules out.
- **At run time a `pr`-rendered workflow follows the committed knob**, read
  inline (the job can't count on shipping-work's merge-mode.sh being
  vendored). Switched back to `direct`, it pushes to the default branch as
  before, without a re-render. Switched to `pr` under a direct-rendered
  workflow, `--check` reports STALE (exit 3).

No API calls. Every fixture repo is built with an explicit path and a
scrubbed `GIT_*` environment (#189). `gh` is a fake on PATH, and the remote
is a local bare repository.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.structural import merge_mode_layouts as layouts

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "skills" / "curating-context" / "scripts"
INSTALL_CADENCE = SCRIPTS / "install-cadence.sh"
MERGE_TOKEN_COUNTS = SCRIPTS / "merge-token-counts.sh"
RECORD_TELEMETRY = SCRIPTS / "record-telemetry.sh"
CHECK_SEAMS = SCRIPTS / "check-seams.sh"
MERGE_MODE_SH = REPO_ROOT / "skills" / "shipping-work" / "scripts" / "merge-mode.sh"
THIS_REPOS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "context-cadence.yml"

LEDGER = ".skills/context-metrics.jsonl"
PR_BRANCH = "context/weekly-measurement"
READ_STEP = "Read the merge mode"
TAKE_STEP = "Take in the measurement PR's rows"
COMMIT_STEP = "Commit the row"


def _env(**extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["LC_ALL"] = "C"
    env.update(extra)
    return env


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(),
    ).stdout.strip()


def _init(path: Path, origin: str | None = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    if origin:
        _git(path, "remote", "add", "origin", origin)
    return path


def _knob(repo: Path, text: str | None) -> None:
    """Write `.skills/merge_mode`; None leaves it absent."""
    if text is None:
        return
    (repo / ".skills").mkdir(exist_ok=True)
    (repo / ".skills" / "merge_mode").write_text(text)


def _install(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALL_CADENCE), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        env=_env(),
    )


def _render(tmp_path: Path, knob: str | None, name: str = "render") -> str:
    repo = _init(tmp_path / name)
    _knob(repo, knob)
    r = _install(repo, "--print", "--cron", "0 15 * * 1")
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _steps(rendered: str) -> dict[str, str]:
    doc = yaml.safe_load(rendered)
    return {
        s["name"]: s["run"]
        for s in doc["jobs"]["measure"]["steps"]
        if s.get("name") and s.get("run")
    }


# --- a remote, a runner checkout, and a fake gh ---------------------------

FAKE_GH = r"""#!/usr/bin/env bash
# A stand-in for gh: logs every call. `pr list` prints $FAKE_GH/prs, one PR
# per line as the workflow's --jq shapes it: `<number> <STATE> <head oid>`.
# With $FAKE_GH/prs.json instead it answers as gh does: the array cut down to
# the --json fields, then the --jq filter, run by jq.
# `pr create` records an OPEN PR whose head is the pushed HEAD, unless
# $FAKE_GH/create_err exists, whose text it prints to stderr.
printf '%s\n' "$*" >>"$FAKE_GH/calls"
case "$1 $2" in
  "pr list")
    [ ! -f "$FAKE_GH/list_err" ] || { cat "$FAKE_GH/list_err" >&2; exit 1; }
    if [ -f "$FAKE_GH/prs.json" ]; then
      fields='' filter='.'
      while [ $# -gt 0 ]; do
        case $1 in --json) fields=$2; shift ;; --jq) filter=$2; shift ;; esac
        shift
      done
      jq -r --arg f "$fields" \
        "map(with_entries(select(.key as \$k | \$f | split(\",\") | index(\$k)))) | $filter" \
        "$FAKE_GH/prs.json"
      exit
    fi
    cat "$FAKE_GH/prs" 2>/dev/null
    exit 0 ;;
  "pr create")
    if [ -f "$FAKE_GH/create_err" ]; then cat "$FAKE_GH/create_err" >&2; exit 1; fi
    n=$(( $(cat "$FAKE_GH/prs" 2>/dev/null | wc -l) + 7 ))
    echo "$n OPEN $(git rev-parse HEAD)" >>"$FAKE_GH/prs"
    echo "https://github.com/o/r/pull/$n"
    exit 0 ;;
esac
echo "fake gh: unhandled: $*" >&2
exit 64
"""


class Rig:
    """A bare origin, its seeded default branch, and one fresh runner clone
    per scheduled run, as Actions gives every run."""

    def __init__(self, tmp_path: Path, knob: str | None):
        self.tmp = tmp_path
        self.origin = tmp_path / "origin.git"
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", str(self.origin)],
            check=True,
            env=_env(),
        )
        self.gh = tmp_path / "gh"
        self.gh.mkdir()
        (self.gh / "bin").mkdir()
        fake = self.gh / "bin" / "gh"
        fake.write_text(FAKE_GH)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        self.runs = 0
        seed = self.clone("seed")
        (seed / ".skills").mkdir()
        (seed / LEDGER).write_text(self.row("2026-10-01") + "\n")
        # The policy file the seam sweep reads; the measurement is a payload.
        (seed / "AGENTS.md").write_text("# Agents\n")
        (seed / ".gitattributes").write_text(
            f"{LEDGER} merge=union\n"
            ".skills/context-token-ratio merge=ours\n"
            ".skills/context-token-counts merge=context-counts\n"
        )
        _knob(seed, knob)
        _git(seed, "add", "-A")
        _git(seed, "commit", "-qm", "seed")
        _git(seed, "push", "-q", "origin", "HEAD:main")
        self.rendered = _render(tmp_path, knob)

    @staticmethod
    def row(ts: str) -> str:
        """A row record-telemetry.sh takes as a predecessor."""
        return json.dumps(
            {
                "ts": ts,
                "repo": "r",
                "file": "AGENTS.md",
                "tokens": 100,
                "tokens_exact": True,
            },
            sort_keys=True,
        )

    def record(self, repo: Path, ts: str, tokens: int) -> None:
        """Append this run's row as the Measure and record step does: the
        real record-telemetry.sh, on a measurement of `tokens`, dated `ts`."""
        from tests.structural.test_telemetry_amend import _payload

        shim = self.tmp / "date-shim"
        if not shim.exists():
            shim.mkdir()
            real = shutil.which("date")
            (shim / "date").write_text(
                "#!/bin/sh\n"
                'if [ "$1" = "+%Y-%m-%d" ]; then echo "$FAKE_TODAY"; '
                f'else exec "{real}" "$@"; fi\n'
            )
            (shim / "date").chmod(0o755)
        r = subprocess.run(
            ["bash", str(RECORD_TELEMETRY), "--baseline=scheduled", "--ledger", LEDGER],
            input=_payload(tokens),
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=60,
            env=_env(FAKE_TODAY=ts, PATH=f"{shim}{os.pathsep}{os.environ['PATH']}"),
        )
        assert r.returncode == 0, r.stdout + r.stderr

    @staticmethod
    def sweep_interval(repo: Path) -> str:
        """The interval the seam sweep spans from this checkout's ledger, as
        the workflow runs it (`--base-ledger`)."""
        r = subprocess.run(
            ["bash", str(CHECK_SEAMS), "--base-ledger", LEDGER],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=60,
            env=_env(),
        )
        found = re.findall(r"^seam_interval: (\S+)$", r.stdout, re.M)
        assert found, r.stdout + r.stderr
        return found[-1]

    def clone(self, name: str) -> Path:
        d = self.tmp / name
        subprocess.run(
            ["git", "clone", "-q", str(self.origin), str(d)], check=True, env=_env()
        )
        _git(d, "config", "user.email", "t@example.com")
        _git(d, "config", "user.name", "t")
        return d

    def calls(self) -> list[str]:
        f = self.gh / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def step(self, name: str, cwd: Path, env: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "-e", "-c", _steps(self.rendered)[name]],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )

    def run(
        self, ts: str, mode_env: str | None = None, tokens: int | None = None
    ) -> subprocess.CompletedProcess:
        """One scheduled run: a fresh clone of main, the knob read and the
        PR's rows taken in (when the render has those steps), one row
        appended, the commit step run. With `tokens`, the row is recorded by
        record-telemetry.sh, and the seam sweep's interval is read first, as
        the workflow orders them; without, it is appended by hand."""
        self.runs += 1
        steps = _steps(self.rendered)
        runner = self.clone(f"runner{self.runs}")
        gh_env = self.tmp / f"github_env{self.runs}"
        gh_env.write_text("")
        env = _env(
            GITHUB_ENV=str(gh_env),
            GITHUB_REF_NAME="main",
            FAKE_GH=str(self.gh),
            MERGE_TOKEN_COUNTS_SH=str(MERGE_TOKEN_COUNTS),
            PATH=f"{self.gh / 'bin'}{os.pathsep}{os.environ['PATH']}",
        )
        if READ_STEP in steps:
            read = self.step(READ_STEP, runner, env)
            assert read.returncode == 0, read.stdout + read.stderr
            for line in gh_env.read_text().splitlines():
                k, _, v = line.partition("=")
                env[k] = v
        if mode_env is not None:
            env["MERGE_MODE"] = mode_env
        self.take = None
        if TAKE_STEP in steps:
            self.take = self.step(TAKE_STEP, runner, env)
            if self.take.returncode:
                return self.take
        self.runner = runner
        if tokens is None:
            led = runner / LEDGER
            led.write_text(led.read_text() + self.row(ts) + "\n")
        else:
            self.interval = self.sweep_interval(runner)
            self.record(runner, ts, tokens)
        return self.step(COMMIT_STEP, runner, env)

    def rows(self, ref: str) -> list[dict]:
        out = _git(self.origin, "show", f"{ref}:{LEDGER}")
        return [json.loads(ln) for ln in out.splitlines() if ln.strip()]

    def show(self, ref: str) -> list[str]:
        out = subprocess.run(
            ["git", "-C", str(self.origin), "show", f"{ref}:{LEDGER}"],
            capture_output=True,
            text=True,
            env=_env(),
        )
        if out.returncode:
            return []
        return [json.loads(ln)["ts"] for ln in out.stdout.splitlines() if ln.strip()]

    def has_branch(self, branch: str) -> bool:
        return (
            subprocess.run(
                ["git", "-C", str(self.origin), "rev-parse", "--verify", "-q", branch],
                capture_output=True,
                env=_env(),
            ).returncode
            == 0
        )


# --- #560's "Done when", verbatim ------------------------------------------


class TestIssueReproduction:
    """#560, "Done when": "With `merge_mode` `pr` and a no-bypass PR-only rule
    on the default branch, [...] the cadence run opens or updates a PR instead
    of failing." and "With the knob absent, both jobs behave exactly as
    before." The refresh-hook half is a separate change."""

    def test_with_merge_mode_pr_the_cadence_run_opens_or_updates_a_pr_instead_of_failing(
        self, tmp_path: Path
    ):
        rig = Rig(tmp_path, knob="pr\n")
        # A no-bypass PR-only rule on the default branch, as a server hook:
        # every push to main is refused the way GitHub refuses it.
        hook = rig.origin / "hooks" / "pre-receive"
        hook.write_text(
            "#!/usr/bin/env bash\n"
            "while read -r _ _ ref; do\n"
            '  if [ "$ref" = refs/heads/main ]; then\n'
            '    echo "remote: error: GH013: Repository rule violations found for refs/heads/main." >&2\n'
            "    exit 1\n"
            "  fi\n"
            "done\n"
        )
        hook.chmod(0o755)

        first = rig.run("2026-10-08")
        assert first.returncode == 0, first.stdout + first.stderr
        assert rig.show("main") == ["2026-10-01"], "the default branch moved"
        assert rig.show(PR_BRANCH) == ["2026-10-01", "2026-10-08"]
        creates = [c for c in rig.calls() if c.startswith("pr create")]
        assert len(creates) == 1, rig.calls()
        assert f"--head {PR_BRANCH}" in creates[0] and "--base main" in creates[0]

        # The second week, PR still open: the same PR is updated, not a new
        # one opened, and last week's row is still on it, first.
        second = rig.run("2026-10-15")
        assert second.returncode == 0, second.stdout + second.stderr
        assert rig.show("main") == ["2026-10-01"]
        assert rig.show(PR_BRANCH) == ["2026-10-01", "2026-10-08", "2026-10-15"]
        assert len([c for c in rig.calls() if c.startswith("pr create")]) == 1

    def test_with_the_knob_absent_the_rendered_workflow_is_byte_identical_to_todays(
        self, tmp_path: Path
    ):
        """This repo's committed workflow is today's render, and this repo has
        no knob. A fixture with the same origin name draws the same cron, and
        carries the committed file as installed so the checkout pin it keeps
        is the committed one. Absent and an explicit `direct` both give it
        back byte for byte."""
        todays = THIS_REPOS_WORKFLOW.read_text()
        knobs = (None, "direct\n", "# reviewed directly\n\n  direct  \n")
        for i, knob in enumerate(knobs):
            repo = _init(
                tmp_path / f"r{i}",
                origin="https://github.com/gregoryfoster/skills.git",
            )
            wf = repo / ".github" / "workflows" / "context-cadence.yml"
            wf.parent.mkdir(parents=True)
            wf.write_text(todays)
            _knob(repo, knob)
            r = _install(repo, "--print")
            assert r.returncode == 0, r.stderr
            assert r.stdout == todays, f"knob {knob!r} changed the direct render"


# --- the inline readers hold merge-mode.sh's grammar -----------------------

# The text inputs test_merge_mode_knob.py pins merge-mode.sh to, plus
# absence. The states no text can write are NOT_TEXT, below.
CASES = [
    None,
    "pr\n",
    "direct\n",
    "# reviewed through PRs since 2026-11\r\n\r\n   pr  \r\n\n",
    "pr",
    "PR\n",
    "pull-request\n",
    "merge\n",
    "pr direct\n",
    "pr\ndirect\n",
    "pr # reviewed\n",
    "",
    "# only a comment\n\n",
]

# The filesystem states test_merge_mode_knob.py also pins merge-mode.sh to,
# exit 2 each (CR 1793). Its fourth, outside a git checkout, does not apply
# to these two readers: install-cadence.sh refuses before it reads the knob
# ("not inside a git repository", exit 1), and the workflow step runs in the
# job's checkout. The hook's reader takes it (test_refresh_hook_pr_mode.py).
NOT_TEXT = [
    "directory",
    "dangling-symlink",
    pytest.param(
        "unreadable",
        marks=pytest.mark.skipif(os.geteuid() == 0, reason="root reads mode 000"),
    ),
]


def _not_text(repo: Path, kind: str) -> None:
    knob = repo / ".skills" / "merge_mode"
    knob.parent.mkdir(exist_ok=True)
    if kind == "directory":
        knob.mkdir()
    elif kind == "dangling-symlink":
        knob.symlink_to(repo / "nowhere")
    else:
        knob.write_text("pr\n")
        knob.chmod(0)


def _merge_mode_sh(repo: Path) -> tuple[int, str]:
    r = subprocess.run(
        ["bash", str(MERGE_MODE_SH)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_env(),
        timeout=30,
    )
    return r.returncode, r.stdout.strip()


class TestTheInlineReadersHoldMergeModeShsGrammar:
    """Two readers besides merge-mode.sh: the installer's (which shape to
    render) and the workflow's (what a `pr`-rendered run does). Same input,
    same answer, or the same refusal."""

    @pytest.mark.parametrize("text", CASES, ids=[repr(c) for c in CASES])
    def test_the_workflow_step_answers_as_merge_mode_sh_does(self, tmp_path, text):
        repo = _init(tmp_path / "r")
        _knob(repo, text)
        want_rc, want = _merge_mode_sh(repo)
        step = _steps(_render(tmp_path, "pr\n"))[READ_STEP]
        gh_env = tmp_path / "github_env"
        gh_env.write_text("")
        r = subprocess.run(
            ["bash", "-e", "-c", step],
            cwd=repo,
            capture_output=True,
            text=True,
            env=_env(GITHUB_ENV=str(gh_env)),
            timeout=30,
        )
        written = gh_env.read_text()
        if want_rc == 0:
            assert r.returncode == 0, r.stdout + r.stderr
            assert written == f"MERGE_MODE={want}\n"
        else:
            assert r.returncode != 0, r.stdout
            assert written == "", "an unusable knob must export no mode"
            assert "::error::" in r.stdout and ".skills/merge_mode" in r.stdout

    @pytest.mark.parametrize("text", CASES, ids=[repr(c) for c in CASES])
    def test_the_installer_renders_as_merge_mode_sh_answers(self, tmp_path, text):
        repo = _init(tmp_path / "r")
        _knob(repo, text)
        want_rc, want = _merge_mode_sh(repo)
        r = _install(repo, "--print", "--cron", "0 15 * * 1")
        if want_rc == 0:
            assert r.returncode == 0, r.stderr
            assert (READ_STEP in r.stdout) is (want == "pr"), want
        else:
            assert r.returncode == 5, r.stdout + r.stderr
            assert r.stdout == "", "an unusable knob must render nothing"
            assert ".skills/merge_mode" in r.stderr

    @pytest.mark.parametrize("kind", NOT_TEXT)
    def test_the_workflow_step_refuses_what_merge_mode_sh_refuses(self, tmp_path, kind):
        repo = _init(tmp_path / "r")
        _not_text(repo, kind)
        assert _merge_mode_sh(repo)[0] == 2, "fixture: merge-mode.sh accepts it"
        step = _steps(_render(tmp_path, "pr\n"))[READ_STEP]
        gh_env = tmp_path / "github_env"
        gh_env.write_text("")
        r = subprocess.run(
            ["bash", "-e", "-c", step],
            cwd=repo,
            capture_output=True,
            text=True,
            env=_env(GITHUB_ENV=str(gh_env)),
            timeout=30,
        )
        assert r.returncode != 0, r.stdout
        assert gh_env.read_text() == "", "an unusable knob must export no mode"
        assert "::error::" in r.stdout and ".skills/merge_mode" in r.stdout

    @pytest.mark.parametrize("kind", NOT_TEXT)
    def test_the_installer_refuses_what_merge_mode_sh_refuses(self, tmp_path, kind):
        repo = _init(tmp_path / "r")
        _not_text(repo, kind)
        assert _merge_mode_sh(repo)[0] == 2, "fixture: merge-mode.sh accepts it"
        r = _install(repo, "--print", "--cron", "0 15 * * 1")
        assert r.returncode == 5, r.stdout + r.stderr
        assert r.stdout == "", "an unusable knob must render nothing"
        assert ".skills/merge_mode" in r.stderr

    def test_the_installer_reads_the_primary_checkout(self, tmp_path: Path):
        """As merge-mode.sh does: an untracked knob is absent from a linked
        worktree, so asking the current checkout would render `direct`."""
        repo = _init(tmp_path / "r")
        (repo / "README.md").write_text("x\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        _knob(repo, "pr\n")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feature/x", str(wt))
        assert _merge_mode_sh(wt) == (0, "pr")
        r = _install(wt, "--print", "--cron", "0 15 * * 1")
        assert r.returncode == 0, r.stderr
        assert READ_STEP in r.stdout

    # #584: in a bare primary and a submodule, the first list entry is a git
    # dir, and the installer read it as the checkout: `direct`, in silence.
    # The workflow step needs no such case: it reads `.skills/merge_mode`
    # relative to the job's checkout, which actions/checkout makes a plain
    # clone, never bare and never a submodule's worktree.

    @pytest.mark.parametrize("layout", sorted(layouts.LAYOUTS))
    @pytest.mark.parametrize("text", ["pr\n", "PR\n"], ids=["pr", "PR"])
    def test_the_installer_reads_the_primary_in_each_layout(
        self, tmp_path, layout, text
    ):
        checkout = layouts.LAYOUTS[layout](tmp_path, text)
        want = (0, "pr") if text == "pr\n" else (2, "")
        assert _merge_mode_sh(checkout) == want, "fixture: merge-mode.sh disagrees"
        r = _install(checkout, "--print", "--cron", "0 15 * * 1")
        if want[0] == 0:
            assert r.returncode == 0, r.stderr
            assert READ_STEP in r.stdout, "read as direct"
        else:
            assert r.returncode == 5, r.stdout + r.stderr
            assert r.stdout == "", "an unusable knob must render nothing"
            assert ".skills/merge_mode" in r.stderr

    @pytest.mark.parametrize("layout", sorted(layouts.LAYOUTS))
    def test_an_inherited_git_dir_does_not_answer(self, tmp_path, layout):
        """CR 1895: as knob_tracked and git_config already scrub it."""
        checkout = layouts.LAYOUTS[layout](tmp_path, "pr\n")
        gitdir = layouts.git(checkout, "rev-parse", "--absolute-git-dir")
        r = subprocess.run(
            ["bash", str(INSTALL_CADENCE), "--print", "--cron", "0 15 * * 1"],
            cwd=checkout,
            capture_output=True,
            text=True,
            timeout=60,
            env=_env(GIT_DIR=gitdir),
        )
        assert r.returncode == 0, r.stderr
        assert READ_STEP in r.stdout, "read as direct"

    @pytest.mark.parametrize(
        ("layout", "committed"),
        [("bare_home", True), ("submodule_linked", False)],
    )
    def test_the_committed_check_asks_the_primary_work_tree(
        self, tmp_path, layout, committed
    ):
        """KNOB_PRIMARY's other reader: whether the knob is committed as it
        reads is asked of the primary's work tree. The bare layout's knob is
        committed; the submodule's is untracked in its checkout."""
        checkout = layouts.LAYOUTS[layout](tmp_path, "pr\n")
        r = _install(checkout)
        assert r.returncode == 0, r.stdout + r.stderr
        wf = checkout / ".github" / "workflows" / "context-cadence.yml"
        assert READ_STEP in wf.read_text(), "read as direct"
        assert ("not committed" in r.stdout) is not committed, r.stdout
        check = _install(checkout, "--check")
        assert "merge mode:         pr" in check.stdout, check.stdout
        assert ("not committed" in check.stdout) is not committed, check.stdout

    def test_the_installer_refuses_a_primary_git_cannot_open(self, tmp_path: Path):
        """Only the primary is refused ("dubious ownership"): unusable, exit
        5, never a fallback to this checkout or to the primary's raw path."""
        repo = _init(tmp_path / "r")
        (repo / "README.md").write_text("x\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        _knob(repo, "pr\n")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feature/x", str(wt))
        r = subprocess.run(
            ["bash", str(INSTALL_CADENCE), "--print", "--cron", "0 15 * * 1"],
            cwd=wt,
            capture_output=True,
            text=True,
            timeout=60,
            env=layouts.different_owner(_env(), wt),
        )
        assert r.returncode == 5, r.stdout + r.stderr
        assert r.stdout == "", "a primary git refuses must render nothing"
        assert "dubious ownership" in r.stderr, "git's reason is let through"
        assert str(repo.resolve()) in r.stderr, r.stderr

    # CR 1892: a primary whose .git is a pointer file lists its store, which
    # names no work tree; #584 made --print exit 5 there with no knob at all.

    @pytest.mark.parametrize("text", [None, "pr\n"], ids=["absent", "pr"])
    def test_a_separate_git_dir_primary_renders_by_its_own_knob(self, tmp_path, text):
        primary, _ = layouts.separate_git_dir(tmp_path, text)
        r = _install(primary, "--print", "--cron", "0 15 * * 1")
        assert r.returncode == 0, r.stderr
        assert "must be run in a work tree" not in r.stderr, r.stderr
        assert (READ_STEP in r.stdout) is (text == "pr\n"), r.stdout

    @pytest.mark.parametrize("text", [None, "pr\n"], ids=["absent", "pr"])
    def test_its_linked_worktree_refuses_and_says_why(self, tmp_path, text):
        _, linked = layouts.separate_git_dir(tmp_path, text)
        r = _install(linked, "--print", "--cron", "0 15 * * 1")
        assert r.returncode == 5, r.stdout + r.stderr
        assert r.stdout == "", "an unreadable knob must render nothing"
        assert layouts.SEPARATE_GIT_DIR_HINT in r.stderr, r.stderr
        assert "primary checkout" in r.stderr, r.stderr

    def test_its_store_git_cannot_open_is_never_the_fallback(self, tmp_path):
        _, linked = layouts.separate_git_dir(tmp_path, "pr\n")
        r = subprocess.run(
            ["bash", str(INSTALL_CADENCE), "--print", "--cron", "0 15 * * 1"],
            cwd=linked,
            capture_output=True,
            text=True,
            timeout=60,
            env=layouts.different_owner(_env(), linked),
        )
        assert r.returncode == 5, r.stdout + r.stderr
        assert "dubious ownership" in r.stderr, r.stderr
        assert layouts.SEPARATE_GIT_DIR_HINT not in r.stderr, r.stderr


# --- the two shapes --------------------------------------------------------


class TestTheTwoShapes:
    def test_pr_is_the_direct_render_plus_insertions_only(self, tmp_path: Path):
        """Nothing the direct workflow does is removed or rewritten in the pr
        shape, so a pr-rendered run whose knob says `direct` runs today's
        steps."""
        direct = _render(tmp_path, None, "d").splitlines()
        pr = _render(tmp_path, "pr\n", "p").splitlines()
        removed = [
            ln
            for ln in difflib.ndiff(direct, pr)
            if ln.startswith("- ") or ln.startswith("? ")
        ]
        assert not removed, removed
        assert len(pr) > len(direct)

    def test_the_token_is_widened_only_when_rendered_for_pr(self, tmp_path: Path):
        assert yaml.safe_load(_render(tmp_path, None, "d"))["permissions"] == {
            "contents": "write"
        }
        assert yaml.safe_load(_render(tmp_path, "pr\n", "p"))["permissions"] == {
            "contents": "write",
            "pull-requests": "write",
        }

    def test_the_mode_is_read_before_the_credential_is_spent(self, tmp_path: Path):
        doc = yaml.safe_load(_render(tmp_path, "pr\n"))
        names = [s.get("name", "") for s in doc["jobs"]["measure"]["steps"]]
        assert names.index(READ_STEP) < names.index("Preflight the credential")

    def test_the_commit_step_gets_gh_a_token(self, tmp_path: Path):
        doc = yaml.safe_load(_render(tmp_path, "pr\n"))
        commit = next(
            s for s in doc["jobs"]["measure"]["steps"] if s.get("name") == COMMIT_STEP
        )
        assert commit["env"] == {"GH_TOKEN": "${{ github.token }}"}

    def test_every_pr_run_block_parses_and_runs_no_live_substitution(
        self, tmp_path: Path
    ):
        from tests.structural.test_cadence_rendered_shell import _strip_heredocs

        for name, script in _steps(_render(tmp_path, "pr\n")).items():
            r = subprocess.run(
                ["bash", "-n"], input=script, capture_output=True, text=True
            )
            assert r.returncode == 0, f"{name}: {r.stderr}"
            live = [ln for ln in _strip_heredocs(script) if re.search(r"(?<!\\)`", ln)]
            assert not live, f"{name}: {live}"


# --- the pr path at run time -----------------------------------------------


class TestThePrPath:
    def test_a_pr_rendered_run_whose_knob_says_direct_pushes_as_today(
        self, tmp_path: Path
    ):
        """The knob is read at run time: switched back to `direct` after a pr
        install, the run pushes to the default branch and never calls gh."""
        rig = Rig(tmp_path, knob="direct\n")
        rig.rendered = _render(tmp_path, "pr\n", "pr-render")
        r = rig.run("2026-10-08")
        assert r.returncode == 0, r.stdout + r.stderr
        assert rig.show("main") == ["2026-10-01", "2026-10-08"]
        assert rig.calls() == []
        assert not rig.has_branch(PR_BRANCH)

    def test_no_mode_in_the_environment_is_refused_not_read_as_direct(
        self, tmp_path: Path
    ):
        rig = Rig(tmp_path, knob="pr\n")
        r = rig.run("2026-10-08", mode_env="")
        assert r.returncode == 1, r.stdout
        assert rig.show("main") == ["2026-10-01"]
        assert "::error::" in r.stdout

    def test_a_human_commit_on_the_default_branch_between_runs_merges_in(
        self, tmp_path: Path
    ):
        """The PR's branch takes the default branch in every week, so it never
        conflicts with the branch it targets."""
        rig = Rig(tmp_path, knob="pr\n")
        assert rig.run("2026-10-08").returncode == 0
        human = rig.clone("human")
        (human / "NOTES.md").write_text("a human change\n")
        _git(human, "add", "-A")
        _git(human, "commit", "-qm", "human")
        _git(human, "push", "-q", "origin", "HEAD:main")
        r = rig.run("2026-10-15")
        assert r.returncode == 0, r.stdout + r.stderr
        assert rig.show(PR_BRANCH) == ["2026-10-01", "2026-10-08", "2026-10-15"]
        _git(rig.origin, "merge-base", "--is-ancestor", "main", PR_BRANCH)

    def test_after_the_pr_merges_the_branch_restarts_from_the_default_branch(
        self, tmp_path: Path
    ):
        """A squash merge leaves the old branch's commits unmerged by ancestry;
        appending to it would carry them again. A branch whose tip was a
        finished PR's head restarts at the default branch plus this row."""
        rig = Rig(tmp_path, knob="pr\n")
        assert rig.run("2026-10-08").returncode == 0
        # Squash-merge the PR by hand, and leave the branch in place.
        squash = rig.clone("squash")
        _git(squash, "fetch", "-q", "origin", PR_BRANCH)
        tip = _git(squash, "rev-parse", "FETCH_HEAD")
        _git(squash, "merge", "-q", "--squash", "FETCH_HEAD")
        _git(squash, "commit", "-qm", "chore: weekly context measurement (#7)")
        _git(squash, "push", "-q", "origin", "HEAD:main")
        (rig.gh / "prs").write_text(f"7 MERGED {tip}\n")
        r = rig.run("2026-10-15")
        assert r.returncode == 0, r.stdout + r.stderr
        assert rig.show(PR_BRANCH) == ["2026-10-01", "2026-10-08", "2026-10-15"]
        assert _git(rig.origin, "rev-parse", f"{PR_BRANCH}~1") == _git(
            rig.origin, "rev-parse", "main"
        ), "the branch should be the default branch plus one commit"
        assert len([c for c in rig.calls() if c.startswith("pr create")]) == 2

    def test_actions_not_allowed_to_open_prs_names_the_setting(self, tmp_path: Path):
        """Hazard 1: the token can push the branch, and the API refuses the PR.
        The row is on the branch; the error says which setting to turn on."""
        rig = Rig(tmp_path, knob="pr\n")
        (rig.gh / "create_err").write_text(
            "pull request create failed: GraphQL: GitHub Actions is not "
            "permitted to create or approve pull requests (createPullRequest)\n"
        )
        r = rig.run("2026-10-08")
        assert r.returncode == 1, r.stdout
        assert rig.show(PR_BRANCH) == ["2026-10-01", "2026-10-08"], (
            "the row must survive on the pushed branch"
        )
        assert "Allow GitHub Actions to create and approve pull requests" in r.stdout
        assert "::error::" in r.stdout

        # The setting turned on, the next run keeps that row rather than
        # restarting the branch over it: no PR ever took it.
        (rig.gh / "create_err").unlink()
        again = rig.run("2026-10-15")
        assert again.returncode == 0, again.stdout + again.stderr
        assert rig.show(PR_BRANCH) == ["2026-10-01", "2026-10-08", "2026-10-15"]
        assert rig.show("main") == ["2026-10-01"]

    def test_a_closed_pr_is_not_reopened_with_its_rows(self, tmp_path: Path):
        """Closed without merging is a human's no: the branch restarts."""
        rig = Rig(tmp_path, knob="pr\n")
        assert rig.run("2026-10-08").returncode == 0
        tip = _git(rig.origin, "rev-parse", PR_BRANCH)
        (rig.gh / "prs").write_text(f"7 CLOSED {tip}\n")
        r = rig.run("2026-10-15")
        assert r.returncode == 0, r.stdout + r.stderr
        assert rig.show(PR_BRANCH) == ["2026-10-01", "2026-10-15"]

    def test_gh_failing_to_list_is_not_read_as_no_pr(self, tmp_path: Path):
        rig = Rig(tmp_path, knob="pr\n")
        (rig.gh / "list_err").write_text("HTTP 401: Bad credentials\n")
        r = rig.run("2026-10-08")
        assert r.returncode == 1, r.stdout
        assert not rig.has_branch(PR_BRANCH)
        assert "gh pr list" in r.stdout

    def test_a_refused_branch_push_is_reported_once_not_retried(self, tmp_path: Path):
        """A ruleset covering the PR branch too: GH013, once."""
        rig = Rig(tmp_path, knob="pr\n")
        hook = rig.origin / "hooks" / "pre-receive"
        count = tmp_path / "pushes"
        hook.write_text(
            "#!/usr/bin/env bash\n"
            f'echo x >>"{count}"\n'
            'echo "remote: error: GH013: Repository rule violations found." >&2\n'
            "exit 1\n"
        )
        hook.chmod(0o755)
        r = rig.run("2026-10-08")
        assert r.returncode == 1, r.stdout
        assert count.read_text().count("x") == 1, "the refusal was retried"
        assert "GH013" in r.stdout + r.stderr
        assert PR_BRANCH in r.stdout


class TestAnOpenPrAlwaysWins:
    """CR 1804: a finished PR whose head is the tip set ENDED even when an
    OPEN PR shared that tip (one PR closed, another opened from the same
    head), so the run restarted the branch over the open PR's rows and then
    said it had updated that PR. And gh's --head matches a branch NAME, so a
    fork's PR from a same-named branch was read as this job's."""

    def test_a_closed_pr_sharing_the_open_prs_tip_does_not_restart_it(
        self, tmp_path: Path
    ):
        rig = Rig(tmp_path, knob="pr\n")
        assert rig.run("2026-10-08").returncode == 0
        tip = _git(rig.origin, "rev-parse", PR_BRANCH)
        (rig.gh / "prs").write_text(f"7 CLOSED {tip}\n8 OPEN {tip}\n")
        r = rig.run("2026-10-15")
        assert r.returncode == 0, r.stdout + r.stderr
        assert rig.show(PR_BRANCH) == ["2026-10-01", "2026-10-08", "2026-10-15"], (
            "the open PR's rows were force-pushed away"
        )
        assert "updated PR #8" in r.stdout

    @pytest.mark.skipif(shutil.which("jq") is None, reason="the fake gh runs --jq")
    def test_a_forks_pr_from_a_same_named_branch_is_not_this_jobs(self, tmp_path: Path):
        rig = Rig(tmp_path, knob="pr\n")
        fork = {"number": 9, "state": "OPEN", "headRefOid": "f" * 40}
        (rig.gh / "prs.json").write_text(
            json.dumps([dict(fork, isCrossRepository=True)])
        )
        r = rig.run("2026-10-08")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "PR #9" not in r.stdout, "a fork's PR was read as this job's"
        assert [c for c in rig.calls() if c.startswith("pr create")]

    @pytest.mark.skipif(shutil.which("jq") is None, reason="the fake gh runs --jq")
    def test_a_same_repo_pr_still_counts(self, tmp_path: Path):
        """The filter's other half: it keeps this repo's own PR."""
        rig = Rig(tmp_path, knob="pr\n")
        assert rig.run("2026-10-08").returncode == 0
        tip = _git(rig.origin, "rev-parse", PR_BRANCH)
        (rig.gh / "prs.json").write_text(
            json.dumps(
                [
                    {
                        "number": 7,
                        "state": "OPEN",
                        "headRefOid": tip,
                        "isCrossRepository": False,
                    }
                ]
            )
        )
        r = rig.run("2026-10-15")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "updated PR #7" in r.stdout
        assert rig.show(PR_BRANCH) == ["2026-10-01", "2026-10-08", "2026-10-15"]


def _repair_dry_run(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(RECORD_TELEMETRY), "--repair", "--dry-run", "--ledger", LEDGER],
        cwd=repo,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        env=_env(),
    )


class TestEachRowFollowsItsTruePredecessor:
    """CR 1803: the job checks out the default branch, whose ledger lacks the
    open PR's rows. Measured there, every row after the first took its
    delta_days and delta_tokens, and the seam sweep its --base-ledger
    interval, from the last MERGED row: the workflow's own delta check
    warned on every run while the PR was open, and the merge landed the
    wrong deltas."""

    def test_the_second_weeks_row_is_measured_after_the_first(self, tmp_path: Path):
        """The reviewer's reproduction: two scheduled runs a week apart with
        the PR left open, each row recorded by the real record-telemetry.sh."""
        rig = Rig(tmp_path, knob="pr\n")
        first = rig.run("2026-10-08", tokens=110)
        assert first.returncode == 0, first.stdout + first.stderr
        week1 = rig.rows(PR_BRANCH)[-1]
        assert (week1["delta_days"], week1["delta_tokens"]) == (7, 10)

        second = rig.run("2026-10-15", tokens=125)
        assert second.returncode == 0, second.stdout + second.stderr
        rows = rig.rows(PR_BRANCH)
        assert [r["ts"] for r in rows] == ["2026-10-01", "2026-10-08", "2026-10-15"]
        assert (rows[-1]["delta_days"], rows[-1]["delta_tokens"]) == (7, 15), (
            "week 2's deltas are against the default branch's last row, not the PR's"
        )
        assert rig.interval == f"{week1['repo_commit']}..worktree", (
            "the seam sweep spans the interval since the last MERGED row"
        )
        # The job's own Check the recorded deltas step, on what it pushed.
        check = _repair_dry_run(rig.runner)
        assert check.returncode == 0, check.stderr
        assert check.stdout == "", check.stdout

    def test_the_row_names_a_commit_the_default_branch_keeps(self, tmp_path: Path):
        """The branch comes in with --no-commit, so the row's repo_commit is
        the default branch's tip, which a squash merge cannot take away from
        the next run's sweep."""
        rig = Rig(tmp_path, knob="pr\n")
        assert rig.run("2026-10-08", tokens=110).returncode == 0
        main_tip = _git(rig.origin, "rev-parse", "main")
        r = rig.run("2026-10-15", tokens=125)
        assert r.returncode == 0, r.stdout + r.stderr
        assert main_tip.startswith(rig.rows(PR_BRANCH)[-1]["repo_commit"])
        assert "measuring after the rows" in rig.take.stdout

    def test_with_nothing_on_the_branch_nothing_is_taken_in(self, tmp_path: Path):
        rig = Rig(tmp_path, knob="pr\n")
        r = rig.run("2026-10-08", tokens=110)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "no rows on" in rig.take.stdout

    def test_a_finished_prs_rows_are_not_taken_in(self, tmp_path: Path):
        """Closed is a no: the row is measured after the default branch."""
        rig = Rig(tmp_path, knob="pr\n")
        assert rig.run("2026-10-08", tokens=110).returncode == 0
        tip = _git(rig.origin, "rev-parse", PR_BRANCH)
        (rig.gh / "prs").write_text(f"7 CLOSED {tip}\n")
        r = rig.run("2026-10-15", tokens=125)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "no rows on" in rig.take.stdout
        assert rig.rows(PR_BRANCH)[-1]["delta_days"] == 14

    def test_gh_failing_spends_no_measurement(self, tmp_path: Path):
        rig = Rig(tmp_path, knob="pr\n")
        (rig.gh / "list_err").write_text("HTTP 502\n")
        r = rig.run("2026-10-08")
        assert r.returncode == 1, r.stdout
        assert "nothing was measured" in r.stdout

    def test_the_take_and_the_push_decide_the_pr_the_same_way(self, tmp_path: Path):
        """Two readers of one decision. The push reads it again, since a PR
        can merge during the run, so they must read it identically."""
        steps = _steps(_render(tmp_path, "pr\n"))

        def decision(script: str) -> list[str]:
            lines = [ln.strip() for ln in script.splitlines()]
            start = next(i for i, ln in enumerate(lines) if ln.startswith("PRS=$("))
            end = next(
                i for i, ln in enumerate(lines) if ln.startswith('if [ -n "$TIP" ]')
            )
            return [
                ln.split(" || {")[0]
                for ln in lines[start : end + 1]
                if ln and not ln.startswith(("echo ", "exit ", "#"))
            ]

        take, push = decision(steps[TAKE_STEP]), decision(steps[COMMIT_STEP])
        assert take == push
        assert any("isCrossRepository" in ln for ln in take)

    def test_the_rows_come_in_before_the_sweep_and_after_the_preflight(
        self, tmp_path: Path
    ):
        doc = yaml.safe_load(_render(tmp_path, "pr\n"))
        names = [s.get("name", "") for s in doc["jobs"]["measure"]["steps"]]
        take = names.index(TAKE_STEP)
        assert names.index("Preflight the credential") < take
        assert take < names.index("Sweep the seams and the counts")


# --- install, --check, and a knob that changes after install ---------------


class TestInstallAndCheck:
    def _installed(self, tmp_path: Path, knob: str | None) -> Path:
        repo = _init(tmp_path / "r")
        _knob(repo, knob)
        r = _install(repo)
        assert r.returncode == 0, r.stdout + r.stderr
        return repo

    def test_check_says_nothing_new_for_absent_or_direct(self, tmp_path: Path):
        repo = self._installed(tmp_path, None)
        absent = _install(repo, "--check")
        _knob(repo, "direct\n")
        direct = _install(repo, "--check")
        assert absent.returncode == direct.returncode == 0
        assert absent.stdout == direct.stdout
        assert "merge mode" not in absent.stdout

    def test_a_knob_set_to_pr_after_a_direct_install_is_stale(self, tmp_path: Path):
        repo = self._installed(tmp_path, None)
        _knob(repo, "pr\n")
        r = _install(repo, "--check")
        assert r.returncode == 3, r.stdout
        assert "merge mode:         STALE" in r.stdout
        # The advertised remedy works.
        assert _install(repo).returncode == 0
        again = _install(repo, "--check")
        assert again.returncode == 0, again.stdout
        assert "merge mode:         pr" in again.stdout

    def test_a_pr_install_whose_knob_goes_back_to_direct_says_so(self, tmp_path: Path):
        repo = self._installed(tmp_path, "pr\n")
        (repo / ".skills" / "merge_mode").unlink()
        r = _install(repo, "--check")
        assert r.returncode == 0, r.stdout
        assert "merge mode:" in r.stdout and "pull-requests: write" in r.stdout

    def test_an_unusable_knob_installs_nothing(self, tmp_path: Path):
        repo = _init(tmp_path / "r")
        _knob(repo, "PR\n")
        r = _install(repo)
        assert r.returncode == 5, r.stdout + r.stderr
        assert not (repo / ".github").exists()
        assert not (repo / ".gitattributes").exists()
        assert "pr" in r.stderr and "direct" in r.stderr

    def test_check_reports_an_unusable_knob(self, tmp_path: Path):
        repo = self._installed(tmp_path, None)
        _knob(repo, "pull-request\n")
        r = _install(repo, "--check")
        assert r.returncode == 3, r.stdout
        assert "merge mode:         UNUSABLE" in r.stdout

    def test_a_pr_install_says_what_github_needs(self, tmp_path: Path):
        repo = _init(tmp_path / "r")
        _knob(repo, "pr\n")
        r = _install(repo)
        assert r.returncode == 0, r.stderr
        assert "Allow GitHub Actions to create and approve pull requests" in r.stdout
        # The knob is untracked here, and the job reads the committed one.
        assert "commit .skills/merge_mode" in r.stdout.lower()

    def test_a_pr_knob_committed_as_direct_is_not_committed_as_it_reads(
        self, tmp_path: Path
    ):
        """CR 1810: tracked is not committed. With `direct` committed and the
        working file edited to `pr`, the installer rendered pr and said
        nothing, while the job reads the committed `direct`."""
        repo = _init(tmp_path / "r")
        _knob(repo, "direct\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "knob")
        _knob(repo, "pr\n")
        r = _install(repo)
        assert r.returncode == 0, r.stderr
        assert READ_STEP in (repo / ".github/workflows/context-cadence.yml").read_text()
        assert "not committed" in r.stdout
        check = _install(repo, "--check")
        assert "not committed" in check.stdout, check.stdout

    def test_a_pr_knob_committed_as_it_reads_says_nothing_more(self, tmp_path: Path):
        repo = _init(tmp_path / "r")
        _knob(repo, "pr\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "knob")
        r = _install(repo)
        assert r.returncode == 0, r.stderr
        assert "not committed" not in r.stdout
        assert "not committed" not in _install(repo, "--check").stdout

    def test_a_staged_but_uncommitted_pr_knob_is_not_committed(self, tmp_path: Path):
        repo = _init(tmp_path / "r")
        (repo / "README.md").write_text("x\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        _knob(repo, "pr\n")
        _git(repo, "add", "-A")
        r = _install(repo)
        assert r.returncode == 0, r.stderr
        assert "not committed" in r.stdout

    def test_a_direct_install_prints_todays_closing_text(self, tmp_path: Path):
        # Same basename, so the same derived cron.
        a = _install(_init(tmp_path / "a" / "r"))
        b_repo = _init(tmp_path / "b" / "r")
        _knob(b_repo, "direct\n")
        b = _install(b_repo)
        assert a.returncode == b.returncode == 0
        assert a.stdout == b.stdout
        assert "pull request" not in a.stdout.lower()

    def test_a_template_that_moved_an_anchor_renders_nothing_for_pr(
        self, tmp_path: Path
    ):
        """The pr shape is spliced in after five anchor lines. A template edit
        that moved one must fail the render, not install a pr workflow
        missing a piece, and must leave the installed file as it was."""
        broken = tmp_path / "scripts" / "install-cadence.sh"
        broken.parent.mkdir()
        text = INSTALL_CADENCE.read_text()
        assert text.count("          # --- push ---\n") == 1
        broken.write_text(text.replace("          # --- push ---\n", ""))
        (broken.parent / "merge-token-counts.sh").write_text(
            MERGE_TOKEN_COUNTS.read_text()
        )
        repo = self._installed(tmp_path, None)
        wf = repo / ".github" / "workflows" / "context-cadence.yml"
        before = wf.read_text()
        _knob(repo, "pr\n")
        for args in (["--print"], []):
            r = subprocess.run(
                ["bash", str(broken), *args],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=60,
                env=_env(),
            )
            assert r.returncode != 0, r.stdout
            assert "anchors" in r.stderr, r.stderr
            assert "Read the merge mode" not in r.stdout
        assert wf.read_text() == before, "a failed render touched the workflow"
