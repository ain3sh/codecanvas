#!/usr/bin/env python3
"""
CodeCanvas SessionStart hook - Auto Init.

Automatically initializes canvas when session starts in a code repository.
Outputs additionalContext so Claude knows the codebase structure.
"""

import json
import os
import sys
from pathlib import Path


def has_canvas_state(cwd: str) -> bool:
    """Check if canvas state already exists."""
    state_path = Path(cwd) / ".codecanvas" / "state.json"
    return state_path.exists()


def load_state_summary(cwd: str) -> str:
    """Load existing state and return useful summary."""
    try:
        state_path = Path(cwd) / ".codecanvas" / "state.json"
        with open(state_path) as f:
            state = json.load(f)
        ps = state.get("parse_summary", {})
        ev_count = len(state.get("evidence", []))
        claims_count = len(state.get("claims", []))
        decisions_count = len(state.get("decisions", []))
        parsed = ps.get("parsed_files", 0)
        return (
            f"[CodeCanvas] State loaded: {parsed} files parsed, "
            f"{ev_count} evidence, {claims_count} claims, {decisions_count} decisions. "
            f"Impact analysis ready."
        )
    except Exception as e:
        return f"[CodeCanvas] State exists but load failed: {e}. Will re-init on first action."


def run_canvas_init(cwd: str) -> str:
    """Run canvas init and return result summary."""
    try:
        from codecanvas.server import canvas_action

        result = canvas_action(action="init", repo_path=cwd)
        return f"[CodeCanvas AUTO-INIT] {result.text}"
    except Exception as e:
        return f"[CodeCanvas] Init error: {e}"


def main():
    # Read hook input from stdin
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        input_data = {}

    cwd = input_data.get("cwd", os.getcwd())

    # Always attempt init - parser handles empty/small directories gracefully
    if has_canvas_state(cwd):
        init_result = load_state_summary(cwd)
    else:
        init_result = run_canvas_init(cwd)

    # Output as additionalContext (injected into Claude's context)
    result = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": init_result}}
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
