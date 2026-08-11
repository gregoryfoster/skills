# Fact Verification

`verify-facts.sh` covers the mechanically checkable claims. This file covers the
rest — and, more importantly, the rule for when you may act on the result.

## The verdict contract

Three verdicts, and conflating them is the way an autonomous run destroys real
guidance.

| Verdict | Means | May you delete on it? |
|---|---|---|
| **TRUE** | A command confirmed it | n/a |
| **FALSE** | A command *refuted* it | Yes — correct it, or delete with the command as the warrant |
| **UNVERIFIABLE** | No check decided | **No.** Ever. |

FALSE requires a command whose output contradicts the claim. "I could not find
it" is UNVERIFIABLE. "I do not think this is right" is UNVERIFIABLE. The
asymmetry is deliberate: a policy file legitimately names things that do not
exist in this checkout — illustrative templates (`references/`), naming
conventions (`lowercase-kebab.md`), and downstream consumer paths
(`skills-vendor/<owner>-<repo>/`). Treating those as FALSE deletes the parts of
the file that were doing the most work.

Record the command and its output for every FALSE verdict. In autonomous mode
that record is the reviewer's only way to check the deletion was warranted.

## Prioritise by decay rate

Verification costs tool calls. Spend them where things actually rot:

| Class | Decay | Check first? |
|---|---|---|
| Issue/PR state | days | Yes |
| Commands and flags | weeks | Yes |
| File and module paths | weeks | Yes |
| Dependency and version pins | weeks | Yes |
| Ports and env var names | months | If cheap |
| Deployment topology, unit names | months | Sample |
| Architecture and boundaries | quarters | Only when the code moved |
| Conventions and rationale | rarely | No |

A weekly run that verifies the top four rows completely beats one that samples
all eight shallowly.

## Per-class method

### Paths and modules
`verify-facts.sh` handles this: exists → TRUE; a suffix match elsewhere in
`git ls-files` → UNVERIFIABLE, likely moved (follow it up, this is the highest-
yield UNVERIFIABLE); nothing → UNVERIFIABLE, could be illustrative.

For the moved case, `git log --diff-filter=D --name-only -- '*<basename>'` finds
where it went. Correcting a moved path is a repair, not a deletion.

### Commands
The script checks only code-formatted commands against runner manifests, and only
calls FALSE when the manifest that *would* define the target exists. A `make
build` with no `Makefile` in the repo is stale-looking but not refuted — it may
document a different surface.

A documented command also carries *where it runs*, and that decides which
manifest is authoritative. The script peels a `cd <dir> &&` chain (and the
subshell and `pushd` forms) and a directory-scoping flag (`make -C <dir>`,
`uv run --directory <dir>`) off the front, then resolves against that directory:
`cd frontend && npm run build` is decided by `frontend/package.json`, not the
root one. Resolving it at the root reported a correct monorepo build command as
FALSE — the one verdict this skill deletes on — which is why the three outcomes
are split deliberately:

| Shape | Verdict | Why |
|---|---|---|
| `cd frontend && npm run build`, `build` in `frontend/package.json` | TRUE | the manifest confirms it |
| `cd frontend && npm run bundle`, no `bundle` there | FALSE | the manifest that governs it refutes it |
| `cd nosuchdir && npm run build` | FALSE | the checkout refutes the `cd` — evidence blames the directory, which is the half to fix |
| `cd docs && npm run build`, `docs/` has no `package.json` | UNVERIFIABLE | nothing refutes it; no deletion licence |
| `cd <workspace> && npm run build`, or an absolute path | UNVERIFIABLE | a placeholder or a path outside this checkout |

Three shapes are knowingly out of scope. An env-assignment prefix (`CI=1 npm run
build`) and a `source … &&` prefix do not change the working directory, so root
resolution stays correct for them. `npm --prefix <dir> run build` puts the flag
before `run`, so the extraction does not match it at all — a silent miss, which
is the safe direction, rather than a false verdict. And in a chain of *two*
runners (`cd frontend && npm run build && npm run test`), only the first inherits
the directory; the second is still resolved at the root. If a chained second
command comes back FALSE, check which directory it actually runs in before
acting on the verdict.

For anything it marks UNVERIFIABLE, **run the command** if it is read-only
(`--help`, `--version`, `--dry-run`, a lint or list subcommand). A documented
command that errors is the single most damaging stale fact in a policy file: the
agent that runs it stops trusting everything else in the file. Never run a
command that writes, deploys, migrates, or restarts to verify a doc claim.

### Dependency and version pins
`grep` the claim against the lockfile or manifest — `uv.lock`, `pyproject.toml`,
`package-lock.json`, `composer.lock`. A pin claim is one of the few classes where
FALSE is clean and mechanical: the manifest is authoritative and present.

### Ports
Cross-check the policy file's claim against systemd units, compose files, and
`--port` defaults in the code. A **port conflict claim** ("9000 belongs to
systemd, use 9001 for dev") is class A guidance and worth verifying precisely —
getting it wrong wastes a whole session on a bind error.

### Environment variables
`git grep -w "$NAME"` across the repo. Present in code → TRUE. Absent everywhere
→ still only UNVERIFIABLE: it may be consumed by the platform, a systemd unit
drop-in, or a deploy pipeline outside the repo. Check `.env.example` and unit
files before concluding anything.

### systemd units and hosts
The script reports a unit named nowhere else in the repo as UNVERIFIABLE, not
FALSE — the authority for a unit's existence is the host, and the repo cannot see
it. Do not delete deployment facts on repo-only evidence. If they matter enough
to be wrong, flag them for a human with host access.

### Issue and PR references
`verify-facts.sh --issues` resolves state via `gh`. The subtle case is not a
missing issue but a **closed** one: the reference is TRUE while the prose around
it ("pending in #42", "blocked on #17") is stale. Read the sentence, not just the
verdict. This is the most common real staleness in the cohort's "Known Issues"
sections.

An unresolvable reference is UNVERIFIABLE — it may be a PR, another repo, or
private.

### Behavioural rules and conventions
Not mechanically verifiable, and mostly should not be. Judge by provenance
instead: `git log -S'<distinctive phrase>' -- AGENTS.md` finds the commit that
added the rule. The question is **which failure, on which code, did this
prevent — and can that failure still happen?** A rule whose subject no longer
exists is a genuine FALSE (the code it constrained is gone, and `git log` proves
it). A rule nobody can justify is UNVERIFIABLE, and stays.

### Architecture prose
Verify only when the code actually moved. `git log --since='3 months ago'
--diff-filter=AD --name-only -- src/` shows added and deleted files; if the
top-level structure is unchanged, the architecture section's *facts* are fine
even if its *placement* is class B.

## Section-level staleness

Some sections are stale as a whole even when every individual claim checks out:

- **Titles that admit it.** "Open Issues (as of last session)", "Current work in
  progress", "Recent changes". These date themselves. Verify every claim, then
  propose moving the section to the tracker.
- **Migration sections describing a completed migration.** If the "during
  migration" caveats reference shims that no longer exist, the whole section is
  FALSE, not just its paths.
- **Numbered constraint lists with gaps.** `1., 2., 4., 5.` means a constraint
  was deleted and the surrounding prose may still reference "rule 3".
- **Two sections that disagree.** The most valuable finding this skill produces
  and the one no single-claim check surfaces. Read the file for internal
  contradiction — a fenced command block that contradicts `docs/COMMANDS.md`, an
  env var documented twice with different defaults. **Do not resolve a
  contradiction by deleting one side.** Determine which is correct, fix that one,
  delete the other with warrant #1, and say so in the PR body.

## The autonomous-mode discipline

Under a schedule, nobody is watching the individual verdicts. Two rules hold the
line:

1. **Every deletion carries its warrant into the PR body** — the verdict, the
   command, and the command's output. A deletion whose warrant cannot be written
   down is not warranted.
2. **When the budget can only be met by acting on UNVERIFIABLE claims, do not
   meet the budget.** Report the shortfall. An over-budget file that is still
   true is strictly better than an on-budget file that lost a load-bearing fact,
   because the second failure is invisible until it costs someone a session.

## The verdicts as Phase 2 states them

Three verdicts, and they are not interchangeable:

- **FALSE** — a command refuted the claim. Eligible for correction or removal.
  Deliberately narrow: a broken markdown link, or a missing target in a runner
  manifest that does exist.
- **TRUE** — confirmed. Note that a *closed* issue reference is TRUE-the-reference
  yet may still make surrounding prose stale ("pending in #42" when #42 shipped).
- **UNVERIFIABLE** — the script could not decide. **Never a licence to delete.**

Then verify what no script can, using
[references/fact-verification.md](fact-verification.md): behavioural
rules, version pins, port numbers, deployment topology, and "known issues"
sections. That file gives the per-class verification command and the rule for
when absence of evidence counts as evidence. Prioritise by decay rate — commands
and issue state rot fastest, architecture prose slowest.
