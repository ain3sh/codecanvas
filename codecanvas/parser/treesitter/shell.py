"""Shell/Bash tree-sitter extraction.

TODO: Implement extraction of definitions, imports, and call sites from shell scripts.
"""

from __future__ import annotations

from typing import List

from tree_sitter import Node

from . import TsCallSite, TsDefinition


def extract_definitions(src: bytes, root: Node) -> List[TsDefinition]:
    """Extract function definitions from shell script AST."""
    # TODO: Implement shell function definition extraction
    # - function foo() { ... }
    # - foo() { ... }
    return []


def extract_import_specs(src: bytes, root: Node) -> List[str]:
    """Extract source commands from shell script AST."""
    # TODO: Implement shell source extraction
    # - source ./script.sh
    # - . ./script.sh
    return []


def extract_call_sites(src: bytes, root: Node) -> List[TsCallSite]:
    """Extract function call sites from shell script AST."""
    # TODO: Implement shell call site extraction
    # - function calls: my_function
    # - command calls: grep, sed, etc.
    return []
