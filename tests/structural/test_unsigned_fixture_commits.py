"""Fixture commits never sign under the caller's git config (#546).

In a cloud session the global config sets `commit.gpgsign=true`, and every
fixture commit went through the session's signing helper. The helper leaked a
file descriptor per call; five full runs exhausted it, and every commit in the
session failed from then on, the session's own included.

Each test here runs an inner pytest under a throwaway signing config: a
`GIT_CONFIG_GLOBAL` file and a `HOME/.gitconfig` that both set
`commit.gpgsign=true`, `tag.gpgsign=true` and a `gpg.program` that fails
loudly and leaves a mark. Both, because a fixture that scrubs `GIT_*` (#189)
reads `HOME`'s, and one that does not reads `GIT_CONFIG_GLOBAL`'s.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# The isolation's own marker: a parent session that set it would make the
# inner run skip isolating, so it is dropped here (spelled out rather than
# imported, so this file does not depend on the code it tests).
MARKER = "SKILLS_TESTS_REAL_HOME"


def _signing_world(tmp_path: Path) -> tuple[dict, Path]:
    mark = tmp_path / "gpg-ran"
    gpg = tmp_path / "gpg-must-not-run"
    gpg.write_text(
        "#!/bin/sh\n"
        'echo "gpg.program ran: a fixture commit tried to sign" >&2\n'
        f'echo "$*" >> "{mark}"\n'
        "exit 1\n"
    )
    gpg.chmod(0o755)
    config = (
        "[user]\n\tname = t\n\temail = t@example.com\n"
        "[commit]\n\tgpgSign = true\n"
        "[tag]\n\tgpgSign = true\n"
        f'[gpg]\n\tformat = openpgp\n\tprogram = "{gpg}"\n'
    )
    global_config = tmp_path / "signing.gitconfig"
    global_config.write_text(config)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text(config)
    env = {
        k: v
        for k, v in os.environ.items()
        if k != MARKER and not k.startswith(("GIT_", "PYTEST_"))
    }
    env.update(HOME=str(home), GIT_CONFIG_GLOBAL=str(global_config))
    return env, mark


def _scrubbed(env: dict) -> dict:
    return {k: v for k, v in env.items() if not k.startswith("GIT_")}


def _inner_pytest(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


class TestTheTrapIsLive:
    """Without this, every test below could pass by never signing at all."""

    def test_a_plain_commit_under_it_signs_and_fails(self, tmp_path):
        env, mark = _signing_world(tmp_path)
        repo = tmp_path / "repo"
        for use in (env, _scrubbed(env)):
            subprocess.run(["git", "init", "-q", str(repo)], check=True, env=use)
            result = subprocess.run(
                ["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "x"],
                capture_output=True,
                text=True,
                env=use,
            )
            assert result.returncode != 0
            assert "gpg.program ran" in result.stderr
        assert len(mark.read_text().splitlines()) == 2


class TestFixtureCommitsDoNotSign:
    def test_a_real_fixture_that_scrubs_git_vars(self, tmp_path):
        """test_structural_tests_reuse's repo fixture commits with GIT_* gone."""
        env, mark = _signing_world(tmp_path)
        result = _inner_pytest(
            env,
            "tests/structural/test_structural_tests_reuse.py"
            "::test_pytests_exit_code_passes_through",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert not mark.exists(), mark.read_text()

    def test_every_commit_shape_scrubbed_or_not(self, tmp_path):
        """Commits, a merge, commit-tree and an annotated tag, from Python and
        from a script, with GIT_* kept and with it scrubbed."""
        env, mark = _signing_world(tmp_path)
        probe = tmp_path / "probe" / "test_probe.py"
        probe.parent.mkdir()
        probe.write_text(
            textwrap.dedent(
                """\
                import os
                import subprocess


                def _env(scrub):
                    return {
                        k: v
                        for k, v in os.environ.items()
                        if not (scrub and k.startswith("GIT_"))
                    }


                def test_nothing_signs(tmp_path):
                    for scrub in (False, True):
                        repo = tmp_path / f"repo-{scrub}"
                        script = (
                            "set -e\\n"
                            f'git init -q "{repo}"\\n'
                            f'cd "{repo}"\\n'
                            "git commit -q --allow-empty -m one\\n"
                            "git checkout -q -b side\\n"
                            "git commit -q --allow-empty -m two\\n"
                            "git checkout -q -\\n"
                            "git merge -q --no-ff -m merged side\\n"
                            "git commit-tree -m tree HEAD^{tree} >/dev/null\\n"
                            "git tag -a -m tagged v1\\n"
                        )
                        subprocess.run(
                            ["bash", "-c", script], check=True, env=_env(scrub)
                        )
                        subprocess.run(
                            ["git", "-C", str(repo), "commit", "-q",
                             "--allow-empty", "-m", "from python"],
                            check=True,
                            env=_env(scrub),
                        )
                """
            )
        )
        result = _inner_pytest(
            {**env, "PYTHONPATH": str(REPO_ROOT)},
            "-p",
            "tests.conftest",
            "--rootdir",
            str(probe.parent),
            str(probe),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert not mark.exists(), mark.read_text()


class TestTheMirror:
    """A HOME change must not change what a HOME-reading test sees."""

    def test_every_entry_of_the_real_home_is_reachable(self, tmp_path):
        from tests.utils import unsigned_git

        real = tmp_path / "real"
        (real / ".cache").mkdir(parents=True)
        (real / ".cache" / "kept").write_text("x")
        (real / ".npmrc").write_text("y")
        (real / ".gitconfig").write_text("[user]\n\tname = caller\n")
        environ = {"HOME": str(real)}
        done = unsigned_git.isolate(environ)
        home = Path(environ["HOME"])
        assert home != real
        assert (home / ".cache" / "kept").read_text() == "x"
        assert (home / ".npmrc").read_text() == "y"
        name = subprocess.run(
            ["git", "config", "--includes", "--global", "user.name"],
            capture_output=True,
            text=True,
            env={"HOME": str(home), "PATH": os.environ["PATH"]},
        ).stdout.strip()
        assert name == "caller", "the caller's own config is still included"
        unsigned_git.restore(done, environ)
        assert environ == {"HOME": str(real)}
        assert (real / ".cache" / "kept").read_text() == "x", "restore kept it"
        assert not done.root.exists()

    def test_a_callers_git_config_global_is_included_and_restored(self, tmp_path):
        from tests.utils import unsigned_git

        own = tmp_path / "own.gitconfig"
        own.write_text("[user]\n\tname = from-global\n")
        environ = {"HOME": str(tmp_path), "GIT_CONFIG_GLOBAL": str(own)}
        done = unsigned_git.isolate(environ)
        assert environ["GIT_CONFIG_GLOBAL"] != str(own)
        sign, name = (
            subprocess.run(
                ["git", "config", "--includes", "--global", key],
                capture_output=True,
                text=True,
                env={**environ, "PATH": os.environ["PATH"]},
            ).stdout.strip()
            for key in ("commit.gpgsign", "user.name")
        )
        assert (sign, name) == ("false", "from-global")
        unsigned_git.restore(done, environ)
        assert environ == {"HOME": str(tmp_path), "GIT_CONFIG_GLOBAL": str(own)}

    def test_an_isolated_session_is_not_isolated_again(self, tmp_path):
        from tests.utils import unsigned_git

        environ = {"HOME": str(tmp_path), unsigned_git.MARKER: "/elsewhere"}
        assert unsigned_git.isolate(environ) is None
        assert environ["HOME"] == str(tmp_path)

    def test_this_session_is_isolated(self):
        from tests.utils import unsigned_git

        assert unsigned_git.MARKER in os.environ
        sign = subprocess.run(
            ["git", "config", "--global", "commit.gpgsign"],
            capture_output=True,
            text=True,
            env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        ).stdout.strip()
        assert sign == "false"
