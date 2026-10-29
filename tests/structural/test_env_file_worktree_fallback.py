"""In a linked worktree, the key in the primary checkout's `.env` is found (#525).

`measure-context.sh` searched `ENV_FILES=".env env"` under `git rev-parse
--show-toplevel`, which in a linked worktree is the worktree. A gitignored
`.env` lives only in the primary checkout, so `--exact` taken in a worktree
warned, fell back to the offline estimate, and reported estimates where an
exact reading was asked for; `--anchor` persisted nothing and exited 2.
`scripts/run-integration-tests.sh` probed the same two names the same way.

The fix is #497's recipe from `shipping-work*`: after the root's names, the
primary checkout's — `$(dirname "$(git rev-parse --path-format=absolute
--git-common-dir)")`. Still parsed for ANTHROPIC_API_KEY alone, never sourced,
and the value is never printed. `--no-env-file` still searches nothing, and an
explicit `--env-file` keeps its meaning: names under the root, no fallback.
When nothing resolves in a linked worktree, the WARN names every path tried
and points at `--env-file`. The network is the existing count_tokens stub.
"""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from .test_credential_preflight import KEY, _clean_env, _no_ant, _Stub
from .test_env_file_names import _checkout_with_worktree, _measure

ROOT = Path(__file__).resolve().parent.parent.parent
RUN_INTEGRATION = ROOT / "scripts" / "run-integration-tests.sh"
OTHER_KEY = "sk-ant-the-worktrees-own"


@pytest.fixture
def layout(tmp_path: Path) -> tuple[Path, Path]:
    return _checkout_with_worktree(tmp_path)


class TestMeasureContextFallsBackToThePrimary:
    def test_the_preflight_resolves_the_primarys_key(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        main, worktree = layout
        env = _no_ant(tmp_path, _clean_env())
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _measure(worktree, env, "--check-credential")
        assert r.returncode == 0, r.stdout + r.stderr
        assert stub.requests[0]["headers"]["x-api-key"] == KEY
        assert "primary checkout" in r.stdout, r.stdout
        assert str(main.resolve() / ".env") in r.stdout, r.stdout
        assert KEY not in r.stdout + r.stderr

    def test_exact_counts_exactly(self, layout: tuple[Path, Path], tmp_path: Path):
        """The issue's symptom: tokens_exact false on a run that asked for
        exact counts, with the key one directory up the whole time."""
        main, worktree = layout
        env = _no_ant(tmp_path, _clean_env())
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _measure(worktree, env, "--exact", "--no-write")
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["policy"]["tokens_exact"] is True, r.stderr
        assert str(main.resolve() / ".env") in r.stderr, r.stderr
        assert KEY not in r.stdout + r.stderr

    def test_the_worktrees_own_file_wins(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        _, worktree = layout
        (worktree / ".env").write_text(f"ANTHROPIC_API_KEY={OTHER_KEY}\n")
        env = _no_ant(tmp_path, _clean_env())
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _measure(worktree, env, "--check-credential")
        assert r.returncode == 0, r.stdout + r.stderr
        assert stub.requests[0]["headers"]["x-api-key"] == OTHER_KEY

    def test_the_primarys_file_is_parsed_not_sourced(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        main, worktree = layout
        marker = tmp_path / "sourced"
        (main / ".env").write_text(f"touch {marker}\nANTHROPIC_API_KEY={KEY}\n")
        env = _no_ant(tmp_path, _clean_env())
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _measure(worktree, env, "--check-credential")
        assert r.returncode == 0, r.stdout + r.stderr
        assert not marker.exists()

    def test_no_env_file_still_searches_nothing(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        _, worktree = layout
        env = _no_ant(tmp_path, _clean_env())
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _measure(worktree, env, "--check-credential", "--no-env-file")
        assert r.returncode == 3, r.stdout + r.stderr
        assert stub.requests == []

    def test_an_explicit_env_file_keeps_its_meaning(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        """Names under the root, as --help says, with no fallback: a caller
        who named a file meant that file."""
        _, worktree = layout
        env = _no_ant(tmp_path, _clean_env())
        with _Stub() as stub:
            env["ANTHROPIC_BASE_URL"] = stub.url
            r = _measure(worktree, env, "--check-credential", "--env-file", ".env")
        assert r.returncode == 3, r.stdout + r.stderr
        assert stub.requests == []
        assert ".env not found" in r.stderr, r.stderr


class TestTheWarnNamesEveryPathTried:
    @pytest.mark.parametrize(
        "mode", [("--check-credential",), ("--exact", "--no-write")]
    )
    def test_in_a_linked_worktree(
        self, layout: tuple[Path, Path], tmp_path: Path, mode: tuple[str, ...]
    ):
        main, worktree = layout
        (main / ".env").unlink()
        env = _no_ant(tmp_path, _clean_env())
        r = _measure(worktree, env, *mode)
        for base in (worktree.resolve(), main.resolve()):
            for name in (".env", "env"):
                assert str(base / name) in r.stderr, r.stderr
        assert "--env-file" in r.stderr.split(str(main.resolve() / "env"), 1)[1]


def _fake_venv(worktree: Path, tmp_path: Path) -> None:
    """A .venv whose pytest reports whether the key arrived, never its value."""
    bindir = tmp_path / "fake-pytest-bin"
    bindir.mkdir()
    pytest_bin = bindir / "pytest"
    pytest_bin.write_text(
        "#!/usr/bin/env bash\n"
        'if [ -n "${ANTHROPIC_API_KEY:-}" ]; then echo "key: set"; '
        'else echo "key: unset"; fi\n'
        '[ "${ANTHROPIC_API_KEY:-}" = "$EXPECT" ] && echo "key: expected"\n'
        "exit 0\n"
    )
    pytest_bin.chmod(pytest_bin.stat().st_mode | stat.S_IEXEC)
    (worktree / ".venv" / "bin").mkdir(parents=True)
    (worktree / ".venv" / "bin" / "activate").write_text(
        f'export PATH="{bindir}:$PATH"\n'
    )


def _run_integration(worktree: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    env = _clean_env()
    env.pop("ANTHROPIC_API_KEY", None)
    env["EXPECT"] = KEY
    return subprocess.run(
        ["bash", str(RUN_INTEGRATION)],
        cwd=str(worktree),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


class TestRunIntegrationTestsFallsBackToThePrimary:
    def test_the_primarys_key_is_exported(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        _, worktree = layout
        _fake_venv(worktree, tmp_path)
        r = _run_integration(worktree, tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "key: expected" in r.stdout, r.stdout + r.stderr
        assert KEY not in r.stdout + r.stderr

    def test_the_warn_names_every_path_tried(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        main, worktree = layout
        (main / ".env").unlink()
        _fake_venv(worktree, tmp_path)
        r = _run_integration(worktree, tmp_path)
        assert "key: unset" in r.stdout, r.stdout + r.stderr
        assert "WARN" in r.stderr, r.stderr
        for base in (worktree.resolve(), main.resolve()):
            for name in (".env", "env"):
                assert str(base / name) in r.stderr, r.stderr

    def test_the_worktrees_own_file_wins(
        self, layout: tuple[Path, Path], tmp_path: Path
    ):
        _, worktree = layout
        (worktree / ".env").write_text(f"ANTHROPIC_API_KEY={OTHER_KEY}\n")
        _fake_venv(worktree, tmp_path)
        r = _run_integration(worktree, tmp_path)
        assert "key: set" in r.stdout and "key: expected" not in r.stdout, r.stdout


@pytest.mark.skipif(os.name != "posix", reason="POSIX paths")
def test_the_layout_is_a_linked_worktree(layout: tuple[Path, Path]):
    """The premise, so the cases above can't pass on a plain checkout."""
    main, worktree = layout
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=str(worktree),
        capture_output=True,
        text=True,
        env=_clean_env(),
        check=True,
    ).stdout.strip()
    assert Path(common).parent.resolve() == main.resolve()
    assert not (worktree / ".env").exists()
