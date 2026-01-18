from __future__ import annotations

import json
import os
import re
import shlex
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from codecanvas.core.models import EdgeType, NodeKind
from codecanvas.core.paths import get_canvas_dir, has_project_markers, top_level_project_roots
from codecanvas.core.refresh import mark_dirty
from codecanvas.core.state import load_state
from codecanvas.server import canvas_action

from ._autocontext_state import AutoContextState
from ._hookio import (
    extract_file_path,
    get_hook_event_name,
    get_str,
    get_tool_input,
    get_tool_name,
    read_stdin_json,
)

# NOTE: Complex workspace-root detection is intentionally disabled for now.
# from ._workspace import resolve_workspace_root

_CODE_EXTS: set[str] = {
    ".py",
    ".pyx",
    ".pxd",
    ".pxi",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".cpp",
    ".c",
    ".rb",
}


def _is_under_app(cwd: str) -> bool:
    try:
        app = Path("/app").absolute()
        p = Path(cwd).absolute()
        return p == app or p.is_relative_to(app)
    except Exception:
        try:
            return str(Path(cwd).absolute()).startswith("/app/")
        except Exception:
            return False


def _configure_tb_artifacts(cwd: str) -> None:
    """In TerminalBench, keep CodeCanvas artifacts outside `/app` for verifier-safety."""

    if not _is_under_app(cwd):
        return
    if (os.environ.get("CANVAS_ARTIFACT_DIR") or "").strip():
        return

    session_dir = (os.environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    if session_dir:
        os.environ["CANVAS_ARTIFACT_DIR"] = str((Path(session_dir) / "codecanvas").absolute())
        return
    os.environ["CANVAS_ARTIFACT_DIR"] = "/tmp/codecanvas"


def _extract_bash_modified_paths(command: str, cwd: str) -> list[Path]:
    if not command:
        return []

    out: list[Path] = []

    def _add(path_str: str) -> None:
        p = (path_str or "").strip().strip("\"'")
        if not p:
            return
        path = Path(p)
        if not path.is_absolute():
            path = Path(cwd) / path
        out.append(path)

    for match in re.finditer(r"(?:^|\s)(?:>>?|\+>)\s*([^\s]+)", command):
        _add(match.group(1))

    try:
        tokens = shlex.split(command)
    except Exception:
        tokens = command.split()

    if not tokens:
        return out

    head = tokens[0]
    if head in {"touch"}:
        for t in tokens[1:]:
            if t.startswith("-"):
                continue
            _add(t)

    if head in {"cp", "mv", "install"}:
        if len(tokens) >= 3:
            _add(tokens[-1])

    if head == "tee":
        for t in tokens[1:]:
            if t.startswith("-"):
                continue
            _add(t)

    if head == "sed" and "-i" in tokens:
        for t in reversed(tokens):
            if t.startswith("-"):
                continue
            _add(t)
            break

    if head == "perl" and "-pi" in tokens:
        for t in reversed(tokens):
            if t.startswith("-"):
                continue
            _add(t)
            break

    return out


def _emit(*, hook_event_name: str, additional_context: str | None = None) -> None:
    out: dict[str, Any] = {
        "suppressOutput": True,
        "hookSpecificOutput": {
            "hookEventName": hook_event_name,
        },
    }
    if additional_context:
        out["hookSpecificOutput"]["additionalContext"] = _limit(additional_context, 900)
    print(json.dumps(out))


def _noop(hook_event_name: str) -> None:
    _emit(hook_event_name=hook_event_name)


def _limit(s: str, n: int) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return (s[: max(0, n - 1)] + "…").strip()


def _debug_logs_enabled() -> bool:
    return os.environ.get("CODECANVAS_DEBUG_LOGS") == "1"


def _debug_log(payload: dict[str, Any]) -> None:
    """Best-effort, append-only debug log persisted under CLAUDE_CONFIG_DIR."""

    if not _debug_logs_enabled():
        return
    try:
        session_dir = os.environ.get("CLAUDE_CONFIG_DIR")
        if not session_dir:
            return
        d = Path(session_dir) / "codecanvas"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "hook_debug.jsonl"

        payload = dict(payload)
        payload.setdefault("ts", time.time())
        line = json.dumps(payload, ensure_ascii=False)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        return


@contextmanager
def _workspace_lock(root: Path, *, timeout_s: float = 2.0):
    """Best-effort cross-process lock for init/impact (hooks run in parallel)."""

    try:
        import fcntl

        lock_dir = get_canvas_dir(root)
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / "lock"
        f = open(lock_path, "a", encoding="utf-8")
    except Exception:
        yield
        return

    deadline = time.time() + float(timeout_s)
    locked = False
    while time.time() < deadline:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
            break
        except BlockingIOError:
            time.sleep(0.02)
        except Exception:
            break

    try:
        yield
    finally:
        try:
            if locked:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            f.close()
        except Exception:
            pass


def _sync_canvas_artifacts_to_session(*, root: Path) -> None:
    """No-op: artifacts are written directly to the configured artifact directory."""
    if _debug_logs_enabled():
        _debug_log({"event": "sync", "skipped": "single_sink", "root": str(root)})
    return


def _maybe_init(*, root: Path, allow_init: bool, lsp_langs: list[str] | None) -> tuple[bool, str]:
    """Ensure the CodeCanvas state in `root` is initialized.

    Returns (did_init, reason).
    """

    os.environ["CANVAS_PROJECT_DIR"] = str(root)
    state = load_state()
    parsed = int(state.parse_summary.get("parsed_files", 0) or 0)
    wants_lsp = bool(lsp_langs)

    if (
        state.initialized
        and state.project_path
        and Path(state.project_path).absolute() == root.absolute()
        and parsed > 0
    ):
        # If we initialized without LSP but warmup later becomes ready, allow a one-time upgrade.
        if wants_lsp and not bool(getattr(state, "use_lsp", False)):
            pass
        else:
            return False, "already_initialized"

    if not allow_init:
        return False, "deferred"

    # Re-init if initialized but empty (common in clone-first workflows).
    if state.initialized and parsed == 0 and not (has_project_markers(root) or top_level_project_roots(root)):
        # If the root isn't marker-backed and doesn't contain project roots, avoid churn.
        return False, "deferred_empty"

    canvas_action(action="init", repo_path=str(root), use_lsp=wants_lsp, lsp_langs=lsp_langs)
    return True, "initialized"


def _symbol_visibility(label: str) -> int:
    name = label.rsplit(".", 1)[-1]
    if name.startswith("__") and name.endswith("__"):
        return 2
    if name.startswith("_"):
        return 1
    return 0


def _parse_symbol_id(symbol_id: str) -> tuple[str, str, int] | None:
    if symbol_id.startswith("fn_"):
        parts = symbol_id.split("_", 2)
        if len(parts) < 3:
            return None
        name = parts[2]
        return "func", name, 1_000_000_000
    if symbol_id.startswith("cls_"):
        parts = symbol_id.split("_", 2)
        if len(parts) < 3:
            return None
        name = parts[2]
        return "class", name, 1_000_000_000
    return None


def _descendant_funcs(graph, node_id: str) -> set[str]:
    out: set[str] = set()
    queue = [node_id]
    seen = {node_id}
    while queue:
        cur = queue.pop(0)
        for child_id in graph.get_children_ids(cur):
            if child_id in seen:
                continue
            seen.add(child_id)
            child = graph.get_node(child_id)
            if child is None:
                continue
            if child.kind == NodeKind.FUNC:
                out.add(child.id)
            elif child.kind in {NodeKind.CLASS, NodeKind.MODULE}:
                queue.append(child.id)
    return out


def _call_edge_degree(graph, node_id: str) -> int:
    outbound = sum(1 for e in graph.get_edges_from(node_id) if e.type == EdgeType.CALL)
    inbound = sum(1 for e in graph.get_edges_to(node_id) if e.type == EdgeType.CALL)
    return outbound + inbound


def _call_edge_score(graph, node_id: str, kind: NodeKind) -> int:
    if kind == NodeKind.FUNC:
        return _call_edge_degree(graph, node_id)
    if kind in {NodeKind.CLASS, NodeKind.MODULE}:
        return sum(_call_edge_degree(graph, fid) for fid in _descendant_funcs(graph, node_id))
    return 0


def _select_best_symbol_in_file(*, file_path: Path) -> str | None:
    symbol_id = _select_symbol_from_graph(file_path)
    if symbol_id:
        return symbol_id
    return _select_symbol_from_state(file_path)


def _select_symbol_from_state(file_path: Path) -> str | None:
    try:
        state = load_state()
        if not state.initialized:
            return None

        target = str(file_path.absolute())
        candidates: list[tuple[int, int, int, str]] = []
        for symbol_id, fs_path in (state.symbol_files or {}).items():
            try:
                if str(Path(fs_path).absolute()) != target:
                    continue
            except Exception:
                continue

            parsed = _parse_symbol_id(symbol_id)
            if parsed is None:
                continue
            kind, name, line_rank = parsed
            kind_rank = 0 if kind == "func" else 1
            vis_rank = _symbol_visibility(name)
            candidates.append((vis_rank, kind_rank, line_rank, symbol_id))

        if not candidates:
            return None

        best_vis = min(c[0] for c in candidates)
        filtered = [c for c in candidates if c[0] == best_vis]
        filtered.sort(key=lambda c: (c[1], c[2], c[3]))
        return filtered[0][3]
    except Exception:
        return None


def _select_symbol_from_graph(file_path: Path) -> str | None:
    try:
        import codecanvas.server as server

        graph = server._graph
        if graph is None:
            return None

        target = str(file_path.absolute())
        candidates: list[tuple[int, int, int, int, int, str]] = []
        for node in graph.nodes:
            try:
                if str(Path(node.fsPath).absolute()) != target:
                    continue
            except Exception:
                continue

            if node.kind not in {NodeKind.FUNC, NodeKind.CLASS}:
                continue

            vis_rank = _symbol_visibility(node.label)
            call_score = _call_edge_score(graph, node.id, node.kind)
            child_score = len(_descendant_funcs(graph, node.id)) if node.kind != NodeKind.FUNC else 0
            kind_rank = 0 if node.kind == NodeKind.FUNC else 1
            line_rank = int(node.start_line or 1_000_000_000)
            candidates.append((-call_score, -child_score, kind_rank, line_rank, vis_rank, node.id))

        if not candidates:
            return None

        best_vis = min(c[4] for c in candidates)
        filtered = [c for c in candidates if c[4] == best_vis]
        filtered.sort()
        return filtered[0][5]
    except Exception:
        return None


def _format_impact_card(*, root: Path, symbol_id: str) -> str:
    try:
        import codecanvas.server as server

        analyzer = server._analyzer
        graph = server._graph

        if analyzer is None or graph is None:
            return ""
        node = analyzer.find_target(symbol_id)
        if node is None:
            return ""

        callers, callees = analyzer.impact_call_counts(node.id)
        callers_n = len(callers)
        callees_n = len(callees)

        if callers_n == 0 and callees_n == 0:
            return ""

        def _top_label(d: dict[str, int]) -> str:
            if not d:
                return ""
            top_id = max(d, key=lambda k: d[k])
            n = graph.get_node(top_id)
            return n.label if n is not None else top_id

        top_caller = _top_label(callers)
        top_callee = _top_label(callees)

        lines = [
            f"[CodeCanvas IMPACT] root={root}",
            f"symbol={node.label} callers={callers_n} callees={callees_n}",
        ]
        if top_caller:
            lines.append(f"top caller: {top_caller}")
        if top_callee:
            lines.append(f"top callee: {top_callee}")
        return "\n".join(lines)
    except Exception:
        return ""


def handle_session_start(input_data: dict[str, Any]) -> str | None:
    # Avoid eager init: we only arm the system here.
    cwd = get_str(input_data, "cwd", default=os.getcwd())
    st = AutoContextState()
    st.write_active_root(cwd, reason="session_start")
    _debug_log({"event": "SessionStart", "cwd": cwd})
    return "[CodeCanvas] AutoContext armed. Init deferred until workspace is detected."


def handle_pre_tool_use(input_data: dict[str, Any]) -> str | None:
    """PreToolUse: auto-init (architecture) when workspace becomes clear.

    This is intentionally limited to init/architecture. Blast-radius messaging runs
    on PostToolUse(Read|Edit|Write) so it reflects recent file activity.
    """

    started = time.time()
    st = AutoContextState()
    sticky_root = st.read_active_root()

    cwd = get_str(input_data, "cwd", default=os.getcwd())
    _configure_tb_artifacts(cwd)
    tool_name = get_tool_name(input_data)

    file_path_str = extract_file_path(input_data)
    file_path = Path(file_path_str) if file_path_str else None

    dirty_paths: list[Path] = []
    if tool_name in {"Edit", "Write"} and file_path is not None:
        dirty_paths = [file_path]
    elif tool_name == "Bash":
        tool_input = get_tool_input(input_data)
        command = get_str(tool_input, "command", "cmd")
        dirty_paths = _extract_bash_modified_paths(command, cwd)

    # NOTE: Complex workspace-root detection is intentionally disabled for now.
    # root = resolve_workspace_root(...)
    root = Path("/app").absolute() if _is_under_app(cwd) else Path(cwd).absolute()

    if dirty_paths:
        mark_dirty(root, dirty_paths, reason=tool_name)

    st.write_active_root(str(root), reason=f"pre_tool_use:{tool_name}")

    root_str = str(root)
    has_markers = has_project_markers(root)
    project_roots = top_level_project_roots(root)
    allow_init = bool(
        has_markers
        or project_roots
        or (file_path is not None and file_path.exists() and file_path.is_file())
    )

    if st.is_init_announced(root=root_str):
        return None

    # LSP warmup spawn gating should be based only on detected language extensions
    # under the `/app` root (TerminalBench protocol). Do not require markers.
    if _is_under_app(cwd):
        try:
            from .lsp_warmup import ensure_worker_running

            ensure_worker_running(root=root)
        except Exception:
            pass
    elif has_markers or project_roots:
        try:
            from .lsp_warmup import ensure_worker_running

            ensure_worker_running(root=root)
        except Exception:
            pass

    now = time.time()
    cooldown_s = 120.0

    inflight_at = st.get_init_inflight_at(root=root_str)
    if inflight_at is not None:
        age_s = now - float(inflight_at)
        if age_s < cooldown_s:
            _debug_log(
                {
                    "event": "PreToolUse",
                    "tool_name": tool_name,
                    "cwd": cwd,
                    "file_path": file_path_str,
                    "resolved_root": root_str,
                    "allow_init": allow_init,
                    "skipped": "init_inflight",
                    "inflight_age_s": age_s,
                }
            )
            return None
        st.clear_init_inflight(root=root_str)

    next_allowed_at = st.get_init_next_allowed_at(root=root_str)
    if next_allowed_at is not None and now < float(next_allowed_at):
        _debug_log(
            {
                "event": "PreToolUse",
                "tool_name": tool_name,
                "cwd": cwd,
                "file_path": file_path_str,
                "resolved_root": root_str,
                "allow_init": allow_init,
                "skipped": "cooldown",
                "next_allowed_in_s": float(next_allowed_at) - now,
            }
        )
        return None

    if not allow_init:
        _debug_log(
            {
                "event": "PreToolUse",
                "tool_name": tool_name,
                "cwd": cwd,
                "file_path": file_path_str,
                "resolved_root": root_str,
                "sticky_root": sticky_root,
                "allow_init": allow_init,
                "attempted_init": False,
                "skipped": "deferred",
            }
        )
        return None

    warmup_status = "missing"
    warmup_failed = False
    ready_langs: list[str] = []
    warmup_updated_at: float | None = None
    try:
        from .lsp_warmup import read_warmup_state

        warm = read_warmup_state()
        if isinstance(warm, dict) and warm.get("root") == root_str:
            v = warm.get("overall")
            if not isinstance(v, str):
                v = warm.get("status")
            if isinstance(v, str):
                warmup_status = v
            ua = warm.get("updated_at")
            if ua is not None:
                try:
                    warmup_updated_at = float(ua)
                except Exception:
                    warmup_updated_at = None
            langs = warm.get("langs")
            if isinstance(langs, dict):
                for lang, info in langs.items():
                    if not isinstance(lang, str) or not isinstance(info, dict):
                        continue
                    if info.get("status") == "ready":
                        ready_langs.append(lang)
    except Exception:
        pass

    if warmup_status in {"failed", "failed_stale"}:
        warmup_failed = True
    if warmup_status == "running" and warmup_updated_at is not None and (now - warmup_updated_at) > 300.0:
        warmup_failed = True
        warmup_status = "failed_stale"

    max_lsp_attempts = 5
    lsp_attempts = st.get_lsp_init_attempts(root=root_str)

    lsp_langs: list[str] | None = None
    if ready_langs and (not warmup_failed) and lsp_attempts < max_lsp_attempts:
        lsp_langs = sorted(set(ready_langs))

    _debug_log(
        {
            "event": "PreToolUse",
            "tool_name": tool_name,
            "cwd": cwd,
            "file_path": file_path_str,
            "resolved_root": root_str,
            "sticky_root": sticky_root,
            "allow_init": allow_init,
            "lsp_attempts": lsp_attempts,
            "warmup_status": warmup_status,
            "ready_langs": lsp_langs or [],
            "use_lsp": bool(lsp_langs),
            "attempted_init": True,
        }
    )

    with _workspace_lock(root):
        did_init = False
        init_reason = ""
        state = None
        parsed_files = 0
        attempt_no: int | None = None
        try:
            st.set_init_inflight_at(root=root_str, at=now)
            if lsp_langs:
                attempt_no = st.inc_lsp_init_attempts(root=root_str)
            did_init, init_reason = _maybe_init(root=root, allow_init=allow_init, lsp_langs=lsp_langs)
            _sync_canvas_artifacts_to_session(root=root)
            state = load_state()
            parsed_files = int(state.parse_summary.get("parsed_files", 0) or 0)
        except Exception as e:
            st.set_init_next_allowed_at(root=root_str, at=time.time() + cooldown_s)
            _debug_log(
                {
                    "event": "PreToolUse",
                    "tool_name": tool_name,
                    "phase": "init",
                    "cwd": cwd,
                    "file_path": file_path_str,
                    "resolved_root": root_str,
                    "allow_init": allow_init,
                    "use_lsp": bool(lsp_langs),
                    "attempt_no": attempt_no,
                    "attempted_init": True,
                    "error": repr(e),
                    "traceback": traceback.format_exc(limit=8),
                }
            )
            return None
        finally:
            st.clear_init_inflight(root=root_str)

        _debug_log(
            {
                "event": "PreToolUse",
                "tool_name": tool_name,
                "phase": "init",
                "cwd": cwd,
                "file_path": file_path_str,
                "resolved_root": root_str,
                "allow_init": allow_init,
                "use_lsp": bool(lsp_langs),
                "attempt_no": attempt_no,
                "attempted_init": True,
                "did_init": did_init,
                "init_reason": init_reason,
                "initialized": bool(state.initialized) if state is not None else False,
                "parsed_files": parsed_files,
                "elapsed_s": time.time() - started,
            }
        )

        if state is None or not state.initialized or parsed_files <= 0:
            st.set_init_next_allowed_at(root=root_str, at=time.time() + cooldown_s)
            return None

        st.set_init_announced(root=root_str)

        ps = state.parse_summary or {}
        cs = state.call_graph_summary or {}
        parsed = ps.get("parsed_files", 0)
        lsp_files = ps.get("lsp_files", 0)
        ts_files = ps.get("tree_sitter_files", 0)
        cg_phase = cs.get("phase", "")
        cg_edges = cs.get("edges_total", 0)
        root_str = state.project_path or str(root)

        return (
            "[CodeCanvas AUTO-INIT] "
            f"root={root_str} "
            f"parse: parsed={parsed} lsp={lsp_files} tree_sitter={ts_files} "
            f"call_graph: phase={cg_phase} edges={cg_edges}"
        )


def handle_post_tool_use(input_data: dict[str, Any]) -> str | None:
    st = AutoContextState()
    cwd = get_str(input_data, "cwd", default=os.getcwd())
    _configure_tb_artifacts(cwd)
    tool_name = get_tool_name(input_data)

    # NOTE: Complex workspace-root detection is intentionally disabled for now.
    # root = resolve_workspace_root(...)
    root = Path("/app").absolute() if _is_under_app(cwd) else Path(cwd).absolute()

    st.write_active_root(str(root), reason=f"post_tool_use:{tool_name}")

    file_path_str = extract_file_path(input_data)
    file_path = Path(file_path_str) if file_path_str else None

    want_impact = bool(
        tool_name in {"Read", "Edit", "Write"}
        and file_path is not None
        and file_path.exists()
        and file_path.is_file()
        and file_path.suffix.lower() in _CODE_EXTS
    )

    if not want_impact:
        _debug_log(
            {
                "event": "PostToolUse",
                "tool_name": tool_name,
                "cwd": cwd,
                "file_path": file_path_str,
                "resolved_root": str(root),
                "want_impact": want_impact,
                "skipped": "no_impact",
            }
        )
        return None

    os.environ["CANVAS_PROJECT_DIR"] = str(root)

    with _workspace_lock(root):
        state = load_state()
        if not state.initialized:
            _debug_log(
                {
                    "event": "PostToolUse",
                    "tool_name": tool_name,
                    "phase": "impact",
                    "cwd": cwd,
                    "file_path": file_path_str,
                    "resolved_root": str(root),
                    "skipped": "not_initialized",
                }
            )
            return None

        try:
            canvas_action(action="status")
        except Exception:
            pass

        symbol_id = _select_best_symbol_in_file(file_path=file_path) if file_path is not None else None
        if symbol_id is None:
            _debug_log(
                {
                    "event": "PostToolUse",
                    "tool_name": tool_name,
                    "phase": "impact",
                    "cwd": cwd,
                    "file_path": file_path_str,
                    "resolved_root": str(root),
                    "skipped": "no_symbol",
                }
            )
            return None

        throttle = st.get_impact_throttle(root=str(root), file_path=str(file_path))
        if throttle is not None and (time.time() - throttle.last_at) < 60.0 and throttle.symbol == symbol_id:
            _debug_log(
                {
                    "event": "PostToolUse",
                    "tool_name": tool_name,
                    "phase": "impact",
                    "cwd": cwd,
                    "file_path": file_path_str,
                    "resolved_root": str(root),
                    "symbol": symbol_id,
                    "skipped": "throttled",
                }
            )
            return None

        started = time.time()
        try:
            res = canvas_action(
                action="impact",
                symbol=symbol_id,
                depth=2,
                max_nodes=20,
                wait_for_call_graph_s=0.5,
            )
        except Exception as e:
            _debug_log(
                {
                    "event": "PostToolUse",
                    "tool_name": tool_name,
                    "phase": "impact",
                    "cwd": cwd,
                    "file_path": file_path_str,
                    "resolved_root": str(root),
                    "symbol": symbol_id,
                    "error": repr(e),
                    "traceback": traceback.format_exc(limit=8),
                }
            )
            return None

        _sync_canvas_artifacts_to_session(root=root)

        ok = any(img.name == "impact" for img in res.images)
        _debug_log(
            {
                "event": "PostToolUse",
                "tool_name": tool_name,
                "phase": "impact",
                "cwd": cwd,
                "file_path": file_path_str,
                "resolved_root": str(root),
                "symbol": symbol_id,
                "impact_ok": ok,
                "elapsed_s": time.time() - started,
            }
        )

        if not ok:
            return None

        card = _format_impact_card(root=root, symbol_id=symbol_id)
        if not card:
            return None

        st.set_impact_throttle(root=str(root), file_path=str(file_path), symbol=symbol_id)
        return card


def main() -> None:
    input_data = read_stdin_json()
    event = get_hook_event_name(input_data)

    try:
        if event == "SessionStart":
            ctx = handle_session_start(input_data)
            _emit(hook_event_name="SessionStart", additional_context=ctx)
            return
        if event == "PreToolUse":
            ctx = handle_pre_tool_use(input_data)
            _emit(hook_event_name="PreToolUse", additional_context=ctx)
            return
        if event == "PostToolUse":
            ctx = handle_post_tool_use(input_data)
            _emit(hook_event_name="PostToolUse", additional_context=ctx)
            return
    except Exception:
        # Hooks must be best-effort; avoid blocking agent execution.
        pass

    _noop(event or "PostToolUse")


if __name__ == "__main__":
    main()
