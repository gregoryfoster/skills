"""The `ours` merge driver has to exist, not just be named (#192).

`install-cadence.sh --check` reported

    calibration merge:  yes (regenerate-on-collision for both)

off a `.gitattributes` grep alone. But `ours` is the one merge driver git does
**not** define for you: `union` and `binary` are built in, `ours` is not, and a
`merge=ours` attribute with no `merge.ours.driver` in config is inert — git
falls back to the built-in 3-way merge and conflicts exactly as if the attribute
were absent. #173 set the driver correctly, but *inside the workflow job*, on a
throwaway runner. Config is not versioned, so every developer clone was
unprotected while `--check` read green.

Reproduced before any of this was written, on a throwaway repo with the
attribute committed and the driver unset::

    $ git merge other
    CONFLICT (content): Merge conflict in .skills/context-token-ratio
    $ cat .skills/context-token-ratio
    <<<<<<< HEAD
    2.55
    =======
    2.47
    >>>>>>> other

`TestTheAttributeAloneIsInert` is that repro, run both ways, so the claim is
executed rather than asserted. The rest pin the two halves of the fix — the
installer defines the driver in the clone it runs in, and `--check` reports it
as its own guarantee, because config and tree are two independent ways to lose
the same file.

Every git invocation here carries an explicit `-C <repo>` and a config
environment pinned to /dev/null. Both matter: a bare `git config` inside a
linked worktree writes to the *shared* `.git/config` of the main checkout
(#189), and a developer with `merge.ours.driver` in `~/.gitconfig` would make
every MISSING assertion below vacuous.
"""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INSTALL_CADENCE = (
    REPO_ROOT / "skills" / "curating-context" / "scripts" / "install-cadence.sh"
)
CADENCE_DOC = (
    REPO_ROOT / "skills" / "curating-context" / "references" / "cadence.md"
)

LEDGER = ".skills/context-metrics.jsonl"
RATIO = ".skills/context-token-ratio"
COUNTS = ".skills/context-token-counts"
DRIVER = "merge.ours.driver"


def _env() -> dict:
    """No inherited GIT_* vars, and no global or system config.

    The GIT_* strip is the same precaution the rest of this suite takes —
    pre-commit exports GIT_INDEX_FILE and friends, which leak into the scripts'
    own git calls. The two /dev/null knobs are specific to this file: `git
    config --get` searches system, global and local, so a machine that already
    carries the driver globally would report every repo here as protected and
    the MISSING half of these tests would assert nothing.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, env=_env(), timeout=30,
    )


def _repo(tmp_path: Path, name: str = "r") -> Path:
    repo = tmp_path / name
    repo.mkdir(exist_ok=True)
    r = _git(repo, "init", "-q", "-b", "main")
    assert r.returncode == 0, r.stderr
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALL_CADENCE), *args],
        cwd=str(repo), capture_output=True, text=True, env=_env(), timeout=30,
    )


def _driver(repo: Path) -> str:
    return _git(repo, "config", "--get", DRIVER).stdout.strip()


class TestTheAttributeAloneIsInert:
    """The defect itself, executed. `merge=ours` without a driver conflicts.

    Run both ways in one test so a future reader cannot mistake the conflict
    for something about the fixture: same repo, same commits, driver the only
    difference.
    """

    def _diverge(self, tmp_path: Path, name: str) -> Path:
        repo = _repo(tmp_path, name)
        (repo / ".skills").mkdir(exist_ok=True)
        (repo / ".gitattributes").write_text(
            f"{RATIO} merge=ours\n{LEDGER} merge=union\n"
        )
        (repo / RATIO).write_text("2.50\n")
        (repo / LEDGER).write_text('{"row":0}\n')
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "base")

        _git(repo, "checkout", "-q", "-b", "other")
        (repo / RATIO).write_text("2.47\n")
        (repo / LEDGER).write_text('{"row":0}\n{"row":"other"}\n')
        _git(repo, "commit", "-qam", "other")

        _git(repo, "checkout", "-q", "main")
        (repo / RATIO).write_text("2.55\n")
        (repo / LEDGER).write_text('{"row":0}\n{"row":"main"}\n')
        _git(repo, "commit", "-qam", "main")
        return repo

    def test_without_the_driver_the_calibration_file_conflicts(
        self, tmp_path: Path
    ):
        repo = self._diverge(tmp_path, "undefined")
        assert _driver(repo) == "", "the driver must be unset for this repro"
        r = _git(repo, "merge", "other")
        assert r.returncode != 0, (
            "merge=ours resolved with no driver defined — if git has started "
            "shipping `ours` as a built-in, this whole issue is moot:\n" + r.stdout
        )
        assert "<<<<<<<" in (repo / RATIO).read_text(), (
            "expected conflict markers in a file that is regenerated and must "
            "never be hand-merged"
        )

    def test_with_the_driver_it_keeps_the_branchs_copy(self, tmp_path: Path):
        repo = self._diverge(tmp_path, "defined")
        _git(repo, "config", DRIVER, "true")
        r = _git(repo, "merge", "other")
        assert r.returncode == 0, r.stdout + r.stderr
        assert (repo / RATIO).read_text() == "2.55\n", (
            "`ours` must keep the copy already on the branch and drop the "
            "replayed one; the next --exact run recomputes it"
        )

    def test_the_ledgers_union_merge_needs_no_driver(self, tmp_path: Path):
        """The asymmetry, pinned so nobody 'fixes' the ledger too.

        `union` IS a built-in. The ledger merges cleanly with config empty,
        which is why #173's attribute worked in consumer repos and the two
        calibration attributes beside it did not.
        """
        repo = self._diverge(tmp_path, "union")
        assert _driver(repo) == ""
        _git(repo, "merge", "other")          # conflicts on the ratio only
        assert (repo / LEDGER).read_text() == (
            '{"row":0}\n{"row":"main"}\n{"row":"other"}\n'
        ), "union did not auto-merge without a driver"


class TestTheInstallerDefinesTheDriver:
    def test_a_plain_install_sets_it(self, tmp_path: Path):
        repo = _repo(tmp_path)
        r = _run(repo)
        assert r.returncode == 0, r.stderr
        assert _driver(repo) == "true", (
            "the installer wrote the attribute and left it inert:\n" + r.stdout
        )

    def test_it_says_so(self, tmp_path: Path):
        """Printed, not silent. The installer's whole output is the handover to
        a human who then has to commit something — and this is the one part
        that cannot be committed."""
        repo = _repo(tmp_path)
        out = _run(repo).stdout
        assert DRIVER in out, out

    def test_it_is_idempotent_and_does_not_churn(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _run(repo)
        second = _run(repo)
        assert second.returncode == 0, second.stderr
        assert _driver(repo) == "true"
        values = _git(repo, "config", "--get-all", DRIVER).stdout.split()
        assert values == ["true"], f"the value was appended, not set: {values}"

    def test_it_is_written_local_to_the_clone(self, tmp_path: Path):
        """--local, so a run inside somebody's repo never edits their global
        config. It is also the correct scope: the driver exists to make one
        repo's committed attributes work."""
        repo = _repo(tmp_path)
        _run(repo)
        assert _git(repo, "config", "--local", "--get", DRIVER).stdout.strip() == (
            "true"
        )

    def test_a_pre_192_install_is_repaired_by_rerunning(self, tmp_path: Path):
        """Every repo the cohort installed between #173 and this fix has all
        three attributes and no driver — including the ones whose --check said
        they were fine. Re-running is what --check tells them to do."""
        repo = _repo(tmp_path)
        _run(repo)
        _git(repo, "config", "--unset", DRIVER)
        assert _run(repo, "--check").returncode == 3

        assert _run(repo).returncode == 0
        assert _driver(repo) == "true"
        assert _run(repo, "--check").returncode == 0

    def test_print_touches_nothing(self, tmp_path: Path):
        repo = _repo(tmp_path)
        assert _run(repo, "--print").returncode == 0
        assert _driver(repo) == "", "--print is documented to change nothing"

    def test_uninstall_leaves_the_driver_alone(self, tmp_path: Path):
        """Deliberate asymmetry with the attributes, which DO come out.

        `merge.ours.driver` is repo-wide and generic: any other `merge=ours`
        attribute in the repo depends on it, and unsetting it on uninstall
        would break rules this script never wrote. Left set it is inert —
        a driver with nothing pointing at it never runs.
        """
        repo = _repo(tmp_path)
        _run(repo)
        r = _run(repo, "--uninstall")
        assert r.returncode == 0, r.stderr
        assert _driver(repo) == "true"


class TestCheckReportsTheDriverIndependently:
    """#173's rule, one level down: each guarantee is its own way to lose the
    file, so each gets its own line. Folding the driver into the calibration
    report would reproduce exactly the combined 'ok' that read green
    through #173."""

    def test_a_fresh_install_reports_it_present(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _run(repo)
        r = _run(repo, "--check")
        assert r.returncode == 0, r.stdout
        assert "ours merge driver:  yes" in r.stdout, r.stdout

    def test_the_attributes_alone_are_not_reported_as_protection(
        self, tmp_path: Path
    ):
        """The bug verbatim: all three attributes present, driver absent,
        `--check` exiting 0 on a guarantee that does not hold."""
        repo = _repo(tmp_path)
        _run(repo)
        _git(repo, "config", "--unset", DRIVER)
        r = _run(repo, "--check")
        assert r.returncode == 3, r.stdout
        assert "ours merge driver:  MISSING" in r.stdout, r.stdout
        # Still reported, and still true — the attributes ARE there. Reporting
        # them as MISSING would send the reader to rewrite a correct file.
        assert "calibration merge:  yes" in r.stdout, r.stdout

    def test_the_failure_text_names_the_one_line_fix(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _run(repo)
        _git(repo, "config", "--unset", DRIVER)
        r = _run(repo, "--check")
        assert "git config merge.ours.driver true" in r.stdout, r.stdout

    def test_the_driver_is_reported_without_the_attributes(self, tmp_path: Path):
        """The other direction. A config-only repo must not read green on the
        attributes, and must not hide the driver line behind them."""
        repo = _repo(tmp_path)
        _git(repo, "config", DRIVER, "true")
        r = _run(repo, "--check")
        assert r.returncode == 3, r.stdout
        assert "ours merge driver:  yes" in r.stdout, r.stdout
        assert "calibration merge:  MISSING" in r.stdout, r.stdout

    def test_all_four_guarantees_are_always_printed(self, tmp_path: Path):
        """Nothing gates on anything else. An empty repo reports four
        failures, not the first one."""
        repo = _repo(tmp_path)
        r = _run(repo, "--check")
        assert r.returncode == 3
        for label in ("workflow:", "ledger union merge:", "calibration merge:",
                      "ours merge driver:"):
            assert label in r.stdout, f"{label} missing from:\n{r.stdout}"

    def test_a_driver_set_to_something_else_counts(self, tmp_path: Path):
        """`true` is what the installer writes, but the guarantee is that the
        driver is DEFINED. A repo that resolves `ours` some other way is
        protected, and telling it otherwise would be a false alarm to match
        the false assurance this issue is about."""
        repo = _repo(tmp_path)
        _run(repo)
        _git(repo, "config", DRIVER, "/bin/true %A %O %B %L %P")
        r = _run(repo, "--check")
        assert r.returncode == 0, r.stdout
        assert "ours merge driver:  yes" in r.stdout, r.stdout

    def test_an_empty_driver_value_is_missing(self, tmp_path: Path):
        """`git config merge.ours.driver ""` exits 0 and prints nothing —
        defined-but-empty is not a driver, and git errors on the merge."""
        repo = _repo(tmp_path)
        _run(repo)
        _git(repo, "config", DRIVER, "")
        r = _run(repo, "--check")
        assert r.returncode == 3, r.stdout
        assert "ours merge driver:  MISSING" in r.stdout, r.stdout


class TestTheDocSaysHowToGetIt:
    """A reader who follows the merge section exactly still ends up
    unprotected, because config does not travel with the tree."""

    def _section(self) -> str:
        text = CADENCE_DOC.read_text()
        head = "## The ledger needs a union merge, and it needs it first"
        assert head in text, "the merge section was renamed"
        body = text.split(head, 1)[1]
        return body.split("\n## ", 1)[0]

    def test_the_merge_section_names_the_driver(self):
        section = self._section()
        assert "git config merge.ours.driver true" in section, section

    def test_it_says_config_does_not_travel_with_the_tree(self):
        """The half a reader gets wrong: they commit .gitattributes, clone
        elsewhere, and the guarantee is gone."""
        section = self._section()
        assert "not versioned" in section or "does not travel" in section, section

    def test_it_names_the_calibration_attributes_too(self):
        section = self._section()
        assert f"{RATIO} merge=ours" in section, section
        assert f"{COUNTS} merge=ours" in section, section
