## Session 2026-10-27 — gregoryfoster/skills (using-mayfly-chat: #386, #387)

A focused backlog: the open issues about one skill, found by grepping every
open issue's title and body for "mayfly" and reading each hit. 107 issues were
open, four matched, and two were in scope. #451 and #475 mention Mayfly only in
passing. Both in-scope issues had been deferred out of patching-hosts v1 on
2026-10-13, and this run is what lifted that. The plan is
`docs/plans/2026-10-27-mayfly-broadcast-backlog.md`, tracked on #503.

**Answers:**

| Q | Answer |
|---|---|
| Q0 | Companion pair **bundled**, #387 first: #386's responder rule names #387's flag |
| Q1–Q3 | All equal; early production (vendored by the cohort); nothing deferred |
| Q4 | One local-worktree agent |
| Q5 | Ceiling 1. The real shared resource was the service the client talks to (below) |
| Merge | Regular `--no-ff` |

**Shape:** 2 issues → 1 work item → 1 single-agent batch. Baseline 8030
passed, 332 skipped, measured in a fresh `origin/main` worktree (lesson 4).

## Lessons

### 1. For a client library, Q5's shared backing service is the service itself

There's no worktree script, test database or port pool here, so Q5's
sub-questions all answered "none". What the worker could actually contend for,
or write to, was mayfly.chat, the production service the vendored client
talks to. Asking whether the worker may validate against it was the one Q5
question that changed the plan. The user answered "fake server only", then
widened it at the scoring gate to a local upstream server or one temporary
channel. Rule candidate: when the backlog changes a client, ask whether the
worker may write to the service, and record the answer as an authorization.
That's one occurrence, so it isn't promoted.

### 2. A repo-wide content guard constrains the new tests' fixtures

The conflict-file grep found nothing contested, but grepping `tests/` for the
skill's name found `test_no_channel_urls.py`. It fails on any tracked file
holding a channel URL, which is exactly what a fake-server test would naturally
write. The brief says the id and key are generated at runtime and the URL lives
only in a mode-600 temp file. This is a variant of `shared-files.md`'s "where a
shared fixture hides", except here the constraint is a guard over all tracked
files, not a fixture. Grep the test tree for the component's name, not only for
the files the issues touch.

### 3. A budget instrument can be unavailable for the whole run

The exact token counter is over its API limit until 2026-11-01. The bundle
edits a ratchet-bound SKILL.md, which lapses its anchor, and that warns rather
than fails. The plan therefore makes the worker hold the *worst-case* estimate
under the ratchet, and puts the re-anchor in the tail with a date. When a gate
has a mode that's always on and one that's occasionally available, check
which modes exist this week before writing the brief.

### 4. The stray sweep missed an ignored file, and the plan's own commit failed on it

Step 0 switched the checkout from an unmerged branch that adds a new skill
back to `main`. `git status --porcelain` came back clean. But the branch's
scripts had left an ignored `__pycache__/*.pyc` behind, so
`skills/adopting-dependabot/` survived the switch with no SKILL.md in it. The
plan commit's hook failed on one test (`every skill is measured`). The first
attempt also hid that: its output was piped through `tail`, and the commit
looked like it had succeeded. Two rules follow. In a repo whose tests enumerate
directories, sweep for strays with `--ignored`. And never pipe a gated commit's
output: write it to a file and read the exit code.

While those two 13-minute hooks ran, another session fast-forwarded
`origin/main` by 17 commits (#376). The push was refused, and the plan's
baseline was stale before any worker read it: 7871/326 became 8030/332. The
fix was to rebase, re-measure in a fresh worktree, amend the doc and the
tracking issue, then push. A baseline belongs to the commit the worker will be
cut from, and the plan isn't on `origin/main` until it's pushed.

### 5. Again, on a tiny backlog the value was in the gates

As on 2026-10-25, there was no geometry to design. The output was the six
`listen` semantics, approved at the scoring gate and written back onto #387,
three hazards for the brief, and a measured baseline. This is the second
occurrence, so it's promoted into `batch-design.md`'s low-discovery paragraph.
That file's exact re-anchor waits for 2026-11-01 too (lesson 3).
