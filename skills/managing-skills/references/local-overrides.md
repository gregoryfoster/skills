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
doctor's drift warning is a comparison of this field against the vendor copy's
`version:`, and the two readings diverge as soon as someone edits an override
after syncing — which is an override's whole job.

```yaml
metadata:
  version: "1.4"
  overrides: <owner>-<repo>/shipping-work-python-fastapi
  override-reason: "Sources /etc/consumer/.env before delegating"
```

`overrides:` names `<submodule-dir-under-skills-vendor>/<skill-name>`; it is
what the doctor uses to find the vendor copy.

## `synced-from:` — the fallback for unversioned vendors

Some upstreams (obra-superpowers, for one) ship no `version:` at all, so an
override of their skills has nothing to compare. Record the vendor commit last
synced from in a sibling key:

```yaml
metadata:
  overrides: obra-superpowers/brainstorming
  synced-from: "obra-superpowers v6.3.0 (b36e082)"
```

The doctor reads the commit inside the parentheses and runs a diff between it
and the submodule's `HEAD`, scoped to the skill's path — so a submodule bump
that touches other skills stays silent, and only a change to the overridden
skill itself warns. An override it cannot assess at all (no `version:` against
a versioned vendor, no `synced-from:` against an unversioned one, a commit not
in the vendor's history) is warned about too, never silently skipped — an
override nothing can compare is the same failure as not detecting drift at all.

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
   enumerate the local deltas. (With `synced-from:`, that text is
   `git -C skills-vendor/<repo> show <commit>:skills/<name>/SKILL.md`.)
2. Put the override where step 5 can still read it, then copy the NEW vendor
   file over it — `cp skills/<name>/SKILL.md /tmp/<name>.orig` and
   `cp skills-vendor/<repo>/skills/<name>/SKILL.md skills/<name>/SKILL.md`.
3. Reapply the local deltas from step 1 onto it — **local deltas onto the
   newer upstream text**, never upstream changes onto the old fork, which
   silently discards every release between the two.
4. Restore the override frontmatter: `overrides:`, `override-reason:`, and
   `version:` (or `synced-from:`) bumped to what was just synced.
5. **Account for every removed line.** Diff the ORIGINAL override against the
   merged result — `diff /tmp/<name>.orig skills/<name>/SKILL.md` — and
   classify every removed line as superseded by upstream, deliberately
   dropped, or reworded with its substance intact elsewhere. A line fitting
   none of those is a local delta the merge lost.
6. Re-check any real script files (a wrapper still `exec`s a script that
   exists?) and commit.

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
