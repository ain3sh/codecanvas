#!/usr/bin/env python3
"""
CodeCanvas PostToolUse hook - Auto Impact on Read.

After Claude reads a file, automatically runs impact analysis on symbols
defined in that file. Outputs additionalContext so Claude sees dependencies.
"""

import json
import os
import sys
from pathlib import Path


def has_canvas_state(cwd: str) -> bool:
    """Check if canvas state exists."""
    state_path = Path(cwd) / ".codecanvas" / "state.json"
    return state_path.exists()


def extract_main_symbol(file_path: str) -> str | None:
    """Extract the main symbol from a file path (module/class name)."""
    path = Path(file_path)
    
    # Skip non-code files
    code_exts = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cpp", ".c", ".rb"}
    if path.suffix not in code_exts:
        return None
    
    # For Python, use module name (filename without .py)
    if path.suffix == ".py":
        return path.stem
    
    # For other languages, use filename
    return path.stem


def ensure_canvas_loaded() -> bool:
    """Ensure canvas state and graph are loaded. Returns True if successful."""
    try:
        from codecanvas.server import canvas_action
        from codecanvas.core.state import load_state
        
        state = load_state()
        if not state.initialized:
            return False
        
        # Trigger _ensure_loaded by calling canvas_action with status
        # Note: "read" action returns early BEFORE _ensure_loaded, so use "status"
        canvas_action(action="status")
        return True
    except Exception:
        return False


def run_impact_analysis(symbol: str) -> str | None:
    """Run impact analysis on a symbol."""
    try:
        from codecanvas.server import canvas_action
        
        result = canvas_action(action="impact", symbol=symbol, depth=2, max_nodes=20)
        
        # Check if it's a meaningful result (not an error message)
        text = result.text or ""
        if "callers" in text.lower() or "callees" in text.lower():
            return f"[CodeCanvas IMPACT] {text}"
        
        return None
    except Exception:
        return None


def find_symbols_in_file(file_path: str, cwd: str) -> list[str]:
    """Find top-level symbols defined in file using the graph."""
    try:
        from codecanvas.server import _graph
        
        if _graph is None:
            return []
        
        # Get relative path
        try:
            rel_path = Path(file_path).relative_to(cwd)
        except ValueError:
            rel_path = Path(file_path)
        
        # Find nodes in this file
        symbols = []
        for node_id, node in _graph.nodes.items():
            if node.file and Path(node.file) == rel_path:
                if node.kind in ("FUNCTION", "CLASS", "METHOD"):
                    symbols.append(node.name)
        
        return symbols[:3]  # Limit to top 3
    except Exception:
        return []


def main():
    # Read hook input from stdin
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        input_data = {}

    cwd = input_data.get("cwd", os.getcwd())
    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    # Skip if no canvas state
    if not has_canvas_state(cwd):
        sys.exit(0)

    # Skip if no file path
    if not file_path:
        sys.exit(0)

    # Ensure canvas state and graph are loaded
    if not ensure_canvas_loaded():
        sys.exit(0)

    # Find symbols in the file
    symbols = find_symbols_in_file(file_path, cwd)
    
    # Fall back to module name
    if not symbols:
        main_symbol = extract_main_symbol(file_path)
        if main_symbol:
            symbols = [main_symbol]

    if not symbols:
        sys.exit(0)

    # Run impact analysis on first symbol(s)
    impact_results = []
    for symbol in symbols[:2]:  # Analyze up to 2 symbols
        result = run_impact_analysis(symbol)
        if result:
            impact_results.append(result)

    if not impact_results:
        sys.exit(0)

    # Output as additionalContext
    combined = "\n".join(impact_results)
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": combined
        }
    }
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
