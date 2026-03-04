# Findings Report Format

Use this structure exactly for every architectural review report.

## Report structure

```
## Architectural Review — [scope description]

### Architecture summary
[2–4 sentences describing the current architecture. Shared context for the findings below.]

### What's solid
- [Genuine architectural strength worth preserving]
- ...

### Findings

#### 🔴 Structural problems
1. **[Module/file]** What: ... Why it matters: ... Suggested approach: ...

#### 🟡 Design improvements
2. **[Module/file]** What: ... Why it matters: ... Suggested approach: ...

#### 💭 Observations & opportunities
3. **[Module/file]** What: ... Why it matters: ... Suggested approach: ...

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
- **What:** Precise description with module/file reference
- **Why it matters:** Architectural impact (maintainability? performance? correctness?)
- **Suggested approach:** Concrete refactoring direction — name new modules, describe the split, sketch the pattern
