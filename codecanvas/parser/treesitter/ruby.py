"""Ruby tree-sitter extraction.

Extracts definitions, imports, and call sites from Ruby source code.
"""

from __future__ import annotations

from typing import List, Optional

from tree_sitter import Node

from . import TsCallSite, TsDefinition, iter_named_nodes, node_range, node_text


def extract_definitions(src: bytes, root: Node) -> List[TsDefinition]:
    """Extract class and method definitions from Ruby AST."""
    out: List[TsDefinition] = []
    class_stack: List[str] = []

    def visit(node: Node) -> None:
        if node.type in {"class", "module"}:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                class_name = node_text(src, name_node)
                out.append(
                    TsDefinition(
                        kind="class",
                        name=class_name,
                        bare_name=class_name,
                        range=node_range(node),
                        parent_class=class_stack[-1] if class_stack else None,
                    )
                )
                class_stack.append(class_name)
                for child in node.named_children:
                    visit(child)
                class_stack.pop()
                return

        if node.type == "method":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                bare = node_text(src, name_node)
                parent_class = class_stack[-1] if class_stack else None
                label = f"{parent_class}.{bare}" if parent_class else bare
                out.append(
                    TsDefinition(
                        kind="func",
                        name=label,
                        bare_name=bare,
                        range=node_range(node),
                        parent_class=parent_class,
                    )
                )

        if node.type == "singleton_method":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                bare = node_text(src, name_node)
                parent_class = class_stack[-1] if class_stack else None
                label = f"{parent_class}.{bare}" if parent_class else bare
                out.append(
                    TsDefinition(
                        kind="func",
                        name=label,
                        bare_name=bare,
                        range=node_range(node),
                        parent_class=parent_class,
                    )
                )

        for child in node.named_children:
            visit(child)

    visit(root)
    return out


def extract_import_specs(src: bytes, root: Node) -> List[str]:
    """Extract require statements from Ruby AST."""
    specs: List[str] = []
    for node in iter_named_nodes(root):
        if node.type == "call":
            method_node = node.child_by_field_name("method")
            if method_node is not None:
                method_name = node_text(src, method_node)
                if method_name in {"require", "require_relative", "load"}:
                    args_node = node.child_by_field_name("arguments")
                    if args_node is not None:
                        for arg in args_node.named_children:
                            if arg.type == "string":
                                raw = node_text(src, arg)
                                specs.append(raw.strip("\"'"))
                                break
    return specs


def extract_call_sites(src: bytes, root: Node) -> List[TsCallSite]:
    """Extract method call sites from Ruby AST."""
    sites: List[TsCallSite] = []
    for node in iter_named_nodes(root):
        if node.type == "call":
            method_node = node.child_by_field_name("method")
            if method_node is not None:
                (line, char) = method_node.start_point
                sites.append(TsCallSite(line=line, char=char))

        elif node.type == "method_call":
            method_node = node.child_by_field_name("method")
            if method_node is not None:
                (line, char) = method_node.start_point
                sites.append(TsCallSite(line=line, char=char))

    return sites
