"""C/C++ tree-sitter extraction.

TODO: Implement extraction of definitions, imports, and call sites from C/C++ source code.
"""

from __future__ import annotations

from typing import List

from tree_sitter import Node

from . import TsCallSite, TsDefinition


def extract_definitions(src: bytes, root: Node) -> List[TsDefinition]:
    """Extract struct and function definitions from C/C++ AST."""
    # TODO: Implement C/C++ definition extraction
    # - function definitions (void foo() {...})
    # - struct definitions (struct Foo {...})
    # - class definitions (C++: class Foo {...})
    # - method definitions (C++: void Foo::bar() {...})
    # - typedef declarations
    return []


def extract_import_specs(src: bytes, root: Node) -> List[str]:
    """Extract #include directives from C/C++ AST."""
    # TODO: Implement C/C++ include extraction
    # - #include <stdio.h>
    # - #include "myheader.h"
    return []


def extract_call_sites(src: bytes, root: Node) -> List[TsCallSite]:
    """Extract function call sites from C/C++ AST."""
    # TODO: Implement C/C++ call site extraction
    # - function calls: foo()
    # - method calls (C++): obj.method() or obj->method()
    # - static method calls (C++): Class::method()
    return []
