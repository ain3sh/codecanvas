"""Rust tree-sitter extraction.

Extracts definitions, imports, and call sites from Rust source code.
"""

from __future__ import annotations

from typing import List, Optional

from tree_sitter import Node

from . import TsCallSite, TsDefinition, iter_named_nodes, node_range, node_text


def extract_definitions(src: bytes, root: Node) -> List[TsDefinition]:
    """Extract struct, enum, and function definitions from Rust AST."""
    out: List[TsDefinition] = []
    impl_stack: List[str] = []

    def visit(node: Node) -> None:
        if node.type == "function_item":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                bare = node_text(src, name_node)
                parent_class = impl_stack[-1] if impl_stack else None
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

        elif node.type == "struct_item":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
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

        elif node.type == "enum_item":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
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

        elif node.type == "trait_item":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
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

        elif node.type == "impl_item":
            type_node = node.child_by_field_name("type")
            impl_name = None
            if type_node is not None:
                if type_node.type == "type_identifier":
                    impl_name = node_text(src, type_node)
                elif type_node.type == "generic_type":
                    ident = type_node.child_by_field_name("type")
                    if ident is not None:
                        impl_name = node_text(src, ident)
            if impl_name:
                impl_stack.append(impl_name)
                for child in node.named_children:
                    visit(child)
                impl_stack.pop()
                return

        for child in node.named_children:
            visit(child)

    visit(root)
    return out


def extract_import_specs(src: bytes, root: Node) -> List[str]:
    """Extract use statements from Rust AST."""
    specs: List[str] = []
    for node in iter_named_nodes(root):
        if node.type == "use_declaration":
            arg = node.child_by_field_name("argument")
            if arg is not None:
                path = _extract_use_path(src, arg)
                if path:
                    specs.append(path)
    return specs


def _extract_use_path(src: bytes, node: Node) -> Optional[str]:
    """Extract the path from a use argument."""
    if node.type == "scoped_identifier":
        return node_text(src, node)
    if node.type == "identifier":
        return node_text(src, node)
    if node.type == "use_as_clause":
        path_node = node.child_by_field_name("path")
        if path_node is not None:
            return node_text(src, path_node)
    if node.type == "use_list":
        for child in node.named_children:
            path = _extract_use_path(src, child)
            if path:
                return path
    if node.type == "scoped_use_list":
        path_node = node.child_by_field_name("path")
        if path_node is not None:
            return node_text(src, path_node)
    return None


def extract_call_sites(src: bytes, root: Node) -> List[TsCallSite]:
    """Extract function/method call sites from Rust AST."""
    sites: List[TsCallSite] = []
    for node in iter_named_nodes(root):
        if node.type == "call_expression":
            fn = node.child_by_field_name("function")
            if fn is None and node.named_children:
                fn = node.named_children[0]
            if fn is not None:
                site = _call_site_from_target(fn)
                if site is not None:
                    sites.append(site)

        elif node.type == "macro_invocation":
            macro_node = node.child_by_field_name("macro")
            if macro_node is not None:
                (line, char) = macro_node.start_point
                sites.append(TsCallSite(line=line, char=char))

    return sites


def _call_site_from_target(target: Node) -> Optional[TsCallSite]:
    """Extract call site location from call target node."""
    if target.type == "field_expression":
        field_node = target.child_by_field_name("field")
        if field_node is not None:
            (line, char) = field_node.start_point
            return TsCallSite(line=line, char=char)
    if target.type == "scoped_identifier":
        name_node = target.child_by_field_name("name")
        if name_node is not None:
            (line, char) = name_node.start_point
            return TsCallSite(line=line, char=char)
    (line, char) = target.start_point
    return TsCallSite(line=line, char=char)
