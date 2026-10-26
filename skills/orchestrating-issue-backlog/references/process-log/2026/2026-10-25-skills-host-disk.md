## Session 2026-10-25 — gregoryfoster/skills (host-disk: #425, #482, #390)

A focused backlog rather than the whole open list: a new-skill proposal (#425,
`maintaining-host-disk`) and the open issues related to it, which were found by
a keyword sweep and confirmed by reading each body. 93 issues were open; three
were in scope. #335 matched the sweep only. The plan is
`docs/plans/2026-10-25-host-disk-backlog.md`, tracked on #485.

**Answers:**

| Q | Answer |
|---|---|
| Q0a | #482 (a patching-hosts editor-build class) **bundled** into #425 |
| Q0b | #425's body **rewritten** to its comments' shape |
| Q0c | #390 independent; its open option decided as reading the GC's config |
| Q1–Q3 | Correctness first; pre-production; nothing deferred |
| Q4–Q5 | Cloud sessions; ceiling 1 by choice, though the two items are file-disjoint |
| Gate | Pin in the skill only; the name `maintaining-host-disk`, which the user picked over the one offered |

**Shape:** 3 issues → 2 work items → 2 single-agent batches in sequence. No
contested files.

## Lessons

### 1. Q0 was decided by reading the upstream artifact, not its thread

Whether #482 overlapped #425 turned on what Provisioner's GC actually prunes.
#425's thread summarised it ("liveness only"), but the layer is public and
18 KB. Pulling it by the issue's own contract and reading the tiers took about a
minute. It turned "candidate pair" into four concrete divergences: a staged
newer build removed, the VSIX cache pruned, Stable only, no Cursor or Windsurf.
The bundle decision then rested on those, and so did the text written to #482.
This is Step 4's "measure instead of asking", run before scoring rather than at
the gate. That's one occurrence, so it isn't promoted.

### 2. A proposal's body decays from upstream before any batch touches it

Six comments on #425, four of them owner decisions in another repo, had replaced
its install source (a private repo became a public image layer), dropped one of
its warnings, and moved its pitfalls into the shipped tool. Nothing in this repo
had shipped, so it isn't rescope-to-residual. The disposition was the same,
though: rewrite the body to the current shape and keep a *Replaced* list
linking each comment. A new-skill issue that collects an upstream contract in
its comments is likely to show this again.

### 3. The only edge between disjoint items was one sentence

The new skill has to say that patching-hosts reads its config, and that is
#390's behaviour. Written in Batch A, it would describe code that doesn't exist
yet. Giving that one sentence to B's worker turned a would-be shared file into a
plain ordering. Rule: where a doc line describes another item's behaviour, the
item that ships the behaviour writes the line.

### 4. Verify a number before it goes into a write-back

The #390 decision comment gave the config's default as the template's value.
Checked against the code a minute later, the number was right but its source
was wrong. The comment was corrected, and its edit history keeps the first
revision. A gate write-back is public and durable, so check a figure before
posting it, not after.

### 5. The rubric's Foundation counted dependents in other repos

In-backlog, #425 has one dependent at most. What scored it a 3 was outside the
repo: a consumer issue blocked on it, and seven hosts' retirements. For a skill
library, Foundation should count downstream repos' dependents. This is flagged
for the rubric, not changed.

### 6. On a small backlog, the value was in the gates

There was nothing to geometrise. The session's output was five GitHub
write-backs (a body rewrite, a title, three comments) and two measurements:
the GC layer, and apt on noble, where `apt-get -s` prints no size line and
`--assume-no` prints both.
