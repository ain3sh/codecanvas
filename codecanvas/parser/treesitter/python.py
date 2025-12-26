"""Python tree-sitter extraction.

Extracts definitions, imports, and call sites from Python source code.
"""

from __future__ import annotations

from typing import List, Optional

from tree_sitter import Node

from . import TsCallSite, TsDefinition, TsRange, iter_named_nodes, node_text, node_range


def extract_definitions(src: bytes, root: Node) -> List[TsDefinition]:
    """Extract class and function definitions from Python AST."""
    out: List[TsDefinition] = []
    class_stack: List[str] = []
    func_depth = 0

    def visit(node: Node) -> None:
        nonlocal func_depth

        if node.type == "class_definition" and func_depth == 0:
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

        if node.type in {"function_definition", "async_function_definition"}:
            if func_depth == 0:
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

            func_depth += 1
            for child in node.named_children:
                visit(child)
            func_depth -= 1
            return

        for child in node.named_children:
            visit(child)

    visit(root)
    return out


def extract_import_specs(src: bytes, root: Node) -> List[str]:
    """Extract import specifiers from Python AST."""
    specs: List[str] = []
    for node in iter_named_nodes(root):
        if node.type == "import_statement":
            for child in node.named_children:
                if child.type == "dotted_name":
                    specs.append(node_text(src, child))
                elif child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    if name_node is not None:
                        specs.append(node_text(src, name_node))
        elif node.type == "import_from_statement":
            mod_node = None
            for child in node.named_children:
                if child.type in {"relative_import", "dotted_name"}:
                    mod_node = child
                    break
            if mod_node is not None:
                specs.append(node_text(src, mod_node))
    return specs


def extract_call_sites(src: bytes, root: Node) -> List[TsCallSite]:
    """Extract function/method call sites from Python AST."""
    sites: List[Optional[TsCallSite]] = []
    for node in iter_named_nodes(root):
        if node.type != "call":
            continue

        fn = node.child_by_field_name("function")
        if fn is None and node.named_children:
            fn = node.named_children[0]
        if fn is None:
            continue

        sites.append(_call_site_from_target(src, fn))
    return [s for s in sites if s is not None]


def _call_site_from_target(src: bytes, target: Node) -> Optional[TsCallSite]:
    """Extract call site location from call target node."""
    # Prefer the final identifier in a member/attribute expression
    for field in ("attribute", "property", "name"):
        field_node = target.child_by_field_name(field)
        if field_node is not None:
            (line, char) = field_node.start_point
            return TsCallSite(line=line, char=char)

    # Fallback: identifier itself or start of expression
    (line, char) = target.start_point
    return TsCallSite(line=line, char=char)
