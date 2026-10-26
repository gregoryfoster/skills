# Host-disk backlog: orchestration plan

Tracking issue: #485. Issues: #425, #482, #390.

## Goal

Ship `maintaining-host-disk` (#425), the skill a cohort host uses to adopt
Provisioner's canonical disk GC and headroom sensor. It installs and updates the
GC from the public `co-image-base` layer under a digest-pinned contract, turns
it on, retires the host's own implementation after checking what that removed,
and carries the repo-side disk knobs no host tool should own. Editor-build
pruning (#482) is part of it. Then patching-hosts gets free-space gates (#390),
so a patch run never fills the disk mid-unpack, nor pushes an adopted host
past its own headroom line.

## Approved approach

| Q | Answer |
|---|---|
| Q0a | #482 **bundled into #425**: the GC's `vscode-servers`/`vscode-clis` tiers already cover its scope; patching-hosts gets a pointer, not a class |
| Q0b | #425's body **rewritten** to its comments' current shape (2026-10-25); the as-filed text is in the edit history, and a *Replaced* list links each comment |
| Q0c | #390 scored **independently**; option 4 is decided as "read the GC's `[sensor] alert_at_percent`", with no new knob line |
| Q1 | **Correctness first**: refuse on doubt, fail toward keeping |
| Q2 | Pre-production (the skill is new; no host depends on it yet) |
| Q3 | Nothing deferred |
| Q4 | Parallel in principle, **cloud sessions** ([cloud-workers.md](../../skills/orchestrating-issue-backlog/references/cloud-workers.md)) |
| Q5 | **Ceiling 1**: the binding resource is plan usage, not worktrees or a shared service |
| Gate | Pin lives **in the skill only**; name **`maintaining-host-disk`** |
| Merge | Regular `--no-ff` merge of each worker branch to `main` |

## Prioritization rubrics

**Score = (Foundation × 2) + (Correctness × 2) + Scope**, max 15. This is the
skill's default rubric. Q1 makes correctness the tiebreaker.

| Dimension | 1 | 2 | 3 |
|---|---|---|---|
| Foundation Leverage | Standalone | 1–2 others benefit | Many depend on it |
| Correctness Risk | Cosmetic | Edge-case / runtime failure | Data loss, silent failure |
| Scope Clarity | Design discovery | Minor decisions | Mechanical |

## Scored backlog

| Item | F | C | S | Score | Blast | Why |
|---|---|---|---|---|---|---|
| #425 + #482 | 3 | 3 | 3 | **15** | Med | F: CannObserv/address-validator#326 and seven host retirements wait on it, and #390's floor applies only on an adopted host. C: it installs root-owned files from a registry, and a wrong retire check fills a production root. S: the contract is fully specified, and the name and pin decisions were made at the gate (2→3) |
| #390 | 1 | 3 | 2 | **10** | Med | C: dpkg on a full disk leaves half-configured packages, and a full root goes into the boot. S: the apt question is measured (below); the margin size is still the implementer's call |

**Measured at the gate (2026-10-25):**

- **The canonical GC.** VERSION 2's layer was pulled anonymously and its digests
  matched the pin. Its VS Code tiers judge liveness from `/proc` and apply the
  60-minute grace, and four details differ from #482's ask. They are listed in
  #425's step 4 and on #482.
- **apt on noble** (`ubuntu:24.04`). `apt-get -s` prints neither "Need to get"
  nor "After this operation". `apt-get --assume-no <op>` prints both, then
  aborts having changed nothing. It needs root and the dpkg lock. Recorded on
  #390.

## Conflict zones

None. The footprints are disjoint:

- **#425 + #482:** a new `skills/maintaining-host-disk/`, `README.md`'s skills
  table, the skill list in `tests/structural/test_per_script_resolution.py`,
  new `tests/structural/test_maintaining_host_disk_*.py`, and one pointer line
  in `skills/patching-hosts/references/pruning.md`.
- **#390:** `skills/patching-hosts/scripts/{apply,probe,reboot-chain}.sh` (and
  `_gate-lib.sh` if the gate lands there), `references/run.md` §3 (line 68's
  by-hand "free disk" line), `references/readings.md` line 50,
  `test_patching_hosts_{apply,probe,reboot}.py` and `patching_hosts_rig.py`.

No test pins either rewritten string. No chain or generated artifact is
involved, and every token-gated file has room: `run.md` ≈6.2k of 10k,
`pruning.md` ≈2.1k, and patching-hosts' `SKILL.md` ≈2.7k of 6k (estimates).

## Dependency graph

```
#425 + #482   new skill; pointer in patching-hosts/references/pruning.md
     │   ordering edge, no shared file at A
     ▼
#390          patching-hosts gates; adds the one [sensor]-read sentence
              to maintaining-host-disk, once the gate exists
```

## Batch execution plan

**3 issues in scope, 0 deferred, 0 closed → 2 work items → 2 batches.**

| Batch | Issues | Agents | Files | Gate |
|---|---|---|---|---|
| A | #425 + #482 | 1 cloud worker, Shape A | as above | Plan pushed; the session launched by a person from claude.ai/code |
| B | #390 | 1 cloud worker | as above, plus one sentence in `skills/maintaining-host-disk/` | A merged to `main` |

Both batches are single-agent, so there is no `batch/<X>` branch. The worker's
pushed branch is the review unit: `425-maintaining-host-disk` for A and
`390-free-space-gates` for B.

**Batch A's commit order:**

1. The puller and its offline tests, red then green.
2. Install, update and remove.
3. The `SKILL.md` and references.
4. The patching-hosts pointer (#482).
5. README and registries.

## Key decisions

- **The puller is the skill's own.** Provisioner's repo is private, so its
  `scripts/pull_disk_gc.sh` can't be vendored. The worker implements the
  contract's steps 1–8 from
  [#425's contract comment](https://github.com/gregoryfoster/skills/issues/425#issuecomment-6371095613).
  Every check refuses on failure: the pinned manifest digest, refusing an
  index, the config digest, exactly one `COPY disk-gc/ / # buildkit` layer by
  `.history` count, the blob and diff_id digests, the member checks before
  extracting, and the exact file set in MANIFEST. It never installs from
  `:latest`.
- **Exact scripts for the stateful steps** (pull and verify; install, update
  and remove), as `AGENTS.md`'s "match freedom to fragility" asks. Turning it
  on and requesting the monitor stay as instructions, since they are per-host
  judgment calls and a request to another repo.
- **Retire-check tooling is in scope** (Q3 deferred nothing). This is a
  hypothesis: the worker builds what can honestly be mechanised, which at
  least means listing a host's known retire-list units and timers and pairing
  them with the GC's report-only `gc` run. It reports where a by-hand
  checklist is the truthful answer, rather than building a diff that can't
  read an arbitrary script.
- **The pin is in the skill only.** It has one home, which the tests assert,
  and a new GC release is a skill commit.
- **#482's divergences are stated, not resolved.** The GC removes a staged
  newer build and prunes the VSIX cache; it matches Stable only and has no
  Cursor or Windsurf support. Changing any of that is Provisioner's to do,
  and raising it there is a post-merge tail item that needs the owner's
  per-action approval.
- **#390 reads `disk-gc.conf` strictly.** A missing file means gates 1–3 only.
  A malformed or unreadable file is a finding, never a silent pass. A missing
  `alert_at_percent` or `mount` takes the GC's own code defaults in VERSION 2
  (85, `/`), cited from that release.
- **`maintaining-host-disk` isn't read-only for B, by design.** B adds one
  sentence, and only after its gate exists, so the skill describes shipped
  behaviour at every commit.
- **Verification-mode asymmetry.** Cloud workers run as root, so every
  `geteuid() == 0` skip fires, and Linux-only tests run there and skip on
  macOS. The orchestrator's local gate after each merge is the first macOS run
  of the new tests. The #479 pilot reconciled the two by cause: a net 35 more
  skips in the cloud, and 5 failures from a newer shellcheck (#481, still
  open). Re-measure both at launch; don't carry them over.
- **No live pull in the cloud is required.** The tests build fixture layers
  offline and stub the registry, as Provisioner's own tests do. Whether the
  cloud network policy reaches `ghcr.io` is unverified. A live pull is optional
  in the worker's report, and its failure isn't a blocker.

## Runtime note on issue-body decay

Batch B's issue (#390) was read at `85caed2`, and patching-hosts has moved
since then (#393/#418–#420 and others). B's brief re-verifies every file:line
in #390 against the tree at launch (Worker step 5), along with A's one-line
change to `pruning.md`. #425's body was rewritten at this gate, but its
contract is a summary of Provisioner's `image/README.md`. Where the two
disagree, the pulled layer's actual bytes win, and the worker reports the
difference.

## Post-merge tail

| Item | Owner | When |
|---|---|---|
| Local macOS pre-ship gate after each merge, reconciled by cause against the worker's cloud count | orchestrator | each merge |
| Close #425, #482 and #390 with summary comments (`shipping-work`) | orchestrator | each merge |
| First live install with the new skill on a real host. Broker is the candidate: its root was at 90% on 2026-10-24 and `prune_editor_builds.sh` is on the retire list | the host's own session, via its adoption issue | after A |
| Adoption issues in the retire-list repos: wslcb, watcher, observo, usa-wa, power-map and broker, plus a comment on CannObserv/address-validator#326 | orchestrator, **each filing approved separately by the owner** | after A |
| Whether to raise #482's divergences on Provisioner | owner's call | after A |
| #390's first live run: the next monthly patch round, mid-November, on a host with `disk-gc.conf` | that host's patch run | after B |
| Close the run on #485: every held review finding's disposition, and spend per batch | orchestrator | end |

## Deferred items

None (Q3).

## Out of scope

- Changes to the GC itself (its tiers, keep rules and sensor). Those belong to
  Provisioner.
- #335 (the macOS `pgrep -a` in `audit-worktree-zombies.sh`). It matched the
  disk keyword sweep only.
