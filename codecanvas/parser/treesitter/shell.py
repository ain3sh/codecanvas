"""Shell/Bash tree-sitter extraction.

Extracts definitions, imports, and call sites from shell scripts.
"""

from __future__ import annotations

from typing import List

from tree_sitter import Node

from . import TsCallSite, TsDefinition, iter_named_nodes, node_range, node_text


def extract_definitions(src: bytes, root: Node) -> List[TsDefinition]:
    """Extract function definitions from shell script AST."""
    out: List[TsDefinition] = []
    for node in iter_named_nodes(root):
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                bare = node_text(src, name_node)
                out.append(
                    TsDefinition(
                        kind="func",
                        name=bare,
                        bare_name=bare,
                        range=node_range(node),
                        parent_class=None,
                    )
                )
    return out


def extract_import_specs(src: bytes, root: Node) -> List[str]:
    """Extract source commands from shell script AST."""
    specs: List[str] = []
    for node in iter_named_nodes(root):
        if node.type == "command":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                cmd_name = node_text(src, name_node)
                if cmd_name in {"source", "."}:
                    for child in node.named_children:
                        if child.type in {"word", "string", "raw_string"}:
                            if child != name_node:
                                raw = node_text(src, child)
                                specs.append(raw.strip("\"'"))
                                break
    return specs


def extract_call_sites(src: bytes, root: Node) -> List[TsCallSite]:
    """Extract function call sites from shell script AST."""
    sites: List[TsCallSite] = []
    for node in iter_named_nodes(root):
        if node.type == "command":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                (line, char) = name_node.start_point
                sites.append(TsCallSite(line=line, char=char))
    return sites
