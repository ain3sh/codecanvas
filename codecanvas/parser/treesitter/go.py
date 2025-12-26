"""Go tree-sitter extraction.

Extracts definitions, imports, and call sites from Go source code.
"""

from __future__ import annotations

from typing import List, Optional

from tree_sitter import Node

from . import TsCallSite, TsDefinition, iter_named_nodes, node_range, node_text


def extract_definitions(src: bytes, root: Node) -> List[TsDefinition]:
    """Extract type and function definitions from Go AST."""
    out: List[TsDefinition] = []

    for node in iter_named_nodes(root):
        if node.type == "function_declaration":
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

        elif node.type == "method_declaration":
            name_node = node.child_by_field_name("name")
            receiver_node = node.child_by_field_name("receiver")
            if name_node is not None:
                bare = node_text(src, name_node)
                receiver_type = _extract_receiver_type(src, receiver_node) if receiver_node else None
                label = f"{receiver_type}.{bare}" if receiver_type else bare
                out.append(
                    TsDefinition(
                        kind="func",
                        name=label,
                        bare_name=bare,
                        range=node_range(node),
                        parent_class=receiver_type,
                    )
                )

        elif node.type == "type_spec":
            name_node = node.child_by_field_name("name")
            type_node = node.child_by_field_name("type")
            if name_node is not None and type_node is not None:
                if type_node.type in {"struct_type", "interface_type"}:
                    class_name = node_text(src, name_node)
                    out.append(
                        TsDefinition(
                            kind="class",
                            name=class_name,
                            bare_name=class_name,
                            range=node_range(node),
                            parent_class=None,
                        )
                    )

    return out


def _extract_receiver_type(src: bytes, receiver: Node) -> Optional[str]:
    """Extract the type name from a method receiver."""
    for child in receiver.named_children:
        if child.type == "parameter_declaration":
            type_node = child.child_by_field_name("type")
            if type_node is not None:
                if type_node.type == "pointer_type":
                    for sub in type_node.named_children:
                        if sub.type == "type_identifier":
                            return node_text(src, sub)
                elif type_node.type == "type_identifier":
                    return node_text(src, type_node)
    return None


def extract_import_specs(src: bytes, root: Node) -> List[str]:
    """Extract import specifiers from Go AST."""
    specs: List[str] = []
    for node in iter_named_nodes(root):
        if node.type == "import_spec":
            path_node = node.child_by_field_name("path")
            if path_node is not None:
                raw = node_text(src, path_node)
                specs.append(raw.strip('"'))
        elif node.type == "interpreted_string_literal":
            parent = node.parent
            if parent is not None and parent.type == "import_declaration":
                raw = node_text(src, node)
                specs.append(raw.strip('"'))
    return specs


def extract_call_sites(src: bytes, root: Node) -> List[TsCallSite]:
    """Extract function/method call sites from Go AST."""
    sites: List[TsCallSite] = []
    for node in iter_named_nodes(root):
        if node.type != "call_expression":
            continue

        fn = node.child_by_field_name("function")
        if fn is None and node.named_children:
            fn = node.named_children[0]
        if fn is None:
            continue

        site = _call_site_from_target(fn)
        if site is not None:
            sites.append(site)
    return sites


def _call_site_from_target(target: Node) -> Optional[TsCallSite]:
    """Extract call site location from call target node."""
    if target.type == "selector_expression":
        field_node = target.child_by_field_name("field")
        if field_node is not None:
            (line, char) = field_node.start_point
            return TsCallSite(line=line, char=char)
    (line, char) = target.start_point
    return TsCallSite(line=line, char=char)
