from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterable, Sequence

_PROJECT_MARKERS: tuple[str, ...] = (
    ".git",
    "pyproject.toml",
    "package.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
)


def get_canvas_dir(project_dir: Path) -> Path:
    """Return the directory used for CodeCanvas artifacts.

    Defaults to `<project_dir>/.codecanvas`.
    Override with `CANVAS_ARTIFACT_DIR` (absolute path recommended).
    """

    override = (os.environ.get("CANVAS_ARTIFACT_DIR") or "").strip()
    if override:
        p = Path(override)
        return p if p.is_absolute() else (Path.cwd() / p).resolve()
    return project_dir / ".codecanvas"


def has_project_markers(root: Path) -> bool:
    try:
        return any((root / m).exists() for m in _PROJECT_MARKERS)
    except Exception:
        return False


def top_level_project_roots(root: Path) -> list[Path]:
    """Return immediate children of `root` that look like project roots."""

    out: list[Path] = []
    try:
        if not root.exists() or not root.is_dir():
            return []
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if has_project_markers(child):
                out.append(child)
    except Exception:
        return []
    return out


def maybe_strip_single_project_prefix(root: Path, rel_path: str) -> str:
    """For multi-repo roots like `/app`, drop the single top-level project prefix.

    If `root` contains exactly one marker-backed child (e.g. `/app/pyknotid`), then
    labels like `pyknotid/src/a.py` become `src/a.py`.

    If there are multiple roots, preserve prefixes (`pyknotid/...`, `bobscalob/...`).
    """

    try:
        roots = top_level_project_roots(root)
        if len(roots) != 1:
            return rel_path
        prefix = roots[0].name.strip("/")
        if not prefix:
            return rel_path
        prefix_slash = prefix + "/"
        return rel_path[len(prefix_slash) :] if rel_path.startswith(prefix_slash) else rel_path
    except Exception:
        return rel_path


def content_roots_for_scan(root: Path) -> Sequence[Path]:
    """Return directories to scan for language presence.

    - If `root` has one top-level project root, scan only that subtree.
    - If it has multiple, scan each.
    - If none, scan `root`.
    """

    roots = top_level_project_roots(root)
    return roots if roots else (root,)


def iter_walk_files(*, roots: Iterable[Path], ignore_dirs: set[str]) -> Iterable[Path]:
    """Yield files under `roots`, pruning `ignore_dirs` by directory name."""

    import os

    for r in roots:
        r = r.absolute()
        for dirpath, dirnames, filenames in os.walk(r, topdown=True):
            kept: list[str] = []
            for d in dirnames:
                if d in ignore_dirs:
                    continue
                kept.append(d)
            dirnames[:] = kept
            for name in filenames:
                yield Path(dirpath) / name


def manifest_path(artifact_dir: Path) -> Path:
    return artifact_dir / "manifest.json"


def _read_json(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        tmp_path.replace(path)
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)


def update_manifest(artifact_dir: Path, filenames: Iterable[str]) -> None:
    try:
        artifact_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    manifest = _read_json(manifest_path(artifact_dir))
    files = manifest.get("files")
    if not isinstance(files, dict):
        files = {}

    now = time.time()
    for name in filenames:
        if not name:
            continue
        entry = {"path": name, "updated_at": now}
        try:
            stat = (artifact_dir / name).stat()
            entry["missing"] = False
            entry["size"] = int(stat.st_size)
            entry["mtime_ns"] = int(stat.st_mtime_ns)
        except Exception:
            entry["missing"] = True
        files[name] = entry

    manifest["version"] = 1
    manifest["updated_at"] = now
    manifest["files"] = files
    _write_json_atomic(manifest_path(artifact_dir), manifest)
