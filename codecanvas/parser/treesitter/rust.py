"""Rust tree-sitter extraction.

TODO: Implement extraction of definitions, imports, and call sites from Rust source code.
"""

from __future__ import annotations

from typing import List

from tree_sitter import Node

from . import TsCallSite, TsDefinition


def extract_definitions(src: bytes, root: Node) -> List[TsDefinition]:
    """Extract struct, enum, and function definitions from Rust AST."""
    # TODO: Implement Rust definition extraction
    # - struct definitions (struct Foo {...})
    # - enum definitions (enum Bar {...})
    # - function definitions (fn foo() {...})
    # - impl blocks and methods (impl Foo { fn bar(&self) {...} })
    # - trait definitions (trait Baz {...})
    return []


def extract_import_specs(src: bytes, root: Node) -> List[str]:
    """Extract use statements from Rust AST."""
    # TODO: Implement Rust import extraction
    # - use std::io;
    # - use crate::module::Item;
    # - use super::parent;
    return []


def extract_call_sites(src: bytes, root: Node) -> List[TsCallSite]:
    """Extract function/method call sites from Rust AST."""
    # TODO: Implement Rust call site extraction
    # - function calls: foo()
    # - method calls: obj.method()
    # - associated function calls: Type::new()
    # - macro invocations: println!()
    return []
