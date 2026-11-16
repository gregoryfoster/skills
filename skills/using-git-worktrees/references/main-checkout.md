# Finding the main checkout

Phase 4 merges in the main checkout, destroy runs from it, and a worktree
made without `worktree-create.sh` links its `.venv`. The first row of `git
worktree list` is not always that checkout
([#614](https://github.com/gregoryfoster/skills/issues/614)), so ask git, as
`shipping-work`'s post-merge pass does:

1. **`git -C <row> rev-parse --show-toplevel`,** `<row>` being the path on
   the first row of `git worktree list`. That holds for a plain primary and
   for a submodule, whose first row is its git dir. It names the main
   checkout.
2. **"must be run in a work tree":** the row has no work tree.
   - **Marked `(bare)`:** a bare repository. The main checkout is the
     linked worktree that holds the default branch, the row ending
     `[<default>]`. If no worktree holds it, ask which checkout is meant.
   - **Unmarked:** the store of a primary made with `git init
     --separate-git-dir`. Only that primary knows its work tree: ask where
     it is.
3. **Any other error from git,** such as "dubious ownership," is a refusal,
   not a layout: stop and report it.

One layout answers wrong at step 1: a `--separate-git-dir` store whose path
ends in `/.git` is listed as the directory above it, which git takes for a
work tree. From a linked worktree nothing tells the two apart, so if the
path it names isn't your checkout, ask where the primary is.

## Linking a `.venv` by hand

A worktree that something else made, such as the Agent tool's `isolation:
"worktree"`, never ran `worktree-create.sh`. Link the main checkout's
`.venv` before the first test run, unless that checkout's
`.skills/worktree_venv` says `none`:

```bash
main=$(git -C "$(git worktree list --porcelain | sed -n '1s/^worktree //p')" rev-parse --show-toplevel) &&
  { grep -qsxE '[[:space:]]*none[[:space:]]*' "$main/.skills/worktree_venv" || ln -s "$main/.venv" .venv; }
```

Where `$main` fails, step 2 applies: link the `.venv` of the checkout it
names, by hand. Link, don't re-create: a freshly resolved environment is a
different one, which can collect fewer tests and still report green.
