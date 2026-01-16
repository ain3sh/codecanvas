from __future__ import annotations

import os
import time
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, cast

from ..core.models import EdgeType, GraphEdge, GraphNode, NodeKind
from .config import detect_language, has_lsp_support
from .lsp import get_lsp_runtime, get_lsp_session_manager, path_to_uri, uri_to_path
from .treesitter import TsCallSite, extract_call_sites
from .utils import find_workspace_root


@dataclass
class CallGraphBuildResult:
    edges: List[GraphEdge] = field(default_factory=list)
    considered_files: int = 0
    processed_callsites: int = 0
    resolved_callsites: int = 0
    skipped_no_caller: int = 0
    skipped_no_definition: int = 0
    skipped_no_callee: int = 0
    skipped_no_callee_reasons: Dict[str, int] = field(default_factory=dict)
    skipped_no_callee_samples: List[Dict[str, object]] = field(default_factory=list)
    lsp_failures: Dict[str, int] = field(default_factory=dict)
    complete: bool = False
    duration_s: float = 0.0


@dataclass(frozen=True)
class FileSymbolIndex:
    funcs: List[GraphNode]
    starts: List[Tuple[int, int]]

    @classmethod
    def from_nodes(cls, nodes: Sequence[GraphNode]) -> "FileSymbolIndex":
        funcs = [n for n in nodes if n.kind == NodeKind.FUNC and n.start_line is not None and n.end_line is not None]
        funcs.sort(key=lambda n: (int(n.start_line or 0), int(n.start_char or 0)))
        starts = [(int(n.start_line or 0), int(n.start_char or 0)) for n in funcs]
        return cls(funcs=funcs, starts=starts)

    def find_enclosing_func(self, *, line: int, char: int) -> Optional[GraphNode]:
        if not self.funcs:
            return None

        idx = bisect_right(self.starts, (int(line), int(char))) - 1
        if idx < 0:
            return None

        cand = self.funcs[idx]
        if _node_contains(cand, line=int(line), char=int(char)):
            return cand

        # Defensive: tolerate rare range overlaps by scanning a few earlier starts.
        for j in range(idx - 1, max(-1, idx - 8), -1):
            n = self.funcs[j]
            if _node_contains(n, line=int(line), char=int(char)):
                return n
            if n.end_line is not None and int(line) > int(n.end_line):
                break
        return None


def _abs(path: str) -> str:
    try:
        return os.path.abspath(path)
    except Exception:
        return path


def _lang_key(file_path: Path) -> Optional[str]:
    lang = detect_language(str(file_path))
    if lang is not None:
        return lang

    ext = file_path.suffix.lstrip(".").lower()
    if ext in {"cc", "hh"}:
        return "c"
    return ext or None


def _safe_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _node_contains(node: GraphNode, *, line: int, char: int) -> bool:
    if node.start_line is None or node.end_line is None:
        return False
    if line < node.start_line or line > node.end_line:
        return False
    if line == node.start_line and node.start_char is not None and char < node.start_char:
        return False
    if line == node.end_line and node.end_char is not None and char > node.end_char:
        return False
    return True


def _build_func_index(nodes: Sequence[GraphNode]) -> Dict[str, FileSymbolIndex]:
    by_file: Dict[str, List[GraphNode]] = {}
    for n in nodes:
        if n.kind != NodeKind.FUNC:
            continue
        if n.start_line is None or n.end_line is None:
            continue
        by_file.setdefault(_abs(n.fsPath), []).append(n)

    return {p: FileSymbolIndex.from_nodes(funcs) for p, funcs in by_file.items()}


async def _resolve_definitions_for_callsites(
    *,
    lang: str,
    file_path: Path,
    text: str,
    callsites: List[TsCallSite],
) -> List[object]:
    """Resolve definition locations for callsites using LSP."""
    mgr = get_lsp_session_manager()
    workspace_root = find_workspace_root(file_path)

    # LspSession routes to multilspy or custom backend based on language
    sess = await mgr.get(lang=lang, workspace_root=str(workspace_root))

    uri = path_to_uri(str(file_path))
    positions = [(cs.line, cs.char) for cs in callsites]
    return await sess.definitions(uri, positions=positions, text=text)


def build_call_graph_edges(
    graph_nodes: Sequence[GraphNode],
    *,
    time_budget_s: float,
    max_callsites_total: int = 500,
    max_callsites_per_file: int = 100,
    lsp_langs: set[str] | None = None,
    limit_to_paths: set[str] | None = None,
    should_continue: Callable[[], bool] | None = None,
) -> CallGraphBuildResult:
    """Build CALL edges using tree-sitter callsites + LSP definition resolution.

    This function never mutates the graph.
    """

    start = time.monotonic()
    res = CallGraphBuildResult()

    func_index = _build_func_index(graph_nodes)
    modules = [n for n in graph_nodes if n.kind == NodeKind.MODULE]
    limit_abs: set[str] | None = None
    if limit_to_paths:
        limit_abs = {_abs(p) for p in limit_to_paths}

    seen_edge_keys: set[str] = set()
    remaining_total = max(0, int(max_callsites_total))

    def _allow_lsp(lang: str) -> bool:
        return True if lsp_langs is None else (lang in lsp_langs)

    def _ok() -> bool:
        return True if should_continue is None else bool(should_continue())

    for mod in modules:
        if not _ok():
            break
        if time_budget_s and (time.monotonic() - start) >= time_budget_s:
            break
        if remaining_total <= 0:
            break

        if limit_abs is not None and _abs(mod.fsPath) not in limit_abs:
            continue

        file_path = Path(mod.fsPath)
        if not file_path.exists() or not file_path.is_file():
            continue

        if not _ok():
            break

        lang = _lang_key(file_path)
        if not lang or not has_lsp_support(lang) or not _allow_lsp(lang):
            continue

        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception:
            continue

        if not _ok():
            break

        callsites = extract_call_sites(text, file_path=file_path, lang_key=lang)
        if not callsites:
            continue

        res.considered_files += 1

        # Map callsites -> caller funcs up-front.
        file_index = func_index.get(_abs(mod.fsPath))
        pairs: List[Tuple[TsCallSite, GraphNode]] = []
        for cs in callsites[:max_callsites_per_file]:
            if remaining_total <= 0:
                break
            if file_index is None:
                res.skipped_no_caller += 1
                continue
            caller = file_index.find_enclosing_func(line=cs.line, char=cs.char)
            if caller is None:
                res.skipped_no_caller += 1
                continue
            pairs.append((cs, caller))
            remaining_total -= 1

        if not pairs:
            continue

        if not _ok():
            break

        # Resolve definitions (bounded by remaining time budget).
        remaining_s = None
        if time_budget_s:
            remaining_s = max(0.0, time_budget_s - (time.monotonic() - start))
            if remaining_s <= 0.0:
                break

        try:
            coro = _resolve_definitions_for_callsites(
                lang=lang,
                file_path=file_path,
                text=text,
                callsites=[cs for (cs, _caller) in pairs],
            )
            results = get_lsp_runtime().run(coro, timeout=remaining_s)
        except Exception as e:
            key = type(e).__name__
            res.lsp_failures[key] = res.lsp_failures.get(key, 0) + 1
            continue

        res.processed_callsites += len(pairs)

        for (cs, caller), def_result in zip(pairs, results):
            if isinstance(def_result, Exception):
                key = type(def_result).__name__
                res.lsp_failures[key] = res.lsp_failures.get(key, 0) + 1
                res.skipped_no_definition += 1
                continue

            if isinstance(def_result, dict):
                locations_iter: List[object] = [def_result]
            elif isinstance(def_result, list):
                locations_iter = def_result
            else:
                res.skipped_no_definition += 1
                continue

            if not locations_iter:
                res.skipped_no_definition += 1
                continue

            res.resolved_callsites += 1

            added = False
            reasons: set[str] = set()
            uris_seen: List[str] = []
            for loc in locations_iter:
                if not isinstance(loc, dict):
                    reasons.add("non_dict_location")
                    continue

                loc_dict = cast(Dict[str, Any], loc)
                target_uri = loc_dict.get("uri")
                if not target_uri:
                    reasons.add("missing_uri")
                    continue
                try:
                    uris_seen.append(str(target_uri))
                except Exception:
                    pass
                target_path = uri_to_path(str(target_uri))
                target_index = func_index.get(_abs(target_path))
                if target_index is None:
                    reasons.add("target_not_indexed")
                    continue

                r = loc_dict.get("range") or {}
                r_dict = cast(Dict[str, Any], r) if isinstance(r, dict) else {}
                start_pos = r_dict.get("start") or {}
                if not isinstance(start_pos, dict):
                    reasons.add("missing_range")
                    continue

                start_pos_dict = cast(Dict[str, Any], start_pos)

                dl = _safe_int(start_pos_dict.get("line"))
                dc = _safe_int(start_pos_dict.get("character"))
                if dl is None or dc is None:
                    reasons.add("missing_range")
                    continue

                callee = target_index.find_enclosing_func(line=dl, char=dc)
                if callee is None:
                    reasons.add("no_enclosing_func")
                    continue

                edge = GraphEdge(from_id=caller.id, to_id=callee.id, type=EdgeType.CALL)
                ek = edge.key()
                if ek in seen_edge_keys:
                    added = True
                    break
                seen_edge_keys.add(ek)
                res.edges.append(edge)
                added = True
                break

            if not added:
                res.skipped_no_callee += 1
                primary = None
                for k in [
                    "target_not_indexed",
                    "no_enclosing_func",
                    "missing_range",
                    "missing_uri",
                    "non_dict_location",
                ]:
                    if k in reasons:
                        primary = k
                        break
                if primary is None:
                    primary = "unknown"

                res.skipped_no_callee_reasons[primary] = res.skipped_no_callee_reasons.get(primary, 0) + 1

                if len(res.skipped_no_callee_samples) < 20:
                    res.skipped_no_callee_samples.append(
                        {
                            "reason": primary,
                            "caller_id": caller.id,
                            "caller_path": caller.fsPath,
                            "callsite": {"line": int(cs.line), "char": int(cs.char)},
                            "definition_uris": uris_seen[:5],
                        }
                    )

    res.complete = remaining_total <= 0
    res.duration_s = time.monotonic() - start
    return res
