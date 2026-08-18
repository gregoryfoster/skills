"""Assertions on the cadence workflow as RENDERED, not as written (#171, #173).

Both defects the usa-wa pilot found share one shape: generated shell was only
ever checked at the layer it was typed in.

#171 — `install-cadence.sh` escaped a backtick pair for its own heredoc but not
for the workflow's bash, so the rendered YAML handed bash a live command
substitution. The `::error::` that names the missing .gitattributes line ran the
attribute as a command and printed the message without its noun. It sits on the
rebase-failure branch, so no run reached it: green everywhere, wrong when read.

#173 — the rendered `Commit the row` step stages three paths and the installer
protected one. The two calibration files (#145) were added to the template
without revisiting the attribute, so the race the ledger was protected against
landed on them instead.

Neither is visible in the installer source. Both are obvious in its output, so
these tests read the output — `--print` it, pull the `run:` blocks out of the
YAML, and check the shell that will actually execute.

Coverage:
- every `run:` block parses under `bash -n`
- no live command substitution survives into a run block (heredoc bodies
  excluded — a backtick there is literal, which is why the neighbouring
  Python heredoc was always correct)
- the rebase-failure diagnostic still names its attribute lines after rendering
- every path the workflow `git add`s carries a merge attribute the installer
  writes
- --check reports the calibration attributes independently of the ledger's
- a repo installed before #173 gains the two missing attributes without a
  duplicated ledger line
"""

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INSTALL_CADENCE = (
    REPO_ROOT / "skills" / "curating-context" / "scripts" / "install-cadence.sh"
)

LEDGER = ".skills/context-metrics.jsonl"
RATIO = ".skills/context-token-ratio"
COUNTS = ".skills/context-token-counts"


def _clean_env() -> dict:
    """Env without inherited GIT_* vars — the precaution the rest of the suite
    takes, and the one this file was missing.

    Git exports GIT_DIR to every hook process, so under pre-commit these tests
    ran with it set; from a linked worktree it is ABSOLUTE, and GIT_DIR beats
    `cwd`. Every git call below therefore addressed the real repo instead of the
    temp fixture: `git init` re-initialised it, and once the installer learned to
    set `merge.ours.driver` (#192) that write landed in the SHARED .git/config of
    the main checkout — from a test whose whole subject is a throwaway
    directory. Observed, not theorised. The same class as #189.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _repo(tmp_path: Path) -> Path:
    # exist_ok because a test may also use the `rendered` fixture, which builds
    # its own repo under the same tmp_path to run --print. That is harmless —
    # --print writes nothing — and `git init` is idempotent.
    r = tmp_path / "r"
    r.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=r, check=True, env=_clean_env())
    return r


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALL_CADENCE), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
        env=_clean_env(),
    )


@pytest.fixture
def rendered(tmp_path: Path) -> dict:
    repo = _repo(tmp_path)
    r = _run(repo, "--print", "--cron", "0 15 * * 1")
    assert r.returncode == 0, r.stderr
    return yaml.safe_load(r.stdout)


def _run_blocks(doc: dict) -> list[tuple[str, str]]:
    return [
        (s.get("name", s.get("uses", "?")), s["run"])
        for s in doc["jobs"]["measure"]["steps"]
        if s.get("run")
    ]


def _strip_heredocs(script: str) -> list[str]:
    """Lines outside heredoc bodies and outside comments.

    A backtick inside `<<'PY'` is literal — the Python drift reporter has always
    had one and has always been correct. Flagging it would make the real finding
    indistinguishable from the noise beside it.
    """
    out, terminator = [], None
    for line in script.splitlines():
        if terminator is not None:
            if line.strip() == terminator:
                terminator = None
            continue
        m = re.search(r"<<-?\s*'?([A-Za-z_][A-Za-z0-9_]*)'?", line)
        if m:
            terminator = m.group(1)
            continue
        if line.lstrip().startswith("#"):
            continue
        out.append(line)
    return out


class TestRenderedShellIsValid:
    def test_every_run_block_parses(self, rendered: dict):
        for name, script in _run_blocks(rendered):
            r = subprocess.run(["bash", "-n"], input=script, capture_output=True,
                               text=True)
            assert r.returncode == 0, f"{name}: {r.stderr}"

    def test_no_live_command_substitution_survives(self, rendered: dict):
        """The #171 class. An unescaped backtick in a rendered run block is bash
        command substitution, whatever it looked like in the installer."""
        offenders = []
        for name, script in _run_blocks(rendered):
            for line in _strip_heredocs(script):
                if re.search(r"(?<!\\)`", line):
                    offenders.append(f"{name}: {line.strip()}")
        assert not offenders, "live backticks in rendered shell:\n" + "\n".join(
            offenders
        )

    def test_the_rebase_diagnostic_still_names_its_attributes(self, rendered: dict):
        """#171's actual damage: the message survived, its noun did not. Assert
        on the shell's OUTPUT, since the bug was invisible in its source."""
        commit = dict(_run_blocks(rendered))["Commit the row"]
        errors = [ln for ln in commit.splitlines() if "::error::" in ln and "merge=" in ln]
        assert len(errors) == 3, errors
        for line in errors:
            printed = subprocess.run(
                ["bash", "-c", line.strip()], capture_output=True, text=True
            )
            assert printed.returncode == 0, printed.stderr
            assert "merge=" in printed.stdout, (
                f"the attribute was eaten before printing: {printed.stdout!r}"
            )


class TestEveryStagedPathIsProtected:
    """#173. The template staged three paths and the installer protected one.
    Compare the two lists rather than trusting them to be edited together."""

    def _staged(self, doc: dict) -> set[str]:
        commit = dict(_run_blocks(doc))["Commit the row"]
        return set(re.findall(r'git add -- "?([^"\s]+)"?', commit))

    def test_the_workflow_stages_the_three_known_paths(self, rendered: dict):
        """Pins the input to the test below — if the template gains a fourth
        staged path, this fails first and says so, rather than the coverage
        silently narrowing to whatever the regex still matched."""
        assert self._staged(rendered) == {LEDGER, RATIO, COUNTS}

    def test_every_staged_path_gets_a_merge_attribute(self, tmp_path: Path,
                                                      rendered: dict):
        repo = _repo(tmp_path)
        assert _run(repo).returncode == 0
        attrs = (repo / ".gitattributes").read_text()
        declared = {
            ln.split()[0]
            for ln in attrs.splitlines()
            if ln.strip() and not ln.startswith("#")
        }
        missing = self._staged(rendered) - declared
        assert not missing, f"staged but unprotected: {sorted(missing)}\n{attrs}"

    def test_calibration_uses_ours_not_union(self, tmp_path: Path):
        """Union-merging these produces two lines for one path with different
        counts, and the estimators read whichever they hit first — worse than a
        conflict, because nothing reports it."""
        repo = _repo(tmp_path)
        _run(repo)
        attrs = (repo / ".gitattributes").read_text()
        assert f"{RATIO} merge=ours" in attrs
        assert f"{COUNTS} merge=ours" in attrs
        assert f"{LEDGER} merge=union" in attrs

    def test_the_ours_driver_is_defined_in_the_workflow(self, rendered: dict):
        """`ours` is the one built-in git does NOT define. Without this the
        attribute is inert and the files conflict exactly as before."""
        commit = dict(_run_blocks(rendered))["Commit the row"]
        assert "git config merge.ours.driver true" in commit


class TestCheckAndRepair:
    def test_check_reports_calibration_separately(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _run(repo)
        r = _run(repo, "--check")
        assert r.returncode == 0, r.stdout
        assert "ledger union merge: yes" in r.stdout
        assert "calibration merge:  yes" in r.stdout

    def test_a_pre_173_install_is_repaired_without_duplication(self, tmp_path: Path):
        """Every repo that adopted between #145 and this fix has the ledger line
        and neither calibration line. Re-running must add exactly the two that
        are missing."""
        repo = _repo(tmp_path)
        (repo / ".gitattributes").write_text(f"{LEDGER} merge=union\n")
        r = _run(repo, "--check")
        assert r.returncode == 3
        assert "calibration merge:  MISSING" in r.stdout

        assert _run(repo).returncode == 0
        attrs = (repo / ".gitattributes").read_text()
        assert attrs.count(f"{LEDGER} merge=union") == 1, attrs
        assert attrs.count(f"{RATIO} merge=ours") == 1, attrs
        assert attrs.count(f"{COUNTS} merge=ours") == 1, attrs
        assert _run(repo, "--check").returncode == 0

    def test_a_partial_calibration_repair_does_not_duplicate_the_heading(
        self, tmp_path: Path
    ):
        """One calibration line missing is the partial-repair path this branch
        exists for, and it re-emitted the two-line heading above the lone
        repaired entry (CR finding 4)."""
        repo = _repo(tmp_path)
        _run(repo)
        attrs = (repo / ".gitattributes").read_text()
        kept = "\n".join(
            ln for ln in attrs.splitlines() if COUNTS not in ln
        ) + "\n"
        (repo / ".gitattributes").write_text(kept)
        _run(repo)
        final = (repo / ".gitattributes").read_text()
        assert final.count("Calibration is regenerated") == 1, final
        assert final.count(f"{COUNTS} merge=ours") == 1, final
        assert _run(repo, "--check").returncode == 0

    def test_uninstall_removes_all_three(self, tmp_path: Path):
        repo = _repo(tmp_path)
        (repo / ".gitattributes").write_text("*.png binary\n")
        _run(repo)
        assert _run(repo, "--uninstall").returncode == 0
        attrs = (repo / ".gitattributes").read_text()
        assert "merge=" not in attrs, attrs
        assert "*.png binary" in attrs, "unrelated rules must survive"
