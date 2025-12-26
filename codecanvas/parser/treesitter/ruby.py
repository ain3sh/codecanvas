"""Ruby tree-sitter extraction.

TODO: Implement extraction of definitions, imports, and call sites from Ruby source code.
"""

from __future__ import annotations

from typing import List

from tree_sitter import Node

from . import TsCallSite, TsDefinition


def extract_definitions(src: bytes, root: Node) -> List[TsDefinition]:
    """Extract class and method definitions from Ruby AST."""
    # TODO: Implement Ruby definition extraction
    # - class definitions (class Foo ... end)
    # - module definitions (module Bar ... end)
    # - method definitions (def foo ... end)
    # - singleton method definitions (def self.foo ... end)
    return []


def extract_import_specs(src: bytes, root: Node) -> List[str]:
    """Extract require statements from Ruby AST."""
    # TODO: Implement Ruby import extraction
    # - require 'foo'
    # - require_relative 'bar'
    # - load 'baz.rb'
    return []


def extract_call_sites(src: bytes, root: Node) -> List[TsCallSite]:
    """Extract method call sites from Ruby AST."""
    # TODO: Implement Ruby call site extraction
    # - method calls: foo()
    # - method calls with receiver: obj.method
    # - block calls: foo { ... }
    return []
