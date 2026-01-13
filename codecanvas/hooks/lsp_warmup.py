from __future__ import annotations

import json
import os
import subprocess
import sys
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


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


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
    state = _read_json(state_path)
    status = state.get("overall") if isinstance(state, dict) else None
    if not isinstance(status, str):
        status = state.get("status") if isinstance(state, dict) else None
    pid = state.get("pid") if isinstance(state, dict) else None
    existing_root = state.get("root") if isinstance(state, dict) else None

    updated_at = state.get("updated_at") if isinstance(state, dict) else None
    try:
        updated_at_f = float(updated_at) if updated_at is not None else None
    except Exception:
        updated_at_f = None

    if (
        isinstance(status, str)
        and status == "running"
        and isinstance(pid, int)
        and _pid_alive(pid)
        and existing_root == str(root)
    ):
        return

    if isinstance(status, str) and status in {"ready", "partial"} and existing_root == str(root):
        return

    # Avoid respawning repeatedly if we just failed for this root.
    if (
        isinstance(status, str)
        and status in {"failed", "failed_stale", "skipped"}
        and existing_root == str(root)
        and updated_at_f is not None
        and (time.time() - updated_at_f) < 300.0
    ):
        return

    d.mkdir(parents=True, exist_ok=True)
    log_path = d / "lsp_warmup.log"

    env = dict(os.environ)
    env["CODECANVAS_LSP_WARMUP_ROOT"] = str(root)

    cmd = [
        sys.executable,
        "-c",
        "from codecanvas.hooks.lsp_warmup import worker_main; worker_main()",
    ]

    try:
        with open(log_path, "a", encoding="utf-8") as log:
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=log,
                stderr=log,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
    except Exception:
        _write_json_atomic(
            state_path,
            {
                "overall": "failed",
                "root": str(root),
                "attempt": int(state.get("attempt") or 0) + 1 if isinstance(state, dict) else 1,
                "started_at": time.time(),
                "updated_at": time.time(),
                "ready_langs": [],
                "last_error": "spawn_failed",
            },
        )
        return

    _write_json_atomic(
        state_path,
        {
            "overall": "running",
            "root": str(root),
            "pid": int(proc.pid),
            "attempt": int(state.get("attempt") or 0) if isinstance(state, dict) else 0,
            "started_at": time.time(),
            "updated_at": time.time(),
        },
    )


def _scan_present_langs(*, root: Path) -> tuple[list[str], list[str], dict[str, str]]:
    from codecanvas.core.paths import content_roots_for_scan, iter_walk_files
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

    content_roots = list(content_roots_for_scan(root))
    present: set[str] = set()
    sample_by_lang: dict[str, str] = {}

    for fp in iter_walk_files(roots=content_roots, ignore_dirs=ignore):
        lang = detect_language(str(fp))
        if not lang:
            continue
        present.add(lang)
        sample_by_lang.setdefault(lang, str(fp))

    return [str(p) for p in content_roots], sorted(present), sample_by_lang


def worker_main() -> None:
    d = _state_dir()
    if d is None:
        return

    state_path = d / "lsp_warmup.json"
    root_str = os.environ.get("CODECANVAS_LSP_WARMUP_ROOT", "").strip()
    if not root_str:
        _write_json_atomic(
            state_path,
            {
                "overall": "failed",
                "root": "",
                "pid": os.getpid(),
                "attempt": 1,
                "started_at": time.time(),
                "updated_at": time.time(),
                "ready_langs": [],
                "last_error": "missing_root",
            },
        )
        return

    root = Path(root_str)
    attempt = 1
    try:
        _write_json_atomic(
            state_path,
            {
                "overall": "running",
                "root": str(root),
                "pid": os.getpid(),
                "attempt": attempt,
                "started_at": time.time(),
                "updated_at": time.time(),
                "langs": {},
            },
        )

        if not root.exists() or not root.is_dir():
            raise RuntimeError("root_missing")

        content_roots, present_langs, sample_by_lang = _scan_present_langs(root=root)

        from codecanvas.parser.config import LSP_SUPPORTED_LANGUAGES, has_lsp_support

        warm_langs = [
            lang
            for lang in present_langs
            if lang in LSP_SUPPORTED_LANGUAGES and has_lsp_support(lang)
        ]

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

            t0 = time.time()

            async def _warm_one() -> None:
                from codecanvas.parser.lsp import get_lsp_session_manager

                mgr = get_lsp_session_manager()
                ws_root = find_workspace_root(Path(sample), prefer_env=False)
                sess = await mgr.get(lang=lang, workspace_root=str(ws_root))
                await sess.document_symbols(str(sample))

            try:
                get_lsp_runtime().run(_warm_one(), timeout=60.0)
                langs_state[lang] = {"status": "ready", "elapsed_s": time.time() - t0}
                ready.append(lang)
            except Exception as e:
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
        _write_json_atomic(
            state_path,
            {
                "overall": "failed",
                "root": str(root),
                "pid": os.getpid(),
                "attempt": attempt,
                "started_at": time.time(),
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
    except Exception:
        pass

    _emit(hook_event_name="SessionStart")


if __name__ == "__main__":
    main()
