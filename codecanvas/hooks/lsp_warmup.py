from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path
from typing import Any

from ._hookio import get_hook_event_name, get_str, read_stdin_json

_ROOT_MARKERS: tuple[str, ...] = (
    ".git",
    "pyproject.toml",
    "package.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
)


def _limit(s: str, n: int) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return (s[: max(0, n - 1)] + "…").strip()


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


def _log(msg: str) -> None:
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        print(f"[codecanvas:lsp-warmup] {ts} {msg}", flush=True)
    except Exception:
        return


def _log_file(path: Path, msg: str) -> None:
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        line = f"[codecanvas:lsp-warmup] {ts} {msg}\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except Exception:
        return


def _state_dir() -> Path | None:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if not config_dir:
        return None
    return Path(config_dir) / "codecanvas"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        return


def _is_marker_root(path: Path) -> bool:
    try:
        if not path.exists() or not path.is_dir():
            return False
        return any((path / m).exists() for m in _ROOT_MARKERS)
    except Exception:
        return False


def read_warmup_state() -> dict[str, Any]:
    d = _state_dir()
    if d is None:
        return {}
    return _read_json(d / "lsp_warmup.json")


def ensure_worker_running(*, root: Path) -> None:
    if os.environ.get("CODECANVAS_DISABLE_LSP_WARMUP") == "1":
        return
    d = _state_dir()
    if d is None:
        return

    root = root.absolute()
    state_path = d / "lsp_warmup.json"

    def _should_skip(state: dict[str, Any]) -> bool:
        status = state.get("overall") if isinstance(state, dict) else None
        if not isinstance(status, str):
            status = state.get("status") if isinstance(state, dict) else None
        existing_root = state.get("root") if isinstance(state, dict) else None

        updated_at = state.get("updated_at") if isinstance(state, dict) else None
        try:
            updated_at_f = float(updated_at) if updated_at is not None else None
        except Exception:
            updated_at_f = None

        if isinstance(status, str) and status in {"ready", "partial"} and existing_root == str(root):
            return True

        # Avoid rerunning repeatedly if we just failed for this root.
        if (
            isinstance(status, str)
            and status in {"failed", "failed_stale", "skipped"}
            and existing_root == str(root)
            and updated_at_f is not None
            and (time.time() - updated_at_f) < 300.0
        ):
            return True

        return False

    # Guard: hooks may call ensure_worker_running concurrently.
    # Use a best-effort flock so only one warmup runs at a time.
    try:
        import fcntl

        lock_path = d / "lsp_warmup.spawn.lock"
        d.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a", encoding="utf-8") as lf:
            try:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            except Exception:
                pass

            state = _read_json(state_path)
            if _should_skip(state):
                return

            attempt = int(state.get("attempt") or 0) + 1 if isinstance(state, dict) else 1
            _run_warmup(root=root, state_path=state_path, attempt=attempt)
            return
    except Exception:
        # If flock isn't available, fall back to best-effort execution.
        state = _read_json(state_path)
        if _should_skip(state):
            return

        attempt = int(state.get("attempt") or 0) + 1 if isinstance(state, dict) else 1
        _run_warmup(root=root, state_path=state_path, attempt=attempt)


def _scan_present_langs(*, root: Path) -> tuple[list[str], list[str], dict[str, str]]:
    from codecanvas.core.paths import iter_walk_files
    from codecanvas.parser.config import detect_language

    ignore = {
        ".git",
        ".codecanvas",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
    }

    # Warmup gating is based only on file extensions under the provided root.
    # For TerminalBench, this root is `/app`.
    content_roots = [root]
    present: set[str] = set()
    sample_by_lang: dict[str, str] = {}

    for fp in iter_walk_files(roots=content_roots, ignore_dirs=ignore):
        lang = detect_language(str(fp))
        if not lang:
            continue
        present.add(lang)
        sample_by_lang.setdefault(lang, str(fp))

    return [str(p) for p in content_roots], sorted(present), sample_by_lang


def _run_warmup(*, root: Path, state_path: Path, attempt: int) -> None:
    d = _state_dir()
    if d is None:
        return

    log_path = d / "lsp_warmup.log"
    started_at = time.time()
    total_timeout_s = float(os.environ.get("CODECANVAS_LSP_WARMUP_TOTAL_TIMEOUT_S", "300"))
    cushion_s = 2.0
    deadline = started_at + total_timeout_s

    try:
        _log_file(log_path, f"warmup_start root={root} pid={os.getpid()} total_timeout_s={total_timeout_s}")
        _write_json_atomic(
            state_path,
            {
                "overall": "running",
                "root": str(root),
                "pid": os.getpid(),
                "attempt": attempt,
                "started_at": started_at,
                "updated_at": started_at,
                "langs": {},
            },
        )

        if not root.exists() or not root.is_dir():
            raise RuntimeError("root_missing")

        content_roots, present_langs, sample_by_lang = _scan_present_langs(root=root)

        _log_file(log_path, f"scan_done content_roots={content_roots} present_langs={present_langs}")

        from codecanvas.parser.config import LSP_SUPPORTED_LANGUAGES, has_lsp_support

        warm_langs = [
            lang
            for lang in present_langs
            if lang in LSP_SUPPORTED_LANGUAGES and has_lsp_support(lang)
        ]

        _log_file(log_path, f"warm_langs={warm_langs}")

        langs_state: dict[str, dict[str, Any]] = {}
        for lang in present_langs:
            if lang not in LSP_SUPPORTED_LANGUAGES:
                langs_state[lang] = {"status": "skipped", "reason": "no_lsp_support"}

        from codecanvas.parser.lsp import get_lsp_runtime
        from codecanvas.parser.utils import find_workspace_root

        ready: list[str] = []
        failed: list[str] = []

        for lang in warm_langs:
            sample = sample_by_lang.get(lang)
            if not sample:
                langs_state[lang] = {"status": "skipped", "reason": "no_sample"}
                continue

            remaining_s = deadline - time.time() - cushion_s
            if remaining_s <= 0:
                langs_state[lang] = {"status": "failed", "error": "TimeoutError: warmup_budget_exhausted"}
                failed.append(lang)
                continue

            t0 = time.time()

            _log_file(log_path, f"warm_start lang={lang} sample={sample}")

            async def _warm_one() -> None:
                from codecanvas.parser.lsp import get_lsp_session_manager

                mgr = get_lsp_session_manager()
                ws_root = find_workspace_root(Path(sample), prefer_env=False)
                _log_file(log_path, f"warm_ws_root lang={lang} ws_root={ws_root}")
                sess = await mgr.get(lang=lang, workspace_root=str(ws_root))
                _log_file(log_path, f"warm_symbols_request lang={lang}")
                await sess.document_symbols(str(sample))
                _log_file(log_path, f"warm_symbols_ok lang={lang}")

            try:
                per_lang_max_s = float(os.environ.get("CODECANVAS_LSP_WARMUP_TIMEOUT_S", "300"))
                timeout_s = max(1.0, min(per_lang_max_s, remaining_s))
                _log_file(log_path, f"warm_timeout lang={lang} timeout_s={timeout_s:.3f} remaining_s={remaining_s:.3f}")
                get_lsp_runtime().run(_warm_one(), timeout=timeout_s)
                langs_state[lang] = {"status": "ready", "elapsed_s": time.time() - t0}
                ready.append(lang)
            except Exception as e:
                _log_file(log_path, f"warm_failed lang={lang} error={type(e).__name__}: {e}")
                langs_state[lang] = {
                    "status": "failed",
                    "elapsed_s": time.time() - t0,
                    "error": f"{type(e).__name__}: {e}",
                }
                failed.append(lang)

        overall = "skipped" if not warm_langs else "failed"
        if ready and failed:
            overall = "partial"
        elif ready:
            overall = "ready"

        _log_file(log_path, f"warm_done overall={overall} ready={ready} failed={failed}")

        _write_json_atomic(
            state_path,
            {
                "overall": overall,
                "root": str(root),
                "content_roots": content_roots,
                "present_langs": present_langs,
                "pid": os.getpid(),
                "attempt": attempt,
                "started_at": time.time(),
                "updated_at": time.time(),
                "langs": langs_state,
                "ready_langs": ready,
            },
        )
    except Exception as e:
        _log_file(log_path, f"warmup_failed error={type(e).__name__}: {e}")
        _write_json_atomic(
            state_path,
            {
                "overall": "failed",
                "root": str(root),
                "pid": os.getpid(),
                "attempt": attempt,
                "started_at": started_at,
                "updated_at": time.time(),
                "langs": {},
                "last_error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc(limit=8),
            },
        )


def main() -> None:
    input_data = read_stdin_json()
    event = get_hook_event_name(input_data)

    if event != "SessionStart":
        _noop(event or "SessionStart")
        return

    cwd = get_str(input_data, "cwd", default=os.getcwd())
    try:
        d = _state_dir()
        if d is not None:
            root = Path("/app") if str(Path(cwd).absolute()).startswith("/app") else Path(cwd).absolute()
            _write_json_atomic(
                d / "lsp_warmup.json",
                {
                    "overall": "idle",
                    "root": str(root),
                    "reason": "session_start",
                    "updated_at": time.time(),
                },
            )
            # Run warmup synchronously during SessionStart so the hook can spend its
            # full timeout budget attempting to initialize LSP(s).
            ensure_worker_running(root=root)
    except Exception:
        pass

    _emit(hook_event_name="SessionStart")


if __name__ == "__main__":
    main()
