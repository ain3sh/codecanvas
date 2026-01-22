from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from .lock import canvas_artifact_lock
from .paths import get_canvas_dir, update_manifest


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except Exception:
        return False
    return True


def _dirty_path(project_dir: Path) -> Path:
    return get_canvas_dir(project_dir) / "dirty.json"


@contextmanager
def _canvas_lock(project_dir: Path):
    with canvas_artifact_lock(project_dir, timeout_s=2.0) as locked:
        if not locked:
            yield False
            return
        yield True


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


def _coerce_entry(path_key: str, entry: dict, *, now: float) -> dict:
    if not isinstance(entry, dict):
        entry = {}

    path_value = entry.get("path") or path_key
    queued_at = entry.get("queued_at") or entry.get("updated_at") or now
    updated_at = entry.get("updated_at") or queued_at
    status = entry.get("status")
    if status not in {"pending", "in_progress"}:
        status = "pending"

    missing_at_mark = entry.get("missing_at_mark")
    if missing_at_mark is None and "missing" in entry:
        missing_at_mark = bool(entry.get("missing"))

    out = {
        "path": str(path_value),
        "queued_at": float(queued_at),
        "updated_at": float(updated_at),
        "status": status,
    }
    if "reason" in entry:
        out["reason"] = entry.get("reason")
    if missing_at_mark is not None:
        out["missing_at_mark"] = bool(missing_at_mark)
    if "mtime_ns" in entry:
        out["mtime_ns"] = int(entry.get("mtime_ns"))
    if "size" in entry:
        out["size"] = int(entry.get("size"))
    if "attempts" in entry:
        try:
            out["attempts"] = max(0, int(entry.get("attempts") or 0))
        except Exception:
            out["attempts"] = 0
    if "last_error" in entry:
        out["last_error"] = entry.get("last_error")
    if status == "in_progress":
        if "claim_id" in entry:
            out["claim_id"] = entry.get("claim_id")
        if "claimed_at" in entry:
            out["claimed_at"] = float(entry.get("claimed_at"))
    return out


def _load_dirty(project_dir: Path) -> dict[str, dict]:
    data = _read_json(_dirty_path(project_dir))
    files = data.get("files")
    if not isinstance(files, dict):
        return {}
    now = time.time()
    return {str(k): _coerce_entry(str(k), v, now=now) for k, v in files.items()}


def _write_dirty(project_dir: Path, files: dict[str, dict]) -> None:
    data = {
        "version": 2,
        "updated_at": time.time(),
        "files": files,
    }
    dirty_path = _dirty_path(project_dir)
    _write_json_atomic(dirty_path, data)
    update_manifest(dirty_path.parent, [dirty_path.name])


def read_dirty(project_dir: Path) -> dict[str, dict]:
    return _load_dirty(project_dir)


def clear_dirty(project_dir: Path) -> int:
    root = project_dir
    with _canvas_lock(root) as locked:
        if not locked:
            return 0
        files = _load_dirty(root)
        count = len(files)
        if count:
            _write_dirty(root, {})
        return count


def mark_dirty(project_dir: Path, paths: Iterable[Path], *, reason: str | None = None) -> int:
    root = project_dir
    now = time.time()
    updated = 0
    with _canvas_lock(root) as locked:
        if not locked:
            return 0
        files = _load_dirty(root)

        for p in paths:
            try:
                p_abs = p.resolve()
            except Exception:
                p_abs = Path(str(p)).absolute()
            if not _is_relative_to(p_abs, root):
                continue
            sig = _file_signature(p_abs)
            entry = files.get(str(p_abs)) or {}
            queued_at = entry.get("queued_at")
            entry = {
                "path": str(p_abs),
                "queued_at": float(queued_at) if queued_at else now,
                "updated_at": now,
                "status": "pending",
                **sig,
            }
            if reason:
                entry["reason"] = reason
            entry.pop("claim_id", None)
            entry.pop("claimed_at", None)
            entry.pop("last_error", None)
            files[str(p_abs)] = _coerce_entry(str(p_abs), entry, now=now)
            updated += 1
        _write_dirty(root, files)
    return updated


def reap_dirty(project_dir: Path, *, ttl_s: float = 60.0) -> int:
    root = project_dir
    with _canvas_lock(root) as locked:
        if not locked:
            return 0
        files = _load_dirty(root)
        if not files:
            return 0

        now = time.time()
        reaped = 0
        for key, item in list(files.items()):
            if item.get("status") != "in_progress":
                continue
            claimed_at = item.get("claimed_at")
            if claimed_at is None:
                continue
            age_s = now - float(claimed_at)
            if age_s < float(ttl_s):
                continue
            item["status"] = "pending"
            item["updated_at"] = now
            item.pop("claim_id", None)
            item.pop("claimed_at", None)
            item["last_error"] = "claim_timeout"
            files[key] = item
            reaped += 1

        if reaped:
            _write_dirty(root, files)
        return reaped


def claim_dirty(project_dir: Path, *, max_items: int | None = None) -> list[dict]:
    root = project_dir
    with _canvas_lock(root) as locked:
        if not locked:
            return []
        files = _load_dirty(root)
        if not files:
            return []

        items = [item for item in files.values() if item.get("status") == "pending"]
        items.sort(key=lambda x: float(x.get("updated_at", 0.0)))
        if max_items is not None:
            items = items[: max(0, int(max_items))]

        now = time.time()
        claimed: list[dict] = []
        for item in items:
            claim_id = str(uuid4())
            item["status"] = "in_progress"
            item["claim_id"] = claim_id
            item["claimed_at"] = now
            item["updated_at"] = now
            files[item["path"]] = item
            claimed.append(dict(item))

        if claimed:
            _write_dirty(root, files)
        return claimed


def ack_dirty(
    project_dir: Path,
    *,
    claim_id: str | None,
    path: str,
    outcome: str,
    error: str | None = None,
) -> bool:
    root = project_dir
    with _canvas_lock(root) as locked:
        if not locked:
            return False
        files = _load_dirty(root)
        if not files:
            return False

        item = files.get(path)
        if not item:
            return False
        if claim_id and item.get("claim_id") != claim_id:
            return False

        now = time.time()
        if outcome in {"ok", "deleted"}:
            files.pop(path, None)
        elif outcome == "deferred":
            item["status"] = "pending"
            item["updated_at"] = now
            item["reason"] = "refresh_deferred"
            item.pop("claim_id", None)
            item.pop("claimed_at", None)
            files[path] = item
        elif outcome == "error":
            item["status"] = "pending"
            item["updated_at"] = now
            item["attempts"] = int(item.get("attempts") or 0) + 1
            item["last_error"] = error or "refresh_error"
            item.pop("claim_id", None)
            item.pop("claimed_at", None)
            files[path] = item
        else:
            return False

        _write_dirty(root, files)
        return True
