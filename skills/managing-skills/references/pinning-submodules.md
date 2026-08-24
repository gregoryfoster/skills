# Holding one submodule at a commit

Use this when a repo must stay on a specific vendored version — an experiment's
control arm, a known-good release pending a breaking change — while its sibling
submodules keep refreshing. Uninstalling the auto-refresh hook also works, but
it is blunt: it stops every other submodule's refresh and the `.skills/doctor.sh`
self-heal too.

Write `.skills/skills-pin`, one `<submodule-path> <commit-ish>` per line. Blank
lines and `#` comments are ignored:

```
# held for the curating-context cohort experiment (wave A control arm)
skills-vendor/gregoryfoster-skills 3fc7b71
```

Commit it. The file is deliberately committed rather than an env var or a
settings key: a hold has to survive across sessions and machines, and be
greppable and reviewable by whoever inherits it.

What the hook does with it:

- Pinned paths are excluded from the submodule update **and** from the
  auto-commit. Excluding only the update is not enough — staging
  `skills-vendor/` wholesale would commit a pinned submodule whose checkout had
  already drifted, ending the hold the update step just honoured.
- Every honoured pin is logged by name in `.git/skills-update.log`, so a hold
  that outlived its reason is visible rather than silent.
- A pin naming a submodule git has no record of, or a line that is not
  `<path> <commit-ish>`, **refuses the whole refresh for that run** and reports
  to stderr. A typo'd path leaves the intended submodule unpinned, which is the
  exact silent bump the pin was written to stop; moving nothing is the only
  safe response.
- If the recorded gitlink is not the pinned commit — the pin was written after
  the pointer had already moved — the hook reports **drift** and still holds the
  pointer still. It will not rewrite the pointer back; reset it by hand and
  commit.

For a one-off hold without committing a file, point `SKILLS_PIN_FILE` at another
path. Resolution is the usual three steps: `$SKILLS_PIN_FILE`, then
`.skills/skills-pin`, then no pins.

`.skills/doctor.sh` needs no pin awareness, but it does not substitute for one:
its `--init --recursive` restores the *recorded* pointer, so it can never move a
submodule past a pin — and equally can never restore a pointer that was already
committed past one.
