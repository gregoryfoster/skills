# `.claude/` settings and hooks (Phase 8)

Literal commands and file contents for the `init-project-fastapi` skill's Phase 8. The rule this shape encodes — that the submodule-refresh hook is a script file rather than an inline JSON one-liner — stays in `SKILL.md`.

## Install the hook script

The submodule-refresh hook ships as a **script file**, not an inline JSON one-liner — the script (from `managing-skills`) is lock-gated once per UTC day, log-bounded, auto-commits **only on `main`** (the old inline form happily committed submodule bumps onto feature branches), and opportunistically re-installs `.skills/doctor.sh` each session:

```bash
mkdir -p .claude/hooks
cp "<SKILL_DIR>/../managing-skills/scripts/skills-submodule-update.sh" .claude/hooks/
chmod +x .claude/hooks/skills-submodule-update.sh
```

## The settings file

**`.claude/settings.json`**

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          { "type": "command", "command": "bash \"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/skills-submodule-update.sh\"" }
        ]
      }
    ]
  },
  "permissions": {
    "allow": [
      "Read(/home/exedev/.claude/projects/**)"
    ]
  }
}
```
