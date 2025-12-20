# CodeCanvas Usage Guide (for Agents)

CodeCanvas helps you analyze code before changing it. It shows what functions call what, and tracks your reasoning as you work.

## Quick Start

```
canvas(action="init", repo_path=".")     # Parse codebase, see architecture
canvas(action="impact", symbol="foo")    # See blast radius before editing foo
canvas(action="claim", text="...", kind="hypothesis")  # Record your analysis
canvas(action="decide", text="...", kind="plan")       # Commit to a plan
canvas(action="mark", symbol="foo", text="tested")     # Mark verified
```

## Recommended Pattern

**Before changing code:** Always run `impact` first to see what might break.

```
1. impact symbol="target"  →  See callers/callees
2. claim text="..."        →  Record what you notice
3. decide text="..."       →  State your plan
4. [make changes]
5. mark symbol="target"    →  Confirm verified
```

## Hooks (Auto-Trigger)

If configured, CodeCanvas auto-suggests init when you start working on a code repository. This happens via the PreToolUse hook when you Read/Edit/Grep files.

## Response Format

Every response includes:
- **What happened** (action result)
- **Board summary** (evidence/claims/decisions count + current focus)
- **Next hint** (suggested next action)

## Tips

1. Use `impact` BEFORE editing to understand blast radius
2. Claims and decisions auto-link to your most recent evidence
3. Run `status` to refresh the board without reparsing
4. Run `read` for text-only output (non-multimodal fallback)
