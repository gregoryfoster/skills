"""#576 — the doctor warns when `merge_mode` `pr` leaves the refresh hook no token.

Under `.skills/merge_mode` `pr` the refresh hook opens its pull request with
gh. With no token from any source it refuses before refreshing, once a day, on
stderr (test_refresh_hook_pr_gh_auth.py), and until #576 every other check read
healthy. The doctor is the one check every session runs.

What this file pins:

- **No token is said**, naming the .env and the remedy, and so is gh missing
  from PATH.
- **The hook's sources count, this shell's export does not**: a GH_TOKEN in
  the repo .env (the primary checkout's, from a linked worktree) or gh's
  stored login silences it. The doctor's own GH_TOKEN or GITHUB_TOKEN does not:
  a SessionStart hook never sees an agent shell's export.
- **Silent where it has nothing to say**: no hook installed, or a knob that
  is absent, `direct`, or anything `merge-mode.sh` does not read as `pr`.
- **Advisory in every mode**: the exit code never moves, `--check-only`
  included.
- **The readers agree**: the doctor reads `pr` exactly when `merge-mode.sh`
  does, and its `env_value` answers as the hook's `_env_value` does.
- **From the primary the hook reads** (CR 1893): in a bare primary and a
  submodule the first `git worktree list` entry is a git dir, so the knob
  and the `.env` fallback are read from the work tree resolved as the hook
  resolves it.
"""

import os
import re
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.structural import merge_mode_layouts as layouts
from tests.structural.test_cadence_merge_mode import CASES, _merge_mode_sh
from tests.structural.test_refresh_hook_pr_gh_auth import ENV_CASES

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "skills" / "managing-skills" / "scripts"
DOCTOR = SCRIPTS / "doctor.sh"
HOOK = SCRIPTS / "skills-submodule-update.sh"

MARKER = "the refresh hook may have no token"
NO_GH = "gh is not on this shell's PATH"

# Real gh's shape for `auth token`: it prints an environment token when one is
# set, else the stored login's, else fails. $LOGIN stands for a stored login.
FAKE_GH = r"""#!/usr/bin/env bash
[ "$1 $2" = "auth token" ] || { echo "fake gh: unhandled: $*" >&2; exit 64; }
if [ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]; then echo env-token; exit 0; fi
[ -f "@LOGIN@" ] && { echo stored-token; exit 0; }
echo "no oauth token found for github.com" >&2
exit 1
"""


def _env(bindir: Path, **extra: str) -> dict:
    """GIT_* scrubbed (#189), no token, the fake gh first on PATH."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("GH_TOKEN", "GITHUB_TOKEN"):
        env.pop(k, None)
    env["PATH"] = f"{bindir}:{env.get('PATH', '/usr/bin:/bin')}"
    env.update(extra)
    return env


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        env=_env(Path("/nonexistent")),
        timeout=60,
    )


@pytest.fixture
def consumer(tmp_path: Path):
    repo = tmp_path / "consumer"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / ".claude" / "hooks").mkdir(parents=True)
    (repo / ".claude" / "hooks" / "skills-submodule-update.sh").write_text(
        "#!/bin/sh\n"
    )
    (repo / ".skills").mkdir()
    (repo / ".skills" / "merge_mode").write_text("pr\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    login = tmp_path / "gh-login"
    gh = bindir / "gh"
    gh.write_text(FAKE_GH.replace("@LOGIN@", str(login)))
    gh.chmod(0o755)
    return SimpleNamespace(path=repo, bindir=bindir, login=login)


def _tools_without_gh(tmp_path: Path) -> Path:
    """A PATH directory holding every runnable on this PATH except gh."""
    tools = tmp_path / "tools"
    tools.mkdir()
    for d in os.environ.get("PATH", "/usr/bin:/bin").split(os.pathsep):
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name == "gh" or (tools / name).exists() or (tools / name).is_symlink():
                continue
            src = Path(d) / name
            try:
                runnable = src.is_file() and os.access(src, os.X_OK)
            except OSError:
                runnable = False
            if runnable:
                (tools / name).symlink_to(src)
    return tools


def _doctor(c, *args: str, cwd: Path | None = None, **env: str):
    return subprocess.run(
        ["bash", str(DOCTOR), "--no-preflight", *args],
        cwd=str(cwd or c.path),
        capture_output=True,
        text=True,
        env=_env(c.bindir, **env),
        timeout=120,
    )


class TestItSays:
    def test_no_token_anywhere_is_said_with_the_remedy(self, consumer):
        result = _doctor(consumer)
        assert result.returncode == 0, result.stderr
        assert MARKER in result.stderr, result.stderr
        assert ".env sets no GH_TOKEN" in result.stderr
        assert "gh auth login" in result.stderr and "#576" in result.stderr

    def test_this_shells_own_token_does_not_count(self, consumer):
        """The agent shell exports GH_TOKEN per command; the hook never sees
        it. Real gh answers `auth token` from it, so it is unset for the ask."""
        for name in ("GH_TOKEN", "GITHUB_TOKEN"):
            result = _doctor(consumer, **{name: "shell-export"})
            assert MARKER in result.stderr, (name, result.stderr)

    def test_gh_missing_from_path_is_said(self, consumer, tmp_path):
        (consumer.bindir / "gh").unlink()
        result = _doctor(consumer, PATH=str(_tools_without_gh(tmp_path)))

        assert result.returncode == 0, result.stderr
        assert NO_GH in result.stderr, result.stderr
        assert MARKER not in result.stderr


class TestTheHooksSourcesSilenceIt:
    @pytest.mark.parametrize(
        "text", ["GH_TOKEN=t\n", "export GH_TOKEN='t'\n", "OTHER=1\nGH_TOKEN=t\n"]
    )
    def test_a_token_in_the_repo_env(self, consumer, text):
        (consumer.path / ".env").write_text(text)
        result = _doctor(consumer)
        assert MARKER not in result.stderr, result.stderr

    def test_an_env_without_gh_token_is_still_said(self, consumer):
        (consumer.path / ".env").write_text("OTHER=1\n# GH_TOKEN=commented\n")
        result = _doctor(consumer)
        assert MARKER in result.stderr, result.stderr

    def test_ghs_stored_login(self, consumer):
        consumer.login.write_text("")
        result = _doctor(consumer)
        assert MARKER not in result.stderr, result.stderr

    def test_a_linked_worktree_reads_the_primarys_knob_and_env(
        self, consumer, tmp_path
    ):
        """Both are git-ignored in a cohort repo, so exist only there."""
        (consumer.path / "README.md").write_text("x\n")
        _git(consumer.path, "add", "README.md")
        _git(
            consumer.path,
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-qm",
            "init",
        )
        wt = tmp_path / "wt"
        _git(consumer.path, "worktree", "add", "-q", "-b", "feature/x", str(wt))
        (wt / ".claude" / "hooks").mkdir(parents=True)
        (wt / ".claude" / "hooks" / "skills-submodule-update.sh").write_text("")

        said = _doctor(consumer, cwd=wt)
        assert MARKER in said.stderr, said.stderr
        primary = subprocess.run(
            ["git", "-C", str(wt), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            env=_env(Path("/nonexistent")),
            timeout=60,
        ).stdout.split("\n")[0]
        named = primary.removeprefix("worktree ") + "/.env sets no GH_TOKEN"
        assert named in said.stderr, said.stderr

        (consumer.path / ".env").write_text("GH_TOKEN=t\n")
        quiet = _doctor(consumer, cwd=wt)
        assert MARKER not in quiet.stderr, quiet.stderr


def _primary(checkout: Path) -> Path:
    """The primary work tree, as the hook's _read_merge_mode resolves it."""
    first = layouts.git(checkout, "worktree", "list", "--porcelain").split("\n\n")[0]
    if "\nbare" in first:
        return checkout.resolve()
    entry = Path(first.splitlines()[0].removeprefix("worktree "))
    return Path(layouts.git(entry, "rev-parse", "--show-toplevel"))


def _layout_consumer(c, checkout: Path) -> Path:
    """`checkout` with the hook installed, as the doctor finds it."""
    hooks = checkout / ".claude" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "skills-submodule-update.sh").write_text("#!/bin/sh\n")
    return checkout


class TestItReadsThePrimaryAsTheHookDoes:
    """CR 1893: the doctor read the knob and the .env fallback from the raw
    first `git worktree list` entry, a git dir in a bare primary and in a
    submodule, so it was silent where the hook refuses every day. It resolves
    the primary as the hook's _read_merge_mode does, and says nothing when
    that fails: the hook names an unusable knob itself, every run."""

    @pytest.mark.parametrize("layout", sorted(layouts.LAYOUTS))
    def test_gh_missing_is_said_in_each_layout(self, consumer, tmp_path, layout):
        checkout = _layout_consumer(
            consumer, layouts.LAYOUTS[layout](tmp_path / "l", "pr\n")
        )
        result = _doctor(consumer, cwd=checkout, PATH=str(_tools_without_gh(tmp_path)))
        assert NO_GH in result.stderr, result.stderr

    @pytest.mark.parametrize("layout", sorted(layouts.LAYOUTS))
    def test_the_primarys_env_answers_in_each_layout(self, consumer, tmp_path, layout):
        checkout = _layout_consumer(
            consumer, layouts.LAYOUTS[layout](tmp_path / "l", "pr\n")
        )
        primary = _primary(checkout)
        said = _doctor(consumer, cwd=checkout)
        assert MARKER in said.stderr, said.stderr
        named = ".env" if primary == checkout.resolve() else f"{primary}/.env"
        assert f"{named} sets no GH_TOKEN" in said.stderr, said.stderr

        (primary / ".env").write_text("GH_TOKEN=t\n")
        quiet = _doctor(consumer, cwd=checkout)
        assert MARKER not in quiet.stderr, quiet.stderr

    def test_a_separate_git_dir_primary(self, consumer, tmp_path):
        """CR 1892's layout: from the primary, its own knob."""
        primary, _ = layouts.separate_git_dir(tmp_path / "l", "pr\n")
        _layout_consumer(consumer, primary)
        result = _doctor(consumer, cwd=primary, PATH=str(_tools_without_gh(tmp_path)))
        assert NO_GH in result.stderr, result.stderr


class TestSilentWhereItHasNothingToSay:
    def test_without_the_hook_installed(self, consumer):
        (consumer.path / ".claude" / "hooks" / "skills-submodule-update.sh").unlink()
        result = _doctor(consumer)
        assert MARKER not in result.stderr, result.stderr

    @pytest.mark.parametrize("text", CASES, ids=[repr(c) for c in CASES])
    def test_it_speaks_exactly_when_merge_mode_sh_reads_pr(self, consumer, text):
        knob = consumer.path / ".skills" / "merge_mode"
        knob.unlink()
        if text is not None:
            knob.write_text(text)
        want = _merge_mode_sh(consumer.path) == (0, "pr")
        result = _doctor(consumer)
        assert (MARKER in result.stderr) == want, (text, result.stderr)


@pytest.mark.parametrize("mode", [[], ["--check-only"]], ids=["default", "check-only"])
def test_advisory_in_every_mode(consumer, mode):
    (consumer.path / ".env").write_text("GH_TOKEN=t\n")
    baseline = _doctor(consumer, *mode)
    assert MARKER not in baseline.stderr
    (consumer.path / ".env").unlink()
    result = _doctor(consumer, *mode)
    assert MARKER in result.stderr, result.stderr
    assert result.returncode == baseline.returncode


def _function(path: Path, name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", path.read_text(), re.M | re.S)
    assert m, f"{path.name} has no {name}() at column 0"
    return m.group(0)


@pytest.mark.parametrize("text", ENV_CASES, ids=[repr(t) for t in ENV_CASES])
def test_the_doctor_reads_the_env_as_the_hook_does(tmp_path, text):
    envfile = tmp_path / ".env"
    envfile.write_text(text)
    f = shlex.quote(str(envfile))
    answers = []
    for path, name in ((DOCTOR, "env_value"), (HOOK, "_env_value")):
        r = subprocess.run(
            [
                "bash",
                "-c",
                "set -euo pipefail\n"
                + _function(path, name)
                + f"{name} {f} GH_TOKEN\n",
            ],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            timeout=30,
        )
        assert r.returncode == 0, r.stderr
        answers.append(r.stdout)
    assert answers[0] == answers[1], text
