"""The orchestrator works in its own worktree, never the main checkout (#505).

`orchestrating-issue-backlog` used to run the orchestrator in the main
checkout: Step 0 and Rule 1 said `git checkout main && git pull --ff-only`,
Orchestrator step 2 said `git checkout -b batch/<X>`, and Step 8 pushed the
plan from local `main` (Rule 2). The #503 session hit four problems with that,
none of them from its backlog (journal 2026-10-27-skills-mayfly, lesson 4):

1. Step 0 moved the user's checkout off a working branch.
2. An *ignored* `__pycache__` the switch left behind kept a deleted skill's
   directory alive. `status --porcelain` was clean, and the plan's own commit
   hook failed on it.
3. `origin/main` moved 17 commits during two 13-minute commit hooks, so the
   push was refused and the briefed baseline was stale before any worker read
   it.
4. pre-commit stashed unstaged edits for each hook run, locking the checkout
   the orchestrator was standing in.

A worktree cut from a freshly fetched `origin/main` avoids 1, 2 and 4, and
turns 3 into a rebase. Each test below pins one half of that model. The
guidance surface is the body plus the top-level reference docs; the session
journal under `process-log/<year>/` is history and may quote the old commands.
"""

import re

import pytest

from tests.utils.skill_loader import SKILLS_DIR, load_skill


@pytest.fixture(scope="module")
def s():
    return load_skill(SKILLS_DIR / "orchestrating-issue-backlog")


@pytest.fixture(scope="module")
def refs(s):
    return s.directory / "references"


@pytest.fixture(scope="module")
def execution(refs):
    return (refs / "execution.md").read_text()


def _rule(execution: str, n: int) -> str:
    """Rule n's section, up to the next heading of any level (Rule 6 is
    followed by `## Recovery`, not by another rule)."""
    start = execution.index(f"### Rule {n} ")
    end = re.compile(r"\n#{2,3} ").search(execution, start + 1)
    return execution[start : end.start() if end else len(execution)]


def test_no_step_moves_the_main_checkout(s, refs):
    """No guidance step checks a branch out in, or pulls into, the main checkout.

    `git checkout main` and `git pull --ff-only` were how Step 0 moved the
    user's branch; `git checkout -b batch/` was how Orchestrator step 2 did. A
    salvage in recovery.md still checks out a branch *there* on purpose — that
    is where the fall-through left the work — but never `main`, which the
    checkout may never have held.
    """
    surface = {"SKILL.md": s.body} | {
        p.name: p.read_text() for p in sorted(refs.glob("*.md"))
    }
    forbidden = [
        r"git (?:-C \S+ )?(?:checkout|switch) main\b",
        r"git (?:-C \S+ )?(?:checkout -b|switch -c) batch/",
        r"git (?:-C \S+ )?pull --ff-only",
        r"push from local `main`",
    ]
    hits = [
        f"{name}: {m.group(0)}"
        for name, text in surface.items()
        for pattern in forbidden
        for m in re.finditer(pattern, text)
    ]
    assert not hits, (
        "orchestrating-issue-backlog must not move the main checkout: the "
        "orchestrator cuts its own worktree from `origin/main` (Rule 1, "
        "#505). Found:\n  " + "\n  ".join(hits)
    )


def test_checklist_item_0_cuts_a_worktree(s):
    item = next(line for line in s.body.splitlines() if line.startswith("0. "))
    assert "orchestrate/<topic>" in item and "`origin/main`" in item, (
        "Checklist item 0 must cut the orchestrator's worktree, "
        f"`orchestrate/<topic>`, from `origin/main` (#505). Found:\n  {item}"
    )


def test_rule_1_cuts_the_worktree_from_a_fresh_origin_main(execution):
    """The branch is cut from `origin/main` first, then given a worktree.

    `worktree-create.sh --new` would be the obvious one-liner, and it is
    wrong: `--new` passes `-b` to `git worktree add` with no start point, so
    the branch is cut from the main checkout's HEAD — whatever branch the user
    happens to be on.
    """
    rule = _rule(execution, 1)
    fetch = rule.find("git fetch origin")
    branch = rule.find("git branch orchestrate/<topic> origin/main")
    create = rule.find("worktree-create.sh orchestrate/<topic>")
    assert -1 not in (fetch, branch, create) and fetch < branch < create, (
        "Rule 1 must fetch, then `git branch orchestrate/<topic> origin/main`, "
        "then hand that existing branch to worktree-create.sh (#505)."
    )
    create_line = next(
        line for line in rule.splitlines() if "worktree-create.sh" in line
    )
    assert "--new" not in create_line.split("#")[0], (
        "Rule 1's worktree-create.sh call must not pass `--new`: it cuts the "
        f"branch from the main checkout's HEAD. Found:\n  {create_line}"
    )


def test_rule_1_fast_forwards_local_main_only_when_safe(execution):
    rule = _rule(execution, 1)
    assert "`git -C <main> merge --ff-only origin/main`" in rule, (
        "Rule 1 must name the one move it allows in the main checkout: a "
        "fast-forward of local `main` from `origin/main` (#505)."
    )
    assert "already on `main` and clean" in rule, (
        "Rule 1 must make that fast-forward conditional on the main checkout "
        "already being on `main` and clean, and otherwise leave it alone — "
        "it may be the user's work in progress (#505)."
    )


def test_rule_2_rebases_on_a_fresh_fetch_before_a_fast_forward_push(execution):
    """Fetch, rebase, then push the named branch — and never force.

    In #503 `origin/main` moved 17 commits while the plan sat in two commit
    hooks; a push built on the morning's fetch was refused. `--rebase-merges`
    because a batch merge is a merge commit, which a plain rebase flattens.
    """
    rule = _rule(execution, 2)
    fetch = rule.find("git fetch origin")
    rebase = rule.find("git rebase --rebase-merges origin/main")
    push = rule.find("git push origin orchestrate/<topic>:main")
    assert -1 not in (fetch, rebase, push) and fetch < rebase < push, (
        "Rule 2 must fetch, rebase onto `origin/main` and only then push "
        "`orchestrate/<topic>:main` (#505)."
    )
    assert not re.search(r"--force|\bpush -f\b", rule), (
        "Rule 2 must never force: a refused push means `origin/main` moved, "
        "and the answer is to fetch and repeat."
    )


def test_baseline_is_measured_where_the_plan_lands(execution):
    """A baseline belongs to the commit workers are cut from.

    #503 measured 7871 / 326 before the push; after the rebase it was
    8030 / 332. Measuring before the push briefs workers a number for a tree
    none of them will have.
    """
    assert "after the Step 8 push" in _rule(execution, 3), (
        "Rule 3 must have the briefed baseline measured at the commit the "
        "plan lands on — after the Step 8 push (#505)."
    )
    assert "re-measure the baseline after it" in _rule(execution, 2), (
        "Rule 2 must send a rebase that moved the tip back to Rule 3's "
        "re-measurement, after the push rather than before it (#505)."
    )


def test_step_8_writes_the_plan_in_the_orchestrators_worktree(s):
    """resolve-plans-dir.sh re-roots to the primary checkout from a linked
    worktree (its `--git-common-dir` block), so run from the orchestrator's
    worktree it prints the MAIN checkout's `docs/plans`. Followed literally,
    Step 8 then writes the plan into the checkout #505 says never to touch,
    and the worktree's commit leaves it out (CR 611).
    """
    body = s.body
    step_8 = body[body.index("### Step 8") : body.index("### Step 9")]
    assert "repo-relative path in your worktree" in step_8, (
        "Step 8 must say the plans-dir resolver answers with the main "
        "checkout's path, and that the doc goes at that repo-relative path "
        "in the orchestrator's worktree (CR 611)."
    )


def test_rule_6_diffs_against_a_launch_snapshot(execution, refs):
    """The detector compares against a snapshot, because it is not ours.

    The orchestrator no longer cleans the main checkout, which may hold the
    user's own edits. Read against "any output", those edits would halt every
    batch; read against the snapshot, only a change is a fall-through.
    """
    assert "snapshot" in _rule(execution, 6), (
        "Rule 6 must snapshot the main checkout's status and HEAD at launch "
        "and treat a difference from it as the signal (#505)."
    )
    step_4 = next(ln for ln in execution.splitlines() if ln.startswith("4. Takes"))
    assert "Rule 6's snapshot" in step_4, (
        "Orchestrator step 4 must take Rule 6's snapshot before the first "
        "launch: step 5 and recovery.md both compare against it (CR 612)."
    )
    recovery = (refs / "recovery.md").read_text()
    assert "launch snapshot" in recovery, (
        "recovery.md must return the main checkout to the branch Rule 6's "
        "launch snapshot recorded, and leave the user's own work out of the "
        "salvage stash (#505)."
    )
