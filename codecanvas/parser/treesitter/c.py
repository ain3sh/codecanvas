"""C/C++ tree-sitter extraction.

Extracts definitions, imports, and call sites from C/C++ source code.
"""

from __future__ import annotations

from typing import List, Optional

from tree_sitter import Node

from . import TsCallSite, TsDefinition, iter_named_nodes, node_range, node_text


def extract_definitions(src: bytes, root: Node) -> List[TsDefinition]:
    """Extract struct and function definitions from C/C++ AST."""
    out: List[TsDefinition] = []
    class_stack: List[str] = []

    def visit(node: Node) -> None:
        if node.type in {"struct_specifier", "class_specifier"}:
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

        if node.type == "function_definition":
            declarator = node.child_by_field_name("declarator")
            if declarator is not None:
                name_node = _find_func_name(declarator)
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


def _find_func_name(declarator: Node) -> Optional[Node]:
    """Recursively find function name from declarator."""
    if declarator.type == "function_declarator":
        inner = declarator.child_by_field_name("declarator")
        if inner is not None:
            return _find_func_name(inner)
    if declarator.type in {"identifier", "field_identifier"}:
        return declarator
    if declarator.type == "qualified_identifier":
        name_node = declarator.child_by_field_name("name")
        if name_node is not None:
            return name_node
    if declarator.type == "pointer_declarator":
        inner = declarator.child_by_field_name("declarator")
        if inner is not None:
            return _find_func_name(inner)
    return None


def extract_import_specs(src: bytes, root: Node) -> List[str]:
    """Extract #include directives from C/C++ AST."""
    specs: List[str] = []
    for node in iter_named_nodes(root):
        if node.type == "preproc_include":
            path_node = node.child_by_field_name("path")
            if path_node is not None:
                raw = node_text(src, path_node)
                specs.append(raw.strip('<>"'))
    return specs


def extract_call_sites(src: bytes, root: Node) -> List[TsCallSite]:
    """Extract function call sites from C/C++ AST."""
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
    if target.type == "field_expression":
        field_node = target.child_by_field_name("field")
        if field_node is not None:
            (line, char) = field_node.start_point
            return TsCallSite(line=line, char=char)
    if target.type == "qualified_identifier":
        name_node = target.child_by_field_name("name")
        if name_node is not None:
            (line, char) = name_node.start_point
            return TsCallSite(line=line, char=char)
    (line, char) = target.start_point
    return TsCallSite(line=line, char=char)
