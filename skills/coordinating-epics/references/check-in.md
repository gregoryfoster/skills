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

Read every comment on the child from the hand-off onward, and read edited comments as they now stand. Review rounds land after the close, sometimes a dozen (broker 102, private-backlog 100).

**CI:**
- Read job-level check-runs on the final SHA **and** on `main`'s tip, never a run's summary (private-backlog 97, status 15).
- Wait for `status: completed` before reading `conclusion`. A null conclusion is not a pass (private-backlog 126, 132).
- The required set is the jobs the range's paths trigger. A missing job may be path-filtered, so check the filter against the diff (private-backlog 143).
- Give every non-green run a one-line cause, read from its log, not guessed (processor F96, F122).
- Name runner-starved or cancelled jobs, and re-check them next time (private-backlog 99).
- A failing scheduled job on the SHA is a re-scan input, not noise. One went unseen for about ten weeks (private-backlog 97).
- Some hosts have no CI. There, the gate is whatever the epic's verify recipe says.

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

**When an incident happened,** report what failed apart from what could have, from the journals (archiver 53).

**States a tick can carry:**
- **Done with a residual.** Tick, and append `Still open: …` to the line (private-launch 31).
- **Landed and live, recorded apart with dates.** Tick at go-live (broker 131).
- **"Not planned".** A completed outcome; the line keeps its reasoning and its reopen trigger (status 67).
- **A ticked line stays ticked.** A regression is a new item that links back (status 50).

Verification is read-only. Never test a refusal by attempting the write on a production path. Use `stat`, `find -perm`, or a scratch copy (status 45).

## 2. Harvest

From the closing comment, the PR, and every comment since the hand-off:
- **Contract diffs.** Diff the contract the epic assumed against the one that shipped (a lock order, a status code, a request shape), and write the difference to every downstream child and to the design doc. One run called this the most valuable thing its coordinator did (archiver 14).
- **`For #N:` notes,** moved to the issue they name. That issue's thread won't read this one's comments (archiver 19, 32). Take each note's latest state across all comments, the closing comment's `For #<epic>:` section, and asides in prose (private-backlog 103, 110).
- **New states, codes or messages** a later UI or SDK child will display (archiver 27).
- **Verification debt,** into the ledger: what's unverified, why it was skipped, how to discharge it, and discharged-by. A later child may discharge it, and the ledger names the child that can (archiver 18, 33, 37; broker 140).
- **Accepted limitations,** routed to the issue where a human will meet them, often the cutover (archiver 38).
- **A limit that repeats across close-outs.** Three "not live-verified" notes in a row meant nothing had been run end to end (private-cli 49).
- **Corrections to a claim.** Search the epic, the trackers and sibling issues for everywhere it was made, including claims the coordinator inherited (private-cli 48).
- **Answers to a later child's step.** Re-verify them, then record them with the evidence where that child will read them (archiver 47).

**Write back as comments,** headed "Changed since filed". A comment only appends, so it can't race a concurrent body edit, and it keeps what the issue first said. Body edits are kept for the epic's checklist and its own lines (archiver 15). A design amendment goes through a docs PR. The hand-off names it as a prerequisite once a child depends on it (archiver 16, 23).

**When an item closes, rewrite the lines that depended on it.** "Depends on #270" becomes "dependency met: the error now carries `retry_after_seconds`, so the route only forwards it" (address-validator 45).

## 3. Re-scan and slot

`scan.sh` reports three cursors, because each one alone missed something:
- **Numbers above `Last issue seen`**, issues and PRs (they share a number space). This catches follow-ups that never mention the epic. A search by creation date returned nothing where the number watermark worked (archiver 10, 17).
- **Updated since `Last check-in`**, with new and edited comments on the epic's items. This catches a reply on a closed child, a gate flipped in another thread, or a late approval (private-backlog 152, watcher F13, status 74). New comments on the epic itself come apart, as `epic_comments`: a sibling coordinator or the operator writes there, never in the body ([siblings.md](siblings.md)).
- **The commit range**, from §1.

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
cat > "$SCRATCH/ops.json" <<'JSON'
[
  {"op": "tick", "ref": "#45"},
  {"op": "note", "ref": "#45", "text": "Shipped 1a2b3c4..5d6e7f8, live {today}."},
  {"op": "set-line", "ref": "#46", "line": "- [ ] #46 dependency met: route only forwards retry_after_seconds"},
  {"op": "add-line", "section": "Tier 1 — bugs", "line": "- [ ] #58 follow-up from #45's review · S"},
  {"op": "header", "field": "Last check-in", "value": "{checked}"},
  {"op": "header", "field": "Last issue seen", "value": "{last_seen}"},
  {"op": "header", "field": "Last verified SHA", "value": "5d6e7f8"},
  {"op": "header", "field": "Next", "value": "#46, brief on the issue"},
  {"op": "log", "text": "{today}: #45 closed and live. 1 new (#58, slotted). Next: #46."}
]
JSON
bash "<epic-edit.sh>" --repo OWNER/REPO --epic N --scan "$SCRATCH/scan.json" --ops "$SCRATCH/ops.json" --dry-run \
  && bash "<epic-edit.sh>" --repo OWNER/REPO --epic N --scan "$SCRATCH/scan.json" --ops "$SCRATCH/ops.json"
```

- **A refusal (exit 3) wrote nothing.** Read the reason. A foreign tick is a claim: verify that child, then pass `--accept-ticks '#N'`. Any other foreign edit means merging by hand: read the diff, rebuild your ops on the live body, and re-run with `--adopt-live`.
- **A lint refusal on a line you only ticked** means the line already held something the lint refuses, such as a short ref. Every changed line is linted whole, so legacy text is fixed the first time it's touched: rewrite the line with `set-line`, then tick.
- **Exit 4: the read-back differs.** The write may have landed partly. Read the epic before anything else.
- **Log every check-in,** including "No new issues; ranking unchanged". Without that line, nobody can tell "checked and found nothing" from "never checked" (address-validator 49).
- **The baseline lives in the per-user state directory,** never `/tmp`, which may or may not survive a reboot (broker 101). If it's lost, the issue's edit history (GraphQL `userContentEdits`) is the fallback (private-backlog 113).
- **Procedure changes go into the epic in the same check-in,** such as a new standing check or a new recipe line, not into host memory alone (private-backlog 148, processor F108).
- **Measured state is rewritten from scratch,** with a measured-at time on every bullet (processor F133).
- **Mirror a gate tier onto a parent epic,** where one exists: one line there, synced on every change to the tier (private-launch 36).
