"""Parser utilities.

Path normalization, import resolution, string stripping, and workspace root detection.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Optional

# =============================================================================
# Path Utilities
# =============================================================================


def normalize_path(path: str) -> str:
    """Normalize path to posix style."""
    parts = path.replace("\\", "/").split("/")
    out: List[str] = []
    for part in parts:
        if not part or part == ".":
            continue
        if part == "..":
            if out:
                out.pop()
            continue
        out.append(part)
    return "/".join(out)


# =============================================================================
# Source Code Utilities
# =============================================================================


def strip_strings_and_comments(src: str) -> str:
    """Remove strings and comments for cleaner parsing."""
    s = src
    s = re.sub(r"/\*[\s\S]*?\*/", "", s)  # Block comments /* */
    s = re.sub(r"(^|[^:])//.*$", r"\1", s, flags=re.MULTILINE)  # Line comments //
    s = re.sub(r"^[ \t]*#.*$", "", s, flags=re.MULTILINE)  # Python comments #
    s = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", s)  # Triple-quoted strings
    s = re.sub(r"\'(?:\\\\.|[^\'\\\\])*\'|\"(?:\\\\.|[^\"\\\\])*\"", "", s)  # Quoted strings
    return s


# =============================================================================
# Import Resolution
# =============================================================================


def join_py_import(from_spec: str, name: str) -> str:
    if not from_spec:
        return name
    if from_spec == ".":
        return f".{name}"
    if from_spec.startswith("."):
        return f"{from_spec}{name}"
    return f"{from_spec}.{name}"


def resolve_import_label(from_label: str, spec: str, lang: str) -> Optional[str]:
    """Resolve import specifier to module label."""
    try:
        posix_from = from_label.replace("\\", "/")
        base_dir = posix_from.rsplit("/", 1)[0] if "/" in posix_from else ""

        def rel(p: str) -> str:
            return normalize_path((base_dir + "/" if base_dir else "") + p)

        if lang == "py":
            if spec.startswith("."):
                up_match = re.match(r"^\.+", spec)
                dots = len(up_match.group(0)) if up_match else 0
                rest = spec[dots:].lstrip(".")
                pops = max(0, dots - 1)
                parts = base_dir.split("/") if base_dir else []
                parts = parts[: max(0, len(parts) - pops)]
                core = normalize_path("/".join(parts) + ("/" + rest.replace(".", "/") if rest else ""))
                return f"{core}.py"
            core = normalize_path(spec.replace(".", "/"))
            return f"{core}.py"

        if lang == "ts":
            if spec.startswith("."):
                core = rel(spec)
                if re.search(r"\.(ts|tsx|js|jsx)$", core, re.I):
                    return core
                return f"{core}.ts"
            if spec.startswith("/"):
                core = normalize_path(spec.lstrip("/"))
                return f"{core}.ts"
            return None

    except Exception:
        return None
    return None


# =============================================================================
# Workspace Root Detection
# =============================================================================

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
