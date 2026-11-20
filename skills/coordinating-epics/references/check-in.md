# The check-in

The detail behind SKILL.md's check-in steps 1–5 and 7. A citation such as "broker 128" names a run's entry in [process-log.md](process-log.md), then that run's finding number.

**Order within a check-in** (broker 106, processor F72, F112, F116):
1. Anything an outside party is waiting on: unblock it first.
2. Read Milestones and gates.
3. Verify.
4. Harvest.
5. Re-scan and slot, **before** writing the hand-off.
6. Re-run the probes just before the write. If you re-scan as well, read the new report and act on what it adds before writing with it.
7. Write.

## 1. Verify

**The unit of verification is the commit range,** `git log <Last verified SHA>..origin/main`: every commit, whether or not it carries the child's number (broker 128, watcher F39). `scan.sh` lists the range and attributes each commit:
- `child`: it cites an epic item;
- `epic`: it cites the epic;
- `bot`: a bot authored it;
- `unattributed`: outside work. Outside work can close epic items too (private-backlog 140).

A null `commits` means the range was skipped, not that it was empty: `commits_skipped` says why, and names the fix that fits. In a clone with no `origin/HEAD`, the tip falls back to GitHub's default branch. If neither resolves, the fix is `--ref`, `git remote set-head origin -a` once in that clone, or, when the clone lacks the default branch itself, a fetch of it.

Read every comment on the child from the hand-off onward, and read edited comments as they now stand. Review rounds land after the close, sometimes a dozen (broker 102, private-backlog 100). A closing comment older than commits in its range is verified on the range's tip, not the SHA it reports (#430).

**CI:**
- Read job-level check-runs on the final SHA **and** on `main`'s tip, never a run's summary (private-backlog 97, status 15).
- Wait for `status: completed` before reading `conclusion`. A null conclusion is not a pass (private-backlog 126, 132).
- The required set is the jobs the range's paths trigger. A missing job may be path-filtered, so check the filter against the diff (private-backlog 143).
- A docs-only merge may run no workflow on `main`. Read the last code merge's run, and check that the diff from it to the tip touches only ignored paths (processor 10-23 F163; private-library 11-17 2).
- Give every non-green run a one-line cause, read from its log, not guessed (processor F96, F122).
- Name runner-starved or cancelled jobs, and re-check them next time (private-backlog 99).
- A failing scheduled job on the SHA is a re-scan input, not noise. One went unseen for about ten weeks (private-backlog 97).
- Some hosts have no CI. There, the gate is whatever the epic's verify recipe says.

`bash "<verify-ci.sh>" --repo OWNER/REPO --sha <final SHA> [--base <SHA before the push>] [--wait 600]` does the first three in one JSON report (#394): a row per job on the SHA, on `main`'s tip, and on each active workflow's latest run on `main`, scheduled ones included. `missing` names a job the push's paths should have run that never did; a job with its own `if:` is `conditional`, never missing. `verdict` is `red`, `pending`, `incomplete` or `green`, and `because` names the jobs behind it, so a red from a managed run (event `dynamic`) reads as that. Dependabot's update job is a row marked `advisory`, never the verdict: its failures are the registry's or the lockfile's, and a warning names them. Its report is what the verification comment holds. Give `--base` for a push of several commits, or a file changed early in it is missed.

**Live, by deliverable** (archiver 8, 49; status 34, 46). Closed is not live, and live can come before closed. Use the recipe the epic recorded:

| Deliverable | Proof |
|---|---|
| A migration | its head in the production database, read-only |
| A route or contract | the served OpenAPI, or the live endpoint |
| A timer or job | its journal, over at least one period plus jitter (status 95) |
| A deploy | the service started after the merge; the diff touches something the process loads (watcher F58) |
| A dependency bump | each live output compared before and after (processor F139) |
| A data repair by hand | each record read back from the public API (private-cli 43) |
| A tool the coordinator itself runs | one real use (processor F136) |

**What the gates can't see:**
- **A wire-visible change behind a path-based changelog rule:** a status, an error `code`, a message, a field. Raise it as a judgment call, not a failure (archiver 25).
- **The main checkout's branch.** `git -C <deploy checkout> branch --show-current` must be `main`, and the tree clean. An implementer once checked out its branch in the directory production ran from (archiver 52).
- **"Done when" boxes.** The coordinator ticks them on the evidence: the test files, the migration, the CHANGELOG, the docs (archiver 9).
- **Follow-ups the PR mentions but never filed.** Grep its body for `follow-up | out of scope | not filed | deferred | held` (private-launch 30).
- **Questions that were open on the issue,** including other repos' questions. Check the closing comment answers each (address-validator 44).
- **Claims made in the closing comment.** Re-run them as the verification steps (status 33). Prove "contract unchanged" from git: `git diff --stat A..B -- <frozen paths>` (status 84).
- **A test that never reaches its target:** a check that skipped on every run, or a fixture that replaced the dependency under test (status 11-17 S2). Where a fix's tests could pass vacuously, remove each half of it at runtime, from a pytest plugin in the scratch directory. The failures that return are the evidence, and the tree is untouched (private-library 11-17 3).
- **A PR merged with no implementer thread,** such as a refresh hook's. It has no review or close-out, so run its checks yourself: CI by job on the head and the merge, a submodule move being a fast-forward, and each reader it feeds (status 11-17 S6; private-library 11-17 8).

**When an incident happened,** report what failed apart from what could have, from the journals (archiver 53).

**States a tick can carry:**
- **Done with a residual.** Tick, and append `Still open: …` to the line (private-launch 31).
- **Landed and live, recorded apart with dates.** Tick at go-live (broker 131).
- **"Not planned".** A completed outcome; the line keeps its reasoning and its reopen trigger (status 67). Tick it with a `not planned: …` note (or `out of epic: …`), and the editor's counts read it as `disposed`, not `done` (processor F177).
- **A ticked line stays ticked.** A regression is a new item that links back (status 50).

Verification is read-only. Never test a refusal by attempting the write on a production path. Use `stat`, `find -perm`, or a scratch copy (status 45).

## 2. Harvest

**Read the closing comment's sections first.** `shipping-work` Step 5 ends it with `**Follow-up:**`, `**Known limits:**` and one `**For #N:**` per later issue, each a bold lead over list items, left out when empty. `For #N:` items go to issue N, `Known limits:` to the limitations and verification debt below, `Follow-up:` to the re-scan. A comment from a repo whose `shipping-work` predates them has none, so read its prose. Either way, read on: notes also land outside the closing comment.

From the closing comment, the PR, and every comment since the hand-off:
- **Contract diffs.** Diff the contract the epic assumed against the one that shipped (a lock order, a status code, a request shape), and write the difference to every downstream child and to the design doc. One run called this the most valuable thing its coordinator did (archiver 14).
- **`For #N:` notes,** moved to the issue they name. That issue's thread won't read this one's comments (archiver 19, 32). Take each note's latest state across all comments, the closing comment's `For #<epic>:` section, and asides in prose (private-backlog 103, 110).
- **New states, codes or messages** a later UI or SDK child will display (archiver 27).
- **Verification debt,** into the ledger: what's unverified, why it was skipped, how to discharge it, and discharged-by. A later child may discharge it, and the ledger names the child that can (archiver 18, 33, 37; broker 140). A debt or gate that waits on an event nobody controls, such as a first live send, gets an expiry and the fallback proof that discharges it then. Otherwise it never discharges, and the operator drops it at close (archiver 11-10 2, watcher 368-F10, notifier C2). A debt nobody can force rides the parked item whose trigger will produce the evidence (processor 11-16 F7). A tick that needs an event after the deploy waits, with that event, its expected time and the check in Watching (status 11-17 S5).
- **Accepted limitations,** routed to the issue where a human will meet them, often the cutover (archiver 38).
- **A limit that repeats across close-outs.** Three "not live-verified" notes in a row meant nothing had been run end to end (private-cli 49).
- **Corrections to a claim.** Search the epic, the trackers and sibling issues for everywhere it was made, including claims the coordinator inherited (private-cli 48).
- **Answers to a later child's step.** Re-verify them, then record them with the evidence where that child will read them (archiver 47).

**A note that never names its child** is the one reading misses. `harvest-candidates.sh` is an optional, advisory step for it. It pairs every paragraph of the source's thread since the hand-off with every open child. A paragraph under a `For #N` heading, lead or item, or one linking `#N`, is settled without a call. Every other pair gets one TypeSafe question: does this paragraph bear on what the child relies on?
- **It's off until the repo opts in,** through `.skills/typesafe` or `TYPESAFE_OPT_IN`. Run it from the epic's repo, so a private repo decides for itself. Each request carries one paragraph, the source's `owner/repo#N`, and one child's number, title and body.
- **It writes nothing to GitHub.**
- **Measured on 4 public epics (#436):** unnamed notes reached the right child in the top 3 for 28 of 36, against 20 by word matching (chance).

Resolve it on its own:

<!-- skill:required id=skill-scripts -->
```bash
N=coordinating-epics
for S in harvest-candidates.sh; do SD=
  for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
    [ -f "$d/$S" ] && { SD="$d"; break; }
  done
  [ -n "$SD" ] || echo "$S not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/" >&2
  echo "<$S>=${SD:?}/$S"
done
```

```bash
bash "<harvest-candidates.sh>" --repo <owner/repo> --epic <N> --source <closed child> > <scratch>/harvest.tsv
```

Read the `named` rows, then the `judged` rows from the top. Verify each row before you write it back. A row ranks a candidate; it isn't a finding. Exits 2 and 4 mean harvest by reading alone. `--help` gives the columns and `--max-calls`, which caps a long thread.

**Write back as comments,** headed "Changed since filed", each posted with `bash "<comment.sh>" --repo OWNER/REPO --issue N --body-file "${SCRATCH:?}/note.md"`. It refuses what the editor's lint refuses, then reads the comment back; exit 4 means it was posted, so read the issue before posting again (#395). A comment only appends, so it can't race a concurrent body edit, and it keeps what the issue first said. Body edits are kept for the epic's checklist and its own lines (archiver 15). A design amendment goes through a docs PR. The hand-off names it as a prerequisite once a child depends on it (archiver 16, 23).

**When an item closes, rewrite the lines that depended on it.** "Depends on #270" becomes "dependency met: the error now carries `retry_after_seconds`, so the route only forwards it" (address-validator 45).

## 3. Re-scan and slot

`scan.sh` reports three cursors, because each one alone missed something:
- **Numbers above `Last issue seen`**, issues and PRs (they share a number space). This catches follow-ups that never mention the epic. A search by creation date returned nothing where the number watermark worked (archiver 10, 17).
- **Updated since `Last check-in`**, with new and edited comments on the epic's items. This catches a reply on a closed child, a gate flipped in another thread, or a late approval (private-backlog 152, watcher F13, status 74). New comments on the epic itself come apart, as `epic_comments`: a sibling coordinator or the operator writes there, never in the body ([siblings.md](siblings.md)). The listing has left out an issue updated minutes earlier (#407), so the window opens 30 minutes early, comments included, and a row or comment from those minutes carries `in_overlap`: likely seen last time, so check before acting twice. The epic's own items are cross-checked too: one the listing missed comes back `recovered`, with a warning.
- **The commit range**, from §1.

**A cross-repo parent** keeps one more cursor per other repo, `- **Last issue seen (owner/repo):** owner/repo#N`. Pass `--also owner/repo` for each, and the report's `also` key gives that repo's number walk and updates, keeping only its rows that are children or mention the epic or a child; `unrelated` counts the rest. Write `{last_seen:owner/repo}` into its line. The editor refuses a new issue there that the write doesn't mention by `owner/repo#N`, and holds `{checked}` when any repo's listing hit its cap, or the epic keeps a cursor for a repo the scan didn't walk (#400). The commit range stays this repo's.

**A child kept on two epics:** pass `--sibling owner/repo#N` for each sibling epic that keeps lines for the same children. `cross_epic` lists each child that leads a checklist item in both, with both boxes and its state. `drift: true` marks boxes that differ (#660). Act on a drift row as on a foreign tick: verify, then bring the lagging box in line, or keep the record on one epic ([siblings.md](siblings.md)).

Also re-read:
- the epics listed under "not tracked here" (status 39);
- other epics' lines that name this repo (broker 118);
- other repos' issues that cite this repo's children, for port-backs (status 49).

**Classify each new item:**
- **child**: slot it by dependency, and add its line in the right tier;
- **closed-in-fact**: verify, link it, and close it with evidence. An issue that claims the epic but isn't linked gets slotted or closed as delivered, never left floating (archiver 45);
- **split**: file the actionable part (private-cli 41);
- **out of epic**: say so plainly, and cross-link it where it changes a remaining step's preconditions (archiver 44, 57);
- **duplicate**;
- **park**, with a trigger.

On an `--account` epic, give each out-of-epic or duplicate issue a line under `## Out of epic` in the body too. `--account` reads the body, never the log comment, so a call that names it only there is refused (#657). It also warns about a ticked line whose subject is still open (`ticked_open`, #662). The subject is the refs the line leads with, so `- [x] #46 + #47` has two. Untick the line, or close the issue. A write that adds a line with two subjects is nudged toward a line each.

**The epic's kind predicts most slots, but read every item.** In 6 public burn-downs, 157 of 177 new issues became children. In 7 themed epics, 75 of 140 were out. A TypeSafe Choice per item lost to that prior plus a mention check in burn-downs, and only tied it in themed epics ([#439](https://github.com/gregoryfoster/skills/issues/439)).

**Before sizing a follow-up,** re-run its snapshot evidence (status 28) and re-derive its counts from source (broker 142). Rank it by how long its problem has been live, not by when it was filed (broker 132). Slot a follow-up as soon as it's seen, even before its parent closes (status 27).

## 4. Blockers and gates

- **Probe, don't wait to be told.** Read each blocker's latest comment, not just its state, and test its observable condition (archiver 21, 28):
  - a served spec;
  - a tag and the build that matches it;
  - an env var's presence and length, plus one read-only call (never print the secret) (archiver 46).
- **A newly available upstream artifact gets the integration checklist** (archiver 41):
  - the pinned tag exists;
  - the served build matches the client version;
  - the signatures the adapter needs;
  - dependency ranges that fit the lock;
  - auth defaults.
- **The operator's prerequisites arrive silently.** So do the operator's own loose ends, such as an issue "drafted, not filed". Search for them by subject keywords at each check-in (power-map 63).
- **Re-read every gate at every tick:**
  - "changes when X lands";
  - gated inputs;
  - upstream-release gates, carrying the last version seen;
  - horizon items;
  - date gates that have opened (broker 114, 133, 146, 152, 155).
- **A calendar gate decides when to deploy, not when to start.** Hand off now with "deploy no earlier than …" (status 31). Strike an expired gate with its date; don't delete it (status 36).
- **Parked items:** at each check-in, run each item's trigger query by keyword, not only by issue number. When any upstream release lands, re-check every parked item against it (processor F133, F138). A child that deletes a capability changes parked rows' *need*, not only their triggers (watcher F54).
- **Re-read the tier order against the operator's rule each tick.** Record a swap as a numbered tiebreak (broker 119).

## 5. Choosing the next child

Use the order rule, then these tiebreaks, adding any new one to the epic's list:
1. **Context freshness:** the child whose code just changed (archiver 24, private-backlog 118, 133).
2. **Migrations one at a time,** keeping the chain linear (archiver 26).
3. **Safety net before capability:** no production link exists without its refresher (archiver 48).
4. **Rename deploy-visible names while the thing is idle** (archiver 50).
5. **A guard goes before what it guards** (watcher F22, private-backlog 89).
6. **Don't under-rank cleanup children;** they re-read code with fresh eyes (archiver 54).

**Say when the next child is the last unblocked one,** to give the operator lead time on the blocker (archiver 35).

**When the whole epic is blocked,** the hand-off lists each blocker, its owner, and its visible evidence, plus the options: wait, or reshape the next child to start without the blocker (archiver 39).

**When the tier or the epic runs out** before its exit criterion, that's a decision point. Offer the options, and restate the operator's rule if the run goes on into backlog mode (private-backlog 150, private-cli 46).

## 7. Writing the epic

One `epic-edit.sh` call per check-in, with every change in its ops file. Write the file with a **quoted** heredoc, so backticks stay text (watcher F10). `{checked}` and `{last_seen}` come from the scan report you read and built the ops from, given with `--scan`. Anything that changed after that scan looked falls inside the next window, not between two (CR 248). Never pass a report you haven't read: it moves the window past whatever it found. The editor refuses a report whose new issues the body doesn't mention (CR 265):

```bash
cat > "${SCRATCH:?}/ops.json" <<'JSON'
[
  {"op": "tick", "ref": "#45"},
  {"op": "compact", "ref": "#45", "link": "https://github.com/OWNER/REPO/issues/45#issuecomment-123"},
  {"op": "set-line", "ref": "#46", "line": "- [ ] #46 dependency met: route only forwards retry_after_seconds"},
  {"op": "note", "ref": "#47", "text": "Deploy no earlier than 2026-10-15T18:00Z."},
  {"op": "add-line", "section": "Tier 1 — bugs", "line": "- [ ] #58 follow-up from #45's review · S"},
  {"op": "header", "field": "Last check-in", "value": "{checked}"},
  {"op": "header", "field": "Last issue seen", "value": "{last_seen}"},
  {"op": "header", "field": "Last verified SHA", "value": "5d6e7f8"},
  {"op": "header", "field": "Next", "value": "#46, brief on the issue"},
  {"op": "log-comment", "text": "{today}: #45 closed and live. 1 new (#58, slotted). Next: #46."}
]
JSON
bash "<epic-edit.sh>" --repo OWNER/REPO --epic N --scan "${SCRATCH:?}/scan.json" --ops "${SCRATCH:?}/ops.json" --dry-run \
  && bash "<epic-edit.sh>" --repo OWNER/REPO --epic N --scan "${SCRATCH:?}/scan.json" --ops "${SCRATCH:?}/ops.json"
```

`compact` cuts #45's line to `- [x] **#45** <its issue title> · [verified](…)`: the link is step 1's verification comment, which holds the evidence the line used to. The `note` op writes the separator itself, so #47's line ends `… · Deploy no earlier than 2026-10-15T18:00Z.` Leave the `·` out of a note's text. A text that starts with one still gets only one.

- **The log comment posts last,** once the body has read back matching, or when the body didn't change. A dry run prints it. `log` still appends in the body, for an epic not yet on this form. If gh fails posting it, the exit is 5 and the body write still stands: re-run the same call, and a comment already posted is found, not posted twice (#654). The match is by the state dir's record of the call (#658), so re-run with the same `--state-dir`; the same call after an exit 0 is a new entry, and posts.

- **A refusal (exit 3) wrote nothing.** Read the reason. A foreign tick is a claim: verify that child, then pass `--accept-ticks '#N'`. Any other foreign edit means merging by hand: read the diff, rebuild your ops on the live body, and re-run with `--adopt-live`.
- **A refusal naming a `header` op** ("set Next to …, but after every op …") is your own op order, not a foreign edit: a later section op removed or changed the line. Put section ops before `header` ops and re-run (#399). The first `header` op on an epic whose cursor lines are a paragraph shows that paragraph becoming list items in the diff, with a note; that is expected.
- **Every part of the body has an op.** `rename-section` renames a heading, `set-preamble` rewrites the intro above the header, and `set-subline` changes or removes one sub-bullet under a child's line by its text prefix. `replace-section` refuses a section holding subsections, and names them: replace a subsection by its own heading, or pass `"scope": "tree"` to replace the whole subtree (#408, #413, #429).
- **A lint refusal on a line you only ticked** means the line already held something the lint refuses, such as a short ref. Every changed line is linted whole (a fenced line for secrets only), so legacy text is fixed the first time it's touched: rewrite the line with `set-line`, then tick.
- **Exit 4: not confirmed.** Either written (`"written": true`) but the read-back differed or failed, or the baseline couldn't be saved; or the PATCH failed and whether it landed is unknown (`"written": "unknown"`). Read the epic before anything else, then take it with `--adopt-live`: the `ERROR` line ends on that step, and where gh's error is behind it (the PATCH's, the read-back's), it follows that line whole, on lines of its own. A PATCH gh reported failed with the body unchanged is exit 2: nothing was written. One gh reported good with the body unchanged is exit 4 with `"written": false` and `"readback": "unchanged"`: nothing landed, and the baseline still holds, so no `--adopt-live` (#653).
- **Watch the body's size.** Every summary gives `"body": {"chars", "limit", "share"}`. Past the host's cap (inferred near 262,144 characters) a write keeps the old body and still reports success (#653), so the editor refuses growth past `--body-limit` and warns past 85%. Report the size beside the counts, and make room before the warning.
- **Log every check-in,** in its `log-comment`, including "No new issues; ranking unchanged". Without that line, nobody can tell "checked and found nothing" from "never checked" (address-validator 49).
- **The baseline lives in the per-user state directory,** never `/tmp`, which may or may not survive a reboot (broker 101). If it's lost, the issue's edit history (GraphQL `userContentEdits`) is the fallback (private-backlog 113).
- **Only this tool saves the baseline.** Another thread once saved its own hand edit there, and the diff read clean (#518). So each body the editor writes or adopts is recorded by hash, and a baseline no record matches is refused. Each run also lists, in `foreign_edits`, the history's edits since the last write that no write of the tool made, matched by time and hash, not login: every thread may write as one account. Read each one before trusting a clean diff. A state directory from before #518 has no record, so its first run refuses: read the live body and its history, then `--adopt-live`.
- **Procedure changes go into the epic in the same check-in,** such as a new standing check or a new recipe line, not into host memory alone (private-backlog 148, processor F108). So does a child that changes the verify surface: one that adds a `pull_request`-only workflow leaves `main`'s merge commits with no check-runs, so the recipe then reads the PR's head SHA (power-map 11-14 A2).
- **Measured state is rewritten from scratch,** with a measured-at time on every bullet (processor F133).
- **Mirror a gate tier onto a parent epic,** where one exists: one line there, synced on every change to the tier (private-launch 36).
