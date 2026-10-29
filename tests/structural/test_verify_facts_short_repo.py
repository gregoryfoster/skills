"""`verify-facts.sh --issues` resolved `watcher#368` as this repo's #368 (#461).

The token grammar's owner group needs a slash, so `watcher#368` failed it and
the bare `#368` matched, which was then resolved against `--repo` (or gh's
inferred repo). The result was a confident TRUE row about the wrong issue: the
prose cited CannObserv/watcher#368 (open), and the verdict was about
gregoryfoster/skills#368 (closed), with "check whether the prose still
describes it as pending" sending the agent to rewrite prose about an issue it
never cited.

A short `<word>#N` is now its own shape. When `<word>` names the current repo
it resolves as a bare `#N` always did, and its row keeps the bare `#N` claim,
the occurrence key #438's `stale-issue-prose.sh` looks it up by. Otherwise it
is UNVERIFIABLE with the fix spelled out: there is no owner to resolve it
against, and guessing one would make TRUE a guess.

`gh` is a fake on PATH: it logs every call and answers from a table.
"""

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
VERIFY = ROOT / "skills" / "curating-context" / "scripts" / "verify-facts.sh"

# repo -> {number: state}; `gh repo view` answers CURRENT.
CURRENT = "gregoryfoster/skills"
FAKE_GH = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$GH_LOG"
if [ "$1 $2" = "repo view" ]; then
  [ -n "${GH_REPO_VIEW:-}" ] || exit 1
  printf '%s\\n' "$GH_REPO_VIEW"; exit 0
fi
num="$3" repo=""
shift 3
while [ $# -gt 0 ]; do
  case "$1" in --repo) repo="$2"; shift 2 ;; *) shift ;; esac
done
[ -n "$repo" ] || repo="${GH_REPO_VIEW:-}"
case "$repo#$num" in
  gregoryfoster/skills#81) echo OPEN ;;
  gregoryfoster/skills#368) echo CLOSED ;;
  CannObserv/watcher#368) echo OPEN ;;
  *) exit 1 ;;
esac
"""


def _clean_env() -> dict:
    """STYLE.md § 'A repo-creating git command must scrub GIT_DIR'."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _repo(tmp_path: Path, policy: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "init", "-q"],
        check=True,
        capture_output=True,
        env=_clean_env(),
    )
    (repo / "AGENTS.md").write_text(policy)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    return repo


def _issues(
    repo: Path, *args: str, repo_view: str | None = CURRENT
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """{claim: (verdict, evidence)} for issue rows, and the gh calls made."""
    log = repo.parent / "gh.log"
    env = _clean_env()
    env["PATH"] = f"{repo.parent / 'bin'}{os.pathsep}{env['PATH']}"
    env["GH_LOG"] = str(log)
    env.pop("GH_REPO_VIEW", None)
    if repo_view is not None:
        env["GH_REPO_VIEW"] = repo_view
    r = subprocess.run(
        ["bash", str(VERIFY), "--issues", *args],
        capture_output=True,
        text=True,
        cwd=str(repo),
        env=env,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    rows = {}
    for row in r.stdout.splitlines():
        verdict, cls, _loc, claim, evidence = row.split("\t")
        if cls == "issue":
            rows[claim] = (verdict, evidence)
    calls = log.read_text().splitlines() if log.exists() else []
    return rows, calls


class TestAShortCrossRepoReference:
    def test_is_unverifiable_not_true_about_this_repo(self, tmp_path: Path):
        """The issue's measurement, reduced: before the fix this was `#368`,
        TRUE, "closed — check whether the prose still describes it"."""
        repo = _repo(tmp_path, "# P\n\nThe headless work is watcher#368.\n")
        rows, calls = _issues(repo, "--repo", CURRENT)
        assert "#368" not in rows, rows
        verdict, evidence = rows["watcher#368"]
        assert verdict == "UNVERIFIABLE", rows
        assert "owner/watcher#368" in evidence, evidence
        assert not any("368" in c for c in calls), calls

    def test_is_unverifiable_without_repo_too(self, tmp_path: Path):
        """With no --repo, gh's own inference names the current repo."""
        repo = _repo(tmp_path, "# P\n\nThe headless work is watcher#368.\n")
        rows, calls = _issues(repo)
        assert rows["watcher#368"][0] == "UNVERIFIABLE", rows
        assert not any("issue view 368" in c for c in calls), calls

    def test_a_bare_reference_beside_it_still_resolves(self, tmp_path: Path):
        repo = _repo(
            tmp_path, "# P\n\nThe headless work is watcher#368; see also #368.\n"
        )
        rows, _ = _issues(repo, "--repo", CURRENT)
        assert rows["#368"][0] == "TRUE", rows
        assert rows["watcher#368"][0] == "UNVERIFIABLE", rows


class TestAShortReferenceToThisRepo:
    def test_resolves_against_this_repo(self, tmp_path: Path):
        """`skills#81` inside gregoryfoster/skills is this repo's #81, and its
        row keeps the bare claim stale-issue-prose.sh keys occurrences by."""
        repo = _repo(tmp_path, "# P\n\nTracked in skills#81.\n")
        rows, calls = _issues(repo, "--repo", CURRENT)
        assert rows == {"#81": ("TRUE", "open")}, rows
        assert any(f"issue view 81 --repo {CURRENT}" in c for c in calls), calls

    def test_the_name_is_compared_without_case(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\nTracked in Skills#81.\n")
        rows, _ = _issues(repo, "--repo", CURRENT)
        assert rows == {"#81": ("TRUE", "open")}, rows

    def test_without_repo_the_inferred_one_is_used(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\nTracked in skills#81.\n")
        rows, _ = _issues(repo)
        assert rows == {"#81": ("TRUE", "open")}, rows

    def test_with_no_repo_known_it_is_unverifiable(self, tmp_path: Path):
        """gh can't name the repo, so `skills#81` can't be told from a
        cross-repo reference: say so rather than guess either way."""
        repo = _repo(tmp_path, "# P\n\nTracked in skills#81.\n")
        rows, _ = _issues(repo, repo_view=None)
        assert rows["skills#81"][0] == "UNVERIFIABLE", rows


class TestAWordThatNamesNoRepo:
    """The same exceptions `_sentences._short_repo` makes (CR 434), so the two
    readers of one reference agree on what it names."""

    def test_a_self_prefix_is_this_repos_item(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\nFixed by PR#81 and gh#81.\n")
        rows, _ = _issues(repo, "--repo", CURRENT)
        assert rows == {"#81": ("TRUE", "open")}, rows

    def test_emphasis_and_digits_are_not_a_repo(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\nSee _#81_ and v2#81.\n")
        rows, _ = _issues(repo, "--repo", CURRENT)
        assert rows["#81"] == ("TRUE", "open"), rows
        assert rows["v2#81"][0] == "UNVERIFIABLE", rows


class TestTheOtherShapesAreUnchanged:
    def test_an_owner_qualified_reference_uses_its_own_repo(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\nSee CannObserv/watcher#368.\n")
        rows, _ = _issues(repo, "--repo", CURRENT)
        assert rows == {"CannObserv/watcher#368": ("TRUE", "open")}, rows

    def test_a_bare_reference_uses_repo(self, tmp_path: Path):
        repo = _repo(tmp_path, "# P\n\nSee #81.\n")
        rows, _ = _issues(repo, "--repo", CURRENT)
        assert rows == {"#81": ("TRUE", "open")}, rows


class TestTheRepoIsAskedOnce:
    def test_gh_repo_view_runs_once_for_many_short_references(self, tmp_path: Path):
        """CR 844: the lookup is cached for the run, as its comment says. A
        command substitution ran it in a subshell, so the cache never
        survived and every short reference cost its own `gh repo view`."""
        repo = _repo(tmp_path, "# P\n\nSee watcher#368, broker#93 and skills#81.\n")
        rows, calls = _issues(repo)
        assert rows["watcher#368"][0] == "UNVERIFIABLE", rows
        assert rows["#81"] == ("TRUE", "open"), rows
        assert sum(c.startswith("repo view") for c in calls) == 1, calls
