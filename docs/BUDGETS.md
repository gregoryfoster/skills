# Budgets — the SKILL.md ratchet and its two readings

How a token budget is measured, anchored and enforced in this repo. The rules
that *state* the budgets live inline in [AGENTS.md](../AGENTS.md) under
`## Self-budget`; this file carries the mechanism behind them — what each
reading means, when they disagree, and how to anchor a file before curating
against a squeeze.

## The SKILL.md self-budget, and how its two readings are reconciled

It binds **both** readings — the offline estimate pre-commit sees, and
`count_tokens` under `SKILL_BUDGET_EXACT=1`. On SKILL.md files the estimate is
observed running 13% low to 7% high, and `POLICY_ESTIMATE_BAND` permits 15%
either way — that band edge, not the observed figure, is what the warning below
computes a worst case from. So neither reading alone is the contract — and only
the estimate is always on, which let
three ratchets be breached past a green suite. Two things close that
([#217](https://github.com/gregoryfoster/skills/issues/217)): every pre-commit
run now **warns** about each skill whose worst permissible exact count exceeds
its ratchet (a warning, not a failure), and
[.github/workflows/skill-budget-exact.yml](../.github/workflows/skill-budget-exact.yml)
runs the exact pass weekly as the gate that does fail. On the commit path the
exact pass stays opt-in, not opportunistic: it costs ~20s and one API call per
surface, and an unusable key must never be able to block a commit.

**What each number means.** The estimate is bytes over
`.skills/context-token-ratio`, a repo-wide figure the weekly cadence refits,
unless the file is **anchored**: a row in `.skills/context-token-counts` prices it
from its own last exact count until it drifts past `CTX_DRIFT_PCT` of that size
and silently reverts to the ratio. Priced from the ratio, a SKILL.md reads
**high** as well as low: `orchestrating-issue-backlog` was curated to fit 34
tokens of apparent headroom that `count_tokens` put at 675
([#294](https://github.com/gregoryfoster/skills/issues/294)). So **anchor before
curating against a squeeze**, and trim only if the exact count is still tight.

Every SKILL.md is anchored by a refresh committed by hand, after adding or
curating a skill or when a green run asks:

```bash
bash skills/curating-context/scripts/measure-context.sh --check-credential &&
for s in skills/*/SKILL.md; do bash skills/curating-context/scripts/measure-context.sh --exact --anchor --file "$s" --docs-dir "${s%/SKILL.md}/references" >/dev/null || break; done
```

`--anchor` writes the per-file rows and never the ratio, which `--calibrate` would
refit to each skill in turn ([#263](https://github.com/gregoryfoster/skills/issues/263));
rows merge per path under `merge=context-counts`
([#237](https://github.com/gregoryfoster/skills/issues/237)). The weekly exact job
does not run it: it holds `contents: read`, and a change to a tracked file wants
a reviewer. Each skill's `references/` is anchored too. A green run asks for it
by warning **ANCHORS** (a SKILL.md with no row, or any lapsed row) and **ESTIMATE
SQUEEZE** (a skill near its ratchet on a ratio-priced estimate) — never failing,
since pre-commit holds no key.
