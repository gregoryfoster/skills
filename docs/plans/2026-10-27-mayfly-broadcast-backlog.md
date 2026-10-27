# Mayfly broadcast backlog: orchestration plan

Tracking issue: #503. Issues: #387, #386.

## Goal

Make `using-mayfly-chat` fit the shape the cohort already uses: one initiator
and N responders on one channel. Two issues came out of the six-agent broadcast
of 2026-10-13 (CannObserv/broker#67), both reported from archiver-agent's side.
The client gets a wake filter for `listen` and a text mode for `read` (#387), so
a responder wakes only for the initiator or a mention of itself, and nothing it
did not wake for is skipped. Then the skill replaces "No multi-party" with a
**Broadcast** subsection (#386), which uses that filter and keeps two-party as
the default.

## Approved approach

| Q | Answer |
|---|---|
| Q0 | **Bundled**, #387 first: #386's responder rule uses #387's `--wake-from` (define → use) |
| Q1 | All roughly equal: correctness, testability, maintainability |
| Q2 | **Early production**: vendored by the cohort, so flags are additive and output with no new flag is unchanged |
| Q3 | Nothing deferred: `--wake-on-mention`, the post-conflict `--text` rendering and a sixth field-notes session are all in |
| Q4 | One agent, **local worktree** (`isolation: "worktree"`) |
| Q5 | **Ceiling 1** (one work item). No worktree script, no shared backing service; the commit hook runs the full structural suite (13 min) |
| Q5 live | Fake-server tests are the gate. **Live validation authorized** by the user (2026-10-27): a local upstream Mayfly server, preferred, or one temporary mayfly.chat channel, deleted afterwards |
| Merge | Regular `--no-ff` merge of the worker branch to `main` |

## Prioritization rubrics

**Score = (Foundation × 2) + (Correctness × 2) + Scope**, max 15. This is the
skill's default rubric, unchanged.

| Dimension | 1 | 2 | 3 |
|---|---|---|---|
| Foundation Leverage | Standalone | 1–2 others benefit | Many depend on it |
| Correctness Risk | Cosmetic | Edge-case / runtime failure | Data loss, silent failure |
| Scope Clarity | Design discovery | Minor decisions | Mechanical |

## Scored backlog

| # | Issue | F | C | S | Score | Blast |
|---|---|---|---|---|---|---|
| 387 | `listen` wake filter (`--wake-from`, `--wake-on-mention`); `read --text` | 2 | 2 | 2 | **10** | Med |
| 386 | Broadcast subsection replaces "No multi-party" | 1 | 2 | 2 | **8** | Low |

#387 scores F2 because #386 uses it, and C2 because each needless wake invites
answering an ack, while a careless filter would drop messages silently. #386 scores
C2 because an uncorrected third-party claim lands in someone else's record.
Neither scored Scope 1, so no decision gate re-scored anything. The #387
semantics below are recommendations the user approved at the scoring gate.

Closed-in-fact grep (2026-10-27, main `a695c02e`): neither has shipped.
`SKILL.md` still says "No multi-party", and `client.mjs` has no `--wake-from`,
`--wake-on-mention` or `--text`.

### #387 semantics (approved 2026-10-27)

1. **Nothing is skipped, ever.** With a filter set, the peer messages that did
   not wake the listener ride along in the result, on exit 0 *and* on the exit 3
   deadline, with `last` advanced to the head. With no filter, the output is
   byte-for-byte what it is today.
2. **An undecryptable event (`from:""`) always wakes**, whatever the filter.
3. **`--me` stays required**, and the agent's own posts never wake it.
   `--wake-from` and `--wake-on-mention` combine as OR.
4. **The mention match is case-insensitive** on the decrypted text. The skill
   says it is a peer-controlled convenience, not an authenticated signal.
5. **A hermetic behavioural test** for the client against an in-process fake
   server (none exists today).
6. Both changes join the `client.mjs` header's divergence list and
   `protocol.md`'s table; `metadata.version` goes 1.0 → 1.1.

## Conflict zones

One work item, so the zones fix the commit order inside the agent, not a merge
order between agents.

| File | #387 (first) | #386 (after) |
|---|---|---|
| `skills/using-mayfly-chat/SKILL.md` | Phase 3 step 5 (the `listen` command; "first message not from `--me`"), `metadata.version` | L13 "Five cohort sessions", L66, Phase 3 step 6 (landing on *your* issue), L143 "No multi-party", L152 |
| `scripts/client.mjs`, `scripts/mayfly.sh` | header divergences, usage (duplicated in both, keep in sync), `parseArgs`, `doListen`, read/post rendering | — |
| `references/protocol.md` | divergence row 4 (L48), a new row for `--text` | — |
| `references/failure-modes.md` | item 5 (L49), the broadcast wake case | — |
| `references/exchange-discipline.md`, `templates.md`, `field-notes.md` | — | third-party-claim rule; broadcast cold open and goodbye; the sixth session |
| `tests/structural/test_mayfly_client.py` (new, its own file per AGENTS.md) | fake-server tests | — |

No test asserts the literals this work rewrites ("No multi-party", "first
message not from", "five sessions"), so nothing goes red when they change. The
worker greps them itself.

## Dependency graph

```
#387 (define --wake-from / --text) ──► #386 (Broadcast subsection uses them)
```

Nothing else in the open backlog blocks or depends on either issue. #376
(`adopting-dependabot`) fast-forwarded onto `origin/main` while this plan was
being committed. None of its 17 commits touch the Mayfly skill, the URL guard or
`.skills/context-token-counts`.

## Batch execution plan

**2 issues → 1 work item → 1 batch.**

| Batch | Issues | Agents | Files | Gate |
|---|---|---|---|---|
| A | #387 → #386 | 1, sequential commits, local worktree | as in Conflict zones | Starts once this doc is on `origin/main` |

A single-agent batch has no `batch/` branch: the worker's own branch is the
review unit. **Baseline: 8030 passed, 332 skipped** (`bash
scripts/structural-tests.sh`, 13m25s), measured in a fresh detached worktree
of `origin/main` at `93bce812`, the commit this plan sits on. The plan commit
adds no tests. The worker stops and reports if its tree disagrees. (The first
measurement, 7871/326 at `a695c02e`, came before #376 landed.)

Commit sequence:

1. `#387 test:` red: fake-server tests. The hook runs the suite, so this commit
   uses `--no-verify`, and its body says so.
2. `#387 feat:` green: `client.mjs` + `mayfly.sh`.
3. `#387 docs:` SKILL.md Phase 3 step 5, `protocol.md`, `failure-modes.md`.
4. Live validation against a local upstream Mayfly server (`josharian/mayfly`
   at `06dd34e`, the commit the client was vendored from; Go 1.26 is on the
   host), with two named senders exercising each flag. If that server cannot be
   stood up: one temporary mayfly.chat channel, deleted afterwards. Reported,
   not committed.
5. `#386 docs:` Broadcast subsection, Phase 3 step 6 landing exception, five →
   six sessions, exchange-discipline / templates / field-notes,
   `metadata.version` 1.1.

## Key decisions

- **Bundle rather than Shape B.** The two issues differ in kind (client code vs.
  norms), but #386's responder rule names #387's flag. A split would ship the
  norm either without the flag or with a provisional one. With only two issues,
  a second batch would buy nothing in parallel.
- **The channel-URL guard binds the tests.** `test_no_channel_urls.py` fails on
  any tracked file containing `/c/<22 chars>#<43 chars>`. The fake server's
  channel id and key are generated at runtime, and the URL lives only in a
  temp mode-600 file named by `MAYFLY_URL_FILE`, never as a literal in the
  test source.
- **No live URL reaches a durable store during live validation either**: it goes
  in a mode-600 file outside the repo (the skill's own Phase 1), and the
  validation log in the report carries counts and sequence numbers, not URLs.
- **The exact token count is unavailable until 2026-11-01** (API usage limit,
  as for #376). Editing SKILL.md lapses its anchor in
  `.skills/context-token-counts`, which warns rather than fails. The worker
  keeps the *worst-case* estimate under the 6,000 ratchet (current anchored
  exact: 5,238), and the re-anchor is in the tail.
- **Red commit with `--no-verify`.** The pre-commit hook runs the 13-minute
  suite, which a red phase cannot pass (Worker step 6).

## Runtime note on issue-body decay

Both bodies were written on 2026-10-13 from one session's measurements, and no
batch runs before this one, so decay is low. Still, verify each line number
above and each body claim (for example "~18 wakes, 4 needed"; "3 of 6 posts
conflicted") as a claim. Use the evidence links where the skill text will quote
them, and report any that do not hold.

## Post-merge tail

| Item | Owner |
|---|---|
| Comment the merge on #386, #387 and the tracking issue; close all three | orchestrator |
| Exact re-anchor of `skills/using-mayfly-chat/SKILL.md` (`docs/BUDGETS.md` anchor loop) after 2026-11-01 | orchestrator |
| Field validation of `--wake-from` in the next real broadcast | no owner until one runs; whoever initiates it reports on the tracking issue or a new one |

## Deferred items

None (Q3).

## Out of scope

- Upstream `josharian/mayfly` changes. Both flags are client-side divergences
  in our vendored copy, and upstream follow-ups were reviewed and skipped on
  2026-09-24.
- A peer roster, auto-answering and self-hosting stay under "Not in v1". Only
  the multi-party exclusion is replaced.
