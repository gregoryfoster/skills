## Session 2026-11-15 — gregoryfoster/skills (epic #516, Wave 8 set O: the patching-hosts follow-ups)

The ninth of Wave 8's local orchestrators. The brief and its update were comments on #629, and Steps 1–9 were skipped. Base `fdc4710e`, 10,446 / 475.
- **Chains:** A (#629, #607, the dry-run gate), B (#646, the reboot chain), C1 (#634, #633, #611) and C2 (#609, #608, #635), the probe's readings, D (#636, #610, the knob and the log), and the journal: nine host entries (#473, #569, #620, #623, #628, #630, #631, #637, #639).
- **Workers:** six, one worktree each, all off the base and merged with `--no-ff`. The journal was written beside the chains and merged last.
- **Decided by the operator before the build:** #636 a new finding kind, which declined the coordinator's recommendation; #610 extend the gate.
- **Review:** one round, CR 2158–2161, four fixes.

## Lessons

### 1. Check a proposed refusal against what runs after it
The brief asked #607 to "name the empty take and refuse, or ask, before the bulk". A held step refuses a run with no green bulk (`apply.sh:572`). So refusing a bulk that takes nothing would strand the held step that does the lane's work. The pre-flight read that line and posted the correction before any worker started. The fix reports the empty take, and the owner approves it as bookkeeping.

### 2. A named edit outside a worker's files beat strict ownership
Each worker had a file list, and leave to make a minimal edit outside it if it named the edit. Five did:
- **B:** `apply.sh`'s `CHAIN_SPAN`, which had to grow with the chain's new 60 s re-read, or a bulk would pass and its chain then be refused;
- **C1:** `policy.md`;
- **C2:** a stale comment in another skill;
- **A:** `_probe-lib.sh`;
- **D:** a probe test.

All six merges were clean. A strict list would have left `CHAIN_SPAN` at 720 s, and that bug wouldn't have shown until a host's window was nearly full.

### 3. When evidence gains quoted text, follow where the evidence goes
#634 asked the probe to quote the matched line, so the owner can judge it without the grep. Doing so put an admin's host unit command line, a password flag or a URL's credentials included, into JSON that ends up in run records and public issues (CR 2158). The probe already reported secrets by name, never by value. Its new quotes didn't. Quoted evidence is now masked, and a host unit is quoted by the matched word alone.

### 4. A fallback chain stops at evidence it can't read
#633's idle clock tries the log directory, then apt's install date. An unreadable log directory fell through to the install date, which reaches further back. That's the dangerous direction, because a false `dormant` is a prune proposal (CR 2159). An unread source now keeps the conservative clock and says why. Order a fallback chain by strength, and treat an unreadable source as unknown, not as absent.

### 5. A journal written ahead of the merge needs a reconcile pass
The journal worker landed the entries in parallel, saying what each fix would ship by issue number. Checked against the merged code, it had one claim wrong: the promoted rule said a dry run counts only against lists "fetched in that run", but the merged gate also takes the host's own lists fetched within a day. Writing the journal early saved wall time, and one pass over its claims kept it true.

### 6. Read a contract's consumers before shipping its change
The operator chose a new finding kind for #636, and the coordinator had warned it would turn archiver red. A read-only pass over the cohort's knob tests (six repos) and knobs (14) narrowed that to one repo. Only archiver has both a knob test and a `disabled:`/`removed:` stage. It also found address-validator going red on its `purged:` date either way. The post-merge steps went on #636 naming exactly those two repos.
