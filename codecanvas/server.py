"""CodeCanvas action API.

This is intentionally explicit (no backwards-compat shims): callers provide an
`action` and corresponding parameters.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Set

from .core.analysis import Analyzer
from .core.graph_meta import load_graph_meta
from .core.lock import canvas_artifact_lock
from .core.models import EdgeType, Graph, GraphEdge, NodeKind
from .core.paths import get_canvas_dir, top_level_project_roots
from .core.refresh import mark_dirty, take_dirty
from .core.snapshot import (
    build_snapshot,
    call_edges_digest_path,
    flip_call_edges_pointer,
    flip_snapshot_pointers,
    write_call_edges_digest,
    write_snapshot_files,
)
from .core.state import AnalysisState, CanvasState, clear_state, load_state, load_tasks_yaml, pick_task, save_state
from .parser import Parser
from .parser.call_graph import build_call_graph_edges
from .parser.utils import find_workspace_root
from .views import save_png
from .views.impact import ImpactView
from .views.task import TaskView


@dataclass(frozen=True)
class CanvasImage:
    name: str
    png_path: str
    png_bytes: bytes


@dataclass(frozen=True)
class CanvasResult:
    text: str
    images: List[CanvasImage] = field(default_factory=list)


_graph: Optional[Graph] = None
_analyzer: Optional[Analyzer] = None
_graph_digest: str | None = None

_graph_lock = threading.RLock()

_call_graph_status: str = "idle"  # idle|working|completed|error
_call_graph_error: str | None = None
_call_graph_last: dict | None = None
_call_graph_thread: threading.Thread | None = None
_call_graph_generation: int = 0
_call_graph_edges_total: int = 0
_call_graph_result_summary: dict | None = None  # Detailed result for diagnostics
_call_graph_cache_info: dict | None = None

_SERVER_INSTANCE_ID = uuid.uuid4().hex
_CALL_EDGE_CACHE_VERSION = 3
_CALL_EDGE_CACHE_NAME = "call_edges.json"


def _normalize_project_path(project_dir: Path) -> str:
    try:
        return str(project_dir.resolve())
    except Exception:
        return str(project_dir)


def _call_edge_cache_path(project_dir: Path, *, digest: str | None = None) -> Path:
    if digest:
        return call_edges_digest_path(project_dir, digest)
    return get_canvas_dir(project_dir) / _CALL_EDGE_CACHE_NAME


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def _load_call_edge_cache(project_dir: Path, *, expected_digest: str | None) -> tuple[list[GraphEdge], dict]:
    paths: list[Path] = []
    if expected_digest:
        paths.append(_call_edge_cache_path(project_dir, digest=expected_digest))
    paths.append(_call_edge_cache_path(project_dir))

    for path in paths:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if int(data.get("version", 0) or 0) != _CALL_EDGE_CACHE_VERSION:
            continue
        cached_project = data.get("project_path")
        if cached_project:
            cached_path = _normalize_project_path(Path(str(cached_project)))
            if cached_path != _normalize_project_path(project_dir):
                continue
        cache_digest = data.get("graph_digest")
        if expected_digest and cache_digest != expected_digest:
            continue
        edges_raw = data.get("edges") or []
        edges: list[GraphEdge] = []
        for item in edges_raw:
            if not isinstance(item, dict):
                continue
            from_id = item.get("from_id")
            to_id = item.get("to_id")
            if not from_id or not to_id:
                continue
            edges.append(GraphEdge(from_id=str(from_id), to_id=str(to_id), type=EdgeType.CALL))
        meta = {
            "cache_path": str(path),
            "cache_edges_total": len(edges),
            "cache_generated_at": data.get("generated_at"),
            "cache_generation": data.get("generation"),
            "cache_source": data.get("source"),
            "cache_graph_digest": cache_digest,
        }
        return edges, meta

    return [], {}


def _merge_cached_call_edges(graph: Graph, project_dir: Path, *, expected_digest: str | None) -> dict | None:
    edges, meta = _load_call_edge_cache(project_dir, expected_digest=expected_digest)
    if not edges:
        return None
    added = 0
    missing_nodes = 0
    for edge in edges:
        if graph.get_node(edge.from_id) is None or graph.get_node(edge.to_id) is None:
            missing_nodes += 1
            continue
        if graph.add_edge(edge):
            added += 1
    meta["cache_edges_added"] = int(added)
    meta["cache_edges_missing_nodes"] = int(missing_nodes)
    return meta


def _persist_call_edge_cache(
    graph: Graph,
    project_dir: Path,
    *,
    generation: int | None,
    source: str,
    graph_digest: str | None,
) -> None:
    try:
        if not graph_digest:
            return
        edges_payload: list[dict[str, str]] = []
        for edge in graph.edges:
            if edge.type != EdgeType.CALL:
                continue
            if graph.get_node(edge.from_id) is None or graph.get_node(edge.to_id) is None:
                continue
            edges_payload.append({"from_id": edge.from_id, "to_id": edge.to_id})
        payload = {
            "version": _CALL_EDGE_CACHE_VERSION,
            "project_path": _normalize_project_path(project_dir),
            "generated_at": time.time(),
            "generation": int(generation) if generation is not None else None,
            "source": str(source),
            "instance_id": _SERVER_INSTANCE_ID,
            "graph_digest": graph_digest,
            "edges": edges_payload,
            "stats": {"edges_total": len(edges_payload)},
        }
        write_call_edges_digest(project_dir, graph_digest, payload)
        pointer_written = flip_call_edges_pointer(project_dir, digest=graph_digest, payload=payload)
        if pointer_written:
            try:
                state = load_state()
                if state.initialized:
                    state.call_edges_digest = graph_digest
                    _save_state_with_lock(state)
            except Exception:
                pass
    except Exception:
        return


def _abs_path(path: str | Path) -> str:
    try:
        return str(Path(path).resolve())
    except Exception:
        return str(path)


def _label_strip_prefix(project_dir: Path) -> str | None:
    try:
        roots = top_level_project_roots(project_dir.absolute())
        if len(roots) == 1:
            prefix = (roots[0].name or "").strip("/")
            return prefix or None
    except Exception:
        return None
    return None


def _compute_graph_meta(
    *,
    state: CanvasState,
    parser_summary: dict | None,
    action: str,
) -> dict | None:
    global _graph_digest
    if _graph is None or not state.project_path:
        return None
    project_dir = Path(state.project_path)
    existing_meta = load_graph_meta(project_dir)
    parse_summary = parser_summary or (state.parse_summary or {})
    label_prefix = _label_strip_prefix(project_dir)
    snapshot = build_snapshot(
        graph=_graph,
        project_dir=project_dir,
        parse_summary=parse_summary,
        use_lsp=bool(getattr(state, "use_lsp", True)),
        lsp_langs=parse_summary.get("lsp_langs") if isinstance(parse_summary, dict) else None,
        label_strip_prefix=label_prefix,
        action=action,
        existing_meta=existing_meta,
    )
    if snapshot.digest:
        _graph_digest = snapshot.digest
        write_snapshot_files(project_dir, snapshot)
        flip_snapshot_pointers(project_dir, snapshot)
    return snapshot.meta


def _reconcile_state_from_meta(state: CanvasState, meta: dict) -> bool:
    changed = False
    if not isinstance(meta, dict):
        return False

    graph_info = meta.get("graph") if isinstance(meta, dict) else None
    if not isinstance(graph_info, dict):
        graph_info = {}
    digest = graph_info.get("digest")
    if digest and digest != state.graph_digest:
        state.graph_digest = str(digest)
        changed = True
    symbol_files = graph_info.get("symbol_files")
    if isinstance(symbol_files, dict) and symbol_files != state.symbol_files:
        state.symbol_files = dict(symbol_files)
        changed = True

    stats = graph_info.get("stats") if isinstance(graph_info, dict) else {}
    modules = stats.get("modules") if isinstance(stats, dict) else None
    classes = stats.get("classes") if isinstance(stats, dict) else None
    funcs = stats.get("funcs") if isinstance(stats, dict) else None

    arch_path = ""
    if state.project_path:
        arch_path = str(get_canvas_dir(Path(state.project_path)) / "architecture.png")

    arch_ev = None
    for ev in state.evidence:
        if ev.kind == "architecture":
            arch_ev = ev
            break
    if arch_ev is None:
        metrics = {}
        if modules is not None:
            metrics["modules"] = modules
        if classes is not None:
            metrics["classes"] = classes
        if funcs is not None:
            metrics["funcs"] = funcs
        state.add_evidence(kind="architecture", png_path=arch_path, symbol=None, metrics=metrics)
        changed = True
    else:
        if arch_path and arch_ev.png_path != arch_path:
            arch_ev.png_path = arch_path
            changed = True
        if isinstance(arch_ev.metrics, dict):
            new_metrics = dict(arch_ev.metrics)
        else:
            new_metrics = {}
        if modules is not None:
            new_metrics["modules"] = modules
        if classes is not None:
            new_metrics["classes"] = classes
        if funcs is not None:
            new_metrics["funcs"] = funcs
        if new_metrics != (arch_ev.metrics or {}):
            arch_ev.metrics = new_metrics
            changed = True
    return changed


def _save_state_with_lock(state: CanvasState) -> None:
    if not state.project_path:
        save_state(state)
        return
    project_dir = Path(state.project_path)
    with canvas_artifact_lock(project_dir, timeout_s=5.0) as locked:
        if locked:
            save_state(state)
            return
    save_state(state)


def _module_labels_from_graph(graph: Graph) -> Set[str]:
    return {n.label for n in graph.nodes if n.kind == NodeKind.MODULE}


def _module_ids_for_paths(graph: Graph, paths: Iterable[str]) -> Set[str]:
    targets = {_abs_path(p) for p in paths}
    return {n.id for n in graph.nodes if n.kind == NodeKind.MODULE and _abs_path(n.fsPath) in targets}


def _importer_paths_for_modules(graph: Graph, module_ids: Set[str]) -> Set[str]:
    if not module_ids:
        return set()
    out: Set[str] = set()
    for edge in graph.edges:
        if edge.type != EdgeType.IMPORT or edge.to_id not in module_ids:
            continue
        node = graph.get_node(edge.from_id)
        if node is not None:
            out.add(node.fsPath)
    return out


def _func_ids_for_paths(graph: Graph, paths: Iterable[str]) -> Set[str]:
    targets = {_abs_path(p) for p in paths}
    return {n.id for n in graph.nodes if n.kind == NodeKind.FUNC and _abs_path(n.fsPath) in targets}


def _refresh_graph_for_dirty_files(
    state: CanvasState,
    *,
    reason: str,
    max_files: int = 6,
    defs_budget_s: float = 0.6,
    calls_budget_s: float = 1.2,
) -> dict | None:
    global _call_graph_edges_total
    if not state.project_path:
        return None

    project_dir = Path(state.project_path)
    dirty_items = take_dirty(project_dir, max_items=max_files)
    if not dirty_items:
        return None

    start = time.monotonic()
    processed_paths: list[str] = []
    skipped_paths: list[str] = []
    removed_node_ids: Set[str] = set()
    defs_updated = 0
    nodes_added = 0
    edges_added = 0
    removed_call_edges = 0
    call_edges_added = 0
    call_edges_skipped_reason = None
    call_edges_skipped_at = None
    call_edges_refresh_ok = False

    lsp_langs = set(state.parse_summary.get("lsp_langs") or []) if state.parse_summary else None
    parser = Parser(use_lsp=state.use_lsp, lsp_langs=lsp_langs)
    prefix = _label_strip_prefix(project_dir)

    with _graph_lock:
        graph_ref = _graph
        if graph_ref is None:
            return None
        known_labels = _module_labels_from_graph(graph_ref)

    for item in dirty_items:
        if defs_budget_s and (time.monotonic() - start) >= defs_budget_s:
            skipped_paths.append(str(item.get("path") or ""))
            continue

        path_str = str(item.get("path") or "").strip()
        if not path_str:
            continue
        file_path = Path(path_str)

        with _graph_lock:
            removed_ids = graph_ref.remove_nodes_by_fs_path(str(file_path))
        removed_node_ids.update(removed_ids)

        if file_path.exists() and file_path.is_file():
            new_graph = parser.parse_file_in_project(
                file_path,
                root=project_dir,
                known_module_labels=known_labels,
                label_strip_prefix=prefix,
            )
            with _graph_lock:
                for node in new_graph.nodes:
                    if graph_ref.add_node(node):
                        nodes_added += 1
                for edge in new_graph.edges:
                    if graph_ref.add_edge(edge):
                        edges_added += 1
            for node in new_graph.nodes:
                if node.kind == NodeKind.MODULE:
                    known_labels.add(node.label)

        defs_updated += 1
        processed_paths.append(str(file_path))

    if skipped_paths:
        mark_dirty(project_dir, [Path(p) for p in skipped_paths if p], reason="refresh_deferred")

    if not processed_paths:
        return None

    with _graph_lock:
        if graph_ref is None:
            return None
        module_ids = _module_ids_for_paths(graph_ref, processed_paths)
        caller_paths = set(processed_paths)
        caller_paths |= _importer_paths_for_modules(graph_ref, module_ids)
        caller_func_ids = _func_ids_for_paths(graph_ref, caller_paths)
        removed_call_edges = graph_ref.remove_edges_by_predicate(
            lambda e: e.type == EdgeType.CALL
            and (e.from_id in caller_func_ids or e.to_id in removed_node_ids)
        )

        nodes_snapshot = list(graph_ref.nodes)

    if _call_graph_thread is not None and _call_graph_thread.is_alive():
        call_edges_skipped_reason = "call_graph_thread_active"
        call_edges_skipped_at = time.time()
    else:
        try:
            result = build_call_graph_edges(
                nodes_snapshot,
                time_budget_s=float(calls_budget_s),
                max_callsites_total=200,
                max_callsites_per_file=50,
                lsp_langs=lsp_langs,
                limit_to_paths={_abs_path(p) for p in caller_paths},
            )
            with _graph_lock:
                if graph_ref is not None:
                    for edge in result.edges:
                        if graph_ref.add_edge(edge):
                            call_edges_added += 1
                    _call_graph_edges_total = sum(1 for e in graph_ref.edges if e.type == EdgeType.CALL)
                    _persist_call_edge_cache(
                        graph_ref,
                        project_dir,
                        generation=_call_graph_generation,
                        source="refresh",
                        graph_digest=_graph_digest,
                    )
                    call_edges_refresh_ok = True
        except Exception as e:
            call_edges_skipped_reason = f"error:{type(e).__name__}"
            call_edges_skipped_at = time.time()

    meta = _compute_graph_meta(state=state, parser_summary=state.parse_summary, action="refresh")
    if meta is not None and _graph is not None:
        _reconcile_state_from_meta(state, meta)

    summary = {
        "updated_at": time.time(),
        "reason": str(reason),
        "dirty_count": len(dirty_items),
        "defs_updated_files": defs_updated,
        "call_edges_updated_files": len(caller_paths),
        "nodes_added": nodes_added,
        "edges_added": edges_added,
        "call_edges_removed": removed_call_edges,
        "call_edges_added": call_edges_added,
        "skipped_paths": skipped_paths,
    }
    metrics = dict(state.refresh_metrics or {})
    metrics.setdefault("refresh_total", 0)
    metrics["refresh_total"] += 1
    if call_edges_refresh_ok:
        metrics.setdefault("call_edges_refresh_ok", 0)
        metrics["call_edges_refresh_ok"] += 1
        metrics["last_call_edges_refresh_ok_at"] = time.time()
    if call_edges_skipped_reason:
        metrics.setdefault("call_edges_skipped_total", 0)
        metrics["call_edges_skipped_total"] += 1
        metrics["last_call_edges_skipped_reason"] = call_edges_skipped_reason
        metrics["last_call_edges_skipped_at"] = call_edges_skipped_at or time.time()
    state.refresh_metrics = metrics
    if call_edges_skipped_reason:
        summary["call_edges_skipped"] = call_edges_skipped_reason
        if call_edges_skipped_at is not None:
            summary["call_edges_skipped_at"] = call_edges_skipped_at
    summary["refresh_metrics"] = metrics

    return summary


def _call_graph_diag(*, phase: str | None = None) -> dict:
    """Build a durable diagnostic snapshot for post-hoc inspection.

    This is intended to be persisted to .codecanvas/state.json (and Harbor extraction).
    """
    thread_alive = bool(_call_graph_thread and _call_graph_thread.is_alive())
    return {
        "pid": int(os.getpid()),
        "instance_id": _SERVER_INSTANCE_ID,
        "updated_at": time.time(),
        "generation": int(_call_graph_generation),
        "status": str(_call_graph_status),
        "error": _call_graph_error,
        "edges_total": int(_call_graph_edges_total),
        "thread_alive": thread_alive,
        "phase": phase,
        "last": dict(_call_graph_last or {}),
        "result": dict(_call_graph_result_summary or {}),
    }


def _persist_call_graph_diag(diag: dict) -> None:
    """Best-effort persist of call graph diagnostics to disk.

    Safe to call from background threads.
    """
    try:
        state = load_state()
        if not state.initialized:
            return
        # Only update the diagnostic field; preserve everything else.
        state.call_graph_summary = dict(diag)
        save_state(state)
    except Exception:
        return


def _build_call_graph_foreground(
    *,
    time_budget_s: float,
    generation: int,
    lsp_langs: set[str] | None = None,
    project_dir: Path | None = None,
) -> int:
    global _graph
    global _call_graph_status, _call_graph_error, _call_graph_last
    global _call_graph_edges_total, _call_graph_result_summary
    if _graph is None:
        return 0

    cache_info = dict(_call_graph_cache_info) if _call_graph_cache_info else None

    with _graph_lock:
        graph_ref = _graph
        nodes_snapshot = list(_graph.nodes)

    try:
        if generation == _call_graph_generation:
            _call_graph_status = "working"
            _call_graph_error = None
            _call_graph_result_summary = {
                "phase": "foreground",
                "time_budget_s": float(time_budget_s),
                "max_callsites_total": 250,
                "max_callsites_per_file": 50,
            }
            if cache_info:
                _call_graph_result_summary["cache"] = cache_info
        result = build_call_graph_edges(
            nodes_snapshot,
            time_budget_s=float(time_budget_s),
            max_callsites_total=250,
            max_callsites_per_file=50,
            lsp_langs=lsp_langs,
            should_continue=lambda: generation == _call_graph_generation,
        )
    except Exception as e:
        if generation == _call_graph_generation:
            _call_graph_status = "error"
            _call_graph_error = f"{type(e).__name__}: {e}"
            _call_graph_result_summary = {
                "phase": "foreground",
                "time_budget_s": float(time_budget_s),
                "error": f"{type(e).__name__}: {e}",
            }
            if cache_info:
                _call_graph_result_summary["cache"] = cache_info
            _persist_call_graph_diag(_call_graph_diag(phase="foreground"))
        return 0

    added = 0
    with _graph_lock:
        if _graph is not graph_ref:
            return 0
        for edge in result.edges:
            if _graph.add_edge(edge):
                added += 1
        _call_graph_edges_total += added
        if generation == _call_graph_generation:
            _call_graph_last = {"edges": int(_call_graph_edges_total), "duration_s": result.duration_s}
            _call_graph_result_summary = {
                "phase": "foreground",
                "time_budget_s": float(time_budget_s),
                "max_callsites_total": 250,
                "max_callsites_per_file": 50,
                "considered_files": result.considered_files,
                "processed_callsites": result.processed_callsites,
                "resolved_callsites": result.resolved_callsites,
                "skipped_no_caller": result.skipped_no_caller,
                "skipped_no_definition": result.skipped_no_definition,
                "skipped_no_callee": result.skipped_no_callee,
                "skipped_no_callee_reasons": dict(result.skipped_no_callee_reasons),
                "skipped_no_callee_samples": list(result.skipped_no_callee_samples),
                "edges_in_result": len(result.edges),
                "edges_added": int(added),
                "edges_total": int(_call_graph_edges_total),
                "lsp_failures": dict(result.lsp_failures),
                "duration_s": result.duration_s,
            }
            if cache_info:
                _call_graph_result_summary["cache"] = cache_info
            _persist_call_graph_diag(_call_graph_diag(phase="foreground"))
            if project_dir is not None:
                _persist_call_edge_cache(
                    _graph,
                    project_dir,
                    generation=generation,
                    source="foreground",
                    graph_digest=_graph_digest,
                )

    return added


def _start_call_graph_background(
    *,
    time_budget_s: float,
    generation: int,
    lsp_langs: set[str] | None = None,
    project_dir: Path | None = None,
) -> None:
    global _graph, _call_graph_status, _call_graph_error, _call_graph_last, _call_graph_thread, _call_graph_edges_total
    if _graph is None:
        return

    with _graph_lock:
        graph_ref = _graph
        nodes_snapshot = list(_graph.nodes)

    def _worker() -> None:
        global _graph
        global _call_graph_status, _call_graph_error, _call_graph_last
        global _call_graph_edges_total, _call_graph_result_summary
        cache_info = dict(_call_graph_cache_info) if _call_graph_cache_info else None

        try:
            if generation == _call_graph_generation:
                _call_graph_status = "working"
                _call_graph_error = None
                _call_graph_result_summary = {
                    "phase": "background",
                    "time_budget_s": float(time_budget_s),
                    "max_callsites_total": 2000,
                    "max_callsites_per_file": 200,
                }
                if cache_info:
                    _call_graph_result_summary["cache"] = cache_info
                _persist_call_graph_diag(_call_graph_diag(phase="background"))
            result = build_call_graph_edges(
                nodes_snapshot,
                time_budget_s=float(time_budget_s),
                max_callsites_total=2000,
                max_callsites_per_file=200,
                lsp_langs=lsp_langs,
                should_continue=lambda: generation == _call_graph_generation,
            )
        except Exception as e:
            if generation == _call_graph_generation:
                _call_graph_status = "error"
                _call_graph_error = f"{type(e).__name__}: {e}"
                _call_graph_result_summary = {
                    "phase": "background",
                    "time_budget_s": float(time_budget_s),
                    "error": f"{type(e).__name__}: {e}",
                }
                if cache_info:
                    _call_graph_result_summary["cache"] = cache_info
                _persist_call_graph_diag(_call_graph_diag(phase="background"))
            return

        with _graph_lock:
            if _graph is None or _graph is not graph_ref:
                return
            added = 0
            for edge in result.edges:
                if _graph.add_edge(edge):
                    added += 1
            _call_graph_edges_total += added
            if generation == _call_graph_generation:
                _call_graph_last = {"edges": int(_call_graph_edges_total), "duration_s": result.duration_s}
                _call_graph_status = "completed"
                _call_graph_result_summary = {
                    "phase": "background",
                    "time_budget_s": float(time_budget_s),
                    "max_callsites_total": 2000,
                    "max_callsites_per_file": 200,
                    "considered_files": result.considered_files,
                    "processed_callsites": result.processed_callsites,
                    "resolved_callsites": result.resolved_callsites,
                    "skipped_no_caller": result.skipped_no_caller,
                    "skipped_no_definition": result.skipped_no_definition,
                    "skipped_no_callee": result.skipped_no_callee,
                    "skipped_no_callee_reasons": dict(result.skipped_no_callee_reasons),
                    "skipped_no_callee_samples": list(result.skipped_no_callee_samples),
                    "edges_in_result": len(result.edges),
                    "edges_added": int(added),
                    "edges_total": int(_call_graph_edges_total),
                    "lsp_failures": dict(result.lsp_failures),
                    "duration_s": result.duration_s,
                }
                if cache_info:
                    _call_graph_result_summary["cache"] = cache_info
                _persist_call_graph_diag(_call_graph_diag(phase="background"))
                if project_dir is not None:
                    _persist_call_edge_cache(
                        _graph,
                        project_dir,
                        generation=generation,
                        source="background",
                        graph_digest=_graph_digest,
                    )

    _call_graph_thread = threading.Thread(target=_worker, name="codecanvas-call-graph", daemon=True)
    _call_graph_thread.start()

    # Watchdog: if the background thread runs far beyond the requested time budget,
    # mark it as timed out so post-hoc diagnostics are actionable.
    def _watchdog() -> None:
        global _call_graph_status, _call_graph_error, _call_graph_result_summary
        # Allow a small grace period beyond the time budget.
        deadline_s = float(time_budget_s) + 5.0
        time.sleep(max(0.0, deadline_s))
        if generation != _call_graph_generation:
            return
        if _call_graph_thread and _call_graph_thread.is_alive():
            _call_graph_status = "error"
            _call_graph_error = f"TimeoutError: background call graph exceeded {time_budget_s}s"
            _call_graph_result_summary = {
                "phase": "background",
                "time_budget_s": float(time_budget_s),
                "error": _call_graph_error,
            }
            _persist_call_graph_diag(_call_graph_diag(phase="background_timeout"))

    threading.Thread(target=_watchdog, name="codecanvas-call-graph-watchdog", daemon=True).start()


def _wait_for_call_graph(timeout_s: float = 10.0) -> None:
    """Wait for background call graph thread to complete."""
    global _call_graph_thread
    if _call_graph_thread and _call_graph_thread.is_alive():
        _call_graph_thread.join(timeout=timeout_s)
        if _call_graph_thread.is_alive():
            # Capture that we timed out waiting (useful when impact is invoked early).
            _persist_call_graph_diag(_call_graph_diag(phase="wait_timeout"))


def _canvas_output_dir(project_dir: str) -> str:
    return str(get_canvas_dir(Path(project_dir)))


def _find_repo_root(start: Path) -> Path:
    return find_workspace_root(start, prefer_env=False)


def canvas_action(
    *,
    action: str,
    repo_path: str | None = None,
    use_lsp: bool = True,
    lsp_langs: list[str] | None = None,
    symbol: str | None = None,
    text: str | None = None,
    kind: str | None = None,
    task_id: str | None = None,
    depth: int = 2,
    max_nodes: int = 20,
    wait_for_call_graph_s: float = 10.0,
) -> CanvasResult:
    action = (action or "").strip().lower()
    if not action:
        return CanvasResult("Missing action")

    if action == "init":
        if not repo_path:
            return CanvasResult("init requires repo_path")
        return _action_init(repo_path, use_lsp=use_lsp, lsp_langs=lsp_langs)

    state = load_state()
    if action == "read":
        if not state.initialized:
            return CanvasResult("Not initialized")
        return CanvasResult(_read_state_text(state))

    if not state.initialized:
        return CanvasResult(
            "Not initialized.\n"
            'Hint: Run canvas(action="init", repo_path=".") first, or this may auto-trigger via hooks.'
        )

    _ensure_loaded(state)

    if action == "impact":
        if not symbol:
            return CanvasResult("impact requires symbol")
        return _action_impact(
            state,
            symbol=symbol,
            depth=depth,
            max_nodes=max_nodes,
            wait_for_call_graph_s=float(wait_for_call_graph_s),
        )
    if action == "claim":
        if text is None:
            return CanvasResult("claim requires text")
        return _action_claim(state, text=text, kind=kind)
    if action == "decide":
        if text is None:
            return CanvasResult("decide requires text")
        return _action_decide(state, text=text, kind=kind)
    if action == "mark":
        if not symbol:
            return CanvasResult("mark requires symbol")
        return _action_mark_skip(state, symbol=symbol, mode="mark", text=text)
    if action == "skip":
        if not symbol:
            return CanvasResult("skip requires symbol")
        return _action_mark_skip(state, symbol=symbol, mode="skip", text=text)
    if action == "task_select":
        if not task_id:
            return CanvasResult("task_select requires task_id")
        return _action_task_select(state, task_id)
    if action == "status":
        refresh_summary = _refresh_graph_for_dirty_files(state, reason="status")
        if refresh_summary:
            state.refresh_summary = refresh_summary
            _save_state_with_lock(state)
        return _render_board(state, f"Status (call_graph={_call_graph_status})")

    return CanvasResult(f"Unknown action: {action}")


def _set_project_dir(project_dir: str) -> None:
    os.environ["CANVAS_PROJECT_DIR"] = project_dir


def _action_init(repo_path: str, *, use_lsp: bool, lsp_langs: list[str] | None) -> CanvasResult:
    global _graph, _analyzer
    global _call_graph_generation, _call_graph_status, _call_graph_error, _call_graph_last, _call_graph_edges_total
    global _call_graph_cache_info

    abs_p = Path(repo_path).absolute()
    abs_path = str(abs_p)
    project_dir = str(_find_repo_root(abs_p)) if abs_p.is_file() else str(abs_p)
    _set_project_dir(project_dir)
    clear_state()
    take_dirty(Path(project_dir))

    allowed_lsp_langs = set(lsp_langs) if lsp_langs else None
    parser = Parser(use_lsp=use_lsp, lsp_langs=allowed_lsp_langs)
    with _graph_lock:
        if Path(abs_path).is_file():
            _graph = parser.parse_file(abs_path)
        else:
            _graph = parser.parse_directory(abs_path)
        _analyzer = Analyzer(_graph)

    _call_graph_generation += 1
    generation = _call_graph_generation
    _call_graph_status = "idle"
    _call_graph_error = None
    _call_graph_last = None
    _call_graph_edges_total = 0
    global _call_graph_result_summary
    _call_graph_result_summary = None
    _call_graph_cache_info = None

    warn = ""
    backend_note = ""
    summary = getattr(parser, "last_summary", None)
    if summary is not None:
        fallback_files = max(0, summary.parsed_files - summary.lsp_files)
        if use_lsp:
            backend_note = f" Parse: lsp={summary.lsp_files}, fallback={fallback_files}."
            if summary.lsp_failures:
                reasons = ", ".join(f"{k}={v}" for k, v in sorted(summary.lsp_failures.items()))
                backend_note += f" Fallback reasons: {reasons}."
        if summary.skipped_files:
            warn = f" Warning: skipped {summary.skipped_files} files; graph may be incomplete."

    state = CanvasState(project_path=project_dir, initialized=True, use_lsp=use_lsp)
    if summary is not None:
        state.parse_summary = {
            "parsed_files": summary.parsed_files,
            "skipped_files": summary.skipped_files,
            "lsp_files": summary.lsp_files,
            "tree_sitter_files": summary.tree_sitter_files,
            "lsp_failures": dict(summary.lsp_failures or {}),
            "fallback_samples": list(summary.fallback_samples or []),
            "skipped_samples": list(summary.skipped_samples or []),
        }
        if allowed_lsp_langs is not None:
            state.parse_summary["lsp_langs"] = sorted(allowed_lsp_langs)

    meta = _compute_graph_meta(state=state, parser_summary=state.parse_summary, action="init")

    cache_info = None
    with _graph_lock:
        cache_info = _merge_cached_call_edges(_graph, Path(project_dir), expected_digest=_graph_digest)
        if cache_info:
            _call_graph_edges_total = int(_graph.stats().get("call_edges", 0))
    if cache_info:
        _call_graph_cache_info = {**cache_info, "edges_total": int(_call_graph_edges_total)}
        _call_graph_result_summary = {"phase": "cache_load", **_call_graph_cache_info}
        if _call_graph_edges_total:
            _call_graph_last = {"edges": int(_call_graph_edges_total), "duration_s": 0.0, "source": "cache"}
        if not use_lsp and _call_graph_edges_total:
            _call_graph_status = "completed"

    call_edges_added = 0
    if use_lsp:
        call_edges_added = _build_call_graph_foreground(
            time_budget_s=0.35,
            generation=generation,
            lsp_langs=allowed_lsp_langs,
            project_dir=Path(project_dir),
        )
        _start_call_graph_background(
            time_budget_s=30.0,
            generation=generation,
            lsp_langs=allowed_lsp_langs,
            project_dir=Path(project_dir),
        )

    # Persist call graph diagnostics immediately so SessionStart logs/state are useful
    # even if the run is terminated early.
    state.call_graph_summary = _call_graph_diag(phase="init")

    state.focus = Path(project_dir).name

    if meta is not None and _graph is not None:
        _reconcile_state_from_meta(state, meta)

    _save_state_with_lock(state)

    board = _render_board(state, "Board").images[0]

    if meta and isinstance(meta.get("graph", {}).get("stats"), dict):
        stats = meta.get("graph", {}).get("stats")
    else:
        with _graph_lock:
            stats = _graph.stats() if _graph is not None else {}

    arch_ev = next((e for e in state.evidence if e.kind == "architecture"), None)
    ev_id = arch_ev.id if arch_ev else "E1"
    png_path = str(get_canvas_dir(Path(project_dir)) / "architecture.png")
    png_bytes = b""
    try:
        png_bytes = Path(png_path).read_bytes()
    except Exception:
        png_bytes = b""

    call_note = "" if not use_lsp else f" Call graph: +{call_edges_added} edges ({_call_graph_status})."
    msg = (
        f"Initialized: {stats.get('modules', 0)} modules, {stats.get('classes', 0)} classes, "
        f"{stats.get('funcs', 0)} funcs. Created evidence {ev_id}.{backend_note}{call_note}{warn}\n\n"
        f"{_board_summary(state)}\n"
        f"{_next_hint('init')}"
    )
    return CanvasResult(
        text=msg,
        images=[
            CanvasImage(name="architecture", png_path=png_path, png_bytes=png_bytes),
            CanvasImage(name="board", png_path=board.png_path, png_bytes=board.png_bytes),
        ],
    )


def _ensure_loaded(state: CanvasState) -> None:
    global _graph, _analyzer
    global _call_graph_generation, _call_graph_edges_total
    global _call_graph_status, _call_graph_error, _call_graph_last, _call_graph_result_summary, _call_graph_cache_info
    if _graph is not None and _analyzer is not None:
        return
    if not state.project_path:
        return

    _set_project_dir(state.project_path)
    _call_graph_status = "idle"
    _call_graph_error = None
    _call_graph_last = None
    _call_graph_edges_total = 0
    _call_graph_result_summary = None

    lsp_langs: set[str] | None = None
    try:
        parsed = getattr(state, "parse_summary", None) or {}
        v = parsed.get("lsp_langs") if isinstance(parsed, dict) else None
        if isinstance(v, list) and all(isinstance(x, str) for x in v):
            lsp_langs = set(v)
    except Exception:
        lsp_langs = None

    parser = Parser(use_lsp=getattr(state, "use_lsp", True), lsp_langs=lsp_langs)
    root = Path(state.project_path)
    with _graph_lock:
        _graph = parser.parse_file(str(root)) if root.is_file() else parser.parse_directory(str(root))
        _analyzer = Analyzer(_graph)

    meta = _compute_graph_meta(state=state, parser_summary=state.parse_summary, action="load")

    _call_graph_cache_info = None
    cache_info = None
    with _graph_lock:
        cache_info = _merge_cached_call_edges(_graph, root, expected_digest=_graph_digest)
        if cache_info:
            _call_graph_edges_total = int(_graph.stats().get("call_edges", 0))
    if cache_info:
        _call_graph_cache_info = {**cache_info, "edges_total": int(_call_graph_edges_total)}
        _call_graph_result_summary = {"phase": "cache_load", **_call_graph_cache_info}
        if _call_graph_edges_total:
            _call_graph_last = {"edges": int(_call_graph_edges_total), "duration_s": 0.0, "source": "cache"}
        if not getattr(state, "use_lsp", True) and _call_graph_edges_total:
            _call_graph_status = "completed"

    if meta is not None and _graph is not None:
        if _reconcile_state_from_meta(state, meta):
            _save_state_with_lock(state)

    if getattr(state, "use_lsp", True):
        _call_graph_generation += 1
        generation = _call_graph_generation
        _build_call_graph_foreground(time_budget_s=0.2, generation=generation, lsp_langs=lsp_langs, project_dir=root)
        _start_call_graph_background(time_budget_s=30.0, generation=generation, lsp_langs=lsp_langs, project_dir=root)


def _action_impact(
    state: CanvasState,
    *,
    symbol: str,
    depth: int,
    max_nodes: int,
    wait_for_call_graph_s: float,
) -> CanvasResult:
    global _graph, _analyzer, _call_graph_result_summary
    assert _graph is not None and _analyzer is not None

    refresh_summary = _refresh_graph_for_dirty_files(state, reason="impact")
    if refresh_summary:
        state.refresh_summary = refresh_summary
    else:
        # Wait for background call graph to complete before analyzing
        _wait_for_call_graph(timeout_s=float(wait_for_call_graph_s))

    if state.project_path:
        meta = load_graph_meta(Path(state.project_path))
        if meta is not None:
            _reconcile_state_from_meta(state, meta)

    # Save call graph summary to state for diagnostics
    state.call_graph_summary = _call_graph_diag(phase="impact")

    with _graph_lock:
        node = _analyzer.find_target(symbol)
    if not node:
        return CanvasResult(f"Symbol not found: {symbol}")

    with _graph_lock:
        analysis_res = _analyzer.analyze(node.id, depth=depth)
    if not analysis_res:
        return CanvasResult(f"Analysis failed for: {node.label}")
    inbound, _outbound = analysis_res

    analysis = AnalysisState(
        target_id=node.id,
        target_label=node.label,
        affected_ids=inbound.nodes.copy(),
        test_ids=set(),
    )
    state.analyses = {node.id: analysis}
    state.focus = node.label

    with _graph_lock:
        caller_counts, callee_counts = _analyzer.impact_call_counts(node.id)

    out_dir = _canvas_output_dir(state.project_path)
    png_path = os.path.join(out_dir, f"impact_{node.id}.png")
    max_side = max(1, min(8, (int(max_nodes) - 1) // 2))
    with _graph_lock:
        svg = ImpactView(_graph).render(
            node.id,
            caller_counts=caller_counts,
            callee_counts=callee_counts,
            max_side=max_side,
            output_path=None,
        )
    png_bytes = save_png(svg, png_path)

    callers = len(caller_counts)
    callees = len(callee_counts)

    callers_top = sorted(caller_counts, key=lambda k: caller_counts[k], reverse=True)[:max_side]
    callees_top = sorted(callee_counts, key=lambda k: callee_counts[k], reverse=True)[:max_side]
    node_count = 1 + len(callers_top) + len(callees_top)
    edge_count = sum(caller_counts[k] for k in callers_top) + sum(callee_counts[k] for k in callees_top)

    ev = state.add_evidence(
        kind="impact",
        png_path=png_path,
        symbol=node.label,
        metrics={
            "depth": depth,
            "node_count": node_count,
            "edge_count": edge_count,
            "callers": callers,
            "callees": callees,
            "caller_edges": sum(caller_counts.values()),
            "callee_edges": sum(callee_counts.values()),
            "call_graph_status": (state.call_graph_summary or {}).get("status"),
            "call_graph_edges_total": (state.call_graph_summary or {}).get("edges_total"),
            "call_graph_generation": (state.call_graph_summary or {}).get("generation"),
            "call_graph_instance_id": (state.call_graph_summary or {}).get("instance_id"),
        },
    )
    _save_state_with_lock(state)

    board = _render_board(state, "Board").images[0]

    affected_count = len(inbound.nodes)
    msg = (
        f'Created {ev.id} (impact "{node.label}"): {callers} callers, {callees} callees.\n'
        f"Blast radius: {affected_count} nodes may be affected by changes.\n\n"
        f"{_board_summary(state)}\n"
        f"{_next_hint('impact')}"
    )
    return CanvasResult(
        text=msg,
        images=[
            CanvasImage(name="impact", png_path=png_path, png_bytes=png_bytes),
            CanvasImage(name="board", png_path=board.png_path, png_bytes=board.png_bytes),
        ],
    )


def _action_claim(state: CanvasState, *, text: str, kind: str | None) -> CanvasResult:
    k = (kind or "hypothesis").strip().lower() or "hypothesis"
    ev_ids = _default_evidence_ids(state)
    cl = state.add_claim(kind=k, text=text or "", evidence_ids=ev_ids)
    _save_state_with_lock(state)

    linked = f" linked to {ev_ids[0]}" if ev_ids else ""
    board_result = _render_board(state, "Board")
    msg = f"Created {cl.id} [{k}]{linked}.\n\n{_board_summary(state)}\n{_next_hint('claim')}"
    return CanvasResult(text=msg, images=board_result.images)


def _action_decide(state: CanvasState, *, text: str, kind: str | None) -> CanvasResult:
    k = (kind or "plan").strip().lower() or "plan"
    ev_ids = _default_evidence_ids(state)
    dc = state.add_decision(kind=k, text=text or "", target=None, evidence_ids=ev_ids)
    _save_state_with_lock(state)

    linked = f" linked to {ev_ids[0]}" if ev_ids else ""
    board_result = _render_board(state, "Board")
    msg = f"Created {dc.id} [{k}]{linked}.\n\n{_board_summary(state)}\n{_next_hint('decide')}"
    return CanvasResult(text=msg, images=board_result.images)


def _resolve_node_id(symbol: str) -> str | None:
    global _graph, _analyzer
    if not symbol:
        return None
    with _graph_lock:
        graph = _graph
        analyzer = _analyzer

        if graph and graph.get_node(symbol):
            return symbol
        if analyzer:
            n = analyzer.find_target(symbol)
            if n:
                return n.id
        if graph:
            # fallback: exact label match
            for n in graph.nodes:
                if n.label == symbol:
                    return n.id
    return None


def _action_mark_skip(state: CanvasState, *, symbol: str, mode: str, text: str | None) -> CanvasResult:
    node_id = _resolve_node_id(symbol)
    if not node_id:
        with _graph_lock:
            suggestions = _analyzer.find_similar_symbols(symbol, limit=5) if _analyzer else []
        if suggestions:
            hint_lines = [f"  - {s.label} ({s.kind.value})" for s in suggestions]
            hint = "\n".join(hint_lines)
            return CanvasResult(
                f'Symbol not found: "{symbol}"\n'
                f"Similar symbols:\n{hint}\n"
                f"Hint: Use exact function/class names from the suggestions above."
            )
        return CanvasResult(
            f'Symbol not found: "{symbol}"\nHint: Run status to see the Evidence Board, or read for available symbols.'
        )

    with _graph_lock:
        node = _graph.get_node(node_id) if _graph else None
        label = node.label if node is not None else symbol
    updated = False
    for a in state.analyses.values():
        if node_id in a.affected_ids:
            if mode == "mark":
                a.addressed_ids.add(node_id)
            else:
                a.skipped_ids.add(node_id)
            updated = True

    if not updated:
        # allow marking a target itself
        for a in state.analyses.values():
            if a.target_id == node_id:
                if mode == "mark":
                    a.addressed_ids.add(node_id)
                else:
                    a.skipped_ids.add(node_id)
                updated = True

    ev_ids = _default_evidence_ids(state)
    if mode == "mark":
        decision_text = (text or f"Marked verified: {label}").strip() or f"Marked verified: {label}"
        state.add_decision(kind="mark", text=decision_text, target=label, evidence_ids=ev_ids)
    else:
        decision_text = (text or f"Skipped: {label}").strip() or f"Skipped: {label}"
        state.add_decision(kind="skip", text=decision_text, target=label, evidence_ids=ev_ids)

    _save_state_with_lock(state)

    action_word = "Marked" if mode == "mark" else "Skipped"
    board_result = _render_board(state, "Board")
    msg = (
        f'{action_word} "{label}" as {"verified" if mode == "mark" else "out-of-scope"}.\n\n'
        f"{_board_summary(state)}{_progress_summary(state)}\n"
        f"{_next_hint(mode)}"
    )
    return CanvasResult(text=msg, images=board_result.images)


def _action_task_select(state: CanvasState, task_id: str) -> CanvasResult:
    tasks = load_tasks_yaml(state.project_path)
    task = pick_task(tasks, task_id)
    if not task:
        return CanvasResult(f"Unknown task_id: {task_id}")
    state.active_task_id = task_id
    _save_state_with_lock(state)

    board_result = _render_board(state, "Board")
    msg = f'Selected task: "{task_id}".\n\n{_board_summary(state)}\n{_next_hint("task_select")}'
    return CanvasResult(text=msg, images=board_result.images)


def _render_board(state: CanvasState, title: str) -> CanvasResult:
    global _graph
    if _graph is None:
        _ensure_loaded(state)
    with _graph_lock:
        graph = _graph
    assert graph is not None

    tasks = load_tasks_yaml(state.project_path)
    png_path = os.path.join(_canvas_output_dir(state.project_path), "task.png")
    with _graph_lock:
        svg = TaskView(graph, state, tasks=tasks).render(output_path=None)
    png_bytes = save_png(svg, png_path)
    return CanvasResult(text=title, images=[CanvasImage(name="board", png_path=png_path, png_bytes=png_bytes)])


def _default_evidence_ids(state: CanvasState) -> list[str]:
    ids: list[str] = []
    if state.focus and state.last_evidence_id_by_focus.get(state.focus):
        ids.append(state.last_evidence_id_by_focus[state.focus])
    elif state.evidence:
        ids.append(state.evidence[-1].id)
    return ids[:2]


def _board_summary(state: CanvasState) -> str:
    """One-line board state for orientation."""
    e = len(state.evidence)
    c = len([x for x in state.claims if x.status == "active"])
    d = len(state.decisions)
    focus = state.focus or "(none)"
    return f"Board: {e} evidence, {c} claims, {d} decisions | Focus: {focus}"


def _progress_summary(state: CanvasState) -> str:
    """Progress on current analysis (if any)."""
    if not state.analyses:
        return ""
    for a in state.analyses.values():
        done, total = a.progress()
        if total > 0:
            return f" | Progress: {done}/{total} addressed"
    return ""


def _next_hint(action: str) -> str:
    """Context-aware next-step suggestion."""
    hints = {
        "init": 'Next: Use impact(symbol="<target>") to analyze a symbol before changing it.',
        "impact": 'Next: Record your analysis with claim(text="...") or plan with decide(text="...").',
        "claim": 'Next: Continue analysis, or commit with decide(text="...").',
        "decide": 'Next: Implement your plan, then mark(symbol="...") when verified.',
        "mark": "Next: Continue with remaining affected nodes, or start new impact analysis.",
        "skip": "Next: Continue with remaining affected nodes, or start new impact analysis.",
        "status": "",
        "task_select": 'Next: Use impact(symbol="...") to begin analysis.',
    }
    return hints.get(action, "")


def _read_state_text(state: CanvasState) -> str:
    lines: list[str] = []
    init_line = f"initialized={state.initialized}  focus={state.focus or ''}"
    init_line += f"  active_task_id={state.active_task_id or ''}"
    init_line += f"  call_graph={_call_graph_status}"
    if _call_graph_error:
        init_line += f"  call_graph_error={_call_graph_error}"
    if _call_graph_last:
        init_line += f"  call_graph_edges={_call_graph_last.get('edges', 0)}"
    lines.append(init_line)

    ps = dict(getattr(state, "parse_summary", {}) or {})
    if ps:
        lines.append(
            "parse: "
            f"parsed={ps.get('parsed_files', 0)} "
            f"lsp={ps.get('lsp_files', 0)} "
            f"tree_sitter={ps.get('tree_sitter_files', 0)} "
            f"skipped={ps.get('skipped_files', 0)}"
        )
        failures = ps.get("lsp_failures") or {}
        if failures:
            reasons = ", ".join(f"{k}={v}" for k, v in sorted(failures.items()))
            lines.append(f"lsp_fallbacks: {reasons}")
    lines.append("")
    lines.append("EVIDENCE:")
    for ev in state.evidence[-20:]:
        sym = f" symbol={ev.symbol}" if ev.symbol else ""
        lines.append(f"- {ev.id} kind={ev.kind}{sym} path={ev.png_path}")
    lines.append("")
    lines.append("CLAIMS:")
    for c in state.claims[-20:]:
        lines.append(f"- {c.id} kind={c.kind} status={c.status} evidence={' '.join(c.evidence_ids)} text={c.text}")
    lines.append("")
    lines.append("DECISIONS:")
    for d in state.decisions[-20:]:
        tgt = f" target={d.target}" if d.target else ""
        lines.append(f"- {d.id} kind={d.kind}{tgt} evidence={' '.join(d.evidence_ids)} text={d.text}")
    return "\n".join(lines).strip() + "\n"


# --- MCP Server ---


def _create_mcp_server():
    """Create and configure the MCP server."""
    import base64
    from typing import Any

    from mcp.server import Server
    from mcp.types import ImageContent, TextContent, Tool

    server = Server("codecanvas")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="canvas",
                description="""CodeCanvas: Visual codebase analysis for agentic workflows.

WORKFLOW (recommended pattern):
1. init → Parse repo, get architecture overview (often auto-triggered via hooks)
2. impact symbol="target" → See blast radius before changing a symbol
3. claim text="..." → Record hypotheses/findings linked to visual evidence
4. decide text="..." → Record plans/commitments before acting
5. mark/skip symbol="..." → Track verification progress

ACTIONS:
• init: Parse repo into graph, render architecture map. Returns architecture.png + board.png
• impact: Analyze a symbol's callers/callees (blast radius). Returns impact.png + board.png
• claim: Record hypothesis|finding|question, auto-linked to recent evidence
• decide: Record plan|test|edit commitment, auto-linked to recent evidence
• mark: Mark symbol as verified in current analysis
• skip: Mark symbol as out-of-scope
• status: Refresh the Evidence Board (cheap, no reparse)
• read: Text-only state dump (for non-multimodal fallback)

EVIDENCE BOARD (board.png):
Your persistent working memory showing Claims, Evidence thumbnails, and Decisions.
Check it to stay oriented on multi-step tasks.

EXAMPLE SESSION:
1. init repo_path="." → E1 (architecture)
2. impact symbol="process_data" → E2 (blast radius: 5 callers, 2 callees)
3. claim text="Changing process_data may break validate_input" kind=hypothesis
4. decide text="Update process_data, then fix validate_input tests" kind=plan
5. [make edits]
6. mark symbol="process_data" text="Verified via unit tests"

TIPS:
• Use impact BEFORE making changes to understand blast radius
• Claims/decisions auto-link to the most recent evidence
• The board shows progress—check it when resuming work""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "One of: init|impact|claim|decide|mark|skip|task_select|status|read",
                        },
                        "repo_path": {"type": "string", "description": "(init) Repo root or file path."},
                        "symbol": {"type": "string", "description": "(impact/mark/skip) Target symbol name."},
                        "text": {"type": "string", "description": "(claim/decide/mark/skip) Free-form text."},
                        "kind": {
                            "type": "string",
                            "description": "(claim/decide) Kind: hypothesis|finding|question|plan|test|edit",
                        },
                        "task_id": {"type": "string", "description": "(task_select) Task id from tasks.yaml"},
                        "depth": {
                            "type": "integer",
                            "default": 2,
                            "description": "Impact neighborhood depth (1-3 recommended).",
                        },
                        "max_nodes": {
                            "type": "integer",
                            "default": 20,
                            "description": "Max nodes in the impact view.",
                        },
                    },
                    "required": ["action"],
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
        if name != "canvas":
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        try:
            args = arguments or {}
            action = (args.get("action") or "").strip()
            depth = int(args.get("depth", 2) or 2)
            max_nodes = int(args.get("max_nodes", 20) or 20)
            wait_for_call_graph_s = float(args.get("wait_for_call_graph_s", 10.0) or 10.0)

            use_lsp_arg = args.get("use_lsp")
            use_lsp = True if use_lsp_arg is None else bool(use_lsp_arg)

            result = canvas_action(
                action=action,
                repo_path=args.get("repo_path"),
                use_lsp=use_lsp,
                symbol=args.get("symbol"),
                text=args.get("text"),
                kind=args.get("kind"),
                task_id=args.get("task_id"),
                depth=depth,
                max_nodes=max_nodes,
                wait_for_call_graph_s=wait_for_call_graph_s,
            )

            contents: list[Any] = [TextContent(type="text", text=result.text)]
            for img in result.images or []:
                contents.append(
                    ImageContent(
                        type="image",
                        data=base64.b64encode(img.png_bytes).decode("ascii"),
                        mimeType="image/png",
                    )
                )
            return contents
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    return server


_mcp_server = None


def get_mcp_server():
    """Get or create the MCP server singleton."""
    global _mcp_server
    if _mcp_server is None:
        _mcp_server = _create_mcp_server()
    return _mcp_server


async def run_mcp_server() -> None:
    """Run the MCP server (entry point for pyproject.toml)."""
    from mcp.server.stdio import stdio_server

    server = get_mcp_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_mcp_server())
