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
  renders today's bytes; `pr` renders today's bytes plus four insertions:
  `pull-requests: write`, a `Read the merge mode` step, `GH_TOKEN` on the
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
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "skills" / "curating-context" / "scripts"
INSTALL_CADENCE = SCRIPTS / "install-cadence.sh"
MERGE_TOKEN_COUNTS = SCRIPTS / "merge-token-counts.sh"
MERGE_MODE_SH = REPO_ROOT / "skills" / "shipping-work" / "scripts" / "merge-mode.sh"
THIS_REPOS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "context-cadence.yml"

LEDGER = ".skills/context-metrics.jsonl"
PR_BRANCH = "context/weekly-measurement"
READ_STEP = "Read the merge mode"
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
# `pr create` records an OPEN PR whose head is the pushed HEAD, unless
# $FAKE_GH/create_err exists, whose text it prints to stderr.
printf '%s\n' "$*" >>"$FAKE_GH/calls"
case "$1 $2" in
  "pr list")
    [ ! -f "$FAKE_GH/list_err" ] || { cat "$FAKE_GH/list_err" >&2; exit 1; }
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
        return json.dumps({"ts": ts, "repo": "r", "tokens": 100}, sort_keys=True)

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

    def run(self, ts: str, mode_env: str | None = None) -> subprocess.CompletedProcess:
        """One scheduled run: a fresh clone of main, the knob read (when the
        render has that step), one row appended, the commit step run."""
        self.runs += 1
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
        if READ_STEP in _steps(self.rendered):
            read = self.step(READ_STEP, runner, env)
            assert read.returncode == 0, read.stdout + read.stderr
            for line in gh_env.read_text().splitlines():
                k, _, v = line.partition("=")
                env[k] = v
        if mode_env is not None:
            env["MERGE_MODE"] = mode_env
        led = runner / LEDGER
        led.write_text(led.read_text() + self.row(ts) + "\n")
        return self.step(COMMIT_STEP, runner, env)

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

# The inputs test_merge_mode_knob.py pins merge-mode.sh to, plus absence.
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
        """The pr shape is spliced in after four anchor lines. A template edit
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
