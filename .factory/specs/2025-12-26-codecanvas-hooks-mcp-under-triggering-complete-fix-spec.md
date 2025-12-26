## Root Causes Identified

After analyzing analytics, state.json files, and source code, I've identified **5 critical bugs**:

---

### BUG 1: `session_init.py` Harmful Early-Exit Heuristics (CRITICAL)

**Location**: `codecanvas/hooks/session_init.py` lines 67-74

**Problem Code**:
```python
# Skip if not a code repo
if not detect_repo(cwd):  # Requires .git, pyproject.toml, etc.
    sys.exit(0)

# Skip if not enough code files
code_count = count_code_files(cwd, limit=5)
if code_count < 5:  # ARBITRARY - kills small tasks!
    sys.exit(0)
```

**Impact**: 
- Task repos without `.git` marker → no init
- Tasks with 1-4 code files → no init
- Many benchmark tasks silently skipped

**Fix**: Remove both checks entirely. The parser handles empty/small directories gracefully (returns empty graph, still outputs useful info).

```python
def main():
    # ... read input ...
    
    # Always attempt init - parser handles edge cases
    if has_canvas_state(cwd):
        # Output actual state info, not generic reminder
        init_result = _summarize_existing_state(cwd)
    else:
        init_result = run_canvas_init(cwd)
    
    # Output result
    result = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": init_result}}
    print(json.dumps(result))
```

---

### BUG 2: `post_read.py` NodeKind Mismatch (CRITICAL)

**Location**: `codecanvas/hooks/post_read.py` line ~78

**Problem**:
```python
if node.kind in ("FUNCTION", "CLASS", "METHOD"):  # WRONG VALUES!
```

**Actual values** (from `core/models.py`):
```python
NodeKind.FUNC = "func"   # not "FUNCTION"
NodeKind.CLASS = "class" # correct but lowercase
# No "METHOD" exists!
```

**Fix**:
```python
if node.kind in ("func", "class"):
```

---

### BUG 3: Analytics Extraction Wrong Keys (Corrupts Data)

**Location**: `terminalbench/analytics/extensions/codecanvas.py`

**Problem**:
```python
m.files_parsed = ps.get("files", 0)       # Should be "parsed_files"
m.functions_parsed = ps.get("functions", 0)  # Should come from evidence metrics
```

**Fix**: Use correct keys from state.json structure.

---

### BUG 4: LSP Servers Not Installed in Harbor

**Evidence**: `"lsp_failures": {"missing_server": 30}` in all state.json files

**Impact**: No call edges (100% tree-sitter fallback)

**Fix**: Install `basedpyright-langserver` in Harbor container, or implement AST-based call inference.

---

### BUG 5: Hook Command Format (Potential)

**Location**: `codecanvas/hooks/hooks.json`

```json
"command": "uv run python -c \"...\""
```

**Fix**: Verify works in Harbor; add fallback if needed.

---

## Implementation Plan

### Phase 1: Critical Bug Fixes

| File | Change |
|------|--------|
| `codecanvas/hooks/session_init.py` | Remove `detect_repo()` and `code_count < 5` early exits |
| `codecanvas/hooks/session_init.py` | Improve `has_canvas_state()` branch to output actual state summary |
| `codecanvas/hooks/post_read.py` | Change `"FUNCTION", "CLASS", "METHOD"` → `"func", "class"` |
| `terminalbench/analytics/extensions/codecanvas.py` | Fix parse_summary key extraction |

### Phase 2: Infrastructure

| Target | Action |
|--------|--------|
| Harbor container | Install `basedpyright-langserver` |
| `hooks.json` | Verify command format |

---

## Specific Code Changes

### `session_init.py` - Remove early exits:

```python
def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        input_data = {}

    cwd = input_data.get("cwd", os.getcwd())

    # REMOVED: detect_repo() check
    # REMOVED: code_count < 5 check
    
    if has_canvas_state(cwd):
        # Load and summarize existing state
        init_result = _load_state_summary(cwd)
    else:
        init_result = run_canvas_init(cwd)

    result = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": init_result
        }
    }
    print(json.dumps(result))
    sys.exit(0)


def _load_state_summary(cwd: str) -> str:
    """Load existing state and return useful summary."""
    try:
        import json
        state_path = Path(cwd) / ".codecanvas" / "state.json"
        with open(state_path) as f:
            state = json.load(f)
        ps = state.get("parse_summary", {})
        ev_count = len(state.get("evidence", []))
        return (
            f"[CodeCanvas] State loaded: {ps.get('parsed_files', 0)} files parsed, "
            f"{ev_count} evidence items. Impact analysis ready."
        )
    except Exception:
        return run_canvas_init(cwd)  # Re-init on error
```

### `post_read.py` - Fix NodeKind values:

```python
# Line ~78
if node.kind in ("func", "class"):  # Was: ("FUNCTION", "CLASS", "METHOD")
    symbols.append(node.name)
```

---

## Priority

1. **session_init.py early exits** - Biggest impact, most tasks affected
2. **post_read.py NodeKind** - Breaks all auto-impact
3. **Analytics extraction** - Fixes experimental data
4. **LSP installation** - Enables call graphs