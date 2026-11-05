"""#576 — the refresh hook's `pr` path can authenticate gh and name its repo.

Under `.skills/merge_mode` `pr` no cohort consumer had opened a PR. Two
defects stopped it, both in the `pr` path:

1. gh had no token in the hook's environment. Cohort hosts keep GH_TOKEN only
   in the git-ignored repo `.env`, which agents load per command, and a
   SessionStart hook runs beside the others, so no export reaches it. The run
   refused at `gh pr list`, after a whole refresh.
2. An SSH-alias remote (`git@github-processor:o/r.git`) became gh's --repo
   host, which gh took for an Enterprise host.

Decided on #576 (comment 6649355308): the hook reads the token itself — the
environment, then the `.env` as data, then gh's stored login — and hands a
`.env` token to gh (and to the https remote's network git calls) per call,
never to its own environment: the refresh runs the new pointer's
install-doctor.sh before anyone has reviewed the bump. No token from any
source is refused in the preflight, before the refresh. `_gh_repo_of` resolves
an SSH host through `ssh -G`. An https remote's push gets gh as a credential
helper.

Fixtures as in test_refresh_hook_pr_mode.py: `gh` and `ssh` are fakes on
PATH, the remote is a local bare repo, and a remote URL that names GitHub is
rewritten onto it by `url.<origin>.insteadOf`. Not available here: a real gh,
a real ssh_config, a real GitHub.
"""

import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.structural.test_pre_ship_env_override import _extract_loader
from tests.structural.test_refresh_hook_pr_mode import (
    PR_BRANCH,
    _assert_content_matches_pointer,
    _calls,
    _commit_knob,
    _creates,
    _gh,
    _main_never_moved,
    _origin,
)
from tests.utils.refresh_hook_consumer import (
    HOOK,
    MS_SCRIPTS,
    build,
    clean_env,
    finish_hook,
    git,
    lock,
    log_text,
    today,
)

TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN")

FAKE_SSH = r"""#!/usr/bin/env bash
# A stand-in for `ssh -G <host>`: prints `hostname <name>` from $MAP, one
# `<alias> <hostname>` per line, else the name itself, as ssh does for a host
# no Host block matches. A name listed in $FAIL exits 255. Logs every call.
printf '%s\n' "$*" >>"@CALLS@"
[ "$1" = "-G" ] || exit 64
shift
[ "$1" != "--" ] || shift
if grep -qxF -- "$1" "@FAIL@" 2>/dev/null; then exit 255; fi
name=$(awk -v h="$1" '$1 == h { print $2; exit }' "@MAP@" 2>/dev/null)
echo "user git"
echo "hostname ${name:-$1}"
echo "port 22"
"""


def _fake_ssh(
    bindir: Path, mapping: dict[str, str], fail: tuple[str, ...] = ()
) -> Path:
    """Installs the fake ssh in `bindir`; returns its call log."""
    calls = bindir.parent / "ssh-calls"
    mapfile = bindir.parent / "ssh-map"
    failfile = bindir.parent / "ssh-fail"
    mapfile.write_text("".join(f"{k} {v}\n" for k, v in mapping.items()))
    failfile.write_text("".join(f"{h}\n" for h in fail))
    fake = bindir / "ssh"
    fake.write_text(
        FAKE_SSH.replace("@CALLS@", str(calls))
        .replace("@MAP@", str(mapfile))
        .replace("@FAIL@", str(failfile))
    )
    fake.chmod(0o755)
    return calls


def _function(name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", HOOK.read_text(), re.M | re.S)
    assert m, f"the hook has no {name}() at column 0"
    return m.group(0)


def _bash(script: str, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + script],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _no_token_env() -> dict:
    env = clean_env()
    for k in TOKEN_VARS:
        env.pop(k, None)
    return env


def _run(c, **extra: str) -> subprocess.CompletedProcess:
    """A session start with no token in the environment, plus `extra`."""
    env = _no_token_env()
    env["PATH"] = f"{c.bindir}:{env.get('PATH', '/usr/bin:/bin')}"
    env.update(extra)
    proc = subprocess.Popen(
        ["bash", str(HOOK)],
        cwd=c.path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    return finish_hook(proc)


def _dotenv(c, text: str) -> None:
    """The consumer's git-ignored .env, as the cohort keeps it."""
    (c.path / ".env").write_text(text)
    with (c.path / ".git" / "info" / "exclude").open("a") as f:
        f.write(".env\n")


def _tokens(c) -> list[str]:
    """The GH_TOKEN each gh call that reaches GitHub was given."""
    f = c.gh / "tokens"
    return f.read_text().splitlines() if f.exists() else []


@pytest.fixture
def pr_consumer(tmp_path):
    """test_refresh_hook_pr_mode.py's consumer: the knob committed, gh faked."""
    c = build(tmp_path)
    _commit_knob(c, "pr\n")
    c.gh = _gh(c)
    c.main0 = _origin(c, "main")
    c.head0 = git(c.path, "rev-parse", "HEAD").stdout.strip()
    return c


def _remote_as(c, url: str) -> None:
    """origin's configured URL becomes `url`; git reaches the bare repo still."""
    git(c.path, "remote", "set-url", "origin", url)
    git(c.path, "config", f"url.{c.origin}.insteadOf", url)


# --- _gh_repo_of: a host gh can use, or nothing --------------------------------

ALIASES = {
    "github-processor": "github.com",
    "github-archiver": "github.com",
    "ssh443": "ssh.github.com",
}

REPO_CASES = [
    ("https://github.com/o/r.git", "github.com/o/r"),
    ("https://github.com/o/r", "github.com/o/r"),
    ("https://x-access-token:abc@github.com/o/r.git", "github.com/o/r"),
    ("git@github.com:o/r.git", "github.com/o/r"),
    # The #576 cases: a deploy-key alias, with and without a user.
    (
        "git@github-processor:CannObserv/processor.git",
        "github.com/CannObserv/processor",
    ),
    ("github-archiver:CannObserv/archiver.git", "github.com/CannObserv/archiver"),
    ("ssh://git@github-processor:22/o/r.git", "github.com/o/r"),
    ("git+ssh://github-processor/o/r.git", "github.com/o/r"),
    # SSH over 443 is github.com to gh.
    ("git@ssh443:o/r.git", "github.com/o/r"),
    # Not a host's: gh resolves the repo from the checkout.
    ("/srv/git/r.git", ""),
    ("./rel/r", ""),
    ("file:///srv/git/r.git", ""),
    ("https://github.com/o/r/extra", ""),
    ("git@github.com:r.git", ""),
]


def _repo_of(tmp_path: Path, url: str, fail: tuple[str, ...] = ()) -> tuple[str, Path]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    calls = _fake_ssh(bindir, ALIASES, fail)
    env = clean_env()
    env["PATH"] = f"{bindir}:{env.get('PATH', '/usr/bin:/bin')}"
    r = _bash(
        f"LOG={shlex.quote(str(tmp_path / 'log'))}\n"
        '_log() { echo "$*" >>"$LOG"; }\n'
        + _function("_gh_repo_of")
        + f"_gh_repo_of {shlex.quote(url)}\n",
        tmp_path,
        env,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip(), calls


class TestTheRepoGhIsGiven:
    @pytest.mark.parametrize("url,want", REPO_CASES, ids=[u for u, _ in REPO_CASES])
    def test_each_remote_shape(self, tmp_path, url, want):
        got, _ = _repo_of(tmp_path, url)
        assert got == want, url

    def test_an_ssh_host_ssh_cannot_name_omits_repo_and_says_so(self, tmp_path):
        got, _ = _repo_of(tmp_path, "git@broken-alias:o/r.git", fail=("broken-alias",))
        assert got == ""
        assert "broken-alias" in (tmp_path / "log").read_text()

    def test_an_option_shaped_host_never_reaches_ssh(self, tmp_path):
        """git refuses a host that begins with `-` (CVE-2017-1000117); so
        does this, before ssh can read it as an option."""
        got, calls = _repo_of(tmp_path, "git@-oProxyCommand=touch%20x:o/r.git")
        assert got == ""
        assert not calls.exists() or calls.read_text() == ""

    def test_an_https_host_is_not_looked_up(self, tmp_path):
        _, calls = _repo_of(tmp_path, "https://github.com/o/r.git")
        assert not calls.exists() or calls.read_text() == ""


# --- _env_value: load_env's grammar, for one name -------------------------------

ENV_CASES = [
    "GH_TOKEN=plain\n",
    "export GH_TOKEN=exported\n",
    'GH_TOKEN="double quoted"\n',
    "GH_TOKEN='single quoted'\n",
    "   GH_TOKEN=leading-blanks\n",
    "GH_TOKEN =key-blank\n",
    "# GH_TOKEN=commented\n",
    "GH_TOKEN=first\nGH_TOKEN=last\n",
    "OTHER=x\nGH_TOKEN=amid\nMORE=y\n",
    "GH_TOKEN=$(touch pwned)\n",
    "GH_TOKEN=a=b=c\n",
    "GH_TOKEN=no-newline",
    "GH_TOKENS=not-it\n",
    "GH_TOKEN=\n",
    "",
]


class TestTheReaderHoldsLoadEnvsGrammar:
    @pytest.mark.parametrize("text", ENV_CASES, ids=[repr(t) for t in ENV_CASES])
    def test_it_answers_as_load_env_does(self, tmp_path, text):
        envfile = tmp_path / ".env"
        envfile.write_text(text)
        f = shlex.quote(str(envfile))
        env = _no_token_env()
        want = _bash(
            _extract_loader("shipping-work")
            + f'\nload_env {f}\nprintf "%s" "${{GH_TOKEN:-}}"\n',
            tmp_path,
            env,
        )
        got = _bash(
            _function("_env_value") + f"_env_value {f} GH_TOKEN\n", tmp_path, env
        )
        assert want.returncode == 0 and got.returncode == 0, (want.stderr, got.stderr)
        assert got.stdout == want.stdout, text
        assert not (tmp_path / "pwned").exists(), "the .env was executed"

    def test_an_absent_file_is_nothing(self, tmp_path):
        got = _bash(
            _function("_env_value") + "_env_value ./absent GH_TOKEN\n",
            tmp_path,
            _no_token_env(),
        )
        assert got.returncode == 0 and got.stdout == ""


def _token_source(cwd: Path, env: dict) -> tuple[int, str, str]:
    r = _bash(
        'PR_GH_REPO="github.com/o/r"\n'
        + _function("_env_value")
        + _function("_pr_token")
        + 'rc=0; _pr_token || rc=$?\nprintf "%s\\n%s\\n%s" "$rc" "$PR_TOKEN_FROM" "$PR_GH_TOKEN"\n',
        cwd,
        env,
    )
    assert r.returncode == 0, r.stderr
    rc, src, tok = r.stdout.split("\n")
    return int(rc), src, tok


class TestWhereTheTokenComesFrom:
    def test_a_linked_worktree_reads_the_primary_checkouts_env(self, tmp_path):
        """A git-ignored .env exists only in the primary checkout."""
        repo = tmp_path / "r"
        git(tmp_path, "init", "-q", "-b", "main", str(repo))
        (repo / "README.md").write_text("x\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "init")
        (repo / ".env").write_text("GH_TOKEN=primary\n")
        wt = tmp_path / "wt"
        git(repo, "worktree", "add", "-q", "-b", "feature/x", str(wt))
        env = _no_token_env()
        env["PATH"] = "/usr/bin:/bin"  # no gh: the .env must answer alone

        rc, src, tok = _token_source(wt, env)

        # The primary as `git worktree list` names it (macOS resolves /var).
        primary = git(wt, "worktree", "list", "--porcelain").stdout.split("\n")[0]
        assert (rc, tok) == (0, "primary")
        assert src == primary.removeprefix("worktree ") + "/.env", src

    def test_the_environment_outranks_the_env_file(self, tmp_path):
        git(tmp_path, "init", "-q", "-b", "main", str(tmp_path / "r"))
        (tmp_path / "r" / ".env").write_text("GH_TOKEN=from-dotenv\n")
        env = _no_token_env()
        env["GITHUB_TOKEN"] = "from-env"

        rc, src, tok = _token_source(tmp_path / "r", env)

        assert rc == 0 and "environment" in src
        assert tok == "", "an environment token is gh's to read, not the hook's to hold"


# --- end to end ---------------------------------------------------------------


def _installer_records_its_token(c) -> Path:
    """An upstream commit whose install-doctor.sh writes the GH_TOKEN it was
    run with. The refresh runs it before any human has seen the bump."""
    seen = c.path.parent / "installer-saw"
    inst = c.up / MS_SCRIPTS / "install-doctor.sh"
    lines = inst.read_text().split("\n", 1)
    inst.write_text(
        lines[0]
        + f'\nprintf "%s\\n" "${{GH_TOKEN:-absent}}" >>{shlex.quote(str(seen))}\n'
        + lines[1]
    )
    git(c.up, "add", "-A")
    git(c.up, "commit", "-qm", "vendor: an installer that reports its environment")
    return seen


class TestTheTokenReachesGhAlone:
    def test_a_token_in_the_env_file_opens_the_pr_and_never_reaches_the_installer(
        self, pr_consumer
    ):
        """status's case: no token in the hook's environment, no stored login,
        GH_TOKEN in the repo .env."""
        c = pr_consumer
        _dotenv(c, "OTHER=1\nGH_TOKEN=from-dotenv\n")
        (c.gh / "no_login").write_text("")
        seen = _installer_records_its_token(c)

        result = _run(c)

        assert result.returncode == 0, result.stderr
        assert "token" not in result.stderr, result.stderr
        assert len(_creates(c.gh)) == 1, _calls(c.gh)
        assert _tokens(c) and set(_tokens(c)) == {"from-dotenv"}, _tokens(c)
        assert seen.read_text().split() and set(seen.read_text().split()) == {
            "absent"
        }, "the .env's token reached the new pointer's installer"
        assert "from-dotenv" not in log_text(c), "the token was logged"
        assert "pr: gh's token comes from .env\n" in log_text(c), log_text(c)
        _main_never_moved(c)
        _assert_content_matches_pointer(c)

    def test_a_token_github_rejects_is_named_by_its_source(self, pr_consumer):
        """The preflight found one, so a refused `gh pr list` means GitHub
        rejected that token; `gh auth status` in another shell can't see it."""
        c = pr_consumer
        _dotenv(c, "GH_TOKEN=stale\n")
        (c.gh / "list_err").write_text("HTTP 401: Bad credentials\n")

        result = _run(c)

        assert result.returncode == 0, result.stderr
        assert "token from .env" in result.stderr, result.stderr
        assert "Bad credentials" in result.stderr
        assert "stale" not in result.stderr, "the token was printed"

    def test_the_hooks_own_environment_outranks_the_env_file(self, pr_consumer):
        c = pr_consumer
        _dotenv(c, "GH_TOKEN=from-dotenv\n")

        result = _run(c, GH_TOKEN="from-env")

        assert result.returncode == 0, result.stderr
        assert len(_creates(c.gh)) == 1
        assert set(_tokens(c)) == {"from-env"}

    def test_gh_s_stored_login_is_the_last_resort(self, pr_consumer):
        c = pr_consumer

        result = _run(c)

        assert result.returncode == 0, result.stderr
        assert len(_creates(c.gh)) == 1
        assert set(_tokens(c)) == {""}, "no token is handed to gh with its own login"
        assert "stored login" in log_text(c)
        # The line the refused run below is held never to write.
        assert "timing: refresh done" in log_text(c)

    def test_no_token_anywhere_is_refused_before_the_refresh(self, pr_consumer):
        """It used to be found at `gh pr list`, after a whole refresh."""
        c = pr_consumer
        (c.gh / "no_login").write_text("")

        first = _run(c)

        assert first.returncode == 0, first.stderr
        assert "no token" in first.stderr, first.stderr
        assert "gh auth login" in first.stderr and ".env" in first.stderr
        assert _calls(c.gh) == [], "gh was asked to reach GitHub with no token"
        assert _origin(c, PR_BRANCH) == ""
        assert "pr: proposing" not in log_text(c)
        assert "timing: refresh done" not in log_text(c), "the refresh ran"
        _main_never_moved(c)
        _assert_content_matches_pointer(c)
        assert lock(c).read_text().strip() == today()

        later = _run(c)
        assert later.stderr == "", "reported again the same day"


class TestTheRemoteGhIsPointedAt:
    def test_an_ssh_alias_remote_gives_gh_github_com(self, pr_consumer):
        """processor's case: `git@github-processor:…` under a Host alias."""
        c = pr_consumer
        _fake_ssh(c.bindir, {"github-processor": "github.com"})
        _remote_as(c, "git@github-processor:CannObserv/processor.git")

        result = _run(c, GH_TOKEN="t")

        assert result.returncode == 0, result.stderr
        lists = [x for x in _calls(c.gh) if x.startswith("pr list")]
        assert lists and lists[0].endswith("--repo github.com/CannObserv/processor"), (
            lists
        )
        assert len(_creates(c.gh)) == 1
        # The body spans lines, so the create's logged call ends the file.
        calls_text = (c.gh / "calls").read_text().rstrip()
        assert calls_text.endswith("--repo github.com/CannObserv/processor"), calls_text


class TestAnHttpsRemotesPush:
    def test_a_callers_git_config_count_is_left_alone_and_logged(self, pr_consumer):
        c = pr_consumer
        _remote_as(c, "https://github.com/o/r.git")
        _dotenv(c, "GH_TOKEN=from-dotenv\n")

        result = _run(
            c, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.x", GIT_CONFIG_VALUE_0="y"
        )

        assert result.returncode == 0, result.stderr
        assert len(_creates(c.gh)) == 1, result.stderr
        assert "GIT_CONFIG_COUNT is already set" in log_text(c)

    def test_its_network_calls_get_gh_as_credential_helper_and_nothing_else_does(
        self, pr_consumer
    ):
        """status's remote is https with no credential helper: once gh has a
        token, the branch push still needs one."""
        c = pr_consumer
        _remote_as(c, "https://github.com/o/r.git")
        _dotenv(c, "GH_TOKEN=from-dotenv\n")
        (c.gh / "no_login").write_text("")
        seen = c.path.parent / "git-calls"
        real_git = shutil.which("git") or "/usr/bin/git"
        (c.bindir / "git").write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s|%s|%s|%s\\n" "$1" "${{GIT_CONFIG_KEY_0:-}}" '
            f'"${{GIT_CONFIG_VALUE_0:-}}" "${{GH_TOKEN:-}}" >>{shlex.quote(str(seen))}\n'
            f'exec {real_git} "$@"\n'
        )

        result = _run(c)

        assert result.returncode == 0, result.stderr
        assert len(_creates(c.gh)) == 1, (result.stderr, _calls(c.gh))
        calls = [ln.split("|") for ln in seen.read_text().splitlines()]
        helper = [
            "credential.https://github.com.helper",
            "!gh auth git-credential",
            "from-dotenv",
        ]
        pushes = [x for x in calls if x[0] == "push"]
        assert pushes and all(x[1:] == helper for x in pushes), pushes
        assert ["ls-remote", *helper] in calls
        others = [x for x in calls if x[0] not in ("push", "ls-remote", "fetch")]
        assert others and all(x[1:] == ["", "", ""] for x in others), [
            x for x in others if x[1:] != ["", "", ""]
        ]
