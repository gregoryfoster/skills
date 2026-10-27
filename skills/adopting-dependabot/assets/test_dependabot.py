"""Pin ``.github/dependabot.yml``: a broken config goes quiet, not red.

Copied from the adopting-dependabot skill (gregoryfoster/skills#376). Edit
the block marked ADAPT and nothing else; every other line is derived from the
repo, so it stays true as the repo changes.

Dependabot's config fails silently. A mistyped ecosystem, a wrong directory
or a missing ``schedule.interval`` produces no PRs and no error anywhere a
person looks, and a quiet bot reads as "no updates available". Past
``open-pull-requests-limit`` (default 5) it opens no more version updates,
and says so nowhere (security updates have their own fixed limit of 10): notifier's dev-tools group and SDK
table went silent for five weeks that way (CannObserv/notifier#103).

Pure file reads plus ``git ls-files``: no network.
"""

import fnmatch
import re
import subprocess
import tomllib
from pathlib import Path, PurePosixPath

import pytest
import yaml

# ---- ADAPT ------------------------------------------------------------------
# The ecosystems this repo turns on. Start with github-actions alone: it needs
# no package resolution, so its first PRs test CI's credential context alone.
ENABLED = {"github-actions"}
# An ecosystem present in the repo but held back, and why. A block for one of
# these fails, so turning it on is a decision with its own issue.
HELD_BACK: dict[str, str] = {
    # "uv": "resolves co-core only from the private wheelhouse (#NNN)",
}
# Packages each uv/pip block must ignore, and why: pins that move in lockstep
# with another repo, not on a bot's schedule.
IGNORED: dict[str, str] = {
    # "co-core": "moves when Processor coordinates a contract change (#NNN)",
}
# The commit types the repo's convention accepts. A Dependabot commit can land
# on main as-is, so its subject must read like the repo's own.
COMMIT_TYPES = {"feat", "fix", "refactor", "docs", "test", "chore", "ci"}
# Every `uses:` pinned as `owner/action@<40-hex sha> # vX.Y.Z`. Dependabot
# moves both. A major-form pin (`@v5`) stops being proposed once upstream
# stops floating major tags (astral-sh/setup-uv from v8 on).
SHA_PINS = False
# -----------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / ".github" / "dependabot.yml"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
PACKAGE_ECOSYSTEMS = {"uv", "pip"}

_ACTION = re.compile(r"^([\w.-]+/[\w.-]+)(?:/[^@]*)?@.+$")
_USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$")
_SHA_PIN = re.compile(r"^[^@]+@[0-9a-f]{40}$")
_VERSION_COMMENT = re.compile(r"^\s+# v\d+\.\d+\.\d+$")


def _load() -> dict:
    """The parsed config, or {} while it's missing, so the failure is test_config_exists's."""
    return (
        yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
        if CONFIG.is_file()
        else {}
    )


def _updates() -> list[dict]:
    return _load().get("updates") or []


def _blocks(ecosystem: str) -> list[dict]:
    return [u for u in _updates() if u.get("package-ecosystem") == ecosystem]


def _directories(block: dict) -> set[str]:
    """A block's directories, whichever of the two spellings it uses."""
    return set(block.get("directories", [])) | (
        {block["directory"]} if "directory" in block else set()
    )


def _tracked() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.splitlines()


def _dir(path: str) -> str:
    parent = PurePosixPath(path).parent.as_posix()
    return "/" if parent == "." else f"/{parent}"


def _workflow_docs() -> list[dict]:
    return [
        yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for p in sorted(WORKFLOWS.glob("*.y*ml"))
    ]


def _uses(node: object) -> list[str]:
    """Every ``uses:`` value in a parsed workflow, at any depth."""
    if isinstance(node, dict):
        found = [node["uses"]] if isinstance(node.get("uses"), str) else []
        return found + [u for value in node.values() for u in _uses(value)]
    if isinstance(node, list):
        return [u for item in node for u in _uses(item)]
    return []


def _actions() -> set[str]:
    """The distinct ``owner/repo`` actions the workflows pin: one PR each."""
    return {
        m.group(1)
        for doc in _workflow_docs()
        for ref in _uses(doc)
        if (m := _ACTION.match(ref))
    }


def _uses_lines() -> list[tuple[str, int, str, str]]:
    """Every ``uses:`` line as written, comment included: (file, line, ref, rest)."""
    return [
        (path.name, n, m.group(1), m.group(2))
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if (m := _USES_LINE.match(line))
    ]


_REQUIREMENTS = re.compile(r"requirements[\w.-]*\.(txt|in)")


def _lock_dirs(ecosystem: str) -> set[str]:
    """Where the repo keeps this ecosystem's manifests, in Dependabot's form.

    pip reads requirements files, a Pipfile, poetry.lock, and a pyproject.toml
    that no uv.lock sits beside (one that does is uv's), as inventory.sh does.
    """
    tracked = _tracked()
    if ecosystem == "uv":
        return {_dir(f) for f in tracked if PurePosixPath(f).name == "uv.lock"}
    present = set(tracked)
    found = set()
    for f in tracked:
        p = PurePosixPath(f)
        uv_beside = (p.parent / "uv.lock").as_posix() in present
        if (
            _REQUIREMENTS.fullmatch(p.name)
            or p.name in {"Pipfile", "poetry.lock"}
            or (p.name == "pyproject.toml" and not uv_beside)
        ):
            found.add(_dir(f))
    return found


def _runtime_count(directory: str) -> int:
    """Runtime requirements in a directory: [project.dependencies], or else the
    requirement lines of its requirements files (not -r/-f options, comments)."""
    base = REPO_ROOT / directory.lstrip("/")
    table = base / "pyproject.toml"
    if table.is_file():
        project = tomllib.loads(table.read_text(encoding="utf-8")).get("project", {})
        if "dependencies" in project:
            return len(project["dependencies"])
    return sum(
        1
        for path in sorted(base.glob("requirements*.txt"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "-"))
    )


def test_config_exists() -> None:
    assert CONFIG.is_file(), "no .github/dependabot.yml: nothing proposes a bump"


def test_config_is_version_2() -> None:
    """Version 1 configs are dead; Dependabot ignores them without erroring."""
    assert _load().get("version") == 2


def test_ecosystems_are_the_enabled_set() -> None:
    configured = {u.get("package-ecosystem") for u in _updates()}
    for eco in configured & HELD_BACK.keys():
        pytest.fail(
            f"{eco} is held back: {HELD_BACK[eco]}. Turning it on is its own decision"
        )
    assert configured == ENABLED, (
        f"configured {sorted(configured, key=str)}, expected {sorted(ENABLED)}. A mistyped "
        "ecosystem (github_actions, python) opens no PR and reports nothing"
    )


@pytest.mark.parametrize(
    "block", _updates(), ids=lambda b: str(b.get("package-ecosystem"))
)
def test_every_block_runs_on_a_schedule(block: dict) -> None:
    """No interval is a config Dependabot rejects, visibly only in its own tab."""
    assert (block.get("schedule") or {}).get("interval"), "no schedule.interval"


@pytest.mark.parametrize(
    "block", _updates(), ids=lambda b: str(b.get("package-ecosystem"))
)
def test_commits_follow_the_repo_convention(block: dict) -> None:
    """The default subject, 'Bump x from a to b', matches no type."""
    prefix = (block.get("commit-message") or {}).get("prefix")
    assert prefix in COMMIT_TYPES, (
        f"commit-message.prefix {prefix!r} is none of {sorted(COMMIT_TYPES)}"
    )


def test_actions_block_covers_every_workflow_and_action() -> None:
    """``/`` scans .github/workflows/ and a root action.yml; any other action.yml needs its directory."""
    if "github-actions" not in ENABLED:
        pytest.skip("github-actions isn't enabled")
    expected = {"/"} | {
        _dir(f)
        for f in _tracked()
        if PurePosixPath(f).name in {"action.yml", "action.yaml"}
        and not f.startswith(".github/workflows/")
    }
    covered = set().union(*(_directories(b) for b in _blocks("github-actions")))
    assert expected <= covered, f"not scanned: {sorted(expected - covered)}"


def _batch(block: dict, names: set[str]) -> int:
    """How many PRs one batch can open: one per group that matches anything,
    plus one per dependency no group matches. A group with no ``patterns``
    matches everything its ``exclude-patterns`` leaves."""
    grouped: set[str] = set()
    groups = 0
    for group in (block.get("groups") or {}).values():
        matched = {
            n
            for n in names
            if any(fnmatch.fnmatch(n, p) for p in group.get("patterns", ["*"]))
            and not any(
                fnmatch.fnmatch(n, p) for p in group.get("exclude-patterns", [])
            )
        }
        groups += bool(matched - grouped)
        grouped |= matched
    return groups + len(names - grouped)


def test_actions_open_pr_limit_outlasts_a_full_batch() -> None:
    if "github-actions" not in ENABLED:
        pytest.skip("github-actions isn't enabled")
    actions = _actions()
    assert actions, "found no `uses:` under .github/workflows/: the derivation broke"
    for block in _blocks("github-actions"):
        limit = block.get("open-pull-requests-limit", 5)
        batch = _batch(block, actions)
        assert limit > batch, (
            f"limit {limit} can be filled by {batch} action PRs; past it Dependabot "
            "opens no more version updates and says so nowhere. Raise open-pull-requests-limit"
        )


def test_the_batch_counts_groups_once():
    """Guard the guard: a grouped block's batch is its groups, not its actions."""
    names = {"actions/checkout", "actions/setup-python", "astral-sh/setup-uv"}
    assert _batch({}, names) == 3
    assert _batch({"groups": {"all": {"patterns": ["*"]}}}, names) == 1
    assert _batch({"groups": {"gh": {"patterns": ["actions/*"]}}}, names) == 2
    assert _batch({"groups": {"a": {"exclude-patterns": ["astral-sh/*"]}}}, names) == 2


@pytest.mark.parametrize("ecosystem", sorted(ENABLED & PACKAGE_ECOSYSTEMS))
def test_package_blocks_cover_every_manifest(ecosystem: str) -> None:
    covered = set().union(*(_directories(b) for b in _blocks(ecosystem)))
    missing = _lock_dirs(ecosystem) - covered
    assert not missing, f"{ecosystem} manifests at {sorted(missing)} get no PRs"


def _package_blocks() -> list[dict]:
    return [b for b in _updates() if b.get("package-ecosystem") in PACKAGE_ECOSYSTEMS]


@pytest.mark.parametrize(
    "block", _package_blocks(), ids=lambda b: ",".join(sorted(_directories(b)))
)
def test_versioning_strategy_is_pinned(block: dict) -> None:
    """The default ``auto`` resolves to ``widen`` for a library, which uv doesn't
    support (dependabot-core#15290). Under uv even this raises floors on
    in-range bumps (notifier#103), so read a library's floor before merging."""
    assert block.get("versioning-strategy") == "increase-if-necessary"


@pytest.mark.parametrize(
    "block", _package_blocks(), ids=lambda b: ",".join(sorted(_directories(b)))
)
def test_dev_churn_is_grouped(block: dict) -> None:
    """Dev tooling carries most of the churn; runtime bumps stay their own PRs."""
    groups = block.get("groups") or {}
    assert any(g.get("dependency-type") == "development" for g in groups.values()), (
        "no development group"
    )


@pytest.mark.parametrize(
    "block", _package_blocks(), ids=lambda b: ",".join(sorted(_directories(b)))
)
def test_lockstep_pins_are_ignored(block: dict) -> None:
    ignored = {i.get("dependency-name") for i in block.get("ignore") or []}
    missing = sorted(IGNORED.keys() - ignored)
    assert not missing, f"not ignored: {missing}. " + "; ".join(
        f"{p}: {IGNORED[p]}" for p in missing
    )


@pytest.mark.parametrize(
    "block", _package_blocks(), ids=lambda b: ",".join(sorted(_directories(b)))
)
def test_package_open_pr_limit_outlasts_a_full_backlog(block: dict) -> None:
    """Each runtime dependency is its own PR and each group one more per directory."""
    runtime = sum(_runtime_count(d) for d in _directories(block))
    grouped = len(block.get("groups") or {}) * len(_directories(block))
    limit = block.get("open-pull-requests-limit", 5)
    assert limit > runtime + grouped, (
        f"limit {limit} can be filled by {runtime} runtime PRs and {grouped} group PRs; "
        "raise open-pull-requests-limit"
    )


def test_every_uses_line_is_read() -> None:
    """The line scan sees every ``uses:`` the parser does, so none escapes the pin rule."""
    parsed = sorted(u for doc in _workflow_docs() for u in _uses(doc))
    assert sorted(ref for _, _, ref, _ in _uses_lines()) == parsed, (
        "the line scan and the parser disagree: write each step's `uses:` unquoted, on its own line"
    )


def _is_pinned(ref: str, rest: str) -> bool:
    """A SHA pin with its version comment, or a ``./`` action in this repo."""
    return ref.startswith("./") or bool(
        _SHA_PIN.match(ref) and _VERSION_COMMENT.match(rest)
    )


def test_every_action_is_sha_pinned_with_its_version() -> None:
    if not SHA_PINS:
        pytest.skip("SHA_PINS is off")
    bad = [
        f"{name}:{n}: {ref}{rest}"
        for name, n, ref, rest in _uses_lines()
        if not _is_pinned(ref, rest)
    ]
    assert not bad, (
        "pin each action as `owner/action@<40-hex sha> # vX.Y.Z`: a tag can be moved, and "
        "a major-form pin stops once upstream stops floating majors. A re-rendered "
        "generated workflow can revert one (gregoryfoster/skills#373). Offending:\n  "
        + "\n  ".join(bad)
    )


def test_the_pin_rule_reads_what_it_should() -> None:
    """Guard the guard: a local action needs no SHA; a tag pin isn't one."""
    assert _is_pinned("./.github/actions/setup", "")
    assert not _is_pinned("actions/checkout@v7", "")
    assert _is_pinned("actions/checkout@" + "0" * 40, " # v7.0.1")
