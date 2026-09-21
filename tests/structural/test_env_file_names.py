"""#296 — an `--env-file` name that cannot work is refused, and one that missed says so.

`measure-context.sh --env-file` takes secrets-file NAMES and joins each to the
repo root as `"$root/$f"`. An absolute path therefore expands to
`<root>//Users/...`, which never exists, and was skipped exactly as a missing
file is: the run fell back to the offline estimate, and its WARN listed the
three credential sources without saying that the file the caller had named
explicitly could never have been read. Same file, same key, both readable — the
only difference between the failing and the working run was the leading `/`.

It was hit from a linked worktree, which is what makes the absolute path the
natural first attempt: `git rev-parse --show-toplevel` there is the WORKTREE, so
a key kept in the main checkout's `.env` matches no name at the root, and the
spelling that works climbs out of it by a depth that depends on the layout.

The rule this file pins, in two halves:

- **Refuse what cannot work.** An absolute name is a usage error, exit 1, with
  an error that names the flag, says names are relative to the root, prints the
  root, and — when the file exists — the relative spelling that reaches it,
  checked rather than guessed. It is raised before the preflight and the
  measurement part ways, so both answer alike: the #271 property that
  `--check-credential` answers for the run it precedes. An absolute path
  holding a space is refused whole, and an empty value is refused too.
- **Explain what merely missed.** When `--env-file` was passed and no credential
  resolved, the no-credential message names each file that was absent or held
  no usable key, in both the preflight and the `--exact` WARN — and so does
  the `ant auth` profile's path, which an installed profile always reaches.

Credential resolution itself — its order, and what the preflight asks the
endpoint — belongs to `test_credential_preflight.py`, whose stub and fixtures
this file borrows rather than copies.
"""

import json
import subprocess
from pathlib import Path

import pytest

from .test_credential_preflight import (
    KEY,
    MEASURE,
    _clean_env,
    _no_ant,
    _Stub,
    _with_ant,
)

# How a Claude Code agent worktree sits inside the checkout that owns the key —
# three levels down, which is where the unobvious depth comes from.
WORKTREE = Path(".claude") / "worktrees" / "wt"


def _git(repo: Path, *args: str) -> None:
    # _clean_env strips every inherited GIT_* variable, so these address the
    # fixture's repository and not the one running the suite (docs/STYLE.md).
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env=_clean_env(),
    )


def _checkout_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """A main checkout holding the key in `.env`, and a linked worktree of it."""
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q")
    (main / "AGENTS.md").write_text("- a policy line\n")
    _git(main, "add", "AGENTS.md")
    _git(
        main,
        "-c",
        "user.email=t@example.com",
        "-c",
        "user.name=t",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "init",
    )
    _git(main, "worktree", "add", "-q", str(WORKTREE))
    (main / ".env").write_text(f"ANTHROPIC_API_KEY={KEY}\n")
    return main, main / WORKTREE


def _measure(cwd: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(MEASURE), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


# The preflight and the measurement, as a caller runs each. Both must give the
# same answer about the same --env-file.
MODES = [("--check-credential",), ("--exact", "--no-write")]


@pytest.fixture
def layout(tmp_path: Path) -> tuple[Path, Path]:
    return _checkout_with_worktree(tmp_path)


class TestAnAbsoluteNameIsRefused:
    @pytest.mark.parametrize("mode", MODES, ids=["preflight", "measurement"])
    def test_it_is_a_usage_error_naming_the_flag_and_the_root(
        self, layout: tuple[Path, Path], tmp_path: Path, mode: tuple[str, ...]
    ):
        main, worktree = layout
        env = _no_ant(tmp_path, _clean_env())
        r = _measure(worktree, env, *mode, "--env-file", str(main / ".env"))
        assert r.returncode == 1, r.stdout + r.stderr
        assert r.stdout == "", "a refused argv must not emit a measurement"
        assert "--env-file" in r.stderr
        assert "relative to the repo root" in r.stderr
        # The root it names is the worktree's, which is the fact the caller did
        # not know — and the one that makes the absolute path look necessary.
        assert str(worktree.resolve()) in r.stderr, r.stderr
        assert KEY not in r.stderr

    def test_the_worktree_case_is_told_the_spelling_that_reaches_the_file(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        """Computed from the layout rather than guessed: three levels here."""
        main, worktree = layout
        env = _no_ant(tmp_path, _clean_env())
        r = _measure(
            worktree, env, "--check-credential", "--env-file", str(main / ".env")
        )
        assert r.returncode == 1, r.stderr
        assert "pass it as: --env-file ../../../.env" in r.stderr, r.stderr

    def test_the_suggested_spelling_actually_works(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        """A suggestion is only worth printing if following it succeeds."""
        main, worktree = layout
        env = _no_ant(tmp_path, _clean_env())
        refused = _measure(
            worktree, env, "--check-credential", "--env-file", str(main / ".env")
        )
        suggested = refused.stderr.split("pass it as: --env-file ", 1)[1].split()[0]
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _measure(worktree, env, "--check-credential", "--env-file", suggested)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "secrets file" in r.stdout
        assert stub.requests[0]["headers"]["x-api-key"] == KEY

    def test_a_path_inside_the_root_is_told_its_plain_name(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        main, _ = layout
        env = _no_ant(tmp_path, _clean_env())
        r = _measure(main, env, "--check-credential", "--env-file", str(main / ".env"))
        assert r.returncode == 1, r.stderr
        assert "pass it as: --env-file .env" in r.stderr, r.stderr

    def test_a_missing_file_gets_no_suggestion(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        """No name reaches a file that is not there, so none is offered."""
        main, worktree = layout
        env = _no_ant(tmp_path, _clean_env())
        missing = main / "no-such-dir" / ".env"
        r = _measure(worktree, env, "--check-credential", "--env-file", str(missing))
        assert r.returncode == 1, r.stderr
        assert f"{missing} -> no such file" in r.stderr, r.stderr
        assert "pass it as" not in r.stderr

    def test_only_the_absolute_names_in_a_list_are_reported(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        main, worktree = layout
        env = _no_ant(tmp_path, _clean_env())
        r = _measure(
            worktree,
            env,
            "--check-credential",
            "--env-file",
            f".env.local {main / '.env'}",
        )
        assert r.returncode == 1, r.stderr
        assert ".env.local ->" not in r.stderr
        assert r.stderr.count(" -> ") == 1, r.stderr

    def test_it_is_refused_even_where_it_would_not_have_been_read(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        """An exported key resolves before any secrets file, so the absolute
        name would never have been consulted. It is refused anyway: whether an
        argv is valid must not depend on the environment it runs in, or the
        same command passes on one runner and fails on the next."""
        main, worktree = layout
        env = _no_ant(tmp_path, _clean_env())
        env["ANTHROPIC_API_KEY"] = KEY
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _measure(
                worktree, env, "--check-credential", "--env-file", str(main / ".env")
            )
        assert r.returncode == 1, r.stdout + r.stderr
        assert stub.requests == [], "the refusal must come before any request"

    def test_the_preflight_and_the_measurement_give_one_answer(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        """#271's property, for the argv rather than the request: the preflight
        exists to predict the run, so it cannot pass what the run would refuse
        or refuse what the run would accept."""
        main, worktree = layout
        env = _no_ant(tmp_path, _clean_env())
        name = str(main / ".env")
        pre = _measure(worktree, env, "--check-credential", "--env-file", name)
        run = _measure(worktree, env, "--exact", "--no-write", "--env-file", name)
        assert (pre.returncode, pre.stderr) == (run.returncode, run.stderr)


class TestAnAbsolutePathHoldingASpace:
    """#296 CR 23. The value is a space-separated list of names, so an absolute
    path with a space in it was split like any list and refused as its first
    fragment — "/…/my -> no such file", which is false — while the file the
    caller actually named went unmentioned. The whole value is now tried as
    the one path it may be before it is split."""

    def test_the_whole_path_is_refused_with_the_spelling_that_reaches_it(
        self, tmp_path: Path
    ):
        spaced = tmp_path / "my repo"
        spaced.mkdir()
        main, worktree = _checkout_with_worktree(spaced)
        env = _no_ant(tmp_path, _clean_env())
        r = _measure(
            worktree, env, "--check-credential", "--env-file", str(main / ".env")
        )
        assert r.returncode == 1, r.stderr
        assert f"{main / '.env'} -> pass it as: --env-file ../../../.env" in (
            r.stderr
        ), r.stderr
        assert "no such file" not in r.stderr, r.stderr

    def test_a_spelling_that_would_itself_be_split_is_not_offered(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        """Outside the root, the space lands in the relative spelling too, and
        offering it would be offering the next refusal."""
        _, worktree = layout
        elsewhere = tmp_path / "key dir" / ".env"
        elsewhere.parent.mkdir()
        elsewhere.write_text(f"ANTHROPIC_API_KEY={KEY}\n")
        env = _no_ant(tmp_path, _clean_env())
        r = _measure(worktree, env, "--check-credential", "--env-file", str(elsewhere))
        assert r.returncode == 1, r.stderr
        assert "holds a space" in r.stderr, r.stderr
        assert "pass it as" not in r.stderr
        assert "no such file" not in r.stderr
        assert KEY not in r.stderr

    def test_a_missing_one_is_split_and_says_that_it_was(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        _, worktree = layout
        missing = tmp_path / "no such dir" / ".env"
        env = _no_ant(tmp_path, _clean_env())
        r = _measure(worktree, env, "--check-credential", "--env-file", str(missing))
        assert r.returncode == 1, r.stderr
        assert f"{tmp_path / 'no'} -> no such file" in r.stderr, r.stderr
        assert "splits its value on spaces" in r.stderr, r.stderr


class TestAnEmptyValueIsRefused:
    """#296 CR 24. `--env-file ""` split to no names, the library searched its
    defaults for want of any, and the messages said "secrets file ()" while
    itemising nothing — so it silently meant `.env env`, the opposite of what
    an empty list most plausibly asks for. Neither --help nor the arity
    helper ever documented an empty value, so it is a usage error naming the
    flag that searches no file."""

    @pytest.mark.parametrize("value", ["", "  "], ids=["empty", "blank"])
    @pytest.mark.parametrize("mode", MODES, ids=["preflight", "measurement"])
    def test_it_is_a_usage_error_naming_no_env_file(
        self,
        layout: tuple[Path, Path],
        tmp_path: Path,
        mode: tuple[str, ...],
        value: str,
    ):
        main, _ = layout
        env = _no_ant(tmp_path, _clean_env())
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _measure(main, env, *mode, "--env-file", value)
        assert r.returncode == 1, r.stdout + r.stderr
        assert r.stdout == ""
        assert "--env-file needs at least one name" in r.stderr, r.stderr
        assert "--no-env-file" in r.stderr
        assert stub.requests == [], "the .env the defaults would find was used"


class TestAMissedNameIsNamed:
    """The #296 reproduction's other half: the WARN listed three sources and
    not the file the caller passed. A typo, a wrong directory and a worktree
    root all look like this, and only the names say which it was."""

    def _names(self, repo: Path) -> str:
        (repo / "keyless.env").write_text("OTHER_VAR=1\n")
        return "missing.env keyless.env"

    def test_the_measurement_warn_names_each_file(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        _, worktree = layout
        env = _no_ant(tmp_path, _clean_env())
        r = _measure(
            worktree, env, "--exact", "--no-write", "--env-file", self._names(worktree)
        )
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["policy"]["tokens_exact"] is False
        assert "missing.env not found" in r.stderr, r.stderr
        assert "keyless.env holds no usable ANTHROPIC_API_KEY" in r.stderr, r.stderr
        assert str(worktree.resolve()) in r.stderr, "the root the names were joined to"

    def test_the_preflight_names_the_same_files(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        _, worktree = layout
        env = _no_ant(tmp_path, _clean_env())
        names = self._names(worktree)
        pre = _measure(worktree, env, "--check-credential", "--env-file", names)
        run = _measure(worktree, env, "--exact", "--no-write", "--env-file", names)
        assert pre.returncode == 3, pre.stderr
        line = next(
            ln
            for ln in run.stderr.splitlines()
            if "--env-file names are searched" in ln
        )
        detail = line.split("--env-file names are searched", 1)[1]
        assert detail in pre.stderr, (pre.stderr, run.stderr)

    def test_the_default_names_are_not_itemised(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        """The convention needs no roll-call: the generic line already says
        `.env`, and a scheduled run with its key in the environment must not
        start narrating two missing files every week."""
        _, worktree = layout
        env = _no_ant(tmp_path, _clean_env())
        r = _measure(worktree, env, "--exact", "--no-write")
        assert "using offline estimate" in r.stderr
        assert "--env-file names are searched" not in r.stderr

    def test_no_env_file_searched_nothing_so_names_nothing(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        _, worktree = layout
        env = _no_ant(tmp_path, _clean_env())
        r = _measure(
            worktree,
            env,
            "--check-credential",
            "--no-env-file",
            "--env-file",
            self._names(worktree),
        )
        assert r.returncode == 3, r.stderr
        assert "--env-file names are searched" not in r.stderr


class TestAMissedNameIsNamedWhenTheProfileAnswers:
    """#296 CR 25. An `ant` profile resolves last and, when installed, always,
    so a mistyped --env-file name never reached the no-credential message that
    itemises it: the run surfaced as a JWT refusal about a credential the
    caller never chose. The names are itemised on the profile's paths too."""

    NAMES = "missing.env"
    INSTEAD = "none was used, so the `ant auth` profile answered instead"

    @staticmethod
    def _jwt_refusal() -> _Stub:
        return _Stub(
            status=401,
            payload={
                "type": "error",
                "error": {
                    "type": "authentication_error",
                    "message": "jwt auth is not yet supported on count_tokens",
                },
            },
        )

    def test_a_refused_preflight_names_the_file(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        _, worktree = layout
        env = _with_ant(tmp_path, _clean_env())
        with self._jwt_refusal() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _measure(worktree, env, "--check-credential", "--env-file", self.NAMES)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "missing.env not found" in r.stderr, r.stderr
        assert self.INSTEAD in r.stderr

    def test_an_unreachable_preflight_names_the_file(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        _, worktree = layout
        env = _with_ant(tmp_path, _clean_env())
        # Port 1: nothing can listen there, as in test_credential_preflight.
        env["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:1"
        r = _measure(worktree, env, "--check-credential", "--env-file", self.NAMES)
        assert r.returncode == 2, r.stdout + r.stderr
        assert "missing.env not found" in r.stderr, r.stderr
        assert self.INSTEAD in r.stderr

    def test_the_measurement_names_the_file(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        _, worktree = layout
        env = _with_ant(tmp_path, _clean_env())
        with self._jwt_refusal() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _measure(
                worktree, env, "--exact", "--no-write", "--env-file", self.NAMES
            )
        assert r.returncode == 0, r.stderr
        assert "WARN --env-file names are searched" in r.stderr, r.stderr
        assert "missing.env not found" in r.stderr
        assert self.INSTEAD in r.stderr

    def test_an_accepted_preflight_names_the_file(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        """#296 CR 55. The one oauth path CR 25 missed: the preflight's exit 0,
        reachable once count_tokens accepts JWT. --help promises the names
        "when ... only an `ant auth` profile" resolves, and an accepted profile
        is still one the caller did not choose over the file they named."""
        _, worktree = layout
        env = _with_ant(tmp_path, _clean_env())
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _measure(worktree, env, "--check-credential", "--env-file", self.NAMES)
        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stdout.startswith("ok: the `ant auth` profile"), r.stdout
        assert "missing.env not found" in r.stderr, r.stderr
        assert self.INSTEAD in r.stderr
        assert "--env-file" not in r.stdout, "stdout stays the one verdict line"
        assert stub.requests[0]["headers"]["authorization"].startswith("Bearer ")

    def test_the_default_names_are_still_not_itemised(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        _, worktree = layout
        env = _with_ant(tmp_path, _clean_env())
        with self._jwt_refusal() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _measure(worktree, env, "--check-credential")
        assert r.returncode == 3, r.stderr
        assert "--env-file names are searched" not in r.stderr

    def test_an_accepted_preflight_on_the_default_names_stays_quiet(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        _, worktree = layout
        env = _with_ant(tmp_path, _clean_env())
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _measure(worktree, env, "--check-credential")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "--env-file names are searched" not in r.stderr


def test_the_help_states_the_contract():
    r = subprocess.run(
        ["bash", str(MEASURE), "--help"], capture_output=True, text=True, timeout=30
    )
    assert r.returncode == 0
    text = " ".join(r.stdout.split())
    assert "An absolute path is refused" in text
    assert "linked worktree is the worktree" in text
    assert "#296" in text
    assert "An empty value is refused; --no-env-file searches no file" in text
