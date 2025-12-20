"""Workspace root detection utilities.

CodeCanvas uses this to choose a stable LSP workspace root (project/worktree),
instead of per-file directories.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Iterable

_DEFAULT_MARKERS: tuple[str, ...] = (
    ".git",
    "pyproject.toml",
    "package.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
)


def find_workspace_root(start: str | Path, *, max_up: int = 30, markers: Iterable[str] = _DEFAULT_MARKERS) -> Path:
    """Find the most likely workspace root directory for a given file or folder.

    Resolution order:
    1) If `CANVAS_PROJECT_DIR` is set and `start` is inside it, use that.
    2) Walk upwards looking for known project markers.
    3) Fallback to the nearest existing directory.
    """

    p = Path(start)
    if p.is_file():
        p = p.parent
    p = p.absolute()

    env_root = os.environ.get("CANVAS_PROJECT_DIR")
    if env_root:
        try:
            env_path = Path(env_root).absolute()
            if env_path.exists() and _is_relative_to(p, env_path):
                return env_path
        except Exception:
            pass

    return _find_workspace_root_cached(str(p), max_up=max_up, markers=tuple(markers))


@lru_cache(maxsize=1024)
def _find_workspace_root_cached(path_str: str, *, max_up: int, markers: tuple[str, ...]) -> Path:
    p = Path(path_str)
    for _ in range(max_up):
        for m in markers:
            try:
                if (p / m).exists():
                    return p
            except Exception:
                continue
        if p.parent == p:
            break
        p = p.parent
    return p


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except Exception:
        return False
