"""Shared language configuration for CodeCanvas parser.

Centralizes language server commands, file extension mappings,
and language detection logic used by both LSP and tree-sitter backends.
"""

from __future__ import annotations

import shutil
from functools import lru_cache
from typing import Any, Dict, List, Optional

# Language server configurations
# Maps language key -> server command and initialization options
LANGUAGE_SERVERS: Dict[str, Dict[str, Any]] = {
    "py": {
        "cmd": ["basedpyright-langserver", "--stdio"],
        "init_options": {},
    },
    "ts": {
        "cmd": ["typescript-language-server", "--stdio"],
        "init_options": {},
    },
    "go": {
        "cmd": ["gopls", "serve"],
        "init_options": {},
    },
    "rs": {
        "cmd": ["rust-analyzer"],
        "init_options": {},
    },
    "java": {
        "cmd": ["jdtls"],
        "init_options": {},
    },
    "rb": {
        "cmd": ["solargraph", "stdio"],
        "init_options": {},
    },
    "c": {
        "cmd": ["clangd"],
        "init_options": {},
    },
    "sh": {
        "cmd": ["bash-language-server", "start"],
        "init_options": {},
    },
}

# File extension to language key mapping
EXTENSION_TO_LANG: Dict[str, str] = {
    # Python
    ".py": "py",
    # TypeScript/JavaScript (consolidated under 'ts')
    ".ts": "ts",
    ".tsx": "ts",
    ".js": "ts",
    ".jsx": "ts",
    # Go
    ".go": "go",
    # Rust
    ".rs": "rs",
    # Java
    ".java": "java",
    # Ruby
    ".rb": "rb",
    # C/C++ (consolidated under 'c')
    ".c": "c",
    ".h": "c",
    ".cpp": "c",
    ".hpp": "c",
    ".cc": "c",
    # Shell
    ".sh": "sh",
    ".bash": "sh",
}

# Languages with tree-sitter support
TREESITTER_LANGUAGES: set[str] = {"py", "ts", "go", "rs", "java", "rb", "c", "sh"}


def detect_language(path: str) -> Optional[str]:
    """Detect language key from file path.

    Args:
        path: File path (e.g., "/path/to/file.py")

    Returns:
        Language key (e.g., "py") or None if extension is unknown
    """
    if "." not in path:
        return None
    ext = "." + path.rsplit(".", 1)[-1]
    return EXTENSION_TO_LANG.get(ext)


def has_lsp_support(lang: str) -> bool:
    """Check if a language has LSP server configured."""
    return lang in LANGUAGE_SERVERS


def has_treesitter_support(lang: str) -> bool:
    """Check if a language has tree-sitter support."""
    return lang in TREESITTER_LANGUAGES


@lru_cache
def is_language_server_installed(lang: str) -> bool:
    """Check if the LSP binary is available on PATH."""
    cfg = LANGUAGE_SERVERS.get(lang)
    if not cfg:
        return False
    cmd = cfg.get("cmd")
    if not cmd:
        return False
    return shutil.which(cmd[0]) is not None


def get_lsp_command(lang: str) -> Optional[List[str]]:
    """Get LSP server command for a language."""
    cfg = LANGUAGE_SERVERS.get(lang)
    if not cfg:
        return None
    return cfg.get("cmd")
