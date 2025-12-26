"""Go tree-sitter extraction.

TODO: Implement extraction of definitions, imports, and call sites from Go source code.
"""

from __future__ import annotations

from typing import List

from tree_sitter import Node

from . import TsCallSite, TsDefinition


def extract_definitions(src: bytes, root: Node) -> List[TsDefinition]:
    """Extract type and function definitions from Go AST."""
    # TODO: Implement Go definition extraction
    # - type declarations (type Foo struct {...})
    # - function declarations (func foo() {...})
    # - method declarations (func (r *Receiver) foo() {...})
    return []


def extract_import_specs(src: bytes, root: Node) -> List[str]:
    """Extract import specifiers from Go AST."""
    # TODO: Implement Go import extraction
    # - import "fmt"
    # - import ( "fmt" "os" )
    return []


def extract_call_sites(src: bytes, root: Node) -> List[TsCallSite]:
    """Extract function/method call sites from Go AST."""
    # TODO: Implement Go call site extraction
    # - function calls: foo()
    # - method calls: obj.Method()
    # - package calls: fmt.Println()
    return []
