from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from .paths import get_canvas_dir, update_manifest


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except Exception:
        return False
    return True


def _dirty_path(project_dir: Path) -> Path:
    return get_canvas_dir(project_dir) / "dirty.json"


def _lock_path(project_dir: Path) -> Path:
    return get_canvas_dir(project_dir) / "lock"


@contextmanager
def _canvas_lock(project_dir: Path):
    lock_path = _lock_path(project_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as f:
        try:
            import fcntl

            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield
                return
        except Exception:
            yield
        else:
            try:
                yield
            finally:
                try:
                    fcntl.flock(f, fcntl.LOCK_UN)
                except Exception:
                    pass


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _file_signature(path: Path) -> dict:
    try:
        stat = path.stat()
    except Exception:
        return {"missing": True}
    return {
        "missing": False,
        "mtime_ns": int(stat.st_mtime_ns),
        "size": int(stat.st_size),
    }


def read_dirty(project_dir: Path) -> dict[str, dict]:
    data = _read_json(_dirty_path(project_dir))
    files = data.get("files")
    return files if isinstance(files, dict) else {}


def mark_dirty(project_dir: Path, paths: Iterable[Path], *, reason: str | None = None) -> int:
    root = project_dir
    now = time.time()
    updated = 0
    with _canvas_lock(root):
        data = _read_json(_dirty_path(root))
        files = data.get("files")
        if not isinstance(files, dict):
            files = {}

        for p in paths:
            try:
                p_abs = p.resolve()
            except Exception:
                p_abs = Path(str(p)).absolute()
            if not _is_relative_to(p_abs, root):
                continue
            sig = _file_signature(p_abs)
            entry = {
                "path": str(p_abs),
                "updated_at": now,
                **sig,
            }
            if reason:
                entry["reason"] = reason
            files[str(p_abs)] = entry
            updated += 1

        data = {
            "version": 1,
            "updated_at": now,
            "files": files,
        }
        dirty_path = _dirty_path(root)
        _write_json_atomic(dirty_path, data)
        update_manifest(dirty_path.parent, [dirty_path.name])
    return updated


def take_dirty(project_dir: Path, *, max_items: int | None = None) -> list[dict]:
    root = project_dir
    with _canvas_lock(root):
        data = _read_json(_dirty_path(root))
        files = data.get("files")
        if not isinstance(files, dict) or not files:
            return []

        items = list(files.values())
        items.sort(key=lambda x: float(x.get("updated_at", 0.0)))
        if max_items is not None:
            items = items[: max(0, int(max_items))]

        for item in items:
            key = item.get("path")
            if key in files:
                files.pop(key, None)

        data = {
            "version": 1,
            "updated_at": time.time(),
            "files": files,
        }
        dirty_path = _dirty_path(root)
        _write_json_atomic(dirty_path, data)
        update_manifest(dirty_path.parent, [dirty_path.name])
    return items
