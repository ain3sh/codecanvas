from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

from .paths import get_canvas_dir


@contextmanager
def canvas_artifact_lock(project_dir: Path, *, timeout_s: float = 2.0):
    """Best-effort cross-process lock for artifact writes.

    Yields True if lock was acquired, else False.
    """

    lock_path = get_canvas_dir(project_dir) / "lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl

        f = lock_path.open("a+", encoding="utf-8")
    except Exception:
        yield False
        return

    deadline = time.time() + float(timeout_s)
    locked = False
    try:
        while time.time() < deadline:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except BlockingIOError:
                time.sleep(0.02)
            except Exception:
                break
        yield locked
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
