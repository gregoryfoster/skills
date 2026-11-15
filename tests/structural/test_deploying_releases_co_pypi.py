"""deploying-releases' co-pypi wrapper, its installer and its consumer test (#632).

The wrapper (``assets/co-pypi/co-pypi.sh``) and its minter (``co_pypi_token.py``)
are extracted from CannObserv/broker at ``bbf1c72f``, made byte-identical across
repos: the key is ``CO_PYPI_KEY``, else ``/etc/<[project].name>/co-pypi-reader.json``.
They are installed with ``install.sh --co-pypi`` under the core's marker scheme,
so a hand edit and an old copy are told apart without the vendor checkout.

The minter imports google-auth only to mint, so everything else here runs
without it; the mint itself runs against a stand-in ``google`` package.
Portable: runs on macOS too.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from tests.structural.deploying_releases_rig import INSTALL, SKILL, clean_env
from tests.utils.nested_pytest import nested_pytest_env

ASSETS = SKILL / "assets" / "co-pypi"
WRAPPER = ASSETS / "co-pypi.sh"
MINTER = ASSETS / "co_pypi_token.py"
CONSUMER_TEST = ASSETS / "test_co_pypi.py"
MARK = "# deploying-releases-co-pypi"
URL = "https://us-west1-python.pkg.dev/co-gcs/co-pypi/simple/"
TOKEN = "ya29.sentinel-never-printed"


def body_sha(text: str) -> str:
    zeroed = re.sub(
        rf"^({re.escape(MARK)}-sha256: ).*$", r"\g<1>" + "0" * 64, text, flags=re.M
    )
    return hashlib.sha256(zeroed.encode()).hexdigest()


@pytest.fixture(scope="module")
def minter():
    spec = importlib.util.spec_from_file_location("co_pypi_token_under_test", MINTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Exec:
    """Stands in for os.execvpe: records the call instead of replacing the process."""

    def __init__(self, raises: OSError | None = None):
        self.calls: list[tuple[str, list[str], dict[str, str]]] = []
        self.raises = raises

    def __call__(self, file, args, env):
        self.calls.append((file, args, env))
        if self.raises:
            raise self.raises


def pyproject(tmp_path: Path, name: str | None = "acme") -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(
        f'[project]\nname = "{name}"\n' if name is not None else "[tool.x]\n"
    )
    return path


def run_main(minter, tmp_path, argv=("uv", "sync", "--locked"), environ=None, **kw):
    minted: list[str] = []

    def mint(path: str) -> str:
        minted.append(path)
        return TOKEN

    execvpe = kw.pop("execvpe", Exec())
    rc = minter.main(
        list(argv),
        environ if environ is not None else {"PATH": "/usr/bin"},
        mint=kw.pop("mint", mint),
        execvpe=execvpe,
        pyproject=kw.pop("pyproject", None) or pyproject(tmp_path),
    )
    return rc, minted, execvpe


class TestTheMarkers:
    @pytest.mark.parametrize("path", [WRAPPER, MINTER], ids=lambda p: p.name)
    def test_line_two_names_the_version(self, path):
        assert path.read_text().splitlines()[1] == f"{MARK}: version 1"

    @pytest.mark.parametrize("path", [WRAPPER, MINTER], ids=lambda p: p.name)
    def test_the_recorded_sha256_is_the_files_own(self, path):
        text = path.read_text()
        recorded = re.search(rf"^{re.escape(MARK)}-sha256: (\w+)$", text, flags=re.M)[1]
        assert recorded == body_sha(text), (
            f"{path.name} changed without re-stamping its marker: set line 3's digest "
            f"to {body_sha(text)}"
        )

    def test_the_wrapper_is_executable(self):
        assert WRAPPER.stat().st_mode & 0o111


class TestTheAllowlist:
    def test_the_shell_lists_match_the_python_ones(self, minter):
        text = WRAPPER.read_text()
        allowed = set(re.search(r"^ALLOWED=\((.*)\)$", text, flags=re.M)[1].split())
        prefixes = tuple(re.search(r"^PREFIXES=\((.*)\)$", text, flags=re.M)[1].split())
        assert allowed == minter.ALLOWED | {minter.KEY_VAR}
        assert prefixes == minter.ALLOWED_PREFIXES

    def test_the_child_environment_is_the_allowlist(self, minter):
        environ = {
            "PATH": "/bin",
            "HOME": "/h",
            "LC_ALL": "C",
            "UV_CACHE_DIR": "/c",
            "SSL_CERT_FILE": "/s",
            "GH_TOKEN": "ghp_x",
            "GOOGLE_APPLICATION_CREDENTIALS": "/writer.json",
            "CO_PYPI_KEY": "/k.json",
            "VIRTUAL_ENV": "/v",
        }
        assert minter.child_environment(environ) == {
            "PATH": "/bin",
            "HOME": "/h",
            "LC_ALL": "C",
            "UV_CACHE_DIR": "/c",
            "SSL_CERT_FILE": "/s",
        }


class TestTheKey:
    def test_the_projects_reader_key_by_default(self, minter, tmp_path):
        rc, minted, _ = run_main(minter, tmp_path)
        assert rc is None and minted == ["/etc/acme/co-pypi-reader.json"]

    def test_co_pypi_key_overrides_the_default(self, minter, tmp_path):
        environ = {"PATH": "/bin", "CO_PYPI_KEY": "/etc/acme-deploy/reader.json"}
        _, minted, _ = run_main(minter, tmp_path, environ=environ)
        assert minted == ["/etc/acme-deploy/reader.json"]

    def test_a_blank_co_pypi_key_is_the_default(self, minter, tmp_path):
        _, minted, _ = run_main(minter, tmp_path, environ={"CO_PYPI_KEY": "  "})
        assert minted == ["/etc/acme/co-pypi-reader.json"]

    def test_never_the_shell_wide_adc_variable(self, minter, tmp_path):
        environ = {"GOOGLE_APPLICATION_CREDENTIALS": "/etc/acme/writer.json"}
        _, minted, execvpe = run_main(minter, tmp_path, environ=environ)
        assert minted == ["/etc/acme/co-pypi-reader.json"]
        assert "GOOGLE_APPLICATION_CREDENTIALS" not in execvpe.calls[0][2]
        assert (
            "GOOGLE_APPLICATION_CREDENTIALS" not in MINTER.read_text().split('"""')[2]
        )

    @pytest.mark.parametrize("name", [None, "", "../etc", "a/b", ".hidden"])
    def test_no_usable_project_name_mints_nothing(self, minter, tmp_path, name, capsys):
        path = pyproject(tmp_path, name)
        rc, minted, execvpe = run_main(minter, tmp_path, pyproject=path)
        assert rc == 1 and minted == [] and execvpe.calls == []
        assert "CO_PYPI_KEY" in capsys.readouterr().err

    def test_no_pyproject_mints_nothing(self, minter, tmp_path, capsys):
        rc, minted, _ = run_main(minter, tmp_path, pyproject=tmp_path / "absent.toml")
        assert rc == 1 and minted == []
        assert "CO_PYPI_KEY" in capsys.readouterr().err

    def test_the_default_reads_the_checkouts_own_pyproject(self, minter):
        assert minter.PYPROJECT == MINTER.resolve().parent.parent / "pyproject.toml"


class TestTheCommand:
    def test_uv_gets_the_pair_and_its_arguments_unchanged(self, minter, tmp_path):
        argv = ("uv", "lock", "--upgrade-package", "co-core")
        rc, _, execvpe = run_main(minter, tmp_path, argv=argv)
        [(file, args, env)] = execvpe.calls
        assert rc is None and file == "uv" and args == list(argv)
        assert env == {
            "PATH": "/usr/bin",
            "UV_INDEX_CO_PYPI_USERNAME": "oauth2accesstoken",
            "UV_INDEX_CO_PYPI_PASSWORD": TOKEN,
        }

    def test_the_key_path_never_reaches_uv(self, minter, tmp_path):
        _, _, execvpe = run_main(minter, tmp_path, environ={"CO_PYPI_KEY": "/k.json"})
        assert "CO_PYPI_KEY" not in execvpe.calls[0][2]

    @pytest.mark.parametrize(
        "argv", [(), ("python", "-c", "1"), ("sh", "-c", "uv sync")]
    )
    def test_anything_but_uv_is_refused_before_a_mint(
        self, minter, tmp_path, argv, capsys
    ):
        rc, minted, execvpe = run_main(minter, tmp_path, argv=argv)
        assert rc == 2 and minted == [] and execvpe.calls == []
        assert "usage" in capsys.readouterr().err

    def test_a_uv_by_path_is_still_uv(self, minter, tmp_path):
        rc, minted, _ = run_main(minter, tmp_path, argv=("/usr/local/bin/uv", "sync"))
        assert rc is None and minted

    def test_a_failed_mint_runs_nothing_and_prints_no_token(
        self, minter, tmp_path, capsys
    ):
        def mint(path):
            raise ValueError("no such key file")

        rc, _, execvpe = run_main(minter, tmp_path, mint=mint)
        out = capsys.readouterr()
        assert rc == 1 and execvpe.calls == []
        assert "/etc/acme/co-pypi-reader.json" in out.err and "ValueError" in out.err

    def test_a_failed_exec_names_the_command_and_prints_no_token(
        self, minter, tmp_path, capsys
    ):
        execvpe = Exec(raises=FileNotFoundError(2, "No such file or directory"))
        rc, _, _ = run_main(minter, tmp_path, execvpe=execvpe)
        out = capsys.readouterr()
        assert rc == 127 and "could not run uv" in out.err
        assert TOKEN not in out.out + out.err


class TestTheMint:
    """mint_token against a stand-in google package: the named key, the scope,
    a refresh, and no ADC search."""

    @pytest.fixture
    def google(self, monkeypatch):
        calls: dict = {}

        class Credentials:
            token = TOKEN

            @classmethod
            def from_service_account_file(cls, path, scopes):
                calls["file"] = (path, scopes)
                return cls()

            def refresh(self, request):
                calls["refresh"] = request

        def default(*a, **k):  # google.auth.default: ADC, which must never run
            raise AssertionError("ADC searched")

        modules = {
            "google": types.ModuleType("google"),
            "google.auth": types.SimpleNamespace(default=default),
            "google.auth.transport": types.ModuleType("google.auth.transport"),
            "google.auth.transport.requests": types.SimpleNamespace(Request=object),
            "google.oauth2": types.ModuleType("google.oauth2"),
            "google.oauth2.service_account": types.SimpleNamespace(
                Credentials=Credentials
            ),
        }
        for name, module in modules.items():
            monkeypatch.setitem(sys.modules, name, module)
        monkeypatch.setattr(
            sys.modules["google.oauth2"],
            "service_account",
            modules["google.oauth2.service_account"],
            raising=False,
        )
        calls["Credentials"] = Credentials
        return calls

    def test_mints_from_the_named_key(self, minter, google):
        assert minter.mint_token("/etc/acme/co-pypi-reader.json") == TOKEN
        assert google["file"] == ("/etc/acme/co-pypi-reader.json", minter.SCOPES)
        assert "refresh" in google

    def test_an_empty_token_is_a_failure(self, minter, google, monkeypatch):
        monkeypatch.setattr(google["Credentials"], "token", None)
        with pytest.raises(RuntimeError, match="no access token"):
            minter.mint_token("/k.json")


@pytest.fixture
def fake_uv(tmp_path) -> Path:
    """A uv that prints its arguments and the names (and CO_PYPI_KEY) it was handed."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    uv = bin_ / "uv"
    uv.write_text(
        '#!/usr/bin/env bash\nprintf "args %s\\n" "$*"\n'
        'compgen -e | sort | sed "s/^/env /"\n'
        'printf "key %s\\n" "${CO_PYPI_KEY:-}"\n'
    )
    uv.chmod(0o755)
    return bin_


LOCKED_GROUP = 'co-pypi = [{ name = "google-auth", extras = ["requests"] }]\n'


def run_wrapper(tmp_path: Path, fake_uv: Path, lock: str | None):
    repo = tmp_path / "acme"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(WRAPPER, repo / "scripts" / "co-pypi.sh")
    if lock is not None:
        (repo / "uv.lock").write_text(lock)
    result = subprocess.run(
        ["bash", str(repo / "scripts" / "co-pypi.sh"), "uv", "lock"],
        capture_output=True,
        text=True,
        env={"PATH": f"{fake_uv}:/usr/bin:/bin", "HOME": str(tmp_path)},
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return (repo / "scripts").resolve(), result


class TestTheShellWrapper:
    @pytest.mark.parametrize(
        "lock", [None, "version = 1\n"], ids=["no-lock", "no-group"]
    )
    def test_a_lock_without_the_group_resolves_it_once_and_says_so(
        self, tmp_path, fake_uv, lock
    ):
        """A repo's first `uv lock` needs the token, so --frozen can't apply yet."""
        scripts, result = run_wrapper(tmp_path, fake_uv, lock)
        assert result.stdout.splitlines()[0] == (
            "args run --no-project --with google-auth[requests]>=2,<3 "
            f"python {scripts}/co_pypi_token.py uv lock"
        )
        assert "holds no co-pypi group yet" in result.stderr

    def test_a_lock_with_the_group_runs_it_frozen_and_quietly(self, tmp_path, fake_uv):
        scripts, result = run_wrapper(tmp_path, fake_uv, LOCKED_GROUP)
        assert result.stdout.splitlines()[0].startswith(
            f"args run --project {scripts.parent} --frozen --only-group co-pypi "
        )
        assert result.stderr == ""

    def test_runs_the_locked_group_from_the_allowlist(self, tmp_path, fake_uv):
        repo = tmp_path / "acme"
        (repo / "scripts").mkdir(parents=True)
        shutil.copy(WRAPPER, repo / "scripts" / "co-pypi.sh")
        (repo / "uv.lock").write_text(LOCKED_GROUP)
        env = {
            "PATH": f"{fake_uv}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "LC_ALL": "C",
            "UV_CACHE_DIR": str(tmp_path / "cache"),
            "CO_PYPI_KEY": "/etc/acme/co-pypi-reader.json",
            "GH_TOKEN": "ghp_x",
            "GOOGLE_APPLICATION_CREDENTIALS": "/etc/acme/writer.json",
            "VIRTUAL_ENV": "/somewhere/.venv",
        }
        result = subprocess.run(
            ["bash", str(repo / "scripts" / "co-pypi.sh"), "uv", "sync", "--locked"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        lines = result.stdout.splitlines()
        scripts = (repo / "scripts").resolve()
        assert lines[0] == (
            f"args run --project {scripts.parent} --frozen --only-group co-pypi "
            f"python {scripts}/co_pypi_token.py uv sync --locked"
        )
        names = {ln[4:] for ln in lines if ln.startswith("env ")}
        assert {"PATH", "HOME", "LC_ALL", "UV_CACHE_DIR", "CO_PYPI_KEY"} <= names
        assert not names & {"GH_TOKEN", "GOOGLE_APPLICATION_CREDENTIALS", "VIRTUAL_ENV"}
        assert "key /etc/acme/co-pypi-reader.json" in lines


def install(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALL), "--repo", str(repo), "--co-pypi", *args],
        capture_output=True,
        text=True,
        env=clean_env(),
        timeout=60,
    )


@pytest.fixture
def repo(tmp_path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=clean_env())
    return tmp_path


class TestInstall:
    def test_installs_the_pair_and_the_test(self, repo):
        result = install(repo)
        assert result.returncode == 0, result.stderr
        assert result.stdout == "installed\t-\t1\n"
        scripts = repo / "scripts"
        assert (scripts / "co-pypi.sh").read_bytes() == WRAPPER.read_bytes()
        assert (scripts / "co_pypi_token.py").read_bytes() == MINTER.read_bytes()
        assert (scripts / "co-pypi.sh").stat().st_mode & 0o111
        assert (
            repo / "tests" / "test_co_pypi.py"
        ).read_bytes() == CONSUMER_TEST.read_bytes()
        assert not (scripts / "deploy.sh").exists(), "--co-pypi installs no core"

    def test_a_ruff_that_reaches_the_minter_is_named(self, repo):
        (repo / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
        assert "extend-exclude" in install(repo).stderr
        (repo / "pyproject.toml").write_text(
            '[tool.ruff]\nextend-exclude = ["scripts/co_pypi_token.py"]\n'
        )
        assert "extend-exclude" not in install(repo).stderr

    def test_a_rerun_that_changes_nothing_still_names_the_setup(self, repo):
        (repo / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
        install(repo)
        result = install(repo)
        assert result.stdout == "current\t1\t1\n"
        assert "co-pypi dependency group" in result.stderr
        assert "extend-exclude" in result.stderr

    def test_a_missing_group_is_named(self, repo):
        (repo / "pyproject.toml").write_text('[project]\nname = "acme"\n')
        assert "co-pypi dependency group" in install(repo).stderr
        (repo / "pyproject.toml").write_text(
            '[dependency-groups]\nco-pypi = ["google-auth[requests]>=2,<3"]\n'
        )
        assert "co-pypi dependency group" not in install(repo, "--replace").stderr

    def test_a_second_install_is_current_and_keeps_the_repos_test(self, repo):
        install(repo)
        test = repo / "tests" / "test_co_pypi.py"
        test.write_text("# the repo's own now\n")
        result = install(repo)
        assert result.returncode == 0 and result.stdout == "current\t1\t1\n"
        assert test.read_text() == "# the repo's own now\n"

    def test_a_repos_own_wrapper_is_refused_without_replace(self, repo):
        (repo / "scripts").mkdir()
        own = repo / "scripts" / "co-pypi.sh"
        own.write_text('#!/usr/bin/env bash\nexec uv run python scripts/mint.py "$@"\n')
        result = install(repo)
        assert result.returncode == 2 and result.stdout.startswith("foreign\t")
        assert "mint.py" in own.read_text()
        result = install(repo, "--replace")
        assert result.returncode == 0 and own.read_bytes() == WRAPPER.read_bytes()

    @pytest.mark.parametrize("check", [True, False], ids=["check", "install"])
    def test_a_repos_own_minter_alone_is_the_one_named(self, repo, check):
        """observo's shape: its own minter, no wrapper."""
        (repo / "scripts").mkdir()
        (repo / "scripts" / "co_pypi_token.py").write_text("print(1)\n")
        result = install(repo, *(["--check"] if check else []))
        assert result.stdout.startswith("foreign\t")
        assert "scripts/co_pypi_token.py" in result.stderr
        assert "co-pypi.sh" not in result.stderr

    def test_a_hand_edited_minter_is_refused(self, repo):
        install(repo)
        minter = repo / "scripts" / "co_pypi_token.py"
        minter.write_text(minter.read_text() + "# a local fix\n")
        result = install(repo)
        assert result.returncode == 2 and result.stdout.startswith("edited\t1\t")
        assert "scripts/co_pypi_token.py in" in result.stderr
        assert "co-pypi.sh" not in result.stderr
        assert minter.read_text().endswith("# a local fix\n")

    def test_half_a_pair_is_drift_and_an_install_completes_it(self, repo):
        install(repo)
        (repo / "scripts" / "co_pypi_token.py").unlink()
        assert install(repo, "--check").stdout.startswith("drift\t1\t")
        result = install(repo)
        assert result.returncode == 0 and result.stdout == "updated\t1\t1\n"
        assert (
            repo / "scripts" / "co_pypi_token.py"
        ).read_bytes() == MINTER.read_bytes()

    def test_the_core_and_the_wrapper_install_apart(self, repo):
        install(repo)
        core = subprocess.run(
            ["bash", str(INSTALL), "--repo", str(repo)],
            capture_output=True,
            text=True,
            env=clean_env(),
        )
        assert core.returncode == 0 and core.stdout == "installed\t-\t1\n"
        assert install(repo, "--check").stdout == "current\t1\t1\n"

    @pytest.mark.parametrize("state", ["missing", "foreign", "edited"])
    def test_check_exits_1_and_writes_nothing(self, repo, state):
        if state == "foreign":
            (repo / "scripts").mkdir()
            (repo / "scripts" / "co-pypi.sh").write_text("#!/usr/bin/env bash\n")
        elif state == "edited":
            install(repo)
            wrapper = repo / "scripts" / "co-pypi.sh"
            wrapper.write_text(wrapper.read_text() + "#\n")
        before = sorted(str(p) for p in repo.rglob("*") if ".git" not in p.parts)
        result = install(repo, "--check")
        assert result.returncode == 1 and result.stdout.split("\t")[0] == state
        assert (
            sorted(str(p) for p in repo.rglob("*") if ".git" not in p.parts) == before
        )


# A consumer the test asset runs in: an index-pinned private package, the
# wrapper's group from PyPI, and the installed pair.
PYPROJECT = f"""[project]
name = "acme"
version = "0.1.0"
dependencies = ["co-core>=0.37,<0.38", "httpx>=0.28"]

[dependency-groups]
co-pypi = ["google-auth[requests]>=2,<3"]

[[tool.uv.index]]
name = "co-pypi"
url = "{URL}"
explicit = true

[tool.uv.sources]
co-core = {{ index = "co-pypi" }}

[tool.ruff]
line-length = 100
extend-exclude = ["skills-vendor/", "scripts/co_pypi_token.py"]
"""
WHEEL = "https://us-west1-python.pkg.dev/co-gcs/co-pypi/co-core/co_core-0.37.1-py3-none-any.whl"
LOCK = f"""version = 1
revision = 3
requires-python = ">=3.12"

[[package]]
name = "acme"
version = "0.1.0"
source = {{ editable = "." }}
dependencies = [{{ name = "co-core" }}, {{ name = "httpx" }}]

[package.dev-dependencies]
co-pypi = [{{ name = "google-auth", extra = ["requests"] }}]

[[package]]
name = "co-core"
version = "0.37.1"
source = {{ registry = "{URL}" }}
wheels = [{{ url = "{WHEEL}", hash = "sha256:{"a" * 64}" }}]

[[package]]
name = "google-auth"
version = "2.40.0"
source = {{ registry = "https://pypi.org/simple" }}
dependencies = [{{ name = "rsa" }}]

[package.optional-dependencies]
requests = [{{ name = "requests" }}]

[[package]]
name = "httpx"
version = "0.28.1"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "requests"
version = "2.32.5"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "rsa"
version = "4.9"
source = {{ registry = "https://pypi.org/simple" }}
"""


@pytest.fixture
def consumer(repo) -> Path:
    (repo / "pyproject.toml").write_text(PYPROJECT)
    (repo / "uv.lock").write_text(LOCK)
    result = install(repo)
    assert result.returncode == 0, result.stderr
    assert "dependency group" not in result.stderr
    assert "extend-exclude" not in result.stderr
    return repo


def run_consumer_tests(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=repo,
        capture_output=True,
        text=True,
        # The nested scrub (#554). The consumer repo IS the calling test's
        # tmp_path here, so the temp root sits in it; the run collects only
        # `tests`, and the consumer's test reads only named files.
        env=nested_pytest_env(repo, clean_env()),
        timeout=120,
    )


def test_the_consumer_passes_its_own_test(consumer):
    result = run_consumer_tests(consumer)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_private_package_in_a_group_is_declared(consumer):
    """A source binds to a dependency group's names too."""
    path = consumer / "pyproject.toml"
    text = path.read_text().replace('"co-core>=0.37,<0.38", ', "")
    path.write_text(
        text.replace("co-pypi = [", 'dev = ["co-core>=0.37,<0.38"]\nco-pypi = [')
    )
    result = run_consumer_tests(consumer)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_workspace_members_private_package_is_declared(consumer):
    """LAYOUT=workspace: the root has no [project], a member declares the name."""
    path = consumer / "pyproject.toml"
    project, rest = path.read_text().split("\n[dependency-groups]", 1)
    path.write_text(
        '[tool.uv.workspace]\nmembers = ["packages/*"]\n\n[dependency-groups]' + rest
    )
    member = consumer / "packages" / "api"
    member.mkdir(parents=True)
    (member / "pyproject.toml").write_text(project)
    result = run_consumer_tests(consumer)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("file", "old", "new"),
    [
        ("pyproject.toml", "explicit = true", "explicit = false"),
        ("pyproject.toml", 'url = "' + URL, 'url = "' + URL.rstrip("/")),
        ("pyproject.toml", 'co-core = { index = "co-pypi" }', ""),
        ("pyproject.toml", '"co-core>=0.37,<0.38", ', ""),
        (
            "pyproject.toml",
            "[[tool.uv.index]]",
            '[tool.uv]\nfind-links = ["./.wheelhouse"]\n\n[[tool.uv.index]]',
        ),
        (
            "pyproject.toml",
            'co-pypi = ["google-auth[requests]>=2,<3"]',
            'co-pypi = ["rsa"]',
        ),
        ("uv.lock", 'hash = "sha256:', 'hash = "md5:'),
        (
            "uv.lock",
            'name = "rsa"\nversion = "4.9"\nsource = { registry = "https://pypi.org/simple" }',
            f'name = "rsa"\nversion = "4.9"\nsource = {{ registry = "{URL}" }}\nwheels = [{{ url = "https://us-west1-python.pkg.dev/r.whl", hash = "sha256:{"b" * 64}" }}]',
        ),
        ("scripts/co_pypi_token.py", "KEY_VAR = ", "KEY_VAR =  "),
        ("pyproject.toml", ', "scripts/co_pypi_token.py"]', "]"),
    ],
    ids=[
        "implicit",
        "url",
        "unsourced",
        "transitive",
        "find-links",
        "no-google-auth",
        "no-sha256",
        "group-needs-index",
        "edited",
        "ruff-reaches-the-minter",
    ],
)
def test_each_invariant_fails_when_broken(consumer, file, old, new):
    path = consumer / file
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new, 1))
    result = run_consumer_tests(consumer)
    assert result.returncode != 0, result.stdout


def test_nothing_in_the_pair_is_one_repos():
    """Byte-identical across repos: no repo's key path or key variable."""
    for path in (WRAPPER, MINTER):
        text = path.read_text()
        paths = set(re.findall(r"/etc/[^\s`'\"),]+", text))
        assert paths <= {
            "/etc/{name}/co-pypi-reader.json",
            "/etc/<[project].name>/co-pypi-reader.json",
            "/etc/<name>/co-pypi-reader.json",
        }, paths
        assert not re.findall(r"\b[A-Z]+_CO_PYPI_(?:KEY|CREDENTIALS)\b", text)


def test_the_wrapper_parses_and_its_minter_compiles():
    assert subprocess.run(["bash", "-n", str(WRAPPER)]).returncode == 0
    compile(MINTER.read_text(), str(MINTER), "exec")
    assert os.access(WRAPPER, os.X_OK)
