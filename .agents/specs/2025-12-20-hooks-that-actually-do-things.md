## The Problem

Current hooks just output `systemMessage` which is "shown to user" but **doesn't inject into Claude's context** and **doesn't run any analysis**. Completely useless.

## The Fix

### Hook 1: SessionStart - Auto Init

**Trigger:** `SessionStart` with matcher `startup`

**Action:** Actually runs `canvas_action(action="init", repo_path=cwd)`

**Output:** `additionalContext` with init summary → **injected into Claude's context**

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [{
          "type": "command",
          "command": "python3 -c \"from codecanvas.hooks.session_init import main; main()\"",
          "timeout": 30
        }]
      }
    ]
  }
}
```

### Hook 2: PostToolUse on Read - Auto Impact

**Trigger:** `PostToolUse` with matcher `Read`

**Action:** After Claude reads a file, extract symbols and run `canvas_action(action="impact", symbol=X)`

**Output:** `additionalContext` with impact analysis → **Claude sees dependencies of what it just read**

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Read",
        "hooks": [{
          "type": "command",
          "command": "python3 -c \"from codecanvas.hooks.post_read import main; main()\"",
          "timeout": 10
        }]
      }
    ]
  }
}
```

### Key Insight from Docs

- `PreToolUse` → `systemMessage` = shown to user only (useless)
- `PostToolUse` → `additionalContext` = **injected into Claude's context** ✓
- `SessionStart` → `additionalContext` = **injected into Claude's context** ✓

## Files to Create/Modify

1. **`codecanvas/hooks/session_init.py`** - Runs init, outputs additionalContext
2. **`codecanvas/hooks/post_read.py`** - Runs impact on read file, outputs additionalContext  
3. **`codecanvas/hooks/hooks.json`** - Updated with SessionStart + PostToolUse
4. **Delete** `codecanvas/hooks/auto_init.py` (replace with above)

## Result

Small model reads a file → hook automatically runs impact analysis → Claude sees "this function is called by X, Y, Z" in its context → makes informed edits without needing to be smart enough to invoke codecanvas manually.