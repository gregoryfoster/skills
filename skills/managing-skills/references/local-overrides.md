# Local overrides: shape, versioning, and re-sync

`SKILL.md` covers creating, updating, and removing an override; this covers the
mechanics that keep one from quietly falling behind its vendor — the failure
[#238](https://github.com/gregoryfoster/skills/issues/238) documents, where an
override's stale `SKILL.md` reintroduced
[#63](https://github.com/gregoryfoster/skills/issues/63) in a consumer sixteen
months after it was fixed upstream, because the file carrying the fix was the
fork.

## The per-script symlink shape

An override needs real files only for what it actually changes; everything else
symlinks into the submodule per script and tracks upstream for free:

```
skills/shipping-work-python-fastapi/
├── SKILL.md              real file (carries the local deltas)
└── scripts/
    ├── pre-ship.sh       real file (a #105-style wrapper that execs upstream)
    ├── check-status.sh   -> ../../../skills-vendor/<owner>-<repo>/skills/shipping-work-python-fastapi/scripts/check-status.sh
    ├── close-issue.sh    -> symlink, likewise
    └── ...
```

This is strictly better than forking the whole directory: it is the smallest
possible drift surface, and in the consumer that motivated #238 it kept five of
six scripts current through every vendor release while the one forked file
drifted. The pattern's own new risk is covered by the doctor as a prerequisite
of this recommendation: `scan_broken()` walks `skills/*/scripts/*` symlinks
too, so when upstream renames or deletes a script the stranded link is reported
as damage instead of surfacing as `No such file or directory` mid-run. (The
top-level scan cannot see it — an initialized, healthy submodule resolves every
top-level symlink — and `scan_uninit` has nothing to say either; the nested
scan is the only detector for this state.)

## What `version:` means in an override

`version:` in an override's frontmatter records **the vendor version last
synced from** — not a version of the local file. Bump it on every re-sync, even
when the local deltas are unchanged. The distinction is load-bearing: the
doctor's drift warning compares this field against the vendor copy's
`version:`, and the two readings diverge as soon as someone edits an override
after syncing — which is an override's whole job.

## Record `synced-from:` too, on every override

`version:` is a comparand only while the vendor keeps bumping it, and vendors
do not. Measured across this repo at the time
[#286](https://github.com/gregoryfoster/skills/issues/286) was filed, **every
versioned `SKILL.md` but one had changed since its last bump** — 34 commits for
`orchestrating-issue-backlog`, 20 for `using-git-worktrees`, 10 for
`shipping-work-python-fastapi`. Many of those changes did not warrant a bump;
the point is narrower. `version:` does not track `SKILL.md` content, so a check
keyed on it cannot see a content change, and the skills at the top of that list
are the ones consumers actually override.

So write **both** keys, whatever the vendor ships:

```yaml
metadata:
  version: "1.4"
  overrides: <owner>-<repo>/shipping-work-python-fastapi
  override-reason: "Sources /etc/consumer/.env before delegating"
  synced-from: "<owner>-<repo> 1.4 (662de71)"
```

`overrides:` names `<submodule-dir-under-skills-vendor>/<skill-name>`; it is
what the doctor uses to find the vendor copy. `synced-from:` is
`"<repo> <tag-or-version> (<commit>)"` — the doctor reads the commit inside the
parentheses and ignores the rest, which is there for people.

An override that omits `synced-from:` is not warned about (for a versioned
vendor the stamps still compare), so nothing breaks by leaving it out. It just
gives up the only comparand that can see an un-bumped change.

## The two comparisons, and why both run

The doctor runs both and reports if **either** fires:

| Comparison | Comparands | Catches |
|---|---|---|
| Version stamps | override `version:` vs vendor `version:` | an override left behind across a release the vendor bumped |
| Recorded commit | `synced-from:` commit vs vendor `HEAD` | a vendor change at **any** version, bumped or not |

The commit comparison used to be a *fallback*, reached only when the vendor
shipped no `version:` at all. That left a third case neither comparand covered:
**the vendor changes and `version:` does not.** CannObserv/archiver's
`shipping-work-python-fastapi` override recorded `synced-from: 662de71` against
a vendor also at `1.4`; four separate `SKILL.md` changes had landed at that same
`1.4` since, and the doctor ran clean — correctly, by the contract it had. Its
scripts were symlinks, so they already had the new behaviour; only the
instructions fell behind, and the gap was found by reading a report rather than
by the doctor. The comparand that would have caught it was already in the
frontmatter, one `git diff` away.

This is not a diff of the override against the vendor. That comparison is
useless here — an override exists to differ, so divergence is the *expected*
state and a warning on it says nothing. This compares **the vendor with
itself**: the commit the override synced from against the vendor now. The
override's own deltas never enter it, so it cannot fire on expected divergence.

When the stamps match and the commit diff fires anyway, the warning **says
so**. A reader told an override has fallen behind checks `version:` first, and
finding it equal on both sides would reasonably conclude the doctor is wrong.

### Which side moved

The commit diff is symmetric: it reports a difference whether the recorded
commit is *behind* the submodule's `HEAD` or *ahead* of it, and the two call for
opposite remedies. Ahead is a real state — the one #286's advice produces when
it is followed halfway: re-sync the override from upstream's newest text, stamp
that commit, leave the pointer where it was. CannObserv/archiver's override did
exactly that, recording `178ec64` while its pointer sat 26 commits back at
`980a0d1`, and the drift report sent its operator to reapply local deltas onto
*older* text ([#290](https://github.com/gregoryfoster/skills/issues/290)).

So the doctor reads the history before it words the finding — for a versioned
vendor and an unversioned one alike:

| The recorded commit is… | Finding | Remedy |
|---|---|---|
| an ancestor of `HEAD` | the override has fallen behind | re-sync it ([below](#re-syncing-a-drifted-override)) |
| a descendant of `HEAD` | the **pointer** is behind the override | bump that one submodule — `git -C skills-vendor/<repo> merge --ff-only <commit>`, then `git add` and commit it — and leave the override alone |
| neither | cannot be assessed | none: a rewritten vendor history or a fork, so no direction can be read |

The pointer finding prints that command under each entry. `--ff-only` never
moves a pointer backwards, so where two overrides of one vendor record
different commits the commands can run in any order and land on the newer. It
also replaces the version comparison for that override rather than joining it:
a pointer lagging a bumped release disagrees on the stamps too, and printing
drift beside it would print both opposite remedies at once.

A submodule [held by a pin](pinning-submodules.md) is the exception. The bump
alone ends the hold, and the auto-refresh hook then reports pin drift at every
session, so the entry says it is pinned — reading `$SKILLS_PIN_FILE`, then
`.skills/skills-pin`, as the hook does — and offers the two repairs that keep
pin and pointer agreeing: re-pin the line to the recorded commit before the
bump, or keep the hold and re-sync the override to the pinned commit instead.

The history needs the recorded commit **on disk**. Where it is not — not
fetched yet, or no `synced-from:` at all — the version stamps are the only
verdict, and they decide by direction, as numbers (1.14 is newer than 1.4):
only an override `version:` **older** than the vendor's is drift. A newer one
is the pointer-lag state seen without the history to prove it, so it is
reported as un-assessable with that reason, never as drift. Unfetched, it read
"last synced at version 1.5, vendor now at version 1.4" with the re-sync remedy
until a fetch let the history speak.

### What the commit diff is scoped to

The override's **own real files** — its `SKILL.md`, plus any script or
reference it keeps as a regular file — named individually in the report, so the
finding is a work order and not just a fact.

Whole-skill-directory scope was a false-positive generator. In the case above it
also reported `scripts/doc-check.sh`, a file the override follows through a
symlink: upstream changed it, the consumer already had the change, and there was
nothing to re-sync. A symlink cannot fall behind by construction, and a regular
file is the only thing that can. That cuts both ways — a **forked** script keeps
its signal here, and this is the only detector it has, because the doctor's
silent-fork check skips a declared override wholesale (its drift is this
check's business).

### When it cannot be assessed

An override the doctor cannot compare is warned about, never silently skipped —
an override nothing can compare is the same failure as not detecting drift at
all. Eight ways to get there:

1. **No vendor copy on disk** at all — an uninitialized submodule, or the skill
   moved upstream. This is the likeliest of the eight and the reason the report
   batches: it makes *every* override unassessable at once.
2. No `version:` in the override, against a versioned vendor.
3. Neither key, against an unversioned vendor.
4. A `synced-from:` with no `(commit)` in it.
5. A recorded commit absent from the vendor's local history — **not fetched
   yet**: `git -C skills-vendor/<repo> fetch`, then re-run. Otherwise a shallow
   clone (`fetch --unshallow`) or a typo.
6. A recorded commit whose history has diverged from the vendor's `HEAD` —
   neither contains the other — so [which side moved](#which-side-moved)
   cannot be read.
7. The `git diff`, or the ancestry check after it, failing.
8. With no fetched commit to decide, a `version:` **newer** than the vendor's,
   or stamps that are not both dotted numbers.

Causes 4–7 are reported **even when the version stamps match and compare
cleanly**: a comparand the operator wrote that quietly does not apply is its own
defect, and matching stamps are no longer the end of the enquiry. Where 5 and 8
meet, they are one entry.

## When an override is *supposed* to omit something

Everything above is about an override falling behind. The opposite case is an
override that omits upstream text **on purpose**, and until
[#265](https://github.com/gregoryfoster/skills/issues/265) the doctor could not
tell the two apart.

A vendor marks the fragments it considers non-optional with
`<!-- skill:required id=<slug> -->` (see
[docs/CONVENTIONS.md](https://github.com/gregoryfoster/skills/blob/main/docs/CONVENTIONS.md)),
and the doctor warns when an override does not carry one. Sometimes it cannot:
`CannObserv/cli` overrides `using-git-worktrees` and ships **no `scripts/`
directory at all** — the project fixes the worktree root at
`.worktrees/<branch-slug>/` and enforces it from its own script — so the
`<SKILL_SCRIPTS>` resolution loop resolves nothing there. Neither offered remedy
fit. Pasting the fragment back puts a runnable-looking fence into a skill file
where running it fails, which is #63 arriving through the remedy; and "drop the
override in favour of per-file symlinks" has nothing to apply to when the whole
delta *is* `SKILL.md`, the one file no symlink can reach.

Declare it instead, in the frontmatter that already explains the override:

```yaml
metadata:
  overrides: <owner>-<repo>/using-git-worktrees
  override-reason: "cli fixes the worktree root and enforces it locally"
  omits-required: "skill-scripts: cli ships none of the vendor's worktree
    scripts, so <SKILL_SCRIPTS> resolution resolves nothing here"
```

`"<id>[, <id>…]: <why>"` — **ids first**, because the doctor reads one
frontmatter line and a reason worth writing gets folded across two.

Three properties worth knowing before relying on it:

- **A declaration names one fragment, not the check.** A fragment armed in a
  later release carries a different id and still reports, which is what stops
  this from becoming a blanket mute that quietly rots.
- **A declaration that excuses nothing is reported.** A renamed id upstream, or
  a fragment the override has since re-synced, leaves a line that reads to the
  next reader as a decision taken while covering nothing. Correct the id or drop
  the line.
- **An un-idded fragment cannot be declared.** If a vendor arms a block without
  an `id=`, the only honest move is an upstream issue asking for one — which is
  the case #265 opened.

One report in this family is not about your file at all: a marker written in any
other form — `id=` with nothing after it, `id=two words`, a stray attribute —
arms **nothing**, so the vendor's claim is compared against no override. The
doctor names the vendor file and line, because that is where the repair belongs;
a consumer cannot fix a claim it does not own. A marker inside a fenced example
is an example, not a claim, and is neither armed nor accused.

## A project's own `scripts/` is not the skill's

The companion check reports a fenced `bash` invocation of a bare `scripts/…`
path in an override, because the agent's cwd is the project root and a skill's
`scripts/` ships inside the skill (#63). But `scripts/` at the project root is
also where a consumer keeps its **own** scripts, and the check read both as the
skill's — flagging `CannObserv/cli`'s correct `scripts/setup-worktree.sh` step
with a remedy (`bash "<SKILL_SCRIPTS>/setup-worktree.sh"`) that has no correct
substitution to make.

Since [#266](https://github.com/gregoryfoster/skills/issues/266) the doctor
skips the report when the named path **exists under the project root**. That is
precise in both directions — a skill's `scripts/X.sh` does not exist there, so
#63's shape still reports — and it covers the copy `using-git-worktrees` already
blesses ("a project-local `scripts/` copy wins if one exists"). Nothing to
configure, and nothing to write differently: keep the instruction as it reads
best, and let the file on disk settle it. The check is state-dependent by
design — delete the project script later and the line starts reporting, because
the instruction really did break.

## Re-syncing a drifted override

The doctor's warning is advisory in every mode — exit 0 even under
`--check-only`, and nothing is ever auto-merged, because the point of an
override is that upstream text cannot be applied blindly. The re-sync is
manual, and the **direction matters and is easy to get backwards**:

1. Diff your override against the OLD vendor text it was synced from, to
   enumerate the local deltas. `synced-from:` names that text exactly —
   `git -C skills-vendor/<repo> show <commit>:skills/<name>/SKILL.md` — which
   is the second reason to keep the key even when the vendor is versioned.
2. Put the override where step 5 can still read it, then copy the NEW vendor
   file over it — `cp skills/<name>/SKILL.md /tmp/<name>.orig` and
   `cp skills-vendor/<repo>/skills/<name>/SKILL.md skills/<name>/SKILL.md`.
3. Reapply the local deltas from step 1 onto it — **local deltas onto the
   newer upstream text**, never upstream changes onto the old fork, which
   silently discards every release between the two.
4. Restore the override frontmatter: `overrides:`, `override-reason:`, and
   **both** `version:` and `synced-from:` bumped to what was just synced. The
   commit for `synced-from:` is the submodule's `HEAD`, which is the text you
   just merged from:
   `git -C skills-vendor/<repo> rev-parse --short HEAD`. Leaving it at the old
   commit re-reports the drift you just paid down; omitting it gives up the
   comparand that catches the next un-bumped change. If you merged from a
   newer commit than the checkout — `origin/main`, say — bump the pointer to
   it in the same commit, or the doctor reports
   [the pointer lagging](#which-side-moved) instead.
5. **Account for every removed line.** Diff the ORIGINAL override against the
   merged result: `diff /tmp/<name>.orig skills/<name>/SKILL.md`. Classify
   every removed line (the `<` side) as superseded by upstream, deliberately
   dropped, or reworded with its substance intact elsewhere. A line fitting
   none of those is a local delta the merge lost. Only `SKILL.md` is named
   above: a forked reference doc or script loses a line the same way, so run
   steps 2 and 5 for each of those the override carries — the accounting
   needs a copy taken before the merge, which is what step 2 is for.
6. Re-check any real script files (a wrapper still `exec`s a script that
   exists?), delete the step 2 copy, and commit.

Step 5 is not step 1's diff run again. Step 1 asks what the override *added*
to the old vendor text; step 5 asks what the merge *took away*, and only the
second question can catch a dropped convention. Verifying by grepping the
merged file for the strings you expected — upstream's new material present,
local conventions present, deliberate omissions absent — is presence-only: it
asks "is what I expect here?", never "what did I take out?", so it passes green
over a delta that is gone. That is
[#267](https://github.com/gregoryfoster/skills/issues/267), where a re-sync's
own verification missed a line and the diff-the-original pass found it.

Step 2's copy is what makes step 5 trustworthy. Diffing against `HEAD`
instead — `git diff HEAD -- skills/<name>/SKILL.md` — is the same diff *only*
when the tree was clean at step 1 and nothing has been committed since, and
both conditions fail quietly: uncommitted edits to the override are destroyed
by step 2's `cp`, and a re-sync committed in stages leaves `HEAD` holding the
vendor text, which turns step 5 into step 1 inverted — the very conflation
this section warns about — and it looks clean.

Judge per **substance**, not per line — most removed lines are reflowed
prose, and a per-line reading drowns in that noise. The miss to look for is a
*substitution*: #267's override told an agent "use `.worktrees/` as the local
directory (verify it is gitignored first)", and the reapplied text carried a
different, equally true worktree line in its place. Both lines were correct,
but one replaced the other instead of joining it, and the re-synced skill
silently stopped saying where worktrees go.

In the #238 consumer this was six small edits and five minutes — once someone
knew to look, which is what the doctor's warning is for.
