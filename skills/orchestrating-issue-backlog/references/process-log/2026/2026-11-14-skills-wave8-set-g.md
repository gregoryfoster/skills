## Session 2026-11-14 — gregoryfoster/skills (epic #516, Wave 8 set G: the gate's own tests)

The eighth of Wave 8's local orchestrators. The brief and its update were comments on #554, and Steps 1–9 were skipped. Base `8f2dbfae`, 10,435 / 475.
- **Chains:** N (#554, nested pytest runs) and F (#616, #617).
- **Workers:** three, all in `batch/g`: N (the scrub), P (a loose end of #554) and F.
- **Review:** CR 2038–2040, one round: two fixes and a stet.
- **Integration gate:** 10,441 / 475 / 0, which is the base plus N's 5 and F's 1.

## Lessons

### 1. Measure the enumeration, don't grep it
Part 1 asked for every test that starts a real pytest. #554 named six files.
- **The method:** one full gate ran with a `sitecustomize` on `PYTHONPATH`. It logged every process started as pytest, plus the outer test that started it, read from the inherited `PYTEST_CURRENT_TEST`.
- **The result:** four of #554's six files start no pytest (ruff, a bash script, `--check` only, a stub venv). Two files nobody had named do.
- **The probe's blind spot:** a child whose environment replaces `PYTHONPATH`, or drops `PYTEST_CURRENT_TEST`. A grep of those sites covered it. The worker's static guard later found exactly the seven.

### 2. "Reproduce before changing" saved a wrong fix
Set H reported xdist refusing `test_patching_hosts_process_log.py` because its "ids collected differently". The brief proposed deterministic ids. P found the ids already deterministic and unique, and the refusal didn't reproduce in 12 runs. It does reproduce on demand when an entry is written while workers are collecting: the diff is an id some workers have and others don't. The proposed fix would have changed nothing. P committed nothing, and that was the right outcome. Run Linux checks on a copy of a worktree, not a bind mount of one that someone may be writing to.

### 3. The worker's evidence beat both the brief's options
The brief offered `--basetemp` or `TMPDIR` for the temp root, and a `PYTEST_ADDOPTS` scrub.
- **The temp root:** N used `PYTEST_DEBUG_TEMPROOT`. It reaches a pytest that a script starts, which `--basetemp` can't, and it moves no other temp file, which `TMPDIR` would.
- **The scrub:** N dropped every `PYTEST_*`, because it measured an inherited `PYTEST_XDIST_WORKER` making a child write over an outer worker's trace file.

The briefed scrub would have shipped that bug. Brief the failure modes, and leave the mechanism open.

### 4. Review a batch's new tests against the batch's own lesson
#616 removed a test's dependence on one git version's wording. In the same batch, #617's new test asserted git's wording (CR 2039). It now compares against the stderr git printed for the same command.

### 5. Measuring a gate without disturbing the gate
- **Bypass the script.** Each full run of `structural-tests.sh` writes back to the shared git dir: a line in `gate-select.log`, which #537's measurement reads, and a rebuilt selection map. So the six before/after runs called pytest directly with the gate's own arguments.
- **Load a plugin with `-p`, not `PYTEST_ADDOPTS`.** At the base, nested runs inherit `PYTEST_ADDOPTS`, and a child that replaces `PYTHONPATH` can't import the plugin.
- **Alternate base and merged runs.** That controls for host drift. The file went from 15.1–19.6 s to 9.3–9.8 s, and its spread from 4.5 s to 0.5 s.

### 6. Schedule deliberate load alone
F's #617 load phase drove host load to 263 while the other two workers ran their gates. P's gate timed out in shellcheck, and N's gate took 15 minutes. A load reproduction is an experiment on a shared host: run it with nothing else running.

### 7. A docs fix inside a doc at its budget
`docs/STYLE.md` was at 9,829 of 10,000 tokens. The first draft of CR 2038 read 10,380 by estimate. A cut that read 9,996 by estimate read 10,020 exact. The final text is 9,976 exact. Take the exact reading before committing to a doc that close to its budget.
