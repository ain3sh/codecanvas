"""Java tree-sitter extraction.

TODO: Implement extraction of definitions, imports, and call sites from Java source code.
"""

from __future__ import annotations

from typing import List

from tree_sitter import Node

from . import TsCallSite, TsDefinition


def extract_definitions(src: bytes, root: Node) -> List[TsDefinition]:
    """Extract class and method definitions from Java AST."""
    # TODO: Implement Java definition extraction
    # - class declarations (class Foo {...})
    # - interface declarations (interface Bar {...})
    # - enum declarations (enum Baz {...})
    # - method declarations (public void foo() {...})
    # - constructor declarations
    return []


def extract_import_specs(src: bytes, root: Node) -> List[str]:
    """Extract import statements from Java AST."""
    # TODO: Implement Java import extraction
    # - import java.util.List;
    # - import static java.lang.Math.PI;
    # - import java.util.*;
    return []


def extract_call_sites(src: bytes, root: Node) -> List[TsCallSite]:
    """Extract method call sites from Java AST."""
    # TODO: Implement Java call site extraction
    # - method calls: obj.method()
    # - static method calls: Class.method()
    # - constructor calls: new Foo()
    return []
