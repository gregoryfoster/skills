# Re-run on an existing project (audit/repair)

Read this before re-running `init-socraticode` on a project that already has
SocratiCode. A first install does not need it.

## The re-run *is* the audit

Running this skill on a project that already has SocratiCode is safe, because
every file edit is idempotent:

| Phase | What a re-run does |
|---|---|
| 1–2 | read-only when already satisfied |
| 3 | policy block and `docs/SOCRATICODE.md` each replace between their own markers, preserving what follows `END`; both hook merges dedupe |
| 4 | migrates a legacy top-level-array manifest in place, and re-validates every artifact path |
| 5 | re-indexes only if the index is missing or stale |
| 6 | re-verifies the completion signals, and re-measures graph yield |

Because Phase 6 re-measures yield, a repo installed before the yield gate
existed gets its degraded policy (variant B) the first time it is audited.

## What a re-run repairs

The common drift found across the cohort
([#65](https://github.com/gregoryfoster/skills/issues/65)):

- a manifest with **no policy block or prefetch hook** (observo);
- hook docs that drifted from `settings.json` (archiver);
- a manifest the server silently rejected, which has been reporting `artifacts
  0/0` as if healthy (gotcha K) — a re-run is the only thing that catches it.

## One thing a re-run must not do quietly

**It must not delete repo-authored content.** Two files, same failure, same
rescue.

On the unmarked-section branch, Phase 3 replaces a whole `## Code Exploration
Policy` span, and a repo that has been running for a while has usually grown its
own prose in there. Rescue anything the template does not itself carry to a
`## Code Exploration Notes (repo-specific)` section outside the markers, and
name every moved block in the report. The first audit re-run is exactly when
this bites and exactly when nobody is watching for it
([#115](https://github.com/gregoryfoster/skills/issues/115)).

`docs/SOCRATICODE.md` has the same shape with a larger blast radius — a whole
file rather than one section — and until
[#210](https://github.com/gregoryfoster/skills/issues/210) it had no markers at
all, so *every* repo installed before then is on the unmarked branch. On
`wslcb-licensing-tracker` three blocks would have gone: the repo's measured
graph yield with its "treat graph answers as a lower bound" caveat, its real
context-artifact list, and why its `.socraticodeignore` deliberately keeps
`skills/`. None of the three belongs in `AGENTS.md` — all are read-once detail,
and the policy section is the one thing `curating-context` will not trim. Rescue
them under a `## Repo-specific notes` heading below the
`<!-- END socraticode-doc -->` marker, and name them in the report too. The
`low`-verdict path is the sharpest
case: variant B tells the author to substitute real measured numbers, which is
repo-authored content the template itself asked for.
