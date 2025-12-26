"""TypeScript/JavaScript tree-sitter extraction.

Extracts definitions, imports, and call sites from TypeScript and JavaScript source code.
"""

from __future__ import annotations

from typing import List, Optional

from tree_sitter import Node

from . import TsCallSite, TsDefinition, iter_named_nodes, node_range, node_text


def extract_definitions(src: bytes, root: Node) -> List[TsDefinition]:
    """Extract class and function definitions from TypeScript/JavaScript AST."""
    out: List[TsDefinition] = []
    class_stack: List[str] = []
    func_depth = 0

    def visit(node: Node) -> None:
        nonlocal func_depth

        if node.type == "class_declaration" and func_depth == 0:
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

        if node.type == "function_declaration":
            name_node = node.child_by_field_name("name")
            if name_node is not None and func_depth == 0:
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

        if node.type == "method_definition" and class_stack and func_depth == 0:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                bare = node_text(src, name_node)
                parent_class = class_stack[-1]
                label = f"{parent_class}.{bare}"
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

        # const foo = () => {} / const foo = function() {}
        if node.type == "variable_declarator" and func_depth == 0:
            name_node = node.child_by_field_name("name")
            value_node = node.child_by_field_name("value")
            if name_node is not None and value_node is not None and value_node.type in {
                "arrow_function",
                "function",
                "function_expression",
            }:
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
    """Extract import specifiers from TypeScript/JavaScript AST."""
    specs: List[str] = []
    for node in iter_named_nodes(root):
        if node.type == "import_statement":
            str_node = next((c for c in node.named_children if c.type == "string"), None)
            if str_node is not None:
                raw = node_text(src, str_node)
                specs.append(raw.strip("\"'"))
        elif node.type == "call_expression":
            fn_node = node.child_by_field_name("function")
            if fn_node is None or fn_node.type != "identifier" or node_text(src, fn_node) != "require":
                continue

            args_node = node.child_by_field_name("arguments")
            if args_node is None:
                continue

            str_arg = next((c for c in args_node.named_children if c.type == "string"), None)
            if str_arg is not None:
                raw = node_text(src, str_arg)
                specs.append(raw.strip("\"'"))
    return specs


def extract_call_sites(src: bytes, root: Node) -> List[TsCallSite]:
    """Extract function/method call sites from TypeScript/JavaScript AST."""
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
    # Prefer the final identifier in a member/attribute expression
    for field in ("attribute", "property", "name"):
        field_node = target.child_by_field_name(field)
        if field_node is not None:
            (line, char) = field_node.start_point
            return TsCallSite(line=line, char=char)

    # Fallback: identifier itself or start of expression
    (line, char) = target.start_point
    return TsCallSite(line=line, char=char)
