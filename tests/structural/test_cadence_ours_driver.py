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

#237 then split the two calibration files. `merge=ours` keeps the side of
whoever RUNS the merge, which is unrelated to which side measured more
recently — and the cadence bot only ever pushes to the default branch, so it
was structurally always the side that lost: a branch merging `origin/main`
silently reverted the week's fresh measurement (`c7be4eb` is the incident
record). The counts file is keyed rows (`<bytes> <tokens> <path>`), so it now
merges per row through `merge-token-counts.sh`: one-sided edits merge
three-way, and a genuine collision keeps, per path, the row whose bytes match
the file as it stands in the tree. The ratio file stays `merge=ours` — a
single scalar has nothing to key on. `TestPerRowNewestWins` and
`TestNewestWinsSurvivesARealMerge` execute that contract;
`TestInstallerWiresTheNewestWinsDriver` pins its three legs (attribute,
clone config, workflow job) and `--check`'s report of each.

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

MERGE_SCRIPT = (
    REPO_ROOT / "skills" / "curating-context" / "scripts"
    / "merge-token-counts.sh"
)
COUNTS_DRIVER = "merge.context-counts.driver"
ATTR_COUNTS = f"{COUNTS} merge=context-counts"

# The real artifact's header shape, so the driver is exercised against rows
# that sit under comments the way they always do in the tree.
HEADER = (
    "# <bytes> <tokens> <path> — per-file token calibration (#145)\n"
    "# Written by measure-context.sh --exact; regenerate rather than hand-edit.\n"
)


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


class TestTheWriteCannotEscapeTheRepoItWasPointedAt:
    """Setting the driver is the first thing this installer writes outside the
    working tree, and it escaped on the first run.

    An inherited GIT_DIR beats `-C` and beats `cwd`: git resolves the config
    file from GIT_DIR and ignores the directory. Git exports GIT_DIR to every
    hook process, and from a linked worktree it is absolute — so the structural
    suite, run under pre-commit, set `merge.ours.driver` in this repo's own
    `.git/config` from a test whose subject was a temp directory. The
    `.gitattributes` half never had this failure mode because it is a plain file
    path under `$ROOT`; config is addressed by environment, not by path.

    Same class as #189, one write later.
    """

    def test_an_inherited_git_dir_does_not_redirect_the_config_write(
        self, tmp_path: Path
    ):
        bystander = _repo(tmp_path, "bystander")
        target = _repo(tmp_path, "target")

        env = _env()
        env["GIT_DIR"] = str(
            _git(bystander, "rev-parse", "--absolute-git-dir").stdout.strip()
        )
        r = subprocess.run(
            ["bash", str(INSTALL_CADENCE)],
            cwd=str(target), capture_output=True, text=True, env=env, timeout=30,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert _driver(bystander) == "", (
            "the installer wrote merge.ours.driver into a repo it was never "
            "pointed at — only GIT_DIR named it:\n" + r.stdout
        )
        assert _driver(target) == "true", r.stdout

    def test_check_reports_the_repo_it_was_run_in(self, tmp_path: Path):
        """The read has the same exposure as the write, and a --check that
        answers about another repo's config is the false assurance this issue
        is about, aimed one repo sideways."""
        elsewhere = _repo(tmp_path, "elsewhere")
        _git(elsewhere, "config", DRIVER, "true")
        here = _repo(tmp_path, "here")

        env = _env()
        env["GIT_DIR"] = str(
            _git(elsewhere, "rev-parse", "--absolute-git-dir").stdout.strip()
        )
        r = subprocess.run(
            ["bash", str(INSTALL_CADENCE), "--check"],
            cwd=str(here), capture_output=True, text=True, env=env, timeout=30,
        )
        assert "ours merge driver:  MISSING" in r.stdout, r.stdout


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
        assert f"{COUNTS} merge=context-counts" in section, section
        assert f"{COUNTS} merge=ours" not in section, (
            "the doc still tells a reader to install the pre-#237 counts "
            "attribute, which silently reverts the cadence's measurements"
        )

    def test_it_records_the_ratio_decision(self):
        """#237 left the implementer to decide whether the ratio file gets the
        newest-wins treatment or stays `merge=ours`. Either way the decision
        and its reasons live in the merge section, not in an issue thread."""
        section = self._section()
        assert "#237" in section, section
        assert COUNTS_DRIVER in section, (
            "the section never names the config key that makes the counts "
            "attribute mean anything:\n" + section
        )


def _drive(repo: Path, ancestor: str, current: str, other: str):
    """Invoke the driver exactly as git does: three temp files — ancestor,
    current, other — with the result left in the CURRENT file and exit 0
    reporting a successful merge."""
    o, a, b = repo / ".merge_O", repo / ".merge_A", repo / ".merge_B"
    o.write_text(ancestor)
    a.write_text(current)
    b.write_text(other)
    r = subprocess.run(
        ["bash", str(MERGE_SCRIPT), str(o), str(a), str(b), COUNTS],
        cwd=str(repo), capture_output=True, text=True, env=_env(), timeout=30,
    )
    return r, (a.read_text() if a.exists() else "")


class TestPerRowNewestWins:
    """#237's contract, executed against the driver script itself.

    The file is keyed rows — `<bytes> <tokens> <path>` — and `merge=ours` kept
    whichever side ran the merge, which has nothing to do with which side
    measured more recently. Per row the driver merges three-way; a genuine
    collision keeps the row whose bytes match the file as it stands in the
    tree, because that row describes a file that exists and the other one
    describes a file nobody has.
    """

    def test_a_one_sided_update_wins_without_consulting_the_tree(
        self, tmp_path: Path
    ):
        """Ordinary three-way first: if only one side re-measured, that side
        wins even when the file has drifted past BOTH rows since."""
        repo = _repo(tmp_path)
        (repo / "AGENTS.md").write_bytes(b"x" * 999)
        base = HEADER + "100 40 AGENTS.md\n"
        r, merged = _drive(repo, base, base, HEADER + "150 60 AGENTS.md\n")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "150 60 AGENTS.md" in merged
        assert "100 40 AGENTS.md" not in merged

        r, merged = _drive(repo, base, HEADER + "150 60 AGENTS.md\n", base)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "150 60 AGENTS.md" in merged

    def test_a_collision_keeps_the_row_matching_the_tree(self, tmp_path: Path):
        """Both sides re-measured. The tree is the arbiter, whichever side of
        the merge the matching row sits on."""
        repo = _repo(tmp_path)
        (repo / "AGENTS.md").write_bytes(b"x" * 150)
        base = HEADER + "100 40 AGENTS.md\n"
        ours = HEADER + "120 44 AGENTS.md\n"
        theirs = HEADER + "150 60 AGENTS.md\n"

        r, merged = _drive(repo, base, ours, theirs)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "150 60 AGENTS.md" in merged, merged

        r, merged = _drive(repo, base, theirs, ours)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "150 60 AGENTS.md" in merged, merged

    def test_a_collision_matching_neither_keeps_the_current_side(
        self, tmp_path: Path
    ):
        """The file moved on since both measurements (or is gone). Nothing to
        arbitrate with, so keep the current side's row — exactly what
        `merge=ours` did — and let the estimators' drift fallback and the next
        --exact run absorb it."""
        repo = _repo(tmp_path)
        (repo / "AGENTS.md").write_bytes(b"x" * 999)
        base = HEADER + "100 40 AGENTS.md\n"
        r, merged = _drive(
            repo, base, HEADER + "120 44 AGENTS.md\n",
            HEADER + "150 60 AGENTS.md\n",
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "120 44 AGENTS.md" in merged, merged

        (repo / "AGENTS.md").unlink()
        r, merged = _drive(
            repo, base, HEADER + "120 44 AGENTS.md\n",
            HEADER + "150 60 AGENTS.md\n",
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "120 44 AGENTS.md" in merged, merged

    def test_a_row_deleted_on_one_side_stays_deleted(self, tmp_path: Path):
        """measure-context.sh drops a row when the file leaves the surface or
        measures degenerate; a merge must not resurrect it."""
        repo = _repo(tmp_path)
        keep = "10 4 docs/a.md\n"
        base = HEADER + keep + "100 40 docs/gone.md\n"
        r, merged = _drive(repo, base, HEADER + keep, base)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "docs/gone.md" not in merged, merged

        r, merged = _drive(repo, base, base, HEADER + keep)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "docs/gone.md" not in merged, merged

    def test_rows_added_on_each_side_both_survive(self, tmp_path: Path):
        """The self-budget gate measures one skill at a time, so two branches
        legitimately calibrate disjoint files; a merge keeps both."""
        repo = _repo(tmp_path)
        base = HEADER + "10 4 docs/a.md\n"
        r, merged = _drive(
            repo, base, base + "20 8 docs/b.md\n", base + "30 12 docs/c.md\n",
        )
        assert r.returncode == 0, r.stdout + r.stderr
        for row in ("10 4 docs/a.md", "20 8 docs/b.md", "30 12 docs/c.md"):
            assert row in merged, merged

    def test_the_output_is_the_writers_shape(self, tmp_path: Path):
        """Header first, rows sorted by path under LC_ALL=C — the same shape
        measure-context.sh writes, so a merged file and a regenerated one
        diff clean."""
        repo = _repo(tmp_path)
        base = HEADER + "10 4 docs/a.md\n"
        r, merged = _drive(
            repo, base, base + "30 12 docs/z.md\n", base + "20 8 docs/b.md\n",
        )
        assert r.returncode == 0, r.stdout + r.stderr
        lines = merged.splitlines()
        assert lines[0].startswith("#"), merged
        rows = [ln for ln in lines if not ln.startswith("#")]
        paths = [" ".join(ln.split()[2:]) for ln in rows]
        assert paths == sorted(paths), merged

    def test_a_path_with_spaces_is_one_key(self, tmp_path: Path):
        """The writer treats the path as fields 3..NF for exactly this case;
        splitting on the third field alone would arbitrate the wrong file."""
        repo = _repo(tmp_path)
        (repo / "docs").mkdir()
        (repo / "docs" / "a b.md").write_bytes(b"x" * 150)
        base = HEADER + "100 40 docs/a b.md\n"
        r, merged = _drive(
            repo, base, HEADER + "120 44 docs/a b.md\n",
            HEADER + "150 60 docs/a b.md\n",
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "150 60 docs/a b.md" in merged, merged


class TestNewestWinsSurvivesARealMerge:
    """The incident, replayed through real git with the attribute and the
    driver wired the way the installer wires them — both merge directions,
    because `git pull --rebase` on the bot swaps ours and theirs."""

    def _calibrated_repo(self, tmp_path: Path, name: str) -> Path:
        repo = _repo(tmp_path, name)
        (repo / ".skills").mkdir()
        (repo / ".gitattributes").write_text(f"{ATTR_COUNTS}\n")
        (repo / "AGENTS.md").write_bytes(b"x" * 150)
        (repo / COUNTS).write_text(HEADER + "100 40 AGENTS.md\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "base")
        return repo

    def _define(self, repo: Path) -> None:
        _git(repo, "config", COUNTS_DRIVER,
             f"bash '{MERGE_SCRIPT}' %O %A %B %P")

    def test_the_incident_merge_keeps_the_fresh_measurement(
        self, tmp_path: Path
    ):
        """#237 verbatim: a branch that touched the counts file merges
        origin/main, which carries the cadence's fresh row. `merge=ours`
        reverted the row to one describing a file 1,342 bytes smaller than
        the one on disk and reported Auto-merging; this keeps it."""
        repo = self._calibrated_repo(tmp_path, "incident")
        self._define(repo)
        _git(repo, "checkout", "-q", "-b", "cadence")
        (repo / COUNTS).write_text(HEADER + "150 60 AGENTS.md\n")
        _git(repo, "commit", "-qam", "weekly measurement")
        _git(repo, "checkout", "-q", "main")
        (repo / COUNTS).write_text(
            HEADER + "100 40 AGENTS.md\n120 44 docs/x.md\n"
        )
        _git(repo, "commit", "-qam", "branch work")
        r = _git(repo, "merge", "cadence")
        assert r.returncode == 0, r.stdout + r.stderr
        merged = (repo / COUNTS).read_text()
        assert "150 60 AGENTS.md" in merged, merged
        assert "100 40 AGENTS.md" not in merged, (
            "the stale row survived the merge — the silent revert is back:\n"
            + merged
        )
        assert "120 44 docs/x.md" in merged, merged

    def test_a_true_collision_is_arbitrated_by_the_tree(self, tmp_path: Path):
        repo = self._calibrated_repo(tmp_path, "collision")
        self._define(repo)
        _git(repo, "checkout", "-q", "-b", "cadence")
        (repo / COUNTS).write_text(HEADER + "150 60 AGENTS.md\n")
        _git(repo, "commit", "-qam", "fresh: matches the 150-byte file")
        _git(repo, "checkout", "-q", "main")
        (repo / COUNTS).write_text(HEADER + "120 44 AGENTS.md\n")
        _git(repo, "commit", "-qam", "stale re-measure")
        r = _git(repo, "merge", "cadence")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "150 60 AGENTS.md" in (repo / COUNTS).read_text()

    def test_the_bot_side_of_a_rebase_keeps_its_fresh_row_too(
        self, tmp_path: Path
    ):
        """The push-retry path: the cadence rebases its measurement onto a
        human commit, and `ours` during that rebase is the HUMAN side — which
        is exactly why merge=ours structurally discarded the bot's row."""
        repo = self._calibrated_repo(tmp_path, "rebase")
        self._define(repo)
        _git(repo, "checkout", "-q", "-b", "bot")
        (repo / COUNTS).write_text(HEADER + "150 60 AGENTS.md\n")
        _git(repo, "commit", "-qam", "weekly measurement")
        _git(repo, "checkout", "-q", "main")
        (repo / COUNTS).write_text(HEADER + "120 44 AGENTS.md\n")
        _git(repo, "commit", "-qam", "human edit")
        _git(repo, "checkout", "-q", "bot")
        r = _git(repo, "rebase", "main")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "150 60 AGENTS.md" in (repo / COUNTS).read_text()

    def test_the_attribute_without_the_driver_still_conflicts(
        self, tmp_path: Path
    ):
        """Same inertness as merge=ours (#192): the new name buys nothing
        until config defines it, and --check owns reporting that."""
        repo = self._calibrated_repo(tmp_path, "inert")
        assert _git(repo, "config", "--get", COUNTS_DRIVER).stdout.strip() == ""
        _git(repo, "checkout", "-q", "-b", "other")
        (repo / COUNTS).write_text(HEADER + "150 60 AGENTS.md\n")
        _git(repo, "commit", "-qam", "other")
        _git(repo, "checkout", "-q", "main")
        (repo / COUNTS).write_text(HEADER + "120 44 AGENTS.md\n")
        _git(repo, "commit", "-qam", "main")
        r = _git(repo, "merge", "other")
        assert r.returncode != 0, r.stdout
        assert "<<<<<<<" in (repo / COUNTS).read_text()


class TestInstallerWiresTheNewestWinsDriver:
    """The three-legged treatment #192 established, applied to the new driver:
    the attribute in .gitattributes, the driver in the clone's config, and the
    driver inside the workflow's rebase job — with --check reporting each leg,
    because each is its own way to lose the row."""

    def test_the_attribute_names_the_per_row_driver(self, tmp_path: Path):
        repo = _repo(tmp_path)
        assert _run(repo).returncode == 0
        attrs = (repo / ".gitattributes").read_text()
        assert ATTR_COUNTS in attrs, attrs
        assert f"{COUNTS} merge=ours" not in attrs, attrs
        # The ratio DECISION (#237): a single scalar has nothing for a per-row
        # driver to key on, so it stays regenerate-on-collision.
        assert f"{RATIO} merge=ours" in attrs, attrs

    def test_a_plain_install_defines_both_drivers(self, tmp_path: Path):
        repo = _repo(tmp_path)
        r = _run(repo)
        assert r.returncode == 0, r.stderr
        assert _driver(repo) == "true"
        value = _git(repo, "config", "--get", COUNTS_DRIVER).stdout.strip()
        assert "merge-token-counts.sh" in value, (
            "the counts attribute was written and left inert:\n" + r.stdout
        )
        for token in ("%O", "%A", "%B"):
            assert token in value, value

    def test_the_configured_command_actually_merges(self, tmp_path: Path):
        """The value is a command line, and nothing else executes it before a
        real collision does. Run it the way git will — through sh, with the
        placeholders substituted."""
        repo = _repo(tmp_path)
        _run(repo)
        value = _git(repo, "config", "--get", COUNTS_DRIVER).stdout.strip()
        (repo / "AGENTS.md").write_bytes(b"x" * 150)
        (repo / "O").write_text("100 40 AGENTS.md\n")
        (repo / "A").write_text("120 44 AGENTS.md\n")
        (repo / "B").write_text("150 60 AGENTS.md\n")
        cmd = (value.replace("%O", "O").replace("%A", "A")
               .replace("%B", "B").replace("%P", COUNTS))
        r = subprocess.run(
            ["sh", "-c", cmd], cwd=str(repo), capture_output=True, text=True,
            env=_env(), timeout=30,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert (repo / "A").read_text().strip() == "150 60 AGENTS.md"

    def test_a_pre_237_install_is_migrated_in_place(self, tmp_path: Path):
        """Every repo installed between #173 and #237 carries the counts file
        under merge=ours. Re-running — which is what --check tells them to do
        — must swap the one line and duplicate nothing."""
        repo = _repo(tmp_path)
        (repo / ".gitattributes").write_text(
            "# Append-only telemetry: concurrent appends must union-merge, or a\n"
            "# scheduled measurement racing a human commit conflicts and is lost.\n"
            f"{LEDGER} merge=union\n"
            "\n"
            "# Calibration is regenerated, never reconciled: on a collision keep\n"
            "# the branch's copy and let the next --exact run recompute it.\n"
            f"{RATIO} merge=ours\n"
            f"{COUNTS} merge=ours\n"
        )
        r = _run(repo)
        assert r.returncode == 0, r.stderr
        attrs = (repo / ".gitattributes").read_text()
        assert f"{COUNTS} merge=ours" not in attrs, attrs
        assert attrs.count(ATTR_COUNTS) == 1, attrs
        assert attrs.count(f"{RATIO} merge=ours") == 1, attrs
        assert attrs.count(f"{LEDGER} merge=union") == 1, attrs
        assert _run(repo, "--check").returncode == 0

    def test_check_reports_the_counts_driver_independently(
        self, tmp_path: Path
    ):
        repo = _repo(tmp_path)
        _run(repo)
        _git(repo, "config", "--unset", COUNTS_DRIVER)
        r = _run(repo, "--check")
        assert r.returncode == 3, r.stdout
        assert "newest-wins driver: MISSING" in r.stdout, r.stdout
        # Still independently true, and still reported as such.
        assert "ours merge driver:  yes" in r.stdout, r.stdout
        assert COUNTS_DRIVER in r.stdout, (
            "the failure text never names the key to set:\n" + r.stdout
        )

    def test_check_flags_a_config_pointing_at_a_missing_script(
        self, tmp_path: Path
    ):
        """A vendored skill reached through a dangling symlink — submodules
        not initialised — leaves a defined driver whose command cannot run,
        and git then conflicts as if the driver were absent."""
        repo = _repo(tmp_path)
        _run(repo)
        _git(repo, "config", COUNTS_DRIVER,
             "bash 'no/such/merge-token-counts.sh' %O %A %B %P")
        r = _run(repo, "--check")
        assert r.returncode == 3, r.stdout
        assert "newest-wins driver: BROKEN" in r.stdout, r.stdout

    def test_check_flags_a_workflow_missing_the_driver_leg(
        self, tmp_path: Path
    ):
        """A workflow rendered before #237 rebases on the runner without the
        driver and conflicts on the counts file. The workflow is the third
        leg, and --check must see all three."""
        repo = _repo(tmp_path)
        _run(repo)
        wf = repo / ".github" / "workflows" / "context-cadence.yml"
        wf.write_text("".join(
            ln for ln in wf.read_text().splitlines(keepends=True)
            if COUNTS_DRIVER not in ln
        ))
        r = _run(repo, "--check")
        assert r.returncode == 3, r.stdout
        assert "workflow drivers:   STALE" in r.stdout, r.stdout

    def test_a_rerun_heals_a_missing_counts_driver(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _run(repo)
        _git(repo, "config", "--unset", COUNTS_DRIVER)
        assert _run(repo, "--check").returncode == 3
        assert _run(repo).returncode == 0
        assert _git(repo, "config", "--get", COUNTS_DRIVER).stdout.strip()
        assert _run(repo, "--check").returncode == 0

    def test_uninstall_removes_the_attribute_and_leaves_the_driver(
        self, tmp_path: Path
    ):
        """Same asymmetry as the ours driver, same reason: the attributes are
        this installer's to remove, a defined driver with nothing pointing at
        it never runs, and unsetting config is one more worktree-shaped write
        this script has no need to make."""
        repo = _repo(tmp_path)
        _run(repo)
        assert _run(repo, "--uninstall").returncode == 0
        assert not (repo / ".gitattributes").exists()
        assert _git(repo, "config", "--get", COUNTS_DRIVER).stdout.strip()
