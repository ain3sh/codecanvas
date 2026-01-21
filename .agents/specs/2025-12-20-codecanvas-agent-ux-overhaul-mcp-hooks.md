# CodeCanvas Agent-UX Overhaul Spec

**Goal**: Transform CodeCanvas into a tool that maximizes leverage for agentic LLMs, enabling smaller models (Haiku 4.5) to match larger models (Opus 4.5) on complex terminalbench tasks.

**Principle**: Don't require the model to be smart. Make the tool smart.

---

## Part 1: Tool Description Overhaul

Replace the current 70-char description with a comprehensive mini-tutorial (~280 words):

```python
description = """CodeCanvas: Visual codebase analysis for agentic workflows.

WORKFLOW (recommended pattern):
1. init → Parse repo, get architecture overview (often auto-triggered)
2. impact symbol="target" → See blast radius before changing a symbol
3. claim text="..." → Record hypotheses/findings linked to visual evidence
4. decide text="..." → Record plans/commitments before acting
5. mark/skip symbol="..." → Track verification progress

ACTIONS:
• init: Parse repo into graph, render architecture map. Returns architecture.png + board.png
• impact: Analyze a symbol's callers/callees. Returns impact.png + board.png
• claim: Record hypothesis|finding|question, auto-linked to recent evidence
• decide: Record plan|test|edit commitment, auto-linked to recent evidence
• mark: Mark symbol as verified in current analysis
• skip: Mark symbol as out-of-scope
• status: Refresh Evidence Board (cheap, no reparse)
• read: Text-only state dump (non-multimodal fallback)

EVIDENCE BOARD (board.png):
Your persistent working memory showing Claims, Evidence thumbnails, and Decisions.
Check it to stay oriented on multi-step tasks.

EXAMPLE SESSION:
1. init repo_path="." → E1 (architecture)
2. impact symbol="process_data" → E2 (blast radius: 5 callers, 2 callees)
3. claim text="Changing process_data may break validate_input" kind=hypothesis
4. decide text="Update process_data, then fix validate_input tests" kind=plan
5. [make edits]
6. mark symbol="process_data" text="Verified via unit tests"

TIPS:
• Use impact BEFORE making changes to understand blast radius
• Claims/decisions auto-link to the most recent evidence
• The board shows progress—check it when resuming work"""
```

**Remove `use_lsp` from inputSchema** (keep internal, default True).

---

## Part 2: Response Text Enhancements

Every response will include three sections:
1. **What happened** (current behavior)
2. **Board summary** (orientation)
3. **Next hint** (workflow guidance)

### New helper functions in `server.py`:

```python
def _board_summary(state: CanvasState) -> str:
    """One-line board state for orientation."""
    e = len(state.evidence)
    c = len([x for x in state.claims if x.status == "active"])
    d = len(state.decisions)
    focus = state.focus or "(none)"
    return f"Board: {e} evidence, {c} claims, {d} decisions | Focus: {focus}"

def _progress_summary(state: CanvasState) -> str:
    """Progress on current analysis (if any)."""
    if not state.analyses:
        return ""
    for a in state.analyses.values():
        done, total = a.progress()
        if total > 0:
            return f" | Progress: {done}/{total} affected nodes addressed"
    return ""

def _next_hint(action: str, state: CanvasState) -> str:
    """Context-aware next-step suggestion."""
    hints = {
        "init": "Next: Use impact(symbol=\"<target>\") to analyze a symbol before changing it.",
        "impact": "Next: Record analysis with claim(text=\"...\") or plan with decide(text=\"...\").",
        "claim": "Next: Continue analysis, or commit with decide(text=\"...\").",
        "decide": "Next: Implement your plan, then mark(symbol=\"...\") when verified.",
        "mark": "Next: Continue with remaining affected nodes, or start new impact analysis.",
        "skip": "Next: Continue with remaining affected nodes, or start new impact analysis.",
        "status": "",
        "task_select": "Next: Use impact(symbol=\"...\") to begin analysis.",
    }
    return hints.get(action, "")
```

### Updated response formats:

**init**:
```
Initialized: 12 modules, 8 classes, 45 funcs. Created evidence E1.
Parse: lsp=15, fallback=2. Call graph: +23 edges (working).

Board: 1 evidence, 0 claims, 0 decisions | Focus: myproject
Next: Use impact(symbol="<target>") to analyze a symbol before changing it.
```

**impact**:
```
Created E2 (impact "process_data"): 5 callers, 2 callees in blast radius.

Board: 2 evidence, 0 claims, 0 decisions | Focus: process_data
Next: Record analysis with claim(text="...") or plan with decide(text="...").
```

**claim**:
```
Created C1 [hypothesis] linked to E2.

Board: 2 evidence, 1 claim, 0 decisions | Focus: process_data
Next: Continue analysis, or commit with decide(text="...").
```

**mark**:
```
Marked "process_data" as verified.

Board: 2 evidence, 1 claim, 2 decisions | Focus: process_data | Progress: 1/5 affected nodes addressed
Next: Continue with remaining affected nodes, or start new impact analysis.
```

---

## Part 3: Error Message Improvements

### Add `find_similar_symbols()` to `Analyzer`:

```python
def find_similar_symbols(self, query: str, limit: int = 5) -> List[GraphNode]:
    """Find symbols similar to query for error suggestions."""
    query_lower = query.lower()
    scored = []
    for n in self.graph.nodes:
        if n.kind == NodeKind.MODULE:
            continue  # Skip modules, suggest funcs/classes
        label_lower = n.label.lower()
        # Score: exact substring > prefix > any overlap
        if query_lower in label_lower:
            score = 100 - len(label_lower)  # Shorter = better
        elif label_lower.startswith(query_lower[:3]) if len(query_lower) >= 3 else False:
            score = 50
        else:
            # Simple overlap score
            overlap = sum(1 for c in query_lower if c in label_lower)
            score = overlap * 10 / max(len(query_lower), 1)
        if score > 5:
            scored.append((score, n))
    scored.sort(key=lambda x: -x[0])
    return [n for _, n in scored[:limit]]
```

### Updated error responses:

**Symbol not found** (in `_action_impact`, `_action_mark_skip`):
```python
with _graph_lock:
    node = _analyzer.find_target(symbol)
if not node:
    suggestions = _analyzer.find_similar_symbols(symbol, limit=5)
    if suggestions:
        hint_lines = [f"  • {s.label} ({s.kind.value} in {Path(s.fsPath).name})" for s in suggestions]
        hint = "\n".join(hint_lines)
        return CanvasResult(
            f"Symbol not found: \"{symbol}\"\n"
            f"Similar symbols:\n{hint}\n"
            f"Hint: Use exact function/class names from the suggestions above."
        )
    return CanvasResult(
        f"Symbol not found: \"{symbol}\"\n"
        f"Hint: Run status to see the Evidence Board, or read for a text dump of available symbols."
    )
```

**Not initialized**:
```python
return CanvasResult(
    "Not initialized.\n"
    "Hint: Run canvas(action=\"init\", repo_path=\".\") first, or this may auto-trigger."
)
```

---

## Part 4: Hooks Integration

Create hooks to auto-trigger CodeCanvas initialization.

### New files:

**`.factory/hooks/codecanvas/hooks.json`**:
```json
{
  "description": "CodeCanvas auto-initialization hook",
  "hooks": {
    "PreToolUse": [
      {
        "matcher": {
          "toolName": "^(Read|Edit|MultiEdit|Create|Grep|Glob)$"
        },
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/codecanvas/auto_init.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

**`.factory/hooks/codecanvas/auto_init.py`**:
```python
#!/usr/bin/env python3
"""Auto-init CodeCanvas when agent uses file tools without prior init."""
import json
import os
import sys
from pathlib import Path

def main():
    # Check if canvas state exists
    project_dir = os.environ.get("CANVAS_PROJECT_DIR", os.getcwd())
    state_path = Path(project_dir) / "results" / "canvas" / "state.json"
    
    if state_path.exists():
        # Already initialized, no action needed
        print(json.dumps({"continue": True}))
        return
    
    # Check if this looks like a code repo worth initializing
    cwd = Path.cwd()
    code_indicators = [".git", "pyproject.toml", "package.json", "Cargo.toml", "go.mod"]
    is_repo = any((cwd / indicator).exists() for indicator in code_indicators)
    
    if not is_repo:
        print(json.dumps({"continue": True}))
        return
    
    # Count code files to avoid initializing tiny dirs
    code_extensions = {".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb"}
    code_files = sum(1 for f in cwd.rglob("*") if f.suffix in code_extensions and "node_modules" not in str(f))
    
    if code_files < 5:
        print(json.dumps({"continue": True}))
        return
    
    # Suggest initialization
    print(json.dumps({
        "continue": True,
        "addToPrompt": (
            "[CodeCanvas] Repository detected with {count} code files but canvas not initialized. "
            "Consider running: canvas(action=\"init\", repo_path=\".\") to enable visual impact analysis."
        ).format(count=code_files)
    }))

if __name__ == "__main__":
    main()
```

---

## Part 5: Implementation Checklist

### Files to modify:

1. **`codecanvas/server.py`**:
   - [ ] Update tool description in `_create_mcp_server()` (~280 words)
   - [ ] Remove `use_lsp` from inputSchema (keep internal default True)
   - [ ] Add `_board_summary(state)` helper
   - [ ] Add `_progress_summary(state)` helper  
   - [ ] Add `_next_hint(action, state)` helper
   - [ ] Update `_action_init()` response text
   - [ ] Update `_action_impact()` response text + error handling
   - [ ] Update `_action_claim()` response text
   - [ ] Update `_action_decide()` response text
   - [ ] Update `_action_mark_skip()` response text + error handling
   - [ ] Update `_action_task_select()` response text
   - [ ] Update "Not initialized" error message

2. **`codecanvas/core/analysis.py`**:
   - [ ] Add `find_similar_symbols(query, limit)` method to `Analyzer`

3. **New: `.factory/hooks/codecanvas/`**:
   - [ ] Create `hooks.json`
   - [ ] Create `auto_init.py`

### Tests to add/update:

- [ ] Test fuzzy symbol matching in `tests/api.py`
- [ ] Test response text includes board summary
- [ ] Test error messages include suggestions

---

## Summary

| Component | Change | Impact |
|-----------|--------|--------|
| **Tool description** | 70 chars → 280 words | Agents learn workflow on first read |
| **Response text** | Add board summary + next hints | No "what now?" confusion |
| **Error messages** | Add fuzzy suggestions | No dead ends |
| **Hooks** | Auto-init on file tool use | Eliminate forgotten init |
| **`use_lsp`** | Hide from schema | Reduce noise |

**Estimated implementation**: ~200 lines of code changes across 3 files + 2 new hook files.