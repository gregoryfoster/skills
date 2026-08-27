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

## Re-syncing a drifted override

The doctor's warning is advisory in every mode — exit 0 even under
`--check-only`, and nothing is ever auto-merged, because the point of an
override is that upstream text cannot be applied blindly. The re-sync is
manual, and the **direction matters and is easy to get backwards**:

1. Diff your override against the OLD vendor text it was synced from, to
   enumerate the local deltas. (With `synced-from:`, that text is
   `git -C skills-vendor/<repo> show <commit>:skills/<name>/SKILL.md`.)
2. Copy the NEW vendor file over the override:
   `cp skills-vendor/<repo>/skills/<name>/SKILL.md skills/<name>/SKILL.md`
3. Reapply the local deltas from step 1 onto it — **local deltas onto the
   newer upstream text**, never upstream changes onto the old fork, which
   silently discards every release between the two.
4. Restore the override frontmatter: `overrides:`, `override-reason:`, and
   `version:` (or `synced-from:`) bumped to what was just synced.
5. Re-check any real script files (a wrapper still `exec`s a script that
   exists?) and commit.

In the #238 consumer this was six small edits and five minutes — once someone
knew to look, which is what the doctor's warning is for.
