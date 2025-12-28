"""CodeCanvas parser - LSP-first with tree-sitter fallback.

Usage:
    from codecanvas.parser import Parser
    parser = Parser()
    graph = parser.parse_directory("/path/to/repo")
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from ..core.models import (
    EdgeType,
    Graph,
    GraphEdge,
    GraphNode,
    NodeKind,
    make_class_id,
    make_func_id,
    make_module_id,
)
from .config import detect_language, has_lsp_support, has_treesitter_support
from .treesitter import definitions_from_parsed, import_specs_from_parsed, parse_source
from .utils import normalize_path, resolve_import_label, strip_strings_and_comments


@dataclass
class ParseSummary:
    """Summary of parsing results."""

    parsed_files: int = 0
    skipped_files: int = 0
    lsp_files: int = 0
    tree_sitter_files: int = 0
    lsp_failures: Dict[str, int] = field(default_factory=dict)
    skipped_samples: List[str] = field(default_factory=list)
    fallback_samples: List[str] = field(default_factory=list)

    def add_skip(self, path: Path, reason: str) -> None:
        self.skipped_files += 1
        if len(self.skipped_samples) < 5:
            self.skipped_samples.append(f"{path}: {reason}")

    def add_lsp_fallback(self, path: Path, category: str, detail: str | None = None) -> None:
        self.lsp_failures[category] = self.lsp_failures.get(category, 0) + 1
        if len(self.fallback_samples) < 5:
            suffix = f": {detail}" if detail else ""
            self.fallback_samples.append(f"{path}: {category}{suffix}")


class Parser:
    """Code parser - LSP-first with tree-sitter fallback.

    Usage:
        parser = Parser()
        graph = parser.parse_directory("/path/to/repo")
        # Or for single file:
        graph = parser.parse_file("/path/to/file.py")
    """

    def __init__(self, use_lsp: bool = True):
        """Initialize parser.

        Args:
            use_lsp: Whether to use language servers when available.
        """
        self.use_lsp = use_lsp
        self.last_summary: ParseSummary = ParseSummary()
        self._known_module_labels: Set[str] = set()

    def parse_directory(
        self,
        path: str,
        extensions: Optional[Set[str]] = None,
        exclude_patterns: Optional[Set[str]] = None,
    ) -> Graph:
        """Parse all files in a directory.

        Args:
            path: Directory path to parse
            extensions: File extensions to include
            exclude_patterns: Path patterns to exclude
        """
        if extensions is None:
            extensions = {
                ".py",
                ".ts",
                ".tsx",
                ".js",
                ".jsx",
                ".go",
                ".rs",
                ".java",
                ".rb",
                ".c",
                ".h",
                ".cc",
                ".hh",
                ".cpp",
                ".hpp",
                ".sh",
                ".bash",
                ".sql",
                ".r",
                ".R",
            }

        if exclude_patterns is None:
            exclude_patterns = {
                "/ref/",
                "/reference/",
                "/context/",
                "/node_modules/",
                "/vendor/",
                "/__pycache__/",
                "/.git/",
                "/venv/",
                "/.venv/",
                "/env/",
                "/dist/",
                "/build/",
                "/.pytest_cache/",
            }

        graph = Graph()
        root = Path(path)
        self.last_summary = ParseSummary()

        # Pre-scan for import resolution.
        # Use os.walk with pruning so we don't traverse excluded directories.
        candidates: List[Path] = []
        root_abs = root.absolute()
        for dirpath, dirnames, filenames in os.walk(root_abs, topdown=True):
            dirpath_posix = str(dirpath).replace("\\", "/") + "/"
            if any(excl in dirpath_posix for excl in exclude_patterns):
                dirnames[:] = []
                continue

            kept: List[str] = []
            for d in dirnames:
                child = (Path(dirpath) / d).absolute()
                child_posix = str(child).replace("\\", "/") + "/"
                if any(excl in child_posix for excl in exclude_patterns):
                    continue
                kept.append(d)
            dirnames[:] = kept

            for name in filenames:
                file_path = Path(dirpath) / name
                if file_path.suffix.lower() not in extensions:
                    continue
                path_str = str(file_path).replace("\\", "/")
                if any(excl in path_str for excl in exclude_patterns):
                    continue
                candidates.append(file_path)

        self._known_module_labels = set()
        for fp in candidates:
            try:
                rel = str(fp.relative_to(root)).replace("\\", "/")
            except ValueError:
                rel = fp.name
            self._known_module_labels.add(normalize_path(rel))

        # Parse files
        for file_path in candidates:
            self._parse_file(file_path, root, graph)
        graph.rebuild_indexes()
        return graph

    def parse_file(self, path: str) -> Graph:
        """Parse a single file."""
        graph = Graph()
        file_path = Path(path)
        self.last_summary = ParseSummary()
        self._known_module_labels = {file_path.name}

        self._parse_file(file_path, file_path.parent, graph)
        graph.rebuild_indexes()
        return graph

    def _parse_file(self, file_path: Path, root: Path, graph: Graph) -> None:
        """Parse a single file into the graph."""
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception:
            self.last_summary.add_skip(file_path, "decode")
            return

        try:
            file_label = str(file_path.relative_to(root)).replace("\\", "/")
        except ValueError:
            file_label = file_path.name
        file_label = normalize_path(file_label)

        lang = detect_language(str(file_path))
        if lang is None:
            ext = file_path.suffix.lstrip(".").lower()
            if ext in {"cc", "hh"}:
                lang = "c"
            else:
                lang = ext if ext else "other"

        module_id = make_module_id(normalize_path(file_label))
        graph.add_node(GraphNode(id=module_id, kind=NodeKind.MODULE, label=file_label, fsPath=str(file_path)))

        # Plain module import detection for languages not handled by `resolve_import_label()`.
        if lang == "c":
            self._detect_includes_c(text, module_id, file_label, graph)
        elif lang == "sh":
            self._detect_sources_sh(text, module_id, file_label, graph)
        elif lang == "r":
            self._detect_sources_r(text, module_id, file_label, graph)

        used_lsp = False

        if self.use_lsp and has_lsp_support(lang):
            from .lsp import LSPError

            try:
                self._parse_with_lsp(file_path, file_label, text, lang, graph, module_id=module_id)
                used_lsp = True
            except LSPError as e:
                msg = str(e).lower()
                if "missing" in msg or "not found" in msg or "not supported" in msg:
                    category = "missing_server"
                elif "timed out" in msg:
                    category = "timeout"
                elif getattr(e, "code", None) is not None:
                    category = "protocol_error"
                else:
                    category = "lsp_error"
                self.last_summary.add_lsp_fallback(file_path, category, detail=str(e))
            except Exception as e:
                self.last_summary.add_lsp_fallback(file_path, "unknown", detail=type(e).__name__)

        parsed_ts = parse_source(text, file_path=file_path, lang_key=lang) if has_treesitter_support(lang) else None

        # Always compute import edges from tree-sitter (where supported).
        if parsed_ts is not None:
            import_specs = import_specs_from_parsed(parsed_ts)
            self._add_import_edges(module_id, file_label, lang, import_specs, graph)

        if used_lsp:
            self.last_summary.lsp_files += 1
            self.last_summary.parsed_files += 1
            return

        # Fallback to tree-sitter defs when LSP is unavailable.
        if parsed_ts is not None:
            defs = definitions_from_parsed(parsed_ts)
            self._add_def_nodes(module_id, file_label, str(file_path), text, defs, graph)
            self.last_summary.tree_sitter_files += 1

        self.last_summary.parsed_files += 1

    def _parse_with_lsp(
        self,
        file_path: Path,
        file_label: str,
        text: str,
        lang: str,
        graph: Graph,
        *,
        module_id: str,
    ) -> None:
        """Parse defs using LSP document symbols."""
        from .lsp import LSPError, get_lsp_runtime, get_lsp_session_manager, path_to_uri
        from .utils import find_workspace_root

        workspace = str(find_workspace_root(file_path))
        uri = path_to_uri(str(file_path))

        async def _fetch_symbols():
            mgr = get_lsp_session_manager()
            # LspSession routes to multilspy or fallback based on language
            sess = await mgr.get(lang=lang, workspace_root=workspace)
            return await sess.document_symbols(uri, text=text)

        symbols = get_lsp_runtime().run(_fetch_symbols())

        lines = text.split("\n")

        self._process_lsp_symbols(symbols, module_id, file_label, str(file_path), lines, graph)

    def _process_lsp_symbols(
        self,
        symbols,
        module_id: str,
        file_label: str,
        fs_path: str,
        lines: List[str],
        graph: Graph,
        parent_class: Optional[str] = None,
        class_ids: Optional[Dict[str, str]] = None,
    ) -> None:
        """Process LSP DocumentSymbol tree into graph nodes."""
        from lsprotocol.types import SymbolKind

        if not symbols:
            return

        if class_ids is None:
            class_ids = {}

        def snippet_from(line: int, span: int = 20) -> str:
            end = min(len(lines), line + span)
            return "\n".join(lines[line:end])

        for sym in symbols:
            kind = sym.kind
            name = sym.name
            line = sym.range.start.line

            if kind == SymbolKind.Class:
                class_id = make_class_id(file_label, name)
                class_ids[name] = class_id
                start = sym.range.start
                end = sym.range.end
                graph.add_node(
                    GraphNode(
                        id=class_id,
                        kind=NodeKind.CLASS,
                        label=name,
                        fsPath=fs_path,
                        parent=module_id,
                        snippet=snippet_from(line),
                        start_line=start.line,
                        start_char=start.character,
                        end_line=end.line,
                        end_char=end.character,
                    )
                )
                # Recurse into children
                if hasattr(sym, "children") and sym.children:
                    self._process_lsp_symbols(
                        sym.children,
                        module_id,
                        file_label,
                        fs_path,
                        lines,
                        graph,
                        parent_class=name,
                        class_ids=class_ids,
                    )

            elif kind in (SymbolKind.Function, SymbolKind.Method):
                start = sym.range.start
                end = sym.range.end
                sel = getattr(sym, "selection_range", None)
                id_line = sel.start.line if sel is not None else start.line
                func_id = make_func_id(file_label, name, id_line)
                if parent_class:
                    label = f"{parent_class}.{name}"
                    parent = class_ids.get(parent_class, module_id)
                else:
                    label = name
                    parent = module_id
                graph.add_node(
                    GraphNode(
                        id=func_id,
                        kind=NodeKind.FUNC,
                        label=label,
                        fsPath=fs_path,
                        parent=parent,
                        snippet=snippet_from(line),
                        start_line=start.line,
                        start_char=start.character,
                        end_line=end.line,
                        end_char=end.character,
                    )
                )

    def _add_def_nodes(
        self,
        module_id: str,
        file_label: str,
        fs_path: str,
        text: str,
        defs,
        graph: Graph,
    ) -> None:
        lines = text.split("\n")

        def snippet_from(line: int, span: int = 20) -> str:
            end = min(len(lines), max(0, line) + span)
            return "\n".join(lines[max(0, line) : end])

        class_ids: Dict[str, str] = {}
        for d in defs:
            if getattr(d, "kind", None) != "class":
                continue
            class_name = str(getattr(d, "bare_name", ""))
            if not class_name:
                continue

            class_id = make_class_id(file_label, class_name)
            class_ids[class_name] = class_id
            r = d.range
            graph.add_node(
                GraphNode(
                    id=class_id,
                    kind=NodeKind.CLASS,
                    label=class_name,
                    fsPath=fs_path,
                    parent=module_id,
                    snippet=snippet_from(r.start_line),
                    start_line=r.start_line,
                    start_char=r.start_char,
                    end_line=r.end_line,
                    end_char=r.end_char,
                )
            )

        for d in defs:
            if getattr(d, "kind", None) != "func":
                continue
            bare = str(getattr(d, "bare_name", ""))
            if not bare:
                continue

            r = d.range
            parent_class = getattr(d, "parent_class", None)
            parent = class_ids.get(parent_class) if parent_class else module_id
            label = str(getattr(d, "name", bare))
            func_id = make_func_id(file_label, bare, r.start_line)
            graph.add_node(
                GraphNode(
                    id=func_id,
                    kind=NodeKind.FUNC,
                    label=label,
                    fsPath=fs_path,
                    parent=parent,
                    snippet=snippet_from(r.start_line),
                    start_line=r.start_line,
                    start_char=r.start_char,
                    end_line=r.end_line,
                    end_char=r.end_char,
                )
            )

    def _add_import_edges(
        self,
        module_id: str,
        file_label: str,
        lang: str,
        import_specs: List[str],
        graph: Graph,
    ) -> None:
        for spec in import_specs:
            spec = (spec or "").strip()
            if not spec:
                continue

            label = resolve_import_label(file_label, spec, lang)
            if not label:
                continue

            if lang == "py" and label.endswith(".py") and label not in self._known_module_labels:
                pkg_label = label[:-3] + "/__init__.py"
                if pkg_label in self._known_module_labels:
                    label = pkg_label

            if lang == "ts" and label not in self._known_module_labels:
                base = re.sub(r"\.(ts|tsx|js|jsx)$", "", label, flags=re.IGNORECASE)
                candidates = [
                    *(base + ext for ext in (".ts", ".tsx", ".js", ".jsx")),
                    *(base + "/index" + ext for ext in (".ts", ".tsx", ".js", ".jsx")),
                ]
                label = next((c for c in candidates if c in self._known_module_labels), label)

            if label not in self._known_module_labels:
                continue

            graph.add_edge(GraphEdge(from_id=module_id, to_id=make_module_id(label), type=EdgeType.IMPORT))

    def _detect_includes_c(self, text: str, module_id: str, file_label: str, graph: Graph) -> None:
        """Detect C/C++ #include directives."""
        stripped = strip_strings_and_comments(text)
        pat = re.compile(r"^\s*#\s*include\s+[<\"]([^>\"]+)[>\"]", re.MULTILINE)
        for m in pat.finditer(stripped):
            inc = (m.group(1) or "").strip()
            if not inc:
                continue
            label = self._resolve_relative_file(file_label, inc)
            if label and label in self._known_module_labels:
                graph.add_edge(
                    GraphEdge(
                        from_id=module_id,
                        to_id=make_module_id(label),
                        type=EdgeType.IMPORT,
                    )
                )

    def _detect_sources_sh(self, text: str, module_id: str, file_label: str, graph: Graph) -> None:
        """Detect shell source commands."""
        stripped = strip_strings_and_comments(text)
        pat = re.compile(r"^(?:\s*source\s+|\s*\.\s+)([^\s]+)", re.MULTILINE)
        for m in pat.finditer(stripped):
            spec = (m.group(1) or "").strip().strip("\"'")
            label = self._resolve_relative_file(file_label, spec)
            if label and label in self._known_module_labels:
                graph.add_edge(
                    GraphEdge(
                        from_id=module_id,
                        to_id=make_module_id(label),
                        type=EdgeType.IMPORT,
                    )
                )

    def _detect_sources_r(self, text: str, module_id: str, file_label: str, graph: Graph) -> None:
        """Detect R source() calls."""
        stripped = strip_strings_and_comments(text)
        pat = re.compile(r"\bsource\(\s*[\"\']([^\"\']+)[\"\']\s*\)")
        for m in pat.finditer(stripped):
            spec = (m.group(1) or "").strip()
            label = self._resolve_relative_file(file_label, spec)
            if label and label in self._known_module_labels:
                graph.add_edge(
                    GraphEdge(
                        from_id=module_id,
                        to_id=make_module_id(label),
                        type=EdgeType.IMPORT,
                    )
                )

    def _resolve_relative_file(self, from_label: str, spec: str) -> Optional[str]:
        """Resolve relative file path to module label."""
        if not spec or spec.startswith("<"):
            return None
        if spec.startswith("/"):
            spec = spec.lstrip("/")

        posix_from = from_label.replace("\\", "/")
        base_dir = posix_from.rsplit("/", 1)[0] if "/" in posix_from else ""
        candidate = normalize_path((base_dir + "/" if base_dir else "") + spec)

        if candidate in self._known_module_labels:
            return candidate

        if not Path(candidate).suffix:
            for ext in (".h", ".hh", ".hpp", ".c", ".cc", ".cpp"):
                cand2 = candidate + ext
                if cand2 in self._known_module_labels:
                    return cand2
        return None


__all__ = ["Parser", "ParseSummary"]
