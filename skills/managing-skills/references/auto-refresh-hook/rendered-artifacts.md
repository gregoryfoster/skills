# A bump that leaves a rendered file behind ([#647](https://github.com/gregoryfoster/skills/issues/647))

Read this when the hook says a bump left `.github/workflows/context-cadence.yml` behind, or to see when it checks. The hook's other mechanics are in [the parent reference](../auto-refresh-hook.md).

## Why it checks

Some skills render a file once and the consumer commits it. `curating-context`'s `install-cadence.sh` renders the weekly cadence workflow this way. When a bump moves the template behind that file, the committed file stays as it was rendered until someone re-runs the renderer. On one cohort host the workflow went through many daily bumps unchanged and kept an `actions/checkout@v5` pin after the template moved to `@v7`. After the host set `.skills/merge_mode` to `pr`, the workflow still pushed to the default branch. `install-cadence.sh --check` would have reported this, but nothing ran it.

## What it runs, and what counts

After a bump that moves the vendored tree, the hook runs each installed renderer's `--check` against the new tree. "Installed" means the rendered file exists. Today there is one renderer, `install-cadence.sh`, for `.github/workflows/context-cadence.yml`. The hook looks for it where the workflow looks for its own scripts: `scripts/`, `.claude/skills/curating-context/scripts/`, then `skills/curating-context/scripts/`.

- **The signal is `--check`'s `re-render: behind` line.** That line says a re-render, keeping the installed schedule and ledger, would change the file. It covers a template-only change and a merge mode the file wasn't rendered for alike.
- **`--check`'s exit 3 is not the signal.** A clone without the per-clone merge drivers is exit 3 on every check, and that isn't something a bump caused. Exit 0 and 3 are both read for the line. Any other exit, or a renderer the hook can't find, is a log line.
- **Nothing is re-rendered.** A re-render is a change a human reviews, and in `pr` mode it belongs after the merge.

## Where it is reported

- **`.git/skills-update.log`:** one `renders:` line for each check. A drift or a failure also logs `--check`'s whole output.
- **stderr, once, from the run whose bump caused it:**
  - **Direct mode:** after the bump commit is pushed, or held unpushed, and only while it is still `HEAD`. A push refused and rolled back leaves no new template to be behind, so nothing is reported. The phase is logged as `renders`.
  - **`pr` mode:** from the run that pushes the bump to `skills/submodule-refresh`, or opens its pull request over a bump an earlier run pushed. A later run that finds the same bump already proposed says nothing.
- **The pull request's body,** in `pr` mode, when this run opens the PR. The hook never edits an open PR's body, because that body is the reviewer's. So a later bump's drift reaches stderr and the log only.

## In `pr` mode, re-render after the merge

The check runs before the content goes back to main's pointer, while the bumped tree is the one checked out. After that the checkout holds main's template again, so a re-render now would write the old one. The report says to re-render once the pull request merges and main is pulled.

`shipping-work`'s doc-check gives the same advice for a branch that changes `.skills/merge_mode`. The renderer reads the knob from the primary checkout, so a re-render on that branch renders the old mode.

## Known limits

- **One renderer, at its default path.** A workflow installed with `--file` elsewhere isn't checked.
- **The check isn't separately bounded.** It is one `--check` plus one `--print` (about a second), inside the hook's 120 s timeout.
