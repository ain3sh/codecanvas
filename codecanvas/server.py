"""CodeCanvas action API.

This is intentionally explicit (no backwards-compat shims): callers provide an
`action` and corresponding parameters.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .core.analysis import Analyzer
from .core.models import Graph
from .core.state import AnalysisState, CanvasState, clear_state, load_state, load_tasks_yaml, pick_task, save_state
from .parser import Parser
from .parser.call_graph import build_call_graph_edges
from .views import save_png
from .views.architecture import ArchitectureView
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

_graph_lock = threading.RLock()

_call_graph_status: str = "idle"  # idle|working|completed|error
_call_graph_error: str | None = None
_call_graph_last: dict | None = None
_call_graph_thread: threading.Thread | None = None
_call_graph_generation: int = 0
_call_graph_edges_total: int = 0
_call_graph_result_summary: dict | None = None  # Detailed result for diagnostics


def _call_graph_diag(*, phase: str | None = None) -> dict:
    """Build a durable diagnostic snapshot for post-hoc inspection.

    This is intended to be persisted to .codecanvas/state.json (and Harbor extraction).
    """
    thread_alive = bool(_call_graph_thread and _call_graph_thread.is_alive())
    return {
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


def _build_call_graph_foreground(*, time_budget_s: float, generation: int) -> int:
    global _graph
    global _call_graph_status, _call_graph_error, _call_graph_last
    global _call_graph_edges_total, _call_graph_result_summary
    if _graph is None:
        return 0

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
        result = build_call_graph_edges(
            nodes_snapshot,
            time_budget_s=float(time_budget_s),
            max_callsites_total=250,
            max_callsites_per_file=50,
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
                "edges_in_result": len(result.edges),
                "edges_added": int(added),
                "edges_total": int(_call_graph_edges_total),
                "lsp_failures": dict(result.lsp_failures),
                "duration_s": result.duration_s,
            }
            _persist_call_graph_diag(_call_graph_diag(phase="foreground"))

    return added


def _start_call_graph_background(*, time_budget_s: float, generation: int) -> None:
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
                _persist_call_graph_diag(_call_graph_diag(phase="background"))
            result = build_call_graph_edges(
                nodes_snapshot,
                time_budget_s=float(time_budget_s),
                max_callsites_total=2000,
                max_callsites_per_file=200,
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
                    "edges_in_result": len(result.edges),
                    "edges_added": int(added),
                    "edges_total": int(_call_graph_edges_total),
                    "lsp_failures": dict(result.lsp_failures),
                    "duration_s": result.duration_s,
                }
                _persist_call_graph_diag(_call_graph_diag(phase="background"))

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
    return os.path.join(project_dir, ".codecanvas")


def _find_repo_root(start: Path) -> Path:
    p = start
    if p.is_file():
        p = p.parent
    p = p.absolute()
    for _ in range(30):
        if (p / "pyproject.toml").exists() or (p / ".git").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    return start.absolute() if start.exists() else Path.cwd().absolute()


def canvas_action(
    *,
    action: str,
    repo_path: str | None = None,
    use_lsp: bool = True,
    symbol: str | None = None,
    text: str | None = None,
    kind: str | None = None,
    task_id: str | None = None,
    depth: int = 2,
    max_nodes: int = 20,
) -> CanvasResult:
    action = (action or "").strip().lower()
    if not action:
        return CanvasResult("Missing action")

    if action == "init":
        if not repo_path:
            return CanvasResult("init requires repo_path")
        return _action_init(repo_path, use_lsp=use_lsp)

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
        return _action_impact(state, symbol=symbol, depth=depth, max_nodes=max_nodes)
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
        return _render_board(state, f"Status (call_graph={_call_graph_status})")

    return CanvasResult(f"Unknown action: {action}")


def _set_project_dir(project_dir: str) -> None:
    os.environ["CANVAS_PROJECT_DIR"] = project_dir


def _action_init(repo_path: str, *, use_lsp: bool) -> CanvasResult:
    global _graph, _analyzer
    global _call_graph_generation, _call_graph_status, _call_graph_error, _call_graph_last, _call_graph_edges_total

    abs_path = str(Path(repo_path).absolute())
    repo_root = _find_repo_root(Path(abs_path))
    project_dir = str(repo_root)
    _set_project_dir(project_dir)
    clear_state()

    parser = Parser(use_lsp=use_lsp)
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

    call_edges_added = 0
    if use_lsp:
        call_edges_added = _build_call_graph_foreground(time_budget_s=0.35, generation=generation)
        _start_call_graph_background(time_budget_s=30.0, generation=generation)

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
    with _graph_lock:
        for node in _graph.nodes:
            state.symbol_files[node.id] = node.fsPath

    # Persist call graph diagnostics immediately so SessionStart logs/state are useful
    # even if the run is terminated early.
    state.call_graph_summary = _call_graph_diag(phase="init")

    state.focus = Path(project_dir).name

    out_dir = _canvas_output_dir(project_dir)
    png_path = os.path.join(out_dir, "architecture.png")
    with _graph_lock:
        svg = ArchitectureView(_graph).render(output_path=None)
    png_bytes = save_png(svg, png_path)

    with _graph_lock:
        stats = _graph.stats()
    ev = state.add_evidence(
        kind="architecture",
        png_path=png_path,
        symbol=None,
        metrics={"modules": stats.get("modules"), "classes": stats.get("classes"), "funcs": stats.get("funcs")},
    )
    save_state(state)

    board = _render_board(state, "Board").images[0]

    diag = state.call_graph_summary or {}
    diag_note = ""
    if use_lsp:
        diag_note = (
            f" Diag: status={diag.get('status')}, thread_alive={diag.get('thread_alive')}, "
            f"edges_total={diag.get('edges_total')}."
        )

    call_note = "" if not use_lsp else f" Call graph: +{call_edges_added} edges ({_call_graph_status}).{diag_note}"
    msg = (
        f"Initialized: {stats['modules']} modules, {stats['classes']} classes, {stats['funcs']} funcs. "
        f"Created evidence {ev.id}.{backend_note}{call_note}{warn}\n\n"
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
    if _graph is not None and _analyzer is not None:
        return
    if not state.project_path:
        return

    parser = Parser(use_lsp=getattr(state, "use_lsp", True))
    root = Path(state.project_path)
    with _graph_lock:
        _graph = parser.parse_file(str(root)) if root.is_file() else parser.parse_directory(str(root))
        _analyzer = Analyzer(_graph)

    if getattr(state, "use_lsp", True):
        _call_graph_generation += 1
        generation = _call_graph_generation
        _call_graph_edges_total = 0
        global _call_graph_result_summary
        _call_graph_result_summary = None
        _build_call_graph_foreground(time_budget_s=0.2, generation=generation)
        _start_call_graph_background(time_budget_s=30.0, generation=generation)

        # Snapshot diagnostics for post-hoc inspection.
        try:
            state.call_graph_summary = _call_graph_diag(phase="ensure_loaded")
            save_state(state)
        except Exception:
            pass


def _action_impact(state: CanvasState, *, symbol: str, depth: int, max_nodes: int) -> CanvasResult:
    global _graph, _analyzer, _call_graph_result_summary
    assert _graph is not None and _analyzer is not None

    # Wait for background call graph to complete before analyzing
    _wait_for_call_graph(timeout_s=10.0)

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
        neigh_nodes, neigh_edges = _analyzer.neighborhood(node.id, hops=depth, max_nodes=max_nodes)

    out_dir = _canvas_output_dir(state.project_path)
    png_path = os.path.join(out_dir, f"impact_{node.id}.png")
    with _graph_lock:
        svg = ImpactView(_graph).render(node.id, neigh_nodes, neigh_edges, output_path=None)
    png_bytes = save_png(svg, png_path)

    callers = len([e for e in neigh_edges if e.to_id == node.id])
    callees = len([e for e in neigh_edges if e.from_id == node.id])

    ev = state.add_evidence(
        kind="impact",
        png_path=png_path,
        symbol=node.label,
        metrics={"depth": depth, "node_count": len(neigh_nodes), "edge_count": len(neigh_edges)},
    )
    save_state(state)

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
    save_state(state)

    linked = f" linked to {ev_ids[0]}" if ev_ids else ""
    board_result = _render_board(state, "Board")
    msg = (
        f"Created {cl.id} [{k}]{linked}.\n\n"
        f"{_board_summary(state)}\n"
        f"{_next_hint('claim')}"
    )
    return CanvasResult(text=msg, images=board_result.images)


def _action_decide(state: CanvasState, *, text: str, kind: str | None) -> CanvasResult:
    k = (kind or "plan").strip().lower() or "plan"
    ev_ids = _default_evidence_ids(state)
    dc = state.add_decision(kind=k, text=text or "", target=None, evidence_ids=ev_ids)
    save_state(state)

    linked = f" linked to {ev_ids[0]}" if ev_ids else ""
    board_result = _render_board(state, "Board")
    msg = (
        f"Created {dc.id} [{k}]{linked}.\n\n"
        f"{_board_summary(state)}\n"
        f"{_next_hint('decide')}"
    )
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
            f'Symbol not found: "{symbol}"\n'
            f"Hint: Run status to see the Evidence Board, or read for available symbols."
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

    save_state(state)

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
    save_state(state)

    board_result = _render_board(state, "Board")
    msg = (
        f'Selected task: "{task_id}".\n\n'
        f"{_board_summary(state)}\n"
        f"{_next_hint('task_select')}"
    )
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
