"""`extensions.worktreeConfig` was evaluated for #189 and refused (direction 3).

The proposal read: "Consider `git config extensions.worktreeConfig true` so a
worktree's `--local` writes stay local." That premise is false, and this file is
the measurement that says so rather than a paragraph asserting it.

A refusal recorded only in prose decays silently — git changes, and the sentence
that justified the decision keeps reading true. So each load-bearing fact gets a
behavioural test against a throwaway repo. If a future git makes the extension
redirect `--local`, or makes it stop shielding what it shields today, the
decision goes **red** and gets re-taken with the new evidence instead of being
inherited on faith.

What was measured (git 2.39.3, Apple Git-145):

1. `git config --local` from a linked worktree writes the **shared** `.git/config`
   with the extension enabled exactly as without it. The extension *adds* a
   `--worktree` scope; it does not move `--local`. `TestLocalWritesStillEscape`.
2. The extension is not inert here — `--worktree` really does write and read a
   per-worktree config even at `core.repositoryformatversion = 0`, where
   `extensions.*` is formally out of contract. So "it does nothing" is not the
   reason for the refusal; "it does not do *that*" is. `TestWhatTheExtensionActuallyBuys`.
3. #189's corruption arrives through an inherited `GIT_DIR`, not through
   `--local`, and the extension does not touch that path: `core.bare = true`
   still lands in the shared config and still makes the main checkout's
   `git status` exit non-zero with empty stdout. `TestGitDirCorruptionIsUnaffected`.
4. The one arrangement that *does* change the outcome — pinning
   `core.bare = false` into the main worktree's `.git/config.worktree` — is a
   blindfold, not a repair: the main checkout reports healthy while the shared
   config is corrupt and every linked worktree is broken. It defeats the Rule 6
   canary that #189 direction 2 shipped. `TestTheCleverVariantIsWorse`.

The decision itself lives in `docs/STYLE.md`; `TestTheDecisionIsRecorded` keeps
the record and the tests from drifting apart, and keeps the falsified claim from
growing back.

No API calls. Every repo is built under `tmp_path`, and every git invocation
scrubs `GIT_*` from the environment first (docs/STYLE.md, "A repo-creating git
command must scrub `GIT_DIR`") — without that, running under this repo's own
pre-commit hook would point these fixtures at the real repository, which is the
very defect under study.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STYLE = REPO_ROOT / "docs" / "STYLE.md"
AGENTS = REPO_ROOT / "AGENTS.md"

# `git config --worktree` and `extensions.worktreeConfig` both arrived in 2.20.
MIN_GIT = (2, 20)


def _clean_env(**overrides: str) -> dict:
    """Env with every `GIT_*` variable dropped, plus explicit overrides.

    `GIT_DIR` outranks both `git -C` and cwd, and git exports it to every hook
    process, so dropping the whole family is the only reliable scrub. Overrides
    are applied *after* the scrub — one test sets `GIT_DIR` deliberately, at a
    path it created under `tmp_path`.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["LC_ALL"] = "C"
    env.update(overrides)
    return env


def _git(cwd: Path, *args: str, check: bool = True, env: dict | None = None):
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=check,
        env=env if env is not None else _clean_env(),
    )


def _git_version() -> tuple[int, ...]:
    out = subprocess.run(
        ["git", "--version"], capture_output=True, text=True, env=_clean_env()
    ).stdout
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out)
    return tuple(int(g) for g in m.groups()) if m else (0, 0, 0)


pytestmark = pytest.mark.skipif(
    _git_version() < MIN_GIT,
    reason=f"needs git >= {'.'.join(map(str, MIN_GIT))} for --worktree config scope",
)


def _get(cwd: Path, key: str, *scope: str) -> str | None:
    """`git config --get`, with `None` for unset rather than an exception."""
    r = _git(cwd, "config", *scope, "--get", key, check=False)
    return r.stdout.strip() if r.returncode == 0 else None


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A one-commit repo, path-resolved through any /var -> /private/var symlink."""
    r = (tmp_path / "repo").resolve()
    r.mkdir()
    _git(tmp_path.resolve(), "init", "-q", "-b", "main", str(r))
    _git(r, "config", "user.email", "test@example.com")
    _git(r, "config", "user.name", "test")
    _git(r, "config", "core.hooksPath", str(r / ".git" / "hooks"))
    (r / "f.txt").write_text("x\n")
    _git(r, "add", "f.txt")
    _git(r, "commit", "-q", "-m", "initial")
    return r


@pytest.fixture
def linked(repo: Path) -> Path:
    """A linked worktree — the vantage point the whole issue is about."""
    wt = repo / ".wt" / "one"
    _git(repo, "worktree", "add", "-q", "-b", "one", str(wt))
    return wt.resolve()


def _enable(repo: Path) -> None:
    _git(repo, "config", "extensions.worktreeConfig", "true")


def _shared_config(repo: Path) -> str:
    return (repo / ".git" / "config").read_text()


class TestLocalWritesStillEscape:
    """The refutation: `--local` from a worktree is shared config either way."""

    def test_without_the_extension_local_reaches_the_shared_config(
        self, repo: Path, linked: Path
    ):
        """Baseline, so the comparison below is a comparison and not an assertion."""
        _git(linked, "config", "--local", "probe.baseline", "landed")
        assert _get(repo, "probe.baseline", "--local") == "landed"
        assert "[probe]" in _shared_config(repo)

    def test_with_the_extension_local_still_reaches_the_shared_config(
        self, repo: Path, linked: Path
    ):
        """#189 direction 3's premise, measured false.

        "so a worktree's `--local` writes stay local" — they do not. The
        extension adds a scope, it does not move an existing one. If this ever
        passes as written in the issue, the refusal in docs/STYLE.md is stale
        and the decision should be re-taken.
        """
        _enable(repo)
        _git(linked, "config", "--local", "probe.afterext", "landed")
        assert _get(repo, "probe.afterext", "--local") == "landed", (
            "extensions.worktreeConfig was adopted-or-refused on the claim that "
            "it redirects a linked worktree's `--local` writes. It does not: the "
            "value landed in the shared .git/config anyway. If git changed this, "
            "re-take the decision recorded in docs/STYLE.md."
        )
        assert "[probe]" in _shared_config(repo), (
            "the section must be physically present in the main checkout's "
            "shared .git/config file, not merely visible through inheritance"
        )

    def test_the_per_worktree_file_is_not_created_by_a_local_write(
        self, repo: Path, linked: Path
    ):
        """Nothing routes to `config.worktree` unless a command asks for it."""
        _enable(repo)
        _git(linked, "config", "--local", "probe.k", "v")
        assert not (repo / ".git" / "worktrees" / "one" / "config.worktree").exists()
        assert not (repo / ".git" / "config.worktree").exists()


class TestWhatTheExtensionActuallyBuys:
    """It is not inert — it adds an opt-in scope. That is all it adds."""

    def test_worktree_scope_writes_and_reads_per_worktree(
        self, repo: Path, linked: Path
    ):
        _enable(repo)
        _git(linked, "config", "--worktree", "probe.wt", "landed")
        assert (repo / ".git" / "worktrees" / "one" / "config.worktree").exists()
        assert "probe.wt" not in _shared_config(repo)
        assert _get(linked, "probe.wt") == "landed"
        assert _get(repo, "probe.wt") is None, (
            "the value must be invisible from the main checkout, or the scope "
            "is not per-worktree at all"
        )

    def test_it_is_honoured_at_repositoryformatversion_zero(
        self, repo: Path, linked: Path
    ):
        """`extensions.*` is formally a v1 feature; this repo is v0.

        Git honours it at v0 regardless, which is why "the setting would be
        inert here" is *not* among the reasons for the refusal — and is itself
        a reason for caution, since it is version-dependent behaviour nobody
        announced. A git that starts ignoring it at v0 turns this red.
        """
        assert _get(repo, "core.repositoryformatversion") == "0"
        _enable(repo)
        _git(linked, "config", "--worktree", "probe.v0", "landed")
        assert _get(linked, "probe.v0") == "landed", (
            "config.worktree was written but not read back — git no longer "
            "honours extensions.worktreeConfig at repositoryformatversion 0"
        )

    def test_core_hookspath_resolves_identically_from_both_checkouts(
        self, repo: Path, linked: Path
    ):
        """#189 flagged the absolute `core.hooksPath` as the adoption risk.

        It is not one: the setting lives in the shared config and both vantage
        points still resolve it to the same absolute path. The reasons to refuse
        are the other three, not this.
        """
        before = _get(repo, "core.hooksPath")
        _enable(repo)
        assert _get(repo, "core.hooksPath") == before
        assert _get(linked, "core.hooksPath") == before

    def test_a_clone_does_not_inherit_the_extension(self, repo: Path, tmp_path: Path):
        """So it can never be a property of the repository anyone else receives."""
        _enable(repo)
        dest = (tmp_path / "clone").resolve()
        _git(tmp_path.resolve(), "clone", "-q", str(repo), str(dest))
        assert _get(dest, "extensions.worktreeConfig") is None


class TestGitDirCorruptionIsUnaffected:
    """The corruption #189 observed does not travel through `--local` at all."""

    @staticmethod
    def _corrupt(repo: Path, tmp_path: Path) -> None:
        """A fixture that means to build its own bare repo, under an inherited GIT_DIR.

        This is the reconstructed mechanism from docs/STYLE.md: git exports
        `GIT_DIR` to every hook process, so a throwaway-repo fixture running
        under pre-commit addresses the real repository. `GIT_DIR` is set
        explicitly here, at a path this test created.
        """
        elsewhere = (tmp_path / "elsewhere").resolve()
        elsewhere.mkdir(exist_ok=True)
        subprocess.run(
            ["git", "init", "--bare", "-q"],
            cwd=str(elsewhere),
            capture_output=True,
            text=True,
            env=_clean_env(GIT_DIR=str(repo / ".git")),
        )

    def test_without_the_extension_the_main_checkout_is_blinded(
        self, repo: Path, linked: Path, tmp_path: Path
    ):
        """Establish the failure shape: `status` fails with *empty stdout*."""
        self._corrupt(repo, tmp_path)
        assert _get(repo, "core.bare", "--local") == "true"
        r = _git(repo, "status", "--porcelain", check=False)
        assert r.returncode != 0, "precondition: the corruption breaks git status"
        assert r.stdout == "", (
            "the reason Rule 6 must read the exit code: a caller inspecting "
            "stdout alone sees exactly what 'clean' looks like"
        )

    def test_the_extension_does_not_prevent_it(
        self, repo: Path, linked: Path, tmp_path: Path
    ):
        """The adoption's actual value against the observed defect: none."""
        _enable(repo)
        self._corrupt(repo, tmp_path)
        assert _get(repo, "core.bare", "--local") == "true", (
            "extensions.worktreeConfig does not keep `core.bare` out of the "
            "shared config — the write never went through `--local`"
        )
        assert _git(repo, "status", "--porcelain", check=False).returncode != 0
        assert not (repo / ".git" / "config.worktree").exists(), (
            "enabling the extension by hand does not relocate core.bare; only "
            "`git sparse-checkout init` moves it, and only when it is already true"
        )


class TestTheCleverVariantIsWorse:
    """Pinning `core.bare` per-worktree hides the corruption from the canary."""

    def test_pinning_core_bare_masks_rule_six_on_the_main_checkout(
        self, repo: Path, linked: Path, tmp_path: Path
    ):
        _enable(repo)
        _git(repo, "config", "--worktree", "core.bare", "false")
        TestGitDirCorruptionIsUnaffected._corrupt(repo, tmp_path)

        assert _get(repo, "core.bare", "--local") == "true", (
            "precondition: the shared config is corrupt"
        )
        # ...and yet every signal the orchestrator has says healthy.
        assert _get(repo, "core.bare") == "false"
        assert (
            _git(repo, "rev-parse", "--is-inside-work-tree").stdout.strip() == "true"
        ), (
            "#189 direction 2's canary reads healthy over a corrupt shared "
            "config — this is why the pin is refused, not adopted"
        )
        assert _git(repo, "status", "--porcelain", check=False).returncode == 0

    def test_the_pin_shields_only_the_main_worktree(
        self, repo: Path, linked: Path, tmp_path: Path
    ):
        """`.git/config.worktree` belongs to the main worktree alone.

        So the arrangement trades a loud, detectable failure for a quiet one:
        the detector says clean while every linked worktree is broken.
        """
        _enable(repo)
        _git(repo, "config", "--worktree", "core.bare", "false")
        TestGitDirCorruptionIsUnaffected._corrupt(repo, tmp_path)

        assert _get(linked, "core.bare") == "true"
        assert (
            _git(linked, "rev-parse", "--is-inside-work-tree").stdout.strip() == "false"
        )
        assert _git(linked, "status", "--porcelain", check=False).returncode != 0


class TestTheDecisionIsRecorded:
    """The prose and these measurements must not drift apart."""

    def test_style_carries_the_refusal_and_points_at_this_file(self):
        text = STYLE.read_text()
        assert "extensions.worktreeConfig` is refused here" in text, (
            "docs/STYLE.md must carry the decision; a refusal nobody can find "
            "gets re-proposed every time the symptom recurs"
        )
        assert "tests/structural/test_worktree_config_extension.py" in text, (
            "the recorded decision must name the evidence, or the next reader "
            "has prose and no way to check it"
        )
        assert "/issues/189" in text

    def test_style_no_longer_claims_the_extension_redirects_local(self):
        """The falsified sentence, pinned so it cannot grow back.

        docs/STYLE.md used to read "`git config --local` from a linked worktree
        writes the shared config *unless `extensions.worktreeConfig` is set*".
        The tests above measure that clause false.
        """
        text = STYLE.read_text()
        assert "unless `extensions.worktreeConfig` is set" not in text

    def test_agents_md_points_to_the_decision(self):
        text = AGENTS.read_text()
        assert "extensions.worktreeConfig" in text, (
            "the always-loaded policy file must at least name the refusal, or "
            "an agent proposes it again without ever opening docs/STYLE.md"
        )
        assert "docs/STYLE.md" in text


class TestThisRepoHasNotAdoptedIt:
    """The live invariant the recorded reasoning assumes."""

    def test_the_extension_is_not_enabled_on_this_repository(self):
        if not (REPO_ROOT / ".git").exists():
            pytest.skip("not a git checkout")
        assert _get(REPO_ROOT, "extensions.worktreeConfig", "--local") is None, (
            "this repository has enabled extensions.worktreeConfig. The refusal "
            "in docs/STYLE.md was written against a repo that had not — re-read "
            "it and either re-take the decision or revert the setting with "
            "`git config --unset extensions.worktreeConfig` in the MAIN checkout"
        )

    def test_core_bare_is_false_in_the_shared_config(self):
        """The #189 symptom itself, checked on the real repository.

        Cheap, and it fails loudly in the one state where `git status` would
        otherwise answer "clean" forever.
        """
        if not (REPO_ROOT / ".git").exists():
            pytest.skip("not a git checkout")
        assert _get(REPO_ROOT, "core.bare", "--local") == "false", (
            "the shared .git/config does not say `core.bare = false`. If it "
            "says true, a worker corrupted the main checkout (#189); repair "
            "with `git config --local core.bare false` in the MAIN checkout"
        )
