"""Tree-sitter backend for CodeCanvas parser.

Provides AST-based code parsing for definitions, imports, and call sites
across multiple programming languages.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional

from tree_sitter import Node, Parser
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


def _get_parser(language_name: str) -> Parser:
    """Get or create a thread-local parser for the given language."""
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
    """Map language key to tree-sitter language name."""
    if lang_key == "py":
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
    return None


# =============================================================================
# AST Utilities (exported for language modules)
# =============================================================================


def iter_named_nodes(root: Node) -> Iterable[Node]:
    """Iterate over all named nodes in the AST."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        for child in reversed(node.named_children):
            stack.append(child)


def node_text(src: bytes, node: Node) -> str:
    """Extract text content of a node."""
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def node_range(node: Node) -> TsRange:
    """Extract range from a node."""
    (sl, sc) = node.start_point
    (el, ec) = node.end_point
    return TsRange(start_line=sl, start_char=sc, end_line=el, end_char=ec)


# =============================================================================
# Core Parsing
# =============================================================================


def parse_source(text: str, *, file_path: Path, lang_key: str) -> Optional[TsParsed]:
    """Parse source code with tree-sitter.

    Args:
        text: Source code text
        file_path: Path to source file (used for language detection)
        lang_key: Language key (e.g., "py", "ts", "go")

    Returns:
        TsParsed object or None if language not supported
    """
    language = _language_for_file(file_path, lang_key)
    if language is None:
        return None

    src = text.encode("utf-8", errors="replace")
    parser = _get_parser(language)
    tree = parser.parse(src)
    return TsParsed(language=language, src=src, tree=tree, root=tree.root_node)


# =============================================================================
# Language Dispatch
# =============================================================================


def import_specs_from_parsed(parsed: TsParsed) -> List[str]:
    """Extract import specifiers from parsed source."""
    from . import python as py_ext
    from . import typescript as ts_ext

    if parsed.language == "python":
        return py_ext.extract_import_specs(parsed.src, parsed.root)
    if parsed.language in {"typescript", "tsx", "javascript"}:
        return ts_ext.extract_import_specs(parsed.src, parsed.root)

    from . import c as c_ext
    from . import go as go_ext
    from . import java as java_ext
    from . import ruby as ruby_ext
    from . import rust as rust_ext
    from . import shell as shell_ext

    dispatch = {
        "go": go_ext, "rust": rust_ext, "java": java_ext,
        "ruby": ruby_ext, "c": c_ext, "cpp": c_ext, "bash": shell_ext,
    }
    if (ext := dispatch.get(parsed.language)):
        return ext.extract_import_specs(parsed.src, parsed.root)
    return []


def definitions_from_parsed(parsed: TsParsed) -> List[TsDefinition]:
    """Extract class/function definitions from parsed source."""
    from . import python as py_ext
    from . import typescript as ts_ext

    if parsed.language == "python":
        return py_ext.extract_definitions(parsed.src, parsed.root)
    if parsed.language in {"typescript", "tsx", "javascript"}:
        return ts_ext.extract_definitions(parsed.src, parsed.root)

    from . import c as c_ext
    from . import go as go_ext
    from . import java as java_ext
    from . import ruby as ruby_ext
    from . import rust as rust_ext
    from . import shell as shell_ext

    dispatch = {
        "go": go_ext, "rust": rust_ext, "java": java_ext,
        "ruby": ruby_ext, "c": c_ext, "cpp": c_ext, "bash": shell_ext,
    }
    if (ext := dispatch.get(parsed.language)):
        return ext.extract_definitions(parsed.src, parsed.root)
    return []


def call_sites_from_parsed(parsed: TsParsed) -> List[TsCallSite]:
    """Extract call sites from parsed source."""
    from . import python as py_ext
    from . import typescript as ts_ext

    if parsed.language == "python":
        return py_ext.extract_call_sites(parsed.src, parsed.root)
    if parsed.language in {"typescript", "tsx", "javascript"}:
        return ts_ext.extract_call_sites(parsed.src, parsed.root)

    from . import c as c_ext
    from . import go as go_ext
    from . import java as java_ext
    from . import ruby as ruby_ext
    from . import rust as rust_ext
    from . import shell as shell_ext

    dispatch = {
        "go": go_ext, "rust": rust_ext, "java": java_ext,
        "ruby": ruby_ext, "c": c_ext, "cpp": c_ext, "bash": shell_ext,
    }
    if (ext := dispatch.get(parsed.language)):
        return ext.extract_call_sites(parsed.src, parsed.root)
    return []


# =============================================================================
# Convenience Wrappers
# =============================================================================


def extract_definitions(text: str, *, file_path: Path, lang_key: str) -> List[TsDefinition]:
    """Parse source and extract definitions."""
    parsed = parse_source(text, file_path=file_path, lang_key=lang_key)
    return definitions_from_parsed(parsed) if parsed else []


def extract_import_specs(text: str, *, file_path: Path, lang_key: str) -> List[str]:
    """Parse source and extract import specifiers."""
    parsed = parse_source(text, file_path=file_path, lang_key=lang_key)
    return import_specs_from_parsed(parsed) if parsed else []


def extract_call_sites(text: str, *, file_path: Path, lang_key: str) -> List[TsCallSite]:
    """Parse source and extract call sites."""
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
    "iter_named_nodes",
    "node_range",
    "node_text",
    "parse_source",
]
