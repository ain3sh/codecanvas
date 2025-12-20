#!/usr/bin/env python3
"""
CodeCanvas auto-init hook (PreToolUse).

Suggests canvas init when:
1. Repo detected (.git, pyproject.toml, package.json, etc.)
2. Contains >=5 code files
3. No existing canvas state

Output: JSON with systemMessage (shown to user) on exit 0.
"""

import json
import os
import sys
from pathlib import Path


def detect_repo(cwd: str) -> bool:
    """Check if current directory is a code repository."""
    markers = [".git", "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "pom.xml"]
    cwd_path = Path(cwd)
    for marker in markers:
        if (cwd_path / marker).exists():
            return True
    return False


def count_code_files(cwd: str, limit: int = 10) -> int:
    """Count code files in directory (stop at limit for efficiency)."""
    code_exts = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cpp", ".c", ".rb"}
    count = 0
    for root, _, files in os.walk(cwd):
        if "node_modules" in root or ".git" in root or "__pycache__" in root:
            continue
        for f in files:
            if any(f.endswith(ext) for ext in code_exts):
                count += 1
                if count >= limit:
                    return count
    return count


def has_canvas_state(cwd: str) -> bool:
    """Check if canvas state already exists."""
    state_path = Path(cwd) / ".codecanvas" / "state.json"
    return state_path.exists()


def main():
    # Read hook input from stdin
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        input_data = {}

    cwd = input_data.get("cwd", os.getcwd())

    # Skip if not a code repo
    if not detect_repo(cwd):
        sys.exit(0)

    # Skip if canvas already initialized
    if has_canvas_state(cwd):
        sys.exit(0)

    # Skip if not enough code files
    code_count = count_code_files(cwd, limit=5)
    if code_count < 5:
        sys.exit(0)

    # Output suggestion as systemMessage (shown to user, doesn't block)
    result = {
        "systemMessage": (
            "[CodeCanvas] Code repository detected without canvas state. "
            'Consider: canvas(action="init", repo_path=".") for impact analysis.'
        )
    }
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
