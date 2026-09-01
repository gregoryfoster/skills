#!/usr/bin/env bash
# install-refresh.sh — wire the skills auto-refresh hook into a consumer repo.
#
# The mechanism lives in install-hook.sh, which takes the hook's constants as
# arguments (#200). This file supplies refresh's three and nothing else: the
# hook name, the skill that vendors it, and the note an operator needs after a
# successful install.
#
# WHY THIS PATH STILL EXISTS. It is named, by path, in README.md's consumer
# quickstart, docs/SKILLS.md, managing-skills/SKILL.md, and in the per-repo
# issues filed against cohort repos for #167 — the ones telling operators to
# run this command and trust its exit code. Renaming it would break every one
# of those at once, for no gain, so it stays as a wrapper.
#
# `.skills/doctor.sh`'s repair advice used to be on that list and no longer is:
# since #224 the doctor names install-hook.sh plus the arguments it reads from
# a <hook>.install manifest, so it derives the repair rather than hardcoding
# this path. One fewer caller to break, not one fewer reason to keep the file.
#
# It takes no arguments of its own: --check, --uninstall, --quiet and --help
# all pass straight through to install-hook.sh, which documents them.
set -euo pipefail

# Parameter expansion rather than `dirname`, which is not a builtin — this runs
# in consumer repos, including the jq-less ones install-hook.sh's degraded paths
# exist for, and a wrapper that cannot find its own directory fails before
# anything it wraps can report why. The subshell keeps the consumer's cwd, which
# install-hook.sh reads to find the repo root.
SELF_DIR="${BASH_SOURCE[0]}"
case "$SELF_DIR" in */*) SELF_DIR="${SELF_DIR%/*}" ;; *) SELF_DIR="." ;; esac
SELF_DIR="$(cd -- "$SELF_DIR" && pwd)"

# No --marker: the default is the hook's own basename, which is exactly what
# this installer matched on before install-hook.sh existed. That keeps the
# registered command byte-identical to the one every installed consumer already
# carries — an entry no `is_current` comparison in the cohort has to be told
# about.
# --timeout 120 is refresh's fourth constant (#259). It is the slowest of the
# three hooks a consumer ends up with — one network round trip per vendored
# repo — so under the harness default it is the likeliest to be killed midway,
# and its UTC-day lock then holds that failure until tomorrow. A value already
# in settings.json is preserved rather than overwritten, so this never undoes a
# consumer's own figure. It is duplicated in skills-submodule-update.install
# because the doctor prints the manifest, and
# tests/structural/test_doctor_hook_registration.py is what keeps the two equal.
exec bash "$SELF_DIR/install-hook.sh" \
  --hook skills-submodule-update.sh \
  --skill managing-skills \
  --timeout 120 \
  --label install-refresh.sh \
  --note 'The hook runs at most once per UTC day, on main only, and auto-commits
the pointer bumps. To confirm it ran, check .git/skills-update.log after a
session start on main.' \
  "$@"
