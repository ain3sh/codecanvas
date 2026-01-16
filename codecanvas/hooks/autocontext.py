from __future__ import annotations

import json
import os
import shutil
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from codecanvas.core.paths import get_canvas_dir, has_project_markers, top_level_project_roots
from codecanvas.core.state import load_state
from codecanvas.server import canvas_action

from ._autocontext_state import AutoContextState
from ._hookio import (
    extract_file_path,
    get_hook_event_name,
    get_str,
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
    """Copy `.codecanvas` outputs from the repo into the persisted Claude session dir."""

    session_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if not session_dir:
        return

    src_dir = get_canvas_dir(root)
    if not src_dir.exists() or not src_dir.is_dir():
        return

    dest_dir = Path(session_dir) / "codecanvas"
    try:
        src_resolved = src_dir.resolve()
        dest_resolved = dest_dir.resolve()
        if src_resolved == dest_resolved or dest_resolved in src_resolved.parents:
            return
    except Exception:
        pass
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


def _select_best_symbol_in_file(*, file_path: Path) -> str | None:
    try:
        state = load_state()
        if not state.initialized:
            return None

        target = str(file_path.absolute())

        # Prefer selecting by `state.symbol_files` (cheap and stable) so we don't have
        # to rebuild the graph inside hook processes.
        by_file = state.symbol_files or {}
        candidates: list[tuple[int, int, str]] = []
        for symbol_id, fs_path in by_file.items():
            try:
                if str(Path(fs_path).absolute()) != target:
                    continue
            except Exception:
                continue

            # Prefer funcs, then classes. (Skip module ids.)
            if symbol_id.startswith("fn_"):
                kind_rank = 0
                try:
                    line_rank = int(symbol_id.rsplit("_", 1)[1])
                except Exception:
                    line_rank = 1_000_000_000
            elif symbol_id.startswith("cls_"):
                kind_rank = 1
                line_rank = 1_000_000_000
            else:
                continue

            candidates.append((kind_rank, line_rank, symbol_id))

        if not candidates:
            return None

        candidates.sort()
        return candidates[0][2]
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
    on PostToolUse(Edit|Write) so it reflects the side-effects of actual changes.
    """

    started = time.time()
    st = AutoContextState()
    sticky_root = st.read_active_root()

    cwd = get_str(input_data, "cwd", default=os.getcwd())
    _configure_tb_artifacts(cwd)
    tool_name = get_tool_name(input_data)

    file_path_str = extract_file_path(input_data)
    file_path = Path(file_path_str) if file_path_str else None

    # NOTE: Complex workspace-root detection is intentionally disabled for now.
    # root = resolve_workspace_root(...)
    root = Path("/app").absolute() if _is_under_app(cwd) else Path(cwd).absolute()

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
