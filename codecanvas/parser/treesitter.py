"""Tree-sitter backend for CodeCanvas parser.

Provides AST-based code parsing for definitions, imports, and call sites.

This module intentionally exposes a small, stable surface:
- `parse_source()` -> `TsParsed`
- `definitions_from_parsed()` -> `List[TsDefinition]`
- `import_specs_from_parsed()` -> `List[str]`
- `call_sites_from_parsed()` -> `List[TsCallSite]`
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any, Iterable, List, Optional, cast

from tree_sitter import Node, Parser, Query, QueryCursor
from tree_sitter_language_pack import get_language

# =============================================================================
# Data Types
# =============================================================================


@dataclass(frozen=True)
class TsRange:
    """Source code range (0-indexed lines and characters)."""

    start_line: int
    start_char: int
    end_line: int
    end_char: int


@dataclass(frozen=True)
class TsDefinition:
    """A class or function definition extracted from source."""

    kind: str  # "class" | "func"
    name: str
    bare_name: str
    range: TsRange
    parent_class: str | None = None


@dataclass(frozen=True)
class TsCallSite:
    """A function/method call site location."""

    line: int
    char: int


@dataclass(frozen=True)
class TsParsed:
    """Parsed source code with tree-sitter AST."""

    language: str
    src: bytes
    tree: Any
    root: Node


# =============================================================================
# Parser Infrastructure
# =============================================================================


_THREAD_LOCAL = threading.local()


@lru_cache(maxsize=256)
def _cached_language(language_name: str):
    return get_language(cast(Any, language_name))


def _get_parser(language_name: str) -> Parser:
    """Get or create a thread-local parser for the given language."""
    parsers = getattr(_THREAD_LOCAL, "parsers", None)
    if parsers is None:
        parsers = {}
        _THREAD_LOCAL.parsers = parsers

    parser = parsers.get(language_name)
    if parser is None:
        lang = _cached_language(language_name)
        parser = Parser()
        set_language = getattr(parser, "set_language", None)
        if callable(set_language):
            set_language(lang)
        else:
            setattr(parser, "language", lang)
        parsers[language_name] = parser
    return parser


def _language_for_file(file_path: Path, lang_key: str) -> Optional[str]:
    """Map CodeCanvas language key to tree-sitter-language-pack language name."""
    if not lang_key:
        return None

    if lang_key == "py":
        return "python"

    if lang_key == "cython":
        # tree_sitter_language_pack does not ship a dedicated Cython grammar in this repo's venv.
        # Treat Cython sources as Python for tree-sitter extraction.
        return "python"

    if lang_key == "ts":
        suf = file_path.suffix.lower()
        if suf in {".tsx", ".jsx"}:
            return "tsx"
        if suf in {".js", ".mjs", ".cjs"}:
            return "javascript"
        return "typescript"

    if lang_key == "go":
        return "go"
    if lang_key == "rs":
        return "rust"
    if lang_key == "java":
        return "java"
    if lang_key == "rb":
        return "ruby"
    if lang_key == "c":
        suf = file_path.suffix.lower()
        if suf in {".cpp", ".hpp", ".cc", ".hh", ".cxx"}:
            return "cpp"
        return "c"
    if lang_key == "sh":
        return "bash"
    if lang_key == "cs":
        return "csharp"
    if lang_key == "kotlin":
        return "kotlin"
    if lang_key == "dart":
        return "dart"
    if lang_key == "r":
        return "r"

    try:
        _cached_language(lang_key)  # raises if unsupported
        return lang_key
    except Exception:
        return None


# =============================================================================
# AST Utilities
# =============================================================================


def node_text(src: bytes, node: Node) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def node_range(node: Node) -> TsRange:
    (sl, sc) = node.start_point
    (el, ec) = node.end_point
    return TsRange(start_line=sl, start_char=sc, end_line=el, end_char=ec)


def _ancestors(node: Node) -> Iterable[Node]:
    cur = getattr(node, "parent", None)
    while cur is not None:
        yield cur
        cur = getattr(cur, "parent", None)


# =============================================================================
# Core Parsing
# =============================================================================


def parse_source(text: str, *, file_path: Path, lang_key: str) -> Optional[TsParsed]:
    language = _language_for_file(file_path, lang_key)
    if language is None:
        return None

    src = text.encode("utf-8", errors="replace")
    tree = _get_parser(language).parse(src)
    return TsParsed(language=language, src=src, tree=tree, root=tree.root_node)


# =============================================================================
# Query Schemas (data-only)
# =============================================================================


@lru_cache(maxsize=1)
def _schemas_package_name() -> str:
    base = __package__ or "codecanvas.parser"
    return f"{base}.schemas"


@lru_cache(maxsize=256)
def _load_schema_text(language_name: str) -> Optional[str]:
    rel = f"{language_name}.scm"

    try:
        files = importlib_resources.files(_schemas_package_name())
        f = files / rel
        if f.is_file():
            return f.read_text(encoding="utf-8")
    except Exception:
        pass

    try:
        p = Path(__file__).parent / "schemas" / rel
        if p.exists() and p.is_file():
            return p.read_text(encoding="utf-8")
    except Exception:
        pass

    return None


@lru_cache(maxsize=256)
def _compile_schema_query(language_name: str, schema_text: str) -> Query:
    return Query(_cached_language(language_name), schema_text)


def _schema_query(language_name: str) -> Optional[Query]:
    schema_text = _load_schema_text(language_name)
    if not schema_text:
        return None
    try:
        return _compile_schema_query(language_name, schema_text)
    except Exception:
        return None


# =============================================================================
# Language helpers (minimal)
# =============================================================================


def _extract_go_receiver_type(src: bytes, receiver: Node) -> Optional[str]:
    for child in receiver.named_children:
        if child.type != "parameter_declaration":
            continue
        type_node = child.child_by_field_name("type")
        if type_node is None:
            continue
        if type_node.type == "pointer_type":
            for sub in type_node.named_children:
                if sub.type == "type_identifier":
                    return node_text(src, sub)
        elif type_node.type == "type_identifier":
            return node_text(src, type_node)
    return None


def _extract_rust_use_path(src: bytes, node: Node) -> Optional[str]:
    if node.type in {"scoped_identifier", "identifier"}:
        return node_text(src, node)
    if node.type == "use_as_clause":
        path_node = node.child_by_field_name("path")
        if path_node is not None:
            return node_text(src, path_node)
    if node.type == "use_list":
        for child in node.named_children:
            path = _extract_rust_use_path(src, child)
            if path:
                return path
    if node.type == "scoped_use_list":
        path_node = node.child_by_field_name("path")
        if path_node is not None:
            return node_text(src, path_node)
    return None


def _find_c_func_name(declarator: Node) -> Optional[Node]:
    if declarator.type == "function_declarator":
        inner = declarator.child_by_field_name("declarator")
        if inner is not None:
            return _find_c_func_name(inner)
    if declarator.type in {"identifier", "field_identifier"}:
        return declarator
    if declarator.type == "qualified_identifier":
        name_node = declarator.child_by_field_name("name")
        if name_node is not None:
            return name_node
    if declarator.type == "pointer_declarator":
        inner = declarator.child_by_field_name("declarator")
        if inner is not None:
            return _find_c_func_name(inner)
    return None


def _rust_impl_target_for(src: bytes, *, node: Node) -> Optional[str]:
    for anc in _ancestors(node):
        if anc.type != "impl_item":
            continue
        type_node = anc.child_by_field_name("type")
        if type_node is None:
            continue
        if type_node.type == "type_identifier":
            return node_text(src, type_node)
        if type_node.type == "generic_type":
            inner = type_node.child_by_field_name("type")
            if inner is not None:
                return node_text(src, inner)
        if type_node.type == "scoped_type_identifier":
            name = type_node.child_by_field_name("name")
            if name is not None:
                return node_text(src, name)
    return None


def _c_func_name_for(src: bytes, *, node: Node) -> Optional[str]:
    decl = node.child_by_field_name("declarator")
    if decl is None:
        return None
    name_node = _find_c_func_name(decl)
    if name_node is None:
        return None
    return node_text(src, name_node)


def _name_from_capture(src: bytes, *, owner: Node, name_node: Node | None) -> Optional[str]:
    if name_node is not None:
        t = node_text(src, name_node).strip()
        return t or None
    field = owner.child_by_field_name("name")
    if field is not None:
        t = node_text(src, field).strip()
        return t or None
    return None


# =============================================================================
# Query-based extraction
# =============================================================================


_CAP_CLASS_NODE = "cc.def.class.node"
_CAP_CLASS_NAME = "cc.def.class.name"
_CAP_FUNC_NODE = "cc.def.func.node"
_CAP_FUNC_NAME = "cc.def.func.name"
_CAP_IMPORT_SPEC = "cc.import.spec"
_CAP_CALL_TARGET = "cc.call.target"


def _definitions_from_schema(parsed: TsParsed, query: Query) -> List[TsDefinition]:
    cursor = QueryCursor(query)

    classes: List[tuple[Node, Node | None]] = []
    funcs: List[tuple[Node, Node | None]] = []
    for _pat, caps in cursor.matches(parsed.root):
        if _CAP_CLASS_NODE in caps:
            cls_node = (caps.get(_CAP_CLASS_NODE) or [None])[0]
            if cls_node is not None:
                name_node = (caps.get(_CAP_CLASS_NAME) or [None])[0]
                classes.append((cls_node, name_node))

        if _CAP_FUNC_NODE in caps:
            fn_node = (caps.get(_CAP_FUNC_NODE) or [None])[0]
            if fn_node is not None:
                name_node = (caps.get(_CAP_FUNC_NAME) or [None])[0]
                funcs.append((fn_node, name_node))

    func_nodes = {n for (n, _name) in funcs}
    drop_class_in_func = parsed.language in {"python", "typescript", "tsx", "javascript"}

    out: List[TsDefinition] = []
    class_name_by_node: dict[Node, str] = {}

    for node, name_node in classes:
        if drop_class_in_func and any(a in func_nodes for a in _ancestors(node)):
            continue

        bare = _name_from_capture(parsed.src, owner=node, name_node=name_node)
        if not bare:
            continue

        parent_class = next((class_name_by_node[a] for a in _ancestors(node) if a in class_name_by_node), None)
        class_name_by_node[node] = bare
        out.append(
            TsDefinition(
                kind="class",
                name=bare,
                bare_name=bare,
                range=node_range(node),
                parent_class=parent_class,
            )
        )

    for node, name_node in funcs:
        if any(a in func_nodes for a in _ancestors(node)):
            continue

        bare = _name_from_capture(parsed.src, owner=node, name_node=name_node)
        if not bare and parsed.language in {"c", "cpp"} and node.type == "function_definition":
            bare = _c_func_name_for(parsed.src, node=node)
        if not bare:
            continue

        parent_class: Optional[str]
        if parsed.language == "go" and node.type == "method_declaration":
            recv = node.child_by_field_name("receiver")
            receiver_type = _extract_go_receiver_type(parsed.src, recv) if recv is not None else None
            parent_class = receiver_type
        elif parsed.language == "rust" and node.type == "function_item":
            parent_class = _rust_impl_target_for(parsed.src, node=node)
        else:
            parent_class = next((class_name_by_node[a] for a in _ancestors(node) if a in class_name_by_node), None)

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

    return out


def _import_specs_from_schema(parsed: TsParsed, query: Query) -> List[str]:
    caps = QueryCursor(query).captures(parsed.root)
    nodes = caps.get(_CAP_IMPORT_SPEC, [])

    specs: List[str] = []
    for n in nodes:
        if parsed.language == "rust":
            path = _extract_rust_use_path(parsed.src, n)
            if path:
                specs.append(path)
            continue

        raw = node_text(parsed.src, n).strip()
        if not raw:
            continue

        if parsed.language in {"typescript", "tsx", "javascript", "ruby", "bash"}:
            raw = raw.strip("\"'")
        elif parsed.language == "go":
            raw = raw.strip('"`')
        elif parsed.language in {"c", "cpp"}:
            raw = raw.strip('<>"')

        if raw:
            specs.append(raw)

    return specs


def _call_sites_from_schema(parsed: TsParsed, query: Query) -> List[TsCallSite]:
    caps = QueryCursor(query).captures(parsed.root)
    nodes = caps.get(_CAP_CALL_TARGET, [])

    sites: List[TsCallSite] = []
    for n in nodes:
        (line, char) = n.start_point
        sites.append(TsCallSite(line=line, char=char))
    return sites


# =============================================================================
# Generic fallbacks
# =============================================================================


_GENERIC_DEF_QUERY = "(_ name: (_) @name) @node"


def _generic_definitions(parsed: TsParsed) -> List[TsDefinition]:
    class_markers = ("class", "struct", "interface", "enum", "trait", "module")
    func_markers = ("function", "method", "constructor")

    query = Query(_cached_language(parsed.language), _GENERIC_DEF_QUERY)
    cursor = QueryCursor(query)

    candidates: List[tuple[Node, Node, str]] = []
    for _pat, caps in cursor.matches(parsed.root):
        node = (caps.get("node") or [None])[0]
        name_node = (caps.get("name") or [None])[0]
        if node is None or name_node is None:
            continue
        t = str(getattr(node, "type", ""))
        if any(m in t for m in class_markers):
            candidates.append((node, name_node, "class"))
        elif any(m in t for m in func_markers):
            candidates.append((node, name_node, "func"))

    if not candidates:
        return []

    func_nodes = {n for (n, _name, kind) in candidates if kind == "func"}
    class_name_by_node: dict[Node, str] = {}

    out: List[TsDefinition] = []

    for node, name_node, kind in candidates:
        if kind != "class":
            continue
        if any(a in func_nodes for a in _ancestors(node)):
            continue

        bare = node_text(parsed.src, name_node)
        if not bare:
            continue

        parent_class = next((class_name_by_node[a] for a in _ancestors(node) if a in class_name_by_node), None)
        class_name_by_node[node] = bare
        out.append(
            TsDefinition(
                kind="class",
                name=bare,
                bare_name=bare,
                range=node_range(node),
                parent_class=parent_class,
            )
        )

    for node, name_node, kind in candidates:
        if kind != "func":
            continue
        if any(a in func_nodes for a in _ancestors(node)):
            continue

        bare = node_text(parsed.src, name_node)
        if not bare:
            continue

        parent_class = next((class_name_by_node[a] for a in _ancestors(node) if a in class_name_by_node), None)
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

    return out


# =============================================================================
# Public extraction API
# =============================================================================


def import_specs_from_parsed(parsed: TsParsed) -> List[str]:
    q = _schema_query(parsed.language)
    if q is None:
        return []
    return _import_specs_from_schema(parsed, q)


def definitions_from_parsed(parsed: TsParsed) -> List[TsDefinition]:
    q = _schema_query(parsed.language)
    if q is None:
        return _generic_definitions(parsed)
    return _definitions_from_schema(parsed, q)


def call_sites_from_parsed(parsed: TsParsed) -> List[TsCallSite]:
    q = _schema_query(parsed.language)
    if q is None:
        return []
    return _call_sites_from_schema(parsed, q)


def extract_definitions(text: str, *, file_path: Path, lang_key: str) -> List[TsDefinition]:
    parsed = parse_source(text, file_path=file_path, lang_key=lang_key)
    return definitions_from_parsed(parsed) if parsed else []


def extract_import_specs(text: str, *, file_path: Path, lang_key: str) -> List[str]:
    parsed = parse_source(text, file_path=file_path, lang_key=lang_key)
    return import_specs_from_parsed(parsed) if parsed else []


def extract_call_sites(text: str, *, file_path: Path, lang_key: str) -> List[TsCallSite]:
    parsed = parse_source(text, file_path=file_path, lang_key=lang_key)
    return call_sites_from_parsed(parsed) if parsed else []


__all__ = [
    "TsCallSite",
    "TsDefinition",
    "TsParsed",
    "TsRange",
    "call_sites_from_parsed",
    "definitions_from_parsed",
    "extract_call_sites",
    "extract_definitions",
    "extract_import_specs",
    "import_specs_from_parsed",
    "node_range",
    "node_text",
    "parse_source",
]
