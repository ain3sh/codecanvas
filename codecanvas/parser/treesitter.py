from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language


@dataclass(frozen=True)
class TsRange:
    start_line: int
    start_char: int
    end_line: int
    end_char: int


@dataclass(frozen=True)
class TsDefinition:
    kind: str  # "class" | "func"
    name: str
    bare_name: str
    range: TsRange
    parent_class: str | None = None


@dataclass(frozen=True)
class TsCallSite:
    line: int
    char: int


@dataclass(frozen=True)
class TsParsed:
    language: str
    src: bytes
    tree: Any
    root: Node


_THREAD_LOCAL = threading.local()


def _get_parser(language_name: str) -> Parser:
    parsers = getattr(_THREAD_LOCAL, "parsers", None)
    if parsers is None:
        parsers = {}
        _THREAD_LOCAL.parsers = parsers

    parser = parsers.get(language_name)
    if parser is None:
        lang = get_language(language_name)
        parser = Parser()
        if hasattr(parser, "set_language"):
            parser.set_language(lang)
        else:
            parser.language = lang
        parsers[language_name] = parser
    return parser


def _language_for_file(file_path: Path, lang_key: str) -> Optional[str]:
    if lang_key == "py":
        return "python"
    if lang_key == "ts":
        suf = file_path.suffix.lower()
        if suf in {".tsx", ".jsx"}:
            return "tsx"
        if suf in {".js", ".mjs", ".cjs"}:
            return "javascript"
        return "typescript"
    return None


def _iter_named_nodes(root: Node) -> Iterable[Node]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        for child in reversed(node.named_children):
            stack.append(child)


def _node_text(src: bytes, node: Node) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _range(node: Node) -> TsRange:
    (sl, sc) = node.start_point
    (el, ec) = node.end_point
    return TsRange(start_line=sl, start_char=sc, end_line=el, end_char=ec)


def parse_source(text: str, *, file_path: Path, lang_key: str) -> Optional[TsParsed]:
    language = _language_for_file(file_path, lang_key)
    if language is None:
        return None

    src = text.encode("utf-8", errors="replace")
    parser = _get_parser(language)
    tree = parser.parse(src)
    root = tree.root_node
    return TsParsed(language=language, src=src, tree=tree, root=root)


def import_specs_from_parsed(parsed: TsParsed) -> List[str]:
    if parsed.language == "python":
        return _extract_python_import_specs(parsed.src, parsed.root)
    if parsed.language in {"typescript", "tsx", "javascript"}:
        return _extract_ts_import_specs(parsed.src, parsed.root)
    return []


def definitions_from_parsed(parsed: TsParsed) -> List[TsDefinition]:
    if parsed.language == "python":
        return _extract_python_definitions(parsed.src, parsed.root)
    if parsed.language in {"typescript", "tsx", "javascript"}:
        return _extract_ts_definitions(parsed.src, parsed.root)
    return []


def call_sites_from_parsed(parsed: TsParsed) -> List[TsCallSite]:
    if parsed.language == "python":
        return _extract_python_call_sites(parsed.src, parsed.root)
    if parsed.language in {"typescript", "tsx", "javascript"}:
        return _extract_ts_call_sites(parsed.src, parsed.root)
    return []


def extract_definitions(text: str, *, file_path: Path, lang_key: str) -> List[TsDefinition]:
    parsed = parse_source(text, file_path=file_path, lang_key=lang_key)
    if parsed is None:
        return []
    return definitions_from_parsed(parsed)


def _extract_python_definitions(src: bytes, root: Node) -> List[TsDefinition]:
    out: List[TsDefinition] = []
    class_stack: List[str] = []
    func_depth = 0

    def visit(node: Node) -> None:
        nonlocal func_depth

        if node.type == "class_definition" and func_depth == 0:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                class_name = _node_text(src, name_node)
                out.append(
                    TsDefinition(
                        kind="class",
                        name=class_name,
                        bare_name=class_name,
                        range=_range(node),
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
                    bare = _node_text(src, name_node)
                    parent_class = class_stack[-1] if class_stack else None
                    label = f"{parent_class}.{bare}" if parent_class else bare
                    out.append(
                        TsDefinition(
                            kind="func",
                            name=label,
                            bare_name=bare,
                            range=_range(node),
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


def _extract_ts_definitions(src: bytes, root: Node) -> List[TsDefinition]:
    out: List[TsDefinition] = []
    class_stack: List[str] = []
    func_depth = 0

    def visit(node: Node) -> None:
        nonlocal func_depth

        if node.type == "class_declaration" and func_depth == 0:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                class_name = _node_text(src, name_node)
                out.append(
                    TsDefinition(
                        kind="class",
                        name=class_name,
                        bare_name=class_name,
                        range=_range(node),
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
                bare = _node_text(src, name_node)
                parent_class = class_stack[-1] if class_stack else None
                label = f"{parent_class}.{bare}" if parent_class else bare
                out.append(
                    TsDefinition(
                        kind="func",
                        name=label,
                        bare_name=bare,
                        range=_range(node),
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
                bare = _node_text(src, name_node)
                parent_class = class_stack[-1]
                label = f"{parent_class}.{bare}"
                out.append(
                    TsDefinition(
                        kind="func",
                        name=label,
                        bare_name=bare,
                        range=_range(node),
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
                bare = _node_text(src, name_node)
                parent_class = class_stack[-1] if class_stack else None
                label = f"{parent_class}.{bare}" if parent_class else bare
                out.append(
                    TsDefinition(
                        kind="func",
                        name=label,
                        bare_name=bare,
                        range=_range(node),
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


def extract_import_specs(text: str, *, file_path: Path, lang_key: str) -> List[str]:
    parsed = parse_source(text, file_path=file_path, lang_key=lang_key)
    if parsed is None:
        return []
    return import_specs_from_parsed(parsed)


def _extract_python_import_specs(src: bytes, root: Node) -> List[str]:
    specs: List[str] = []
    for node in _iter_named_nodes(root):
        if node.type == "import_statement":
            for child in node.named_children:
                if child.type == "dotted_name":
                    specs.append(_node_text(src, child))
                elif child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    if name_node is not None:
                        specs.append(_node_text(src, name_node))
        elif node.type == "import_from_statement":
            mod_node = None
            for child in node.named_children:
                if child.type in {"relative_import", "dotted_name"}:
                    mod_node = child
                    break
            if mod_node is not None:
                specs.append(_node_text(src, mod_node))
    return specs


def _extract_ts_import_specs(src: bytes, root: Node) -> List[str]:
    specs: List[str] = []
    for node in _iter_named_nodes(root):
        if node.type == "import_statement":
            str_node = next((c for c in node.named_children if c.type == "string"), None)
            if str_node is not None:
                raw = _node_text(src, str_node)
                specs.append(raw.strip("\"'"))
        elif node.type == "call_expression":
            fn_node = node.child_by_field_name("function")
            if fn_node is None or fn_node.type != "identifier" or _node_text(src, fn_node) != "require":
                continue

            args_node = node.child_by_field_name("arguments")
            if args_node is None:
                continue

            str_arg = next((c for c in args_node.named_children if c.type == "string"), None)
            if str_arg is not None:
                raw = _node_text(src, str_arg)
                specs.append(raw.strip("\"'"))
    return specs


def extract_call_sites(text: str, *, file_path: Path, lang_key: str) -> List[TsCallSite]:
    parsed = parse_source(text, file_path=file_path, lang_key=lang_key)
    if parsed is None:
        return []
    return call_sites_from_parsed(parsed)


def _extract_python_call_sites(src: bytes, root: Node) -> List[TsCallSite]:
    sites: List[Optional[TsCallSite]] = []
    for node in _iter_named_nodes(root):
        if node.type != "call":
            continue

        fn = node.child_by_field_name("function")
        if fn is None and node.named_children:
            fn = node.named_children[0]
        if fn is None:
            continue

        sites.append(_call_site_from_target(src, fn))
    return [s for s in sites if s is not None]


def _extract_ts_call_sites(src: bytes, root: Node) -> List[TsCallSite]:
    sites: List[TsCallSite] = []
    for node in _iter_named_nodes(root):
        if node.type != "call_expression":
            continue

        fn = node.child_by_field_name("function")
        if fn is None and node.named_children:
            fn = node.named_children[0]
        if fn is None:
            continue

        site = _call_site_from_target(src, fn)
        if site is not None:
            sites.append(site)
    return sites


def _call_site_from_target(src: bytes, target: Node) -> Optional[TsCallSite]:
    # Prefer the final identifier in a member/attribute expression.
    for field in ("attribute", "property", "name"):
        field_node = target.child_by_field_name(field)
        if field_node is not None:
            (line, char) = field_node.start_point
            return TsCallSite(line=line, char=char)

    # Fallback: identifier itself or start of expression.
    (line, char) = target.start_point
    return TsCallSite(line=line, char=char)
