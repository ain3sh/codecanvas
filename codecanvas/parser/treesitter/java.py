"""Java tree-sitter extraction.

Extracts definitions, imports, and call sites from Java source code.
"""

from __future__ import annotations

from typing import List, Optional

from tree_sitter import Node

from . import TsCallSite, TsDefinition, iter_named_nodes, node_range, node_text


def extract_definitions(src: bytes, root: Node) -> List[TsDefinition]:
    """Extract class and method definitions from Java AST."""
    out: List[TsDefinition] = []
    class_stack: List[str] = []

    def visit(node: Node) -> None:
        if node.type in {"class_declaration", "interface_declaration", "enum_declaration"}:
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

        if node.type in {"method_declaration", "constructor_declaration"}:
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
    """Extract import statements from Java AST."""
    specs: List[str] = []
    for node in iter_named_nodes(root):
        if node.type == "import_declaration":
            for child in node.named_children:
                if child.type == "scoped_identifier":
                    specs.append(node_text(src, child))
                    break
    return specs


def extract_call_sites(src: bytes, root: Node) -> List[TsCallSite]:
    """Extract method call sites from Java AST."""
    sites: List[TsCallSite] = []
    for node in iter_named_nodes(root):
        if node.type == "method_invocation":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                (line, char) = name_node.start_point
                sites.append(TsCallSite(line=line, char=char))

        elif node.type == "object_creation_expression":
            type_node = node.child_by_field_name("type")
            if type_node is not None:
                (line, char) = type_node.start_point
                sites.append(TsCallSite(line=line, char=char))

    return sites
