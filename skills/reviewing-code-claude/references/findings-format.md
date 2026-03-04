# Findings Report Format

Use this structure exactly for every code review report.

## Report structure

```
## Code & Documentation Review — [scope description]

### What's solid
- [Genuine positive, not filler]
- ...

### Findings

#### 🔴 Bugs
1. **[File:line]** What: ... Why it matters: ... Suggested fix: ...

#### 🟡 Issues to fix
2. **[File:line]** What: ... Why it matters: ... Suggested fix: ...

#### 💭 Minor / observations
3. **[File:line]** What: ... Why it matters: ... Suggested fix: ...

### Summary
[1–2 sentences.]
```

## Numbering rules

- Numbers are **globally sequential** across the entire report — never reset between severity groups
- Top-level items: `1.`, `2.`, `3.`
- Sub-items under one finding: `2a.`, `2b.`
- Second review rounds continue from where the last round ended

## Per-finding format

Each finding must include:
- **What:** Precise description with file/line reference
- **Why it matters:** Impact (bug? style? future maintenance?)
- **Suggested fix:** Concrete, not vague. Include code snippets when they clarify.

## Summary

1–2 sentences covering:
- Overall assessment
- Highest-priority items to address first
