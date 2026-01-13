from __future__ import annotations

import json
import os
import shutil
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from codecanvas.core.models import GraphNode, NodeKind
from codecanvas.core.state import load_state
from codecanvas.server import canvas_action

from ._autocontext_state import AutoContextState
from ._hookio import (
    extract_file_path,
    get_hook_event_name,
    get_mapping,
    get_str,
    get_tool_name,
    read_stdin_json,
)
from ._workspace import resolve_workspace_root

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


def _debug_log(payload: dict[str, Any]) -> None:
    """Best-effort, append-only debug log persisted under CLAUDE_CONFIG_DIR."""

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

        lock_dir = root / ".codecanvas"
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


def _has_project_markers(root: Path) -> bool:
    markers = (
        ".git",
        "pyproject.toml",
        "package.json",
        "go.mod",
        "Cargo.toml",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
    )
    for m in markers:
        try:
            if (root / m).exists():
                return True
        except Exception:
            continue
    return False


def _sync_canvas_artifacts_to_session(*, root: Path) -> None:
    """Copy `.codecanvas` outputs from the repo into the persisted Claude session dir."""

    session_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if not session_dir:
        return

    src_dir = root / ".codecanvas"
    if not src_dir.exists() or not src_dir.is_dir():
        return

    dest_dir = Path(session_dir) / "codecanvas"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    state_path = src_dir / "state.json"
    if state_path.exists():
        try:
            shutil.copy2(state_path, dest_dir / "state.json")
        except Exception:
            pass

    try:
        for png in src_dir.glob("*.png"):
            try:
                shutil.copy2(png, dest_dir / png.name)
            except Exception:
                continue
    except Exception:
        return


def _maybe_init(*, root: Path, allow_init: bool, use_lsp: bool) -> tuple[bool, str]:
    """Ensure the CodeCanvas state in `root` is initialized.

    Returns (did_init, reason).
    """

    os.environ["CANVAS_PROJECT_DIR"] = str(root)
    state = load_state()
    parsed = int(state.parse_summary.get("parsed_files", 0) or 0)

    if (
        state.initialized
        and state.project_path
        and Path(state.project_path).absolute() == root.absolute()
        and parsed > 0
    ):
        return False, "already_initialized"

    if not allow_init:
        return False, "deferred"

    # Re-init if initialized but empty (common in clone-first workflows).
    if state.initialized and parsed == 0 and not _has_project_markers(root):
        # If the root isn't marker-backed, avoid repeatedly re-initializing empties.
        return False, "deferred_empty"

    canvas_action(action="init", repo_path=str(root), use_lsp=bool(use_lsp))
    return True, "initialized"


def _select_best_symbol_in_file(*, file_path: Path) -> Optional[GraphNode]:
    try:
        from codecanvas.server import _ensure_loaded, _graph

        state = load_state()
        if not state.initialized:
            return None
        _ensure_loaded(state)
        if _graph is None:
            return None

        target = str(file_path.absolute())
        candidates: list[GraphNode] = []
        for node in _graph.nodes:
            try:
                if str(Path(node.fsPath).absolute()) != target:
                    continue
            except Exception:
                continue
            if node.kind not in {NodeKind.FUNC, NodeKind.CLASS}:
                continue
            candidates.append(node)

        if not candidates:
            return None

        def _score(n: GraphNode) -> tuple[int, int, int, int, int]:
            kind_score = {
                NodeKind.FUNC: 300,
                NodeKind.CLASS: 200,
                NodeKind.MODULE: 100,
            }.get(n.kind, 0)

            deg = len(_graph.get_edges_from(n.id)) + len(_graph.get_edges_to(n.id))
            child_count = len(_graph.get_children(n.id))

            suffix = Path(n.fsPath).suffix.lower()
            header_suffixes = {".h", ".hh", ".hpp", ".hxx"}
            ext_score = 0 if suffix in header_suffixes else 1

            has_range = 1 if (n.start_line is not None and n.end_line is not None) else 0
            return (kind_score, deg, child_count, ext_score, has_range)

        return max(candidates, key=_score)
    except Exception:
        return None


def _format_impact_card(*, root: Path, node: GraphNode) -> str:
    try:
        from codecanvas.server import _analyzer, _graph

        if _analyzer is None or _graph is None:
            return ""
        callers, callees = _analyzer.impact_call_counts(node.id)
        callers_n = len(callers)
        callees_n = len(callees)

        if callers_n == 0 and callees_n == 0:
            return ""

        def _top_label(d: dict[str, int]) -> str:
            if not d:
                return ""
            top_id = max(d, key=lambda k: d[k])
            n = _graph.get_node(top_id)
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
    on PostToolUse(Edit|Write) so it reflects the side-effects of actual changes.
    """

    started = time.time()
    st = AutoContextState()
    sticky_root = st.read_active_root()

    cwd = get_str(input_data, "cwd", default=os.getcwd())
    tool_name = get_tool_name(input_data)
    tool_input = get_mapping(input_data, "tool_input", "toolInput")

    file_path_str = extract_file_path(input_data)
    file_path = Path(file_path_str) if file_path_str else None

    root = resolve_workspace_root(
        tool_name=tool_name,
        tool_input=tool_input,
        tool_response={},
        cwd=cwd,
        sticky_root=sticky_root,
    )

    if root is None:
        _debug_log(
            {
                "event": "PreToolUse",
                "tool_name": tool_name,
                "cwd": cwd,
                "file_path": file_path_str,
                "resolved_root": "",
                "sticky_root": sticky_root,
                "allow_init": False,
                "needs_lock": False,
                "attempted_init": False,
                "attempted_impact": False,
                "skipped": "no_root",
            }
        )
        return None

    st.write_active_root(str(root), reason=f"pre_tool_use:{tool_name}")

    try:
        from .lsp_warmup import ensure_worker_running

        ensure_worker_running(root=root)
    except Exception:
        pass

    root_str = str(root)
    allow_init = bool(
        _has_project_markers(root)
        or (file_path is not None and file_path.exists() and file_path.is_file())
    )

    if st.is_init_announced(root=root_str):
        return None

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
    warmup_ready = False
    warmup_failed = False
    warmup_updated_at: float | None = None
    try:
        from .lsp_warmup import read_warmup_state

        warm = read_warmup_state()
        if isinstance(warm, dict) and warm.get("root") == root_str:
            v = warm.get("status")
            if isinstance(v, str):
                warmup_status = v
            ua = warm.get("updated_at")
            if ua is not None:
                try:
                    warmup_updated_at = float(ua)
                except Exception:
                    warmup_updated_at = None
    except Exception:
        pass

    if warmup_status == "ready":
        warmup_ready = True
    if warmup_status == "failed":
        warmup_failed = True
    if warmup_status == "running" and warmup_updated_at is not None and (now - warmup_updated_at) > 900.0:
        warmup_failed = True
        warmup_status = "failed_stale"

    max_lsp_attempts = 5
    lsp_attempts = st.get_lsp_init_attempts(root=root_str)

    if warmup_failed or lsp_attempts >= max_lsp_attempts:
        use_lsp = False
    elif lsp_attempts == 0:
        use_lsp = True
    elif warmup_ready:
        use_lsp = True
    else:
        st.set_init_next_allowed_at(root=root_str, at=now + cooldown_s)
        _debug_log(
            {
                "event": "PreToolUse",
                "tool_name": tool_name,
                "cwd": cwd,
                "file_path": file_path_str,
                "resolved_root": root_str,
                "allow_init": allow_init,
                "lsp_attempts": lsp_attempts,
                "warmup_status": warmup_status,
                "skipped": "warmup_not_ready",
            }
        )
        return None

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
            "use_lsp": use_lsp,
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
            if use_lsp:
                attempt_no = st.inc_lsp_init_attempts(root=root_str)
            did_init, init_reason = _maybe_init(root=root, allow_init=allow_init, use_lsp=use_lsp)
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
                    "use_lsp": use_lsp,
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
                "use_lsp": use_lsp,
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
        cg_edges = cs.get("call_edges_total", 0)
        root_str = state.project_path or str(root)

        return (
            "[CodeCanvas AUTO-INIT] "
            f"root={root_str} "
            f"parse: parsed={parsed} lsp={lsp_files} tree_sitter={ts_files} "
            f"call_graph: phase={cg_phase} edges={cg_edges}"
        )


def handle_post_tool_use(input_data: dict[str, Any]) -> str | None:
    st = AutoContextState()
    sticky_root = st.read_active_root()

    cwd = get_str(input_data, "cwd", default=os.getcwd())
    tool_name = get_tool_name(input_data)
    tool_input = get_mapping(input_data, "tool_input", "toolInput")
    tool_response = get_mapping(input_data, "tool_response", "toolResponse")

    root = resolve_workspace_root(
        tool_name=tool_name,
        tool_input=tool_input,
        tool_response=tool_response,
        cwd=cwd,
        sticky_root=sticky_root,
    )
    if root is None:
        _debug_log(
            {
                "event": "PostToolUse",
                "tool_name": tool_name,
                "cwd": cwd,
                "file_path": extract_file_path(input_data),
                "resolved_root": "",
                "sticky_root": sticky_root,
                "skipped": "no_root",
            }
        )
        return None

    st.write_active_root(str(root), reason=f"post_tool_use:{tool_name}")

    file_path_str = extract_file_path(input_data)
    file_path = Path(file_path_str) if file_path_str else None

    want_impact = bool(
        tool_name in {"Edit", "Write"}
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

        best = _select_best_symbol_in_file(file_path=file_path) if file_path is not None else None
        if best is None:
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
        if throttle is not None and (time.time() - throttle.last_at) < 60.0 and throttle.symbol == best.id:
            _debug_log(
                {
                    "event": "PostToolUse",
                    "tool_name": tool_name,
                    "phase": "impact",
                    "cwd": cwd,
                    "file_path": file_path_str,
                    "resolved_root": str(root),
                    "symbol": best.id,
                    "skipped": "throttled",
                }
            )
            return None

        started = time.time()
        try:
            res = canvas_action(
                action="impact",
                symbol=best.id,
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
                    "symbol": best.id,
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
                "symbol": best.id,
                "impact_ok": ok,
                "elapsed_s": time.time() - started,
            }
        )

        if not ok:
            return None

        card = _format_impact_card(root=root, node=best)
        if not card:
            return None

        st.set_impact_throttle(root=str(root), file_path=str(file_path), symbol=best.id)
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
