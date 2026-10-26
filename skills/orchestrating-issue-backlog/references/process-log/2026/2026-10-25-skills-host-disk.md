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

*Corrected 2026-10-26:* `--assume-no` doesn't always abort. It installs when
an install of exactly the packages named needs no prompt (lesson 7).

## Execution (2026-10-25 to 2026-10-26)

| Batch | Worker rounds | Review | Outcome |
|---|---|---|---|
| A (#425 + #482) | 4 | CR 520–559 across the worker rounds, then the owner's own `CR --fix` over the 97 merged commits (CR 560–580) | merged `--no-ff`, pushed `5f3a3dd0`; #425 and #482 closed |
| B (#390) | 3: a preflight block, the build, then CR 581–588 | one orchestrator review; 586 filed as #499 | merged `--no-ff` as `1d90f342` |

Batch B ran from 16:55 to 22:06 UTC. Plan usage isn't readable from the
orchestrator, so spend is given in rounds.

### 7. The orchestrator's own measurement was the most dangerous error

At the gate, `apt-get --assume-no` was measured on `upgrade` and on an
install that pulled in other packages. Both prompted, so both aborted. The
plan and #390 then generalised that to "prints both figures and changes
nothing". But an install of exactly the packages named asks nothing, so
`--assume-no` has nothing to refuse, and it **installs**. Batch B's worker had
been told the brief was "proposals, not specifications", so it re-measured on
the step's own shape, and caught it. Rule: a measurement transfers only to the
invocation measured. When a brief prescribes a tool on the strength of the
gate's measurement, say which invocation was measured.

### 8. A strict baseline caught a latent race the local gate never could

The brief said "stop on any other difference", and the cloud's baseline had
one extra failure: one of Batch A's tests asserted that a killed child was
gone. The cloud container's PID 1 reaps lazily, so the child sat as a zombie,
and `kill(pid, 0)` succeeds on a zombie. macOS and systemd reap fast enough to
win the race. The fix was test-only and landed on `main` before the
re-baseline. It cost one round of about 30 minutes. Verification-mode
asymmetry is wider than root against non-root: PID 1's behaviour differs too.

### 9. Don't predict the direction of a skip delta

Batch A's pilot had more skips in the cloud than on macOS, from root. By
Batch B, Linux-only tests outnumbered the root skips (228 in the cloud against
326 on macOS). The plan's "re-measure, don't carry over" was right. The
brief's "more skips than macOS" wasn't.

### 10. Quote the upstream code into the round when the worker can't reach it

The cloud session couldn't pull the GC layer (403 from the blob host through
its proxy), so the worker read the GC's config as configparser's defaults. The
orchestrator had the layer locally, and three findings (the rounded-up Use%,
`[DEFAULT]` not being a fallback, and the 1–100 range) came from reading it.
Round 3 quoted the relevant lines into its comment, and the worker fixed all
three against them.

### 11. `gh api -f body=@file` posts the path

`-f` takes the value raw; only `-F` reads `@file`. One round comment went up
as a path, and was patched before the worker was woken.
